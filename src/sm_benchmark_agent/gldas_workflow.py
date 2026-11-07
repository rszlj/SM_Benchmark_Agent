"""Bounded GLDAS pilot within the extension agent, with explicit annual contexts."""
from contextlib import closing
from dataclasses import asdict
import json
import re
from pathlib import Path
import sqlite3
import tempfile
import zipfile

from .adapters import SourceUnit
from .archives import verify_archive
from .delivery import checksum, export_gridded_archive, validate_plan
from .extension_agent import identity, normalize_request
from .gldas21 import GLDAS21Adapter, PROFILE
from .grid import anchor_cell_from_id, context_grid, ContextResolution

CONTEXT_SOURCES = {'srtm', 'hwsd2', 'mcd12q1'}


def check_public_metadata(value):
    if isinstance(value, dict):
        if {str(k).lower() for k in value} & {'project', 'project_id', 'account', 'credentials', 'token', 'access_token', 'private_key', 'client_email'}:
            raise ValueError('Private provider fields are forbidden in context metadata')
        for child in value.values():
            check_public_metadata(child)
    elif isinstance(value, list):
        for child in value:
            check_public_metadata(child)
    elif isinstance(value, str) and re.match(r'^(?:[A-Za-z]:[\\/]|\\\\|/(?:Users|home|mnt|tmp|Volumes)/)', value):
        raise ValueError('Private absolute paths are forbidden in context metadata')


def checked_context(path, anchor_id, year):
    """Require explicit public context assets; verify hashes and exact raster grids.

    This validates the selected prepared context, not the upstream derivations.
    Source-specific processing provenance must accompany the supplied assets.
    """
    path = Path(path).resolve()
    doc = json.loads(path.read_text(encoding='utf-8'))
    if doc.get('anchor_id') != anchor_id or doc.get('year') != year or doc.get('station_targets') != 'absent':
        raise ValueError('Context plan must match the anchor/year and declare absent station targets')
    if not doc.get('release_id') or doc['release_id'].startswith('benchmark-initial-'):
        raise ValueError('An extension needs a distinct release identifier')
    # A context-only plan may have no raster inputs when every context source is
    # explicitly unavailable. The GLDAS input is added before final validation.
    assets = validate_plan(dict(doc, station_targets='optional'), path.parent)
    states = {r['source']: r for r in doc['availability']}
    if len(states) != len(doc['availability']) or set(states) != CONTEXT_SOURCES | {'ismn'}:
        raise ValueError('Context plan requires exactly SRTM, HWSD2, MCD12Q1 and absent ISMN availability')
    anchor = anchor_cell_from_id(anchor_id)
    present = set()
    manifests = set()
    grid_count = 0
    data_names = {s: set() for s in CONTEXT_SOURCES}
    declared_names = {}
    bound_assets = []
    for entry, source, destination in assets:
        if entry.get('sha256') != checksum(source):
            raise ValueError('Context assets require matching explicit SHA-256 values')
        name = destination.as_posix()
        source_id = entry['source_id']
        if name == 'metadata/grid.json' and entry.get('kind') == 'grid':
            if entry['role'] != 'metadata':
                raise ValueError('Grid must be metadata')
            grid = json.loads(source.read_text(encoding='utf-8'))
            check_public_metadata(grid)
            if grid['anchor'] != asdict(anchor):
                raise ValueError('Context grid anchor metadata mismatch')
            grid_count += 1
        elif name == f'metadata/source_manifests/{source_id}.json' and source_id in CONTEXT_SOURCES:
            if entry['role'] != 'metadata':
                raise ValueError('Source manifest must be metadata')
            metadata = json.loads(source.read_text(encoding='utf-8'))
            check_public_metadata(metadata)
            if metadata.get('source_id') != source_id or metadata.get('anchor_id') != anchor_id or metadata.get('year') != year:
                raise ValueError('Context source metadata identity mismatch')
            if metadata.get('state') != states[source_id]['state']:
                raise ValueError('Context source metadata availability mismatch')
            manifests.add(source_id)
            declared_names[source_id] = set(metadata.get('files', []))
        elif source_id in CONTEXT_SOURCES and (name.startswith(f'static/{source_id}/') if source_id != 'mcd12q1' else name.startswith('annual/mcd12q1/')):
            if entry['role'] != ('annual_context' if source_id == 'mcd12q1' else 'static_context'):
                raise ValueError('Context data role mismatch')
            present.add(source_id)
            data_names[source_id].add(name)
            if source.suffix.lower() == '.tif':
                import rasterio
                import math
                subdivisions = {'srtm': 20, 'hwsd2': 1, 'mcd12q1': 2}[source_id]
                grid = context_grid(anchor, ContextResolution('context', subdivisions))
                with rasterio.open(source) as raster:
                    expected = (grid.bounds.xmin, grid.bounds.ymin, grid.bounds.xmax, grid.bounds.ymax)
                    if raster.crs is None or raster.crs.to_epsg() != 6933 or (raster.height, raster.width) != (grid.rows, grid.columns):
                        raise ValueError('Context raster CRS/dimensions mismatch')
                    if not all(math.isclose(a, b, rel_tol=0, abs_tol=1e-6) for a, b in zip(raster.bounds, expected)):
                        raise ValueError('Context raster bounds mismatch')
                    from affine import Affine
                    if not raster.transform.almost_equals(Affine(grid.exact_spacing_m, 0, grid.upper_left_x_m,
                                                                0, -grid.exact_spacing_m, grid.upper_left_y_m)):
                        raise ValueError('Context raster alignment mismatch')
                    if any(dtype != 'float32' for dtype in raster.dtypes) or any(v is None or not math.isnan(v) for v in raster.nodatavals):
                        raise ValueError('Context raster must use float32/NaN')
                    raster.read()
            elif not (source_id == 'hwsd2' and source.suffix.lower() == '.csv'):
                raise ValueError('Unsupported prepared context asset type')
        else:
            raise ValueError('Unreviewed file in context asset plan')
        bound_assets.append(dict(entry, path=str(source)))
    if grid_count != 1 or manifests != CONTEXT_SOURCES:
        raise ValueError('Exact grid and public metadata for every context source are required')
    for source_id in CONTEXT_SOURCES:
        if data_names[source_id] != declared_names[source_id]:
            raise ValueError('Context data membership differs from source manifest')
        state = states[source_id]['state']
        if state not in {'available', 'partial', 'unavailable'}:
            raise ValueError('Context source must be prepared or explicitly unavailable')
        if (state in {'available', 'partial'}) != (source_id in present):
            raise ValueError('Context data files do not match declared availability')
    return dict(doc, assets=bound_assets)


