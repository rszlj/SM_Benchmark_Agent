"""One anchor/year Multi-source preparation and station-free annual assembly."""
import argparse
from dataclasses import asdict
import json
from pathlib import Path
import tempfile
import zipfile

from .adapters import SourceUnit, default_registry
from .archives import verify_archive
from .delivery import checksum, export_gridded_archive
from .extension_agent import normalize_request, identity
from .gldas_workflow import checked_context, CONTEXT_SOURCES
from .gldas_workflow import check_public_metadata
from .catalogue import SOURCE_COLUMNS
from . import periods

SOURCES = set(SOURCE_COLUMNS) - CONTEXT_SOURCES - {"ismn"}


def workflow_hashes():
    root = Path(__file__).parent
    return {p.relative_to(root).as_posix(): checksum(p) for p in sorted(root.rglob('*.py'))}


def adapter_for(source, adapters):
    return adapters[source] if adapters is not None else default_registry().require(source)


def plan_multi(request, *, context_plan, asset_root, adapters=None):
    req = normalize_request(request)
    selected = sorted(set(req['sources']) & SOURCES)
    if (len(req['anchor_ids']) != 1 or len(req['years']) != 1 or req['station_targets'] != 'absent'
            or not selected or set(req['sources']) - (SOURCES | CONTEXT_SOURCES)):
        raise ValueError('Multi-source workflow requires one anchor/year, absent targets, and selected Multi-source sources with optional context sources')
    anchor, year = req['anchor_ids'][0], req['years'][0]
    output, cache = Path(req['output_root']).resolve(), Path(asset_root).resolve()
    if output == cache or output.is_relative_to(cache) or cache.is_relative_to(output):
        raise ValueError('Delivery and cache require separate directory trees')
    context = checked_context(context_plan, anchor, year)
    sources = []
    for source in selected:
        adapter = adapter_for(source, adapters)
        if adapter.retries != 2 or adapter.profile_id != default_registry().require(source).profile_id:
            raise ValueError('Unified workflow requires registered profiles and two bounded retries')
        sources.append(asdict(adapter.plan(SourceUnit(source, adapter.profile_id, anchor, year, **(req['requested_period'] or {})), asset_root=asset_root)))
    plan = {'schema': 'benchmark-multi-extension-plan-v1', 'request': req,
            'context_plan': str(Path(context_plan).resolve()), 'context_sha256': checksum(Path(context_plan)),
            'context_assets': [{'destination': a['destination'], 'sha256': a['sha256']} for a in context['assets']],
            'release_id': context['release_id'], 'asset_root': str(Path(asset_root).resolve()),
            'processing_code_sha256': workflow_hashes(), 'sources': sources, 'retry_limit': 2,
            'included_context_sources': sorted(CONTEXT_SOURCES),
            'profile_ids': {s['unit']['source_id']: s['unit']['profile_id'] for s in sources},
            'limitations': {'smap_l4': 'legacy 13km geographic sampling; native EASE cell equivalence unverified'} if 'smap_l4' in selected else {},
            'maximum_provider_operations_excluding_auth': None if any(s['remote_operations'] is None for s in sources) else sum(s['remote_operations'] for s in sources),
            'download_bytes': None}
    return dict(plan, plan_id=identity(plan))


