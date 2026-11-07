"""Offline extension planning, verified ZIP reuse and a bounded GLDAS pilot.

All remote preparation requires explicit selection, a reviewed plan ID and
user-owned provider authorization. Other source workflows remain unsupported.
"""
import argparse
from contextlib import closing
from dataclasses import asdict
from datetime import date
import hashlib
import json
import os
from pathlib import Path
import shutil
import sqlite3
import tempfile

from .archives import verify_archive
from .catalogue import ReleaseCatalogue, SOURCE_COLUMNS
from .grid import anchor_cell, anchor_cell_from_id, context_grid, ContextResolution
from .native_cells import era5_land_native_cell
from .native_cells import gldas21_native_cell
from .native_cells import imerg_v07_native_cell


def identity(value):
    return hashlib.sha256(json.dumps(value, sort_keys=True, separators=(',', ':'),
                                     allow_nan=False).encode()).hexdigest()


def normalize_request(request):
    allowed = {'schema', 'spatial', 'years', 'start', 'end', 'sources', 'station_targets',
               'output_root', 'credential_ref', 'max_packages'}
    if set(request) - allowed:
        raise ValueError('Unknown request fields: ' + ', '.join(sorted(set(request) - allowed)))
    if request.get('schema', 'benchmark-extension-request-v1') != 'benchmark-extension-request-v1':
        raise ValueError('Unsupported request schema')
    sources = request.get('sources')
    if not isinstance(sources, list) or not sources or not all(isinstance(s, str) for s in sources):
        raise ValueError('sources must be a nonempty list of registered IDs')
    unknown = set(sources) - SOURCE_COLUMNS.keys()
    if unknown:
        raise ValueError('Unsupported registered sources: ' + ', '.join(sorted(unknown)))
    targets = request.get('station_targets', 'required')
    if targets not in {'required', 'optional', 'absent'}:
        raise ValueError('station_targets must be required, optional or absent')
    if targets == 'absent' and 'ismn' in sources:
        raise ValueError('ismn conflicts with station_targets=absent')
    if targets == 'required':
        sources = [*sources, 'ismn']
    if 'years' in request:
        if 'start' in request or 'end' in request:
            raise ValueError('Supply years or start/end, not both')
        years = request['years']
        if not isinstance(years, list) or not years or any(type(y) is not int or not 1 <= y <= 9999 for y in years):
            raise ValueError('years must contain integer calendar years')
        period = None
    else:
        start, end = date.fromisoformat(request['start']), date.fromisoformat(request['end'])
        if start > end:
            raise ValueError('start must not follow end')
        years = list(range(start.year, end.year + 1))
        period = {'start': start.isoformat(), 'end': end.isoformat()}
    limit = request.get('max_packages', 100)
    if type(limit) is not int or limit < 1:
        raise ValueError('max_packages must be a positive integer')
    spatial = request['spatial']
    if not isinstance(spatial, dict) or len(spatial) != 1:
        raise ValueError('spatial must contain exactly one of points, bbox or anchor_ids')
    if 'points' in spatial:
        if not isinstance(spatial['points'], list) or not spatial['points']:
            raise ValueError('points must be nonempty [longitude, latitude] pairs')
        anchors = sorted({anchor_cell(*p).anchor_id for p in spatial['points']})
    elif 'anchor_ids' in spatial:
        if not isinstance(spatial['anchor_ids'], list) or not spatial['anchor_ids']:
            raise ValueError('anchor_ids must be nonempty')
        anchors = sorted({anchor_cell_from_id(a).anchor_id for a in spatial['anchor_ids']})
    elif 'bbox' in spatial:
        west, south, east, north = spatial['bbox']
        if west > east or south > north:
            raise ValueError('bbox requires west <= east and south <= north; split antimeridian ranges')
        nw, se = anchor_cell(west, north), anchor_cell(east, south)
        count = (se.row - nw.row + 1) * (se.column - nw.column + 1) * len(set(years))
        if count > limit:
            raise ValueError(f'Request scope {count} packages exceeds max_packages={limit}')
        anchors = [f'EASE2_M09km_R{r:04d}_C{c:04d}' for r in range(nw.row, se.row + 1)
                   for c in range(nw.column, se.column + 1)]
    else:
        raise ValueError('Unknown spatial selector')
    count = len(anchors) * len(set(years))
    if count > limit:
        raise ValueError(f'Request scope {count} packages exceeds max_packages={limit}')
    output = request.get('output_root')
    if not isinstance(output, str) or not output.strip():
        raise ValueError('output_root is required')
    ref = request.get('credential_ref')
    if ref is not None and (not isinstance(ref, str) or not ref.strip()):
        raise ValueError('credential_ref must reference a user-owned file; no inline credentials')
    normalized = {'schema': 'benchmark-extension-request-v1', 'anchor_ids': anchors,
                  'years': sorted(set(years)), 'requested_period': period,
                  'sources': sorted(set(sources)), 'station_targets': targets,
                  'output_root': output, 'credential_ref': ref, 'max_packages': limit}
    return dict(normalized, request_id=identity(normalized))


