"""Preview or prepare one anchor/year's V1 static and annual contexts.

Use `prepare` for contexts and `hwsd-global` for explicit initial global caching.
Both default to offline preview and require the unchanged plan ID to execute.
"""
import argparse
from dataclasses import asdict
import json
from pathlib import Path
import re
import shutil
import tempfile

from .adapters import SourceUnit
from .context_sources import ContextAdapter, PROFILES, processing_hashes, hwsd_cache_record
from .delivery import checksum
from .extension_agent import normalize_request, identity
from .gldas_workflow import checked_context
from .grid import anchor_cell_from_id
from .processing.hwsd2 import prepare_hwsd2_global, HWSD2_SNAPSHOT_ID, HWSD2_RASTER_SHA256, HWSD2_DATABASE_SHA256


def plan_contexts(request, *, asset_root, release_id, hwsd_cache=None, adapters=None):
    req = normalize_request(request)
    if len(req['anchor_ids']) != 1 or len(req['years']) != 1 or req['station_targets'] != 'absent':
        raise ValueError('Context preparation currently requires one anchor/year and absent station targets')
    if set(req['sources']) not in (set(PROFILES), set(PROFILES) | {'gldas21'}):
        raise ValueError('Context preparation requires exactly SRTM, HWSD2, MCD12Q1 (optionally GLDAS for later assembly)')
    if not re.fullmatch(r'[A-Za-z0-9][A-Za-z0-9_.-]{0,100}', release_id) or release_id.startswith('benchmark-initial-'):
        raise ValueError('A distinct path-safe extension release ID is required')
    anchor, year = req['anchor_ids'][0], req['years'][0]
    source_plans = []
    for source, profile in PROFILES.items():
        adapter = adapters[source] if adapters else ContextAdapter(source, hwsd_cache=hwsd_cache)
        source_plans.append(asdict(adapter.plan(SourceUnit(source, profile, anchor, year), asset_root=asset_root)))
    plan = {'schema': 'benchmark-context-plan-v1', 'request': req, 'release_id': release_id,
            'asset_root': str(Path(asset_root).resolve()),
            'hwsd_cache': str(Path(hwsd_cache).resolve()) if hwsd_cache else None,
            'global_inputs': hwsd_cache_record(hwsd_cache) if hwsd_cache else None,
            'processing_code_sha256': {**processing_hashes(), 'context_workflow.py': checksum(Path(__file__))},
            'sources': source_plans, 'download_bytes': None,
            'maximum_provider_operations_excluding_auth': sum(p['remote_operations'] or 0 for p in source_plans)}
    return dict(plan, plan_id=identity(plan))


def verify_plan(plan, accepted_plan_id):
    if accepted_plan_id != plan['plan_id'] or identity({k: v for k, v in plan.items() if k != 'plan_id'}) != plan['plan_id']:
        raise ValueError('Execution requires the unchanged reviewed plan ID')


