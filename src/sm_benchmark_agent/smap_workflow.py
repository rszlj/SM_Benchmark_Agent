"""One anchor/year SMAPL4 preparation and station-free annual assembly."""
import argparse
from dataclasses import asdict
import json
from pathlib import Path
import tempfile
import zipfile

from .adapters import SourceUnit
from .archives import verify_archive
from .delivery import checksum, export_gridded_archive
from .extension_agent import normalize_request, identity
from .gldas_workflow import checked_context, CONTEXT_SOURCES
from .smap_sources import SMAPL4Adapter, PROFILES, code_hashes, profile


def workflow_hashes():
    root = Path(__file__).parent
    return {**code_hashes(), **{n: checksum(root / n) for n in
            ('smap_workflow.py', 'delivery.py', 'archives.py', 'gldas_workflow.py', 'extension_agent.py')}}


def plan_smap(request, *, context_plan, asset_root, adapters=None):
    req = normalize_request(request)
    if req['requested_period'] is not None:
        raise ValueError('Use sm-benchmark-prepare for exact date-range preparation')
    selected = sorted(set(req['sources']) & set(PROFILES))
    if (len(req['anchor_ids']) != 1 or len(req['years']) != 1 or req['station_targets'] != 'absent'
            or not selected or set(req['sources']) - (set(PROFILES) | CONTEXT_SOURCES)):
        raise ValueError('SMAPL4 workflow requires one anchor/year, absent targets, and selected SMAPL4 sources with optional context sources')
    anchor, year = req['anchor_ids'][0], req['years'][0]
    context = checked_context(context_plan, anchor, year)
    sources = []
    for source in selected:
        adapter = adapters[source] if adapters else SMAPL4Adapter(source)
        sources.append(asdict(adapter.plan(SourceUnit(source, PROFILES[source], anchor, year), asset_root=asset_root)))
    plan = {'schema': 'benchmark-smap-extension-plan-v1', 'request': req,
            'context_plan': str(Path(context_plan).resolve()), 'context_sha256': checksum(Path(context_plan)),
            'context_assets': [{'destination': a['destination'], 'sha256': a['sha256']} for a in context['assets']],
            'release_id': context['release_id'], 'asset_root': str(Path(asset_root).resolve()),
            'processing_code_sha256': workflow_hashes(), 'sources': sources, 'retry_limit': 2,
            'included_context_sources': sorted(CONTEXT_SOURCES),
            'source_profiles': [profile(SourceUnit(**s['unit'])) for s in sources],
            'maximum_provider_operations_excluding_auth': sum(s['remote_operations'] or 0 for s in sources),
            'download_bytes': None}
    return dict(plan, plan_id=identity(plan))


def execute_smap(plan, *, accepted_plan_id, adapters=None):
    if accepted_plan_id != plan['plan_id'] or identity({k: v for k, v in plan.items() if k != 'plan_id'}) != plan['plan_id']:
        raise ValueError('Execution requires unchanged reviewed plan ID')
    if workflow_hashes() != plan['processing_code_sha256'] or checksum(Path(plan['context_plan'])) != plan['context_sha256']:
        raise ValueError('Processing code or context plan changed after review')
    req = plan['request']
    anchor, year = req['anchor_ids'][0], req['years'][0]
    context = checked_context(plan['context_plan'], anchor, year)
    root, cache = Path(req['output_root']).resolve(), Path(plan['asset_root'])
    if root == cache or root.is_relative_to(cache):
        raise ValueError('Delivery must be outside the source cache')
    stable = identity({k: v for k, v in plan.items() if k not in {'plan_id', 'sources', 'maximum_provider_operations_excluding_auth'}})
    target = root / 'packages' / anchor / f'{year}.zip'
    if target.exists():
        verify_archive(target, anchor_id=anchor, year=year)
        with zipfile.ZipFile(target) as archive:
            provenance = json.loads(archive.read('metadata/smap_extension.json'))
            if provenance['scope_id'] != stable:
                raise FileExistsError('Existing package belongs to another scope')
        return {'status': 'reused', 'archive': str(target), 'sha256': checksum(target)}
    prepared = []
    for item in plan['sources']:
        unit = SourceUnit(**item['unit'])
        adapter = adapters[unit.source_id] if adapters else SMAPL4Adapter(unit.source_id)
        if adapter.retries != plan['retry_limit']:
            raise ValueError('SMAPL4 retry policy changed after review')
        output = adapter.prepare(adapter.plan(unit, asset_root=cache), output_root=cache, credential_ref=req['credential_ref'])
        adapter.validate(output)
        prepared.append(output)
    root.mkdir(parents=True, exist_ok=True)
    with tempfile.TemporaryDirectory(prefix='.smap-', dir=root) as temporary:
        stage = Path(temporary)
        assets, availability = list(context['assets']), list(context['availability'])
        for output in prepared:
            source = output.unit.source_id
            names = []
            for path in output.files[:-1]:
                name = 'source_cell_time_series/smap_l4/smap_l4_3hourly.parquet'
                names.append(name)
                assets.append({'path': str(path.resolve()), 'destination': name, 'role': 'source_cell_time_series',
                               'source_id': source, 'sha256': checksum(path)})
            metadata = dict(output.public_metadata, files=names)
            metadata.pop('file')
            metadata['anchor_id'] = anchor
            path = stage / f'{source}.json'
            path.write_text(json.dumps(metadata, indent=2), encoding='utf-8')
            assets.append({'path': str(path), 'destination': f'metadata/source_manifests/{source}.json',
                           'source_id': source, 'role': 'metadata', 'sha256': checksum(path)})
            availability.append({'source': source, 'state': metadata['state'], 'reason': metadata['reason']})
        path = stage / 'provenance.json'
        path.write_text(json.dumps({'scope_id': stable, 'release_id': plan['release_id'],
                                    'processing_code_sha256': workflow_hashes(),
                                    'temporal_policy': 'V1 three-hour calendar; missing slots are null, never interpolated'}, indent=2), encoding='utf-8')
        assets.append({'path': str(path), 'destination': 'metadata/smap_extension.json', 'source_id': 'smap-extension',
                       'role': 'metadata', 'sha256': checksum(path)})
        delivery = dict(context, assets=assets, availability=availability, processing_version='sm-benchmark-agent-0.1.0.dev0')
        path = stage / 'plan.json'
        path.write_text(json.dumps(delivery, indent=2), encoding='utf-8')
        export_gridded_archive(path, root, dry_run=False)
    return {'status': 'packaged', 'archive': str(target), 'sha256': checksum(target), 'availability': availability}


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
        plan = plan_smap(json.loads(args.request.read_text(encoding='utf-8')), context_plan=args.context_plan, asset_root=args.asset_root)
        result = execute_smap(plan, accepted_plan_id=args.accept_plan) if args.execute else plan
    except Exception as exc:
        parser.exit(2, f'{type(exc).__name__}: SMAPL4 workflow did not complete; inspect scope, dependencies and checkpoints.\n')
    print(json.dumps(result, indent=2, allow_nan=False))


if __name__ == '__main__':
    main()