def plan_gldas(request, *, context_plan, asset_root, adapter=None):
    normalized = normalize_request(request)
    if normalized['requested_period'] is not None:
        raise ValueError('Use sm-benchmark-prepare for exact date-range preparation')
    if normalized['station_targets'] != 'absent' or set(normalized['sources']) != CONTEXT_SOURCES | {'gldas21'}:
        raise ValueError('GLDAS pilot requires absent targets and exactly gldas21, srtm, hwsd2, mcd12q1 sources')
    if len(normalized['anchor_ids']) != 1 or len(normalized['years']) != 1:
        raise ValueError('Pilot execution is bounded to one anchor and one year')
    anchor_id, year = normalized['anchor_ids'][0], normalized['years'][0]
    adapter = adapter or GLDAS21Adapter()
    context = checked_context(context_plan, anchor_id, year)
    source = adapter.plan(SourceUnit('gldas21', PROFILE, anchor_id, year), asset_root=asset_root)
    plan = {'schema': 'benchmark-gldas-extension-plan-v1', 'request': normalized,
            'context_plan': str(Path(context_plan).resolve()),
            'context_sha256': checksum(Path(context_plan)),
            'context_assets': [{'destination': a['destination'], 'sha256': a['sha256']} for a in context['assets']],
            'asset_root': str(Path(asset_root).resolve()), 'source': asdict(source),
            'retry_limit': adapter.retries, 'release_id': context['release_id'],
            'remote_scope': {'native_cells': 1, 'calendar_years': 1, 'variables': 4,
                             'maximum_data_calls_including_retries': source.remote_operations,
                             'authentication': 'official user sign-in and configured project required for missing months',
                             'download_bytes': None},
            'processing_code_sha256': code_hashes()}
    return dict(plan, plan_id=identity(plan))


def code_hashes():
    return {name: checksum(Path(__file__).with_name(name)) for name in
            ('gldas21.py', 'gldas_workflow.py', 'extension_agent.py', 'adapters.py',
             'grid.py', 'native_cells.py', 'delivery.py', 'archives.py')}