def plan_extension(request, catalogue):
    normalized = normalize_request(request)
    units, geometry = [], []
    for anchor_id in normalized['anchor_ids']:
        anchor = anchor_cell_from_id(anchor_id)
        geometry.append({'anchor': asdict(anchor), 'context': asdict(context_grid(anchor, ContextResolution('1 km', 1))),
                         'native_cells': {source: fn(anchor.centre_longitude, anchor.centre_latitude)
                                          for source, fn in {'era5_land': era5_land_native_cell,
                                                             'gldas21': gldas21_native_cell,
                                                             'imerg_v07': imerg_v07_native_cell}.items()
                                          if source in normalized['sources']}})
        for year in normalized['years']:
            row = catalogue.package(anchor_id, year)
            reusable = bool(row and row['build_status'] == 'complete'
                            and catalogue.archive_path(row).is_file()
                            and normalized['station_targets'] != 'absent')
            if normalized['station_targets'] == 'required' and row and int(row['station_count']) < 1:
                reusable = False
            states = {s: catalogue.availability(anchor_id, year, s) for s in normalized['sources']}
            published = bool(row and row['build_status'] == 'complete')
            reason = ('Existing full annual package; includes unselected sources and station targets. '
                      'Source gaps are preserved.' if reusable else
                      'V1 catalogue records this package, but no compatible local ZIP is available. '
                      'Remote package access is not yet implemented.' if published else
                      'Not present in V1. Source preparation and retrieval adapters are required.')
            units.append({'anchor_id': anchor_id, 'year': year,
                          'state': 'reusable' if reusable else 'requires_user_action',
                          'reason': reason,
                          'catalogue_match': published,
                          'sources': {s: dict(v, plan_state=('unavailable' if v['state'] == 'unavailable'
                                                           else 'reusable' if reusable else 'requires_user_action'))
                                      for s, v in states.items()},
                          'archive_path': row['archive_path'] if published else None,
                          'archive_sha256': row['archive_sha256'] if published else None,
                          'archive_bytes': int(row['archive_bytes']) if published else None})
    result = {'schema': 'benchmark-extension-plan-v1', 'request': normalized,
              'release_id': catalogue.release['release_id'], 'geometry': geometry, 'units': units,
              'estimates': {'package_count': len(units),
                            'known_copy_bytes': sum(u['archive_bytes'] or 0 for u in units if u['state'] == 'reusable'),
                            'remote_operations': 0, 'download_bytes': None,
                            'unresolved_packages': sum(u['state'] != 'reusable' for u in units)},
              'execution': 'Explicit --execute --accept-plan PLAN_ID required; local ZIP reuse only.'}
    return dict(result, plan_id=identity(result))