def execute_multi(plan, *, accepted_plan_id, adapters=None):
    if accepted_plan_id != plan['plan_id'] or identity({k: v for k, v in plan.items() if k != 'plan_id'}) != plan['plan_id']:
        raise ValueError('Execution requires unchanged reviewed plan ID')
    if workflow_hashes() != plan['processing_code_sha256'] or checksum(Path(plan['context_plan'])) != plan['context_sha256']:
        raise ValueError('Processing code or context plan changed after review')
    req = plan['request']
    anchor, year = req['anchor_ids'][0], req['years'][0]
    context = checked_context(plan['context_plan'], anchor, year)
    root, cache = Path(req['output_root']).resolve(), Path(plan['asset_root'])
    if root == cache or root.is_relative_to(cache) or cache.is_relative_to(root):
        raise ValueError('Delivery must be outside the source cache')
    stable = identity({k: v for k, v in plan.items() if k not in {'plan_id', 'sources', 'maximum_provider_operations_excluding_auth'}})
    period = req['requested_period']
    package_name = f"{period['start']}_{period['end']}.zip" if period else f'{year}.zip'
    target = root / 'packages' / anchor / package_name
    if target.exists():
        verify_archive(target, anchor_id=anchor, year=year)
        with zipfile.ZipFile(target) as archive:
            provenance = json.loads(archive.read('metadata/multi_extension.json'))
            if provenance['scope_id'] != stable:
                raise FileExistsError('Existing package belongs to another scope')
        return {'status': 'reused', 'archive': str(target), 'sha256': checksum(target)}
    prepared, unavailable, validations = [], [], {}
    # Adapter checkpoints are the durable source of progress, including failed runs.
    # Never turn execution/auth failures into an unavailable scientific source.
    for item in plan['sources']:
        unit = SourceUnit(**item['unit'])
        adapter = adapter_for(unit.source_id, adapters)
        if adapter.retries != plan['retry_limit'] or adapter.profile_id != unit.profile_id:
            raise ValueError('Source profile or retry policy changed after review')
        current = adapter.plan(unit, asset_root=cache)
        before, now = item['remote_operations'], current.remote_operations
        if before is not None and (now is None or now > before):
            raise ValueError('Retrieval scope increased; replan before execution')
        if current.state == 'unavailable':
            unavailable.append({'source_id': unit.source_id, 'profile_id': unit.profile_id,
                                'anchor_id': anchor, 'year': year, **periods.metadata(unit), 'state': 'unavailable',
                                'reason': current.reason, 'files': []})
            continue
        if current.state not in {'retrievable', 'reusable'}:
            raise ValueError('Source requires user action before execution')
        output = adapter.prepare(current, output_root=cache, credential_ref=req['credential_ref'])
        if output.unit != unit:
            raise ValueError('Prepared source identity mismatch')
        validation = adapter.validate(output)
        if not validation.passed:
            raise ValueError('Source scientific validation failed')
        check_public_metadata(dict(output.public_metadata))
        validations[unit.source_id] = asdict(validation)
        prepared.append(output)
    root.mkdir(parents=True, exist_ok=True)
    with tempfile.TemporaryDirectory(prefix='.multi-', dir=root) as temporary:
        stage = Path(temporary)
        assets, availability = list(context['assets']), list(context['availability'])
        for output in prepared:
            source = output.unit.source_id
            names = []
            for path in output.files[:-1]:
                name, role = destination(source, path, year)
                names.append(name)
                assets.append({'path': str(path.resolve()), 'destination': name, 'role': role,
                               'source_id': source, 'sha256': checksum(path)})
            metadata = dict(output.public_metadata, files=names)
            metadata.pop('file', None)
            metadata.pop('assets', None)
            metadata['anchor_id'] = anchor
            path = stage / f'{source}.json'
            path.write_text(json.dumps(metadata, indent=2), encoding='utf-8')
            assets.append({'path': str(path), 'destination': f'metadata/source_manifests/{source}.json',
                           'source_id': source, 'role': 'metadata', 'sha256': checksum(path)})
            availability.append({'source': source, 'state': metadata['state'], 'reason': metadata['reason']})
        for metadata in unavailable:
            source = metadata['source_id']
            path = stage / f'{source}.json'
            path.write_text(json.dumps(metadata, indent=2), encoding='utf-8')
            assets.append({'path': str(path), 'destination': f'metadata/source_manifests/{source}.json',
                           'source_id': source, 'role': 'metadata', 'sha256': checksum(path)})
            availability.append({'source': source, 'state': 'unavailable', 'reason': metadata['reason']})
        path = stage / 'provenance.json'
        path.write_text(json.dumps({'scope_id': stable, 'release_id': plan['release_id'],
                                    'processing_code_sha256': workflow_hashes(),
                                    'requested_period': period, 'selected_sources': sorted(plan['profile_ids']), 'profile_ids': plan['profile_ids'],
                                    'validation': validations, 'limitations': plan['limitations'],
                                    'assembly_policy': 'Source-specific science unchanged; no temporal or spatial harmonization' }, indent=2), encoding='utf-8')
        assets.append({'path': str(path), 'destination': 'metadata/multi_extension.json', 'source_id': 'multi-extension',
                       'role': 'metadata', 'sha256': checksum(path)})
        delivery = dict(context, requested_period=period, assets=assets, availability=availability, processing_version='sm-benchmark-agent-0.1.0.dev0')
        path = stage / 'plan.json'
        path.write_text(json.dumps(delivery, indent=2), encoding='utf-8')
        export_gridded_archive(path, root, dry_run=False)
    return {'status': 'packaged', 'archive': str(target), 'sha256': checksum(target), 'availability': availability}


def destination(source, path, year):
    if source in {'gldas21', 'era5_land', 'imerg_v07', 'smap_l4'}:
        if source == 'smap_l4':
            filename = 'smap_l4_3hourly.parquet'
        else:
            cadence = {'gldas21': '3hourly', 'era5_land': 'hourly', 'imerg_v07': 'half_hourly'}[source]
            filename = f'{source}_{year}_native_pixel_{cadence}.parquet'
        return f'source_cell_time_series/{source}/{filename}', 'source_cell_time_series'
    return f'annual/{source}/{path.name}', 'raster_inputs'


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--request', type=Path, required=True)
    parser.add_argument('--context-plan', type=Path, required=True)
    parser.add_argument('--asset-root', type=Path, required=True)
    parser.add_argument('--execute', action='store_true')
    parser.add_argument('--accept-plan')
    args = parser.parse_args()
    if args.accept_plan and not args.execute:
        parser.error('--accept-plan requires --execute')
    try:
        plan = plan_multi(json.loads(args.request.read_text(encoding='utf-8')), context_plan=args.context_plan, asset_root=args.asset_root)
        result = execute_multi(plan, accepted_plan_id=args.accept_plan) if args.execute else plan
    except Exception as exc:
        parser.exit(2, f'{type(exc).__name__}: Multi-source workflow did not complete; inspect scope, dependencies and checkpoints.\n')
    print(json.dumps(result, indent=2, allow_nan=False))


if __name__ == '__main__':
    main()