def execute_contexts(plan, *, accepted_plan_id, adapters=None):
    verify_plan(plan, accepted_plan_id)
    if plan['processing_code_sha256'] != {**processing_hashes(), 'context_workflow.py': checksum(Path(__file__))}:
        raise ValueError('Context code changed after planning')
    if plan['hwsd_cache'] and hwsd_cache_record(plan['hwsd_cache']) != plan['global_inputs']:
        raise ValueError('HWSD2 global inputs changed after planning')
    if any(p['state'] == 'requires_user_action' for p in plan['sources']):
        raise ValueError('Prepare the required HWSD2 global cache before context retrieval')
    req = plan['request']
    anchor, year = req['anchor_ids'][0], req['years'][0]
    root = Path(req['output_root']).resolve()
    cache = Path(plan['asset_root'])
    if root == cache or root.is_relative_to(cache):
        raise ValueError('Output must be outside the source cache')
    final = root / 'contexts' / plan['release_id'] / anchor / str(year)
    stable = identity({k: v for k, v in plan.items() if k not in {'plan_id', 'sources', 'maximum_provider_operations_excluding_auth'}})
    if final.exists():
        doc = checked_context(final / 'context.json', anchor, year)
        if doc.get('scope_id') != stable:
            raise FileExistsError('Existing context belongs to another scope')
        return {'status': 'reused', 'context_plan': str(final / 'context.json')}
    prepared = []
    for item in plan['sources']:
        unit = SourceUnit(**item['unit'])
        adapter = adapters[unit.source_id] if adapters else ContextAdapter(unit.source_id, hwsd_cache=plan['hwsd_cache'])
        if adapter.retries != 2:
            raise ValueError('Context workflow uses the reviewed two-retry policy')
        value = adapter.prepare(adapter.plan(unit, asset_root=cache), output_root=cache, credential_ref=req['credential_ref'])
        adapter.validate(value)
        prepared.append(value)
    final.parent.mkdir(parents=True, exist_ok=True)
    with tempfile.TemporaryDirectory(prefix='.assemble-context-', dir=final.parent) as temporary:
        stage = Path(temporary) / 'context'
        stage.mkdir()
        assets, states = [], []
        def add(path, name, source, role, kind=None):
            target = stage / name
            target.parent.mkdir(parents=True, exist_ok=True)
            shutil.copyfile(path, target)
            assets.append({'path': name, 'destination': name, 'source_id': source,
                           'role': role, 'kind': kind, 'sha256': checksum(target)})
        grid = Path(temporary) / 'grid.json'
        grid.write_text(json.dumps({'anchor': asdict(anchor_cell_from_id(anchor))}), encoding='utf-8')
        add(grid, 'metadata/grid.json', 'grid', 'metadata', 'grid')
        for value in prepared:
            source = value.unit.source_id
            metadata = dict(value.public_metadata)
            folder = 'annual' if source == 'mcd12q1' else 'static'
            names = []
            for path in value.files[:-1]:
                name = f'{folder}/{source}/{path.name}'
                add(path, name, source, 'annual_context' if folder == 'annual' else 'static_context')
                names.append(name)
            metadata.update(year=year, files=names)
            metadata.pop('assets')
            meta_path = Path(temporary) / f'{source}.json'
            meta_path.write_text(json.dumps(metadata, indent=2), encoding='utf-8')
            add(meta_path, f'metadata/source_manifests/{source}.json', source, 'metadata')
            states.append({'source': source, 'state': metadata['state'], 'reason': metadata['reason']})
        doc = {'anchor_id': anchor, 'year': year, 'release_id': plan['release_id'], 'scope_id': stable,
               'processing_version': 'sm-benchmark-agent-0.1.0.dev0', 'station_targets': 'absent',
               'assets': assets, 'availability': states + [{'source': 'ismn', 'state': 'unavailable', 'reason': 'absent_by_design'}]}
        (stage / 'context.json').write_text(json.dumps(doc, indent=2) + '\n', encoding='utf-8')
        checked_context(stage / 'context.json', anchor, year)
        if final.exists():
            raise FileExistsError('Context output appeared during assembly')
        stage.rename(final)
    return {'status': 'prepared', 'context_plan': str(final / 'context.json'), 'availability': states}


def global_plan(cache_root):
    root = Path(cache_root).resolve()
    prepared = root / HWSD2_SNAPSHOT_ID / 'prepared'
    record = hwsd_cache_record(prepared) if (prepared / 'prepared.manifest.json').exists() else None
    if record is None and prepared.exists() and any(prepared.iterdir()):
        raise ValueError('Incomplete HWSD2 prepared cache; inspect it before retrying global preparation')
    plan = {'schema': 'benchmark-hwsd-global-plan-v1', 'cache_root': str(root),
            'prepared_root': str(prepared), 'existing_inputs': record,
            'archive_sha256': [HWSD2_RASTER_SHA256, HWSD2_DATABASE_SHA256],
            'maximum_archive_downloads': 0 if record else 2,
            'download_bytes': None, 'scope': 'global raster and database; not a one-point download',
            'processing_code_sha256': processing_hashes()}
    return dict(plan, plan_id=identity(plan))


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    sub = parser.add_subparsers(dest='operation', required=True)
    context = sub.add_parser('prepare')
    context.add_argument('--request', type=Path, required=True)
    context.add_argument('--asset-root', type=Path, required=True)
    context.add_argument('--release-id', required=True)
    context.add_argument('--hwsd-cache', type=Path)
    global_cache = sub.add_parser('hwsd-global')
    global_cache.add_argument('--cache-root', type=Path, required=True)
    for command in (context, global_cache):
        command.add_argument('--execute', action='store_true')
        command.add_argument('--accept-plan')
    args = parser.parse_args()
    if args.accept_plan and not args.execute:
        parser.error('--accept-plan requires --execute')
    try:
        if args.operation == 'prepare':
            plan = plan_contexts(json.loads(args.request.read_text(encoding='utf-8')),
                                 asset_root=args.asset_root, release_id=args.release_id, hwsd_cache=args.hwsd_cache)
            result = execute_contexts(plan, accepted_plan_id=args.accept_plan) if args.execute else plan
        else:
            plan = global_plan(args.cache_root)
            result = plan
            if args.execute:
                verify_plan(plan, args.accept_plan)
                if plan['existing_inputs'] is None:
                    from .processing.srtm import _gdal_module
                    _gdal_module()
                    import access_parser
                    prepare_hwsd2_global(args.cache_root)
                hwsd_cache_record(plan['prepared_root'])
                result = {'status': 'verified', 'prepared_root': plan['prepared_root']}
    except Exception as exc:
        parser.exit(2, f'{type(exc).__name__}: context preparation did not complete; inspect configuration, dependencies and checkpoints.\n')
    print(json.dumps(result, indent=2, allow_nan=False))


if __name__ == '__main__':
    main()