def execute_reuse(plan, catalogue, *, accepted_plan_id):
    if accepted_plan_id != plan['plan_id'] or identity({k: v for k, v in plan.items() if k != 'plan_id'}) != plan['plan_id']:
        raise ValueError('Execution requires the unchanged reviewed plan ID')
    if any(u['state'] != 'reusable' for u in plan['units']):
        raise ValueError('Unresolved units; this executor only reuses existing packages')
    root = Path(plan['request']['output_root']).resolve()
    if any(root == p or root.is_relative_to(p) for p in (catalogue.root, catalogue.package_root)):
        raise ValueError('Output must be outside the published release')
    root.mkdir(parents=True, exist_ok=True)
    results = []
    with closing(sqlite3.connect(root / 'extension_state.sqlite', timeout=60)) as connection:
        connection.execute('CREATE TABLE IF NOT EXISTS units (request_id TEXT, anchor_id TEXT, year INTEGER, status TEXT, PRIMARY KEY(request_id,anchor_id,year))')
        for unit in plan['units']:
            anchor, year = unit['anchor_id'], unit['year']
            key = plan['request']['request_id'], anchor, year
            def record(status):
                connection.execute('INSERT OR REPLACE INTO units VALUES (?,?,?,?)', (*key, status))
                connection.commit()
            record('running')
            temporary = None
            try:
                target = root / 'packages' / anchor / f'{year}.zip'
                check = dict(anchor_id=anchor, year=year, sha256=unit['archive_sha256'])
                if target.exists():
                    verify_archive(target, **check)
                    status = 'reused'
                else:
                    row = catalogue.package(anchor, year)
                    if row is None or row['archive_sha256'] != unit['archive_sha256']:
                        raise ValueError('Catalogue changed after planning')
                    source = catalogue.archive_path(row)
                    verify_archive(source, **check)
                    target.parent.mkdir(parents=True, exist_ok=True)
                    fd, name = tempfile.mkstemp(suffix='.zip.part', dir=target.parent)
                    os.close(fd)
                    temporary = Path(name)
                    shutil.copyfile(source, temporary)
                    verify_archive(temporary, **check)
                    os.link(temporary, target)
                    status = 'verified'
                record(status)
                results.append({'anchor_id': anchor, 'year': year, 'status': status,
                                'archive_path': target.relative_to(root).as_posix(),
                                'sha256': unit['archive_sha256']})
            except Exception:
                record('failed')
                raise
            finally:
                if temporary is not None:
                    temporary.unlink(missing_ok=True)
    return {'request_id': plan['request']['request_id'], 'status': 'complete', 'packages': results}


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--workflow', choices=['reuse', 'gldas'], default='reuse')
    parser.add_argument('--request', type=Path, required=True)
    parser.add_argument('--release-root', type=Path)
    parser.add_argument('--package-root', type=Path, help='External directory containing packages/; defaults to release root')
    parser.add_argument('--context-plan', type=Path, help='Reviewed public static/annual assets for the GLDAS pilot')
    parser.add_argument('--asset-root', type=Path, help='Prepared-source checkpoint/cache directory')
    parser.add_argument('--execute', action='store_true')
    parser.add_argument('--accept-plan', help='Exact plan_id from the preceding preview')
    args = parser.parse_args()
    if args.accept_plan and not args.execute:
        parser.error('--accept-plan requires --execute')
    if args.workflow == 'reuse' and (not args.release_root or args.context_plan or args.asset_root):
        parser.error('reuse requires --release-root and does not accept GLDAS context/cache arguments')
    if args.workflow == 'gldas' and (not args.context_plan or not args.asset_root or args.release_root or args.package_root):
        parser.error('gldas requires --context-plan and --asset-root; release/package roots belong to reuse')
    try:
        request = json.loads(args.request.read_text(encoding='utf-8'))
        if args.workflow == 'gldas':
            from .gldas_workflow import plan_gldas, execute_gldas
            plan = plan_gldas(request, context_plan=args.context_plan, asset_root=args.asset_root)
            result = execute_gldas(plan, accepted_plan_id=args.accept_plan) if args.execute else plan
        else:
            catalogue = ReleaseCatalogue(args.release_root, package_root=args.package_root)
            plan = plan_extension(request, catalogue)
            result = execute_reuse(plan, catalogue, accepted_plan_id=args.accept_plan) if args.execute else plan
    except (ValueError, KeyError, TypeError, OSError, RuntimeError, ImportError) as exc:
        if args.workflow == 'gldas':
            parser.exit(2, f'{type(exc).__name__}: GLDAS workflow did not complete; inspect inputs, dependencies and checkpoint state.\n')
        parser.exit(2, f'{type(exc).__name__}: {exc}\n')
    print(json.dumps(result, indent=2, allow_nan=False))


if __name__ == '__main__':
    main()