def execute_gldas(plan, *, accepted_plan_id, adapter=None):
    if accepted_plan_id != plan['plan_id'] or identity({k: v for k, v in plan.items() if k != 'plan_id'}) != plan['plan_id']:
        raise ValueError('Execution requires the unchanged reviewed plan ID')
    if plan['processing_code_sha256'] != code_hashes():
        raise ValueError('Processing code changed after planning')
    if checksum(Path(plan['context_plan'])) != plan['context_sha256']:
        raise ValueError('Context plan changed after review')
    request = plan['request']
    anchor_id, year = request['anchor_ids'][0], request['years'][0]
    context = checked_context(plan['context_plan'], anchor_id, year)
    root = Path(request['output_root']).resolve()
    if root == Path(plan['asset_root']) or root.is_relative_to(Path(plan['asset_root'])):
        raise ValueError('Delivery output must be outside the prepared-source cache')
    target = root / 'packages' / anchor_id / f'{year}.zip'
    # Stable scope identity excludes transient checkpoint progress estimates.
    scope = identity({'request': request, 'context_sha256': plan['context_sha256'],
                      'context_assets': plan['context_assets'], 'profile': PROFILE,
                      'processing_code_sha256': plan['processing_code_sha256']})
    if target.exists():
        verify_archive(target, anchor_id=anchor_id, year=year)
        with zipfile.ZipFile(target) as archive:
            provenance = json.loads(archive.read('metadata/extension.json'))
            if provenance['scope_id'] != scope:
                raise FileExistsError('Existing package belongs to another extension scope')
        return {'status': 'reused', 'archive': str(target), 'sha256': checksum(target)}
    if plan['source']['state'] == 'unavailable':
        raise ValueError('GLDAS period is outside the selected product coverage')
    adapter = adapter or GLDAS21Adapter(retries=plan['retry_limit'])
    if adapter.retries != plan['retry_limit']:
        raise ValueError('Retry policy changed after planning')
    root.mkdir(parents=True, exist_ok=True)
    with closing(sqlite3.connect(root / 'extension_state.sqlite')) as db:
        db.execute('CREATE TABLE IF NOT EXISTS source_runs (scope_id TEXT PRIMARY KEY, state TEXT, reason TEXT)')
        def record(state, reason=None):
            db.execute('INSERT OR REPLACE INTO source_runs VALUES (?,?,?)', (scope, state, reason))
            db.commit()
        record('running')
        try:
            unit = SourceUnit('gldas21', PROFILE, anchor_id, year)
            source_plan = adapter.plan(unit, asset_root=plan['asset_root'])
            prepared = adapter.prepare(source_plan, output_root=plan['asset_root'], credential_ref=request['credential_ref'])
            validation = adapter.validate(prepared)
            if not validation.passed:
                raise ValueError('GLDAS scientific validation failed')
            record('verified')
            with tempfile.TemporaryDirectory(prefix='.assembly-', dir=root) as temporary:
                staging = Path(temporary)
                relative_data = f'source_cell_time_series/gldas21/gldas21_{year}_native_pixel_3hourly.parquet'
                metadata = dict(prepared.public_metadata, anchor_id=anchor_id, file=relative_data)
                (staging / 'gldas21.json').write_text(json.dumps(metadata, indent=2) + '\n', encoding='utf-8')
                provenance = {'scope_id': scope, 'profile_id': PROFILE, 'release_id': plan['release_id'],
                              'processing_code_sha256': plan['processing_code_sha256'],
                              'validation': asdict(validation), 'context_validation': 'hashes, source identity and raster grid; upstream scientific derivations not rerun'}
                (staging / 'extension.json').write_text(json.dumps(provenance, indent=2) + '\n', encoding='utf-8')
                assets = list(context['assets'])
                for path, destination, role in [(prepared.files[0], relative_data, 'source_cell_time_series'),
                                               (staging / 'gldas21.json', 'metadata/source_manifests/gldas21.json', 'metadata'),
                                               (staging / 'extension.json', 'metadata/extension.json', 'metadata')]:
                    assets.append({'path': str(path.resolve()), 'destination': destination, 'role': role,
                                   'source_id': PROFILE, 'sha256': checksum(path)})
                availability = list(context['availability']) + [{'source': 'gldas21', 'state': metadata['state'], 'reason': metadata['reason']}]
                delivery = dict(context, processing_version='sm-benchmark-agent-0.1.0.dev0',
                                assets=assets, availability=availability)
                path = staging / 'plan.json'
                path.write_text(json.dumps(delivery, indent=2) + '\n', encoding='utf-8')
                export_gridded_archive(path, root, dry_run=False)
            record('packaged', metadata['state'])
            return {'status': 'packaged', 'archive': str(target), 'sha256': checksum(target),
                    'source_availability': metadata['state'], 'validation': asdict(validation)}
        except Exception as exc:
            record('failed', type(exc).__name__)
            raise


