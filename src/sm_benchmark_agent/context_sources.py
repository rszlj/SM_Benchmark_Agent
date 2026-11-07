"""Reviewed static/annual context adapters, independent of production inventories."""
from dataclasses import asdict
import json
from pathlib import Path
import shutil
import tempfile
import tomllib
from urllib.request import urlopen

from .adapters import SourcePlan, PreparedSource, ValidationResult
from .archives import safe_relative
from .delivery import checksum
from .grid import anchor_cell_from_id, context_grid, ContextResolution
from .gldas21 import fetch_with_retry
from .gldas_workflow import check_public_metadata
from .processing import srtm, hwsd2, landcover

PROFILES = {
    'srtm': 'srtm-v1-horn-six-band',
    'hwsd2': 'hwsd2-v1-corrected-seven-layer',
    'mcd12q1': 'mcd12q1-v1-igbp-annual',
}
RESOLUTIONS = {'srtm': ('50 m', 20), 'hwsd2': ('1 km', 1), 'mcd12q1': ('500 m', 2)}
SCIENCE = {
    'srtm': {'product': 'USGS/SRTMGL1_003', 'temporal_support': 'static',
             'variables': list(srtm.SRTM_OUTPUT_BANDS),
             'units': ['m', 'degree', 'degree', 'dimensionless', 'dimensionless', 'dimensionless'],
             'processing': 'GDAL Horn in local azimuthal-equidistant CRS at 30 m; average to exact 50 m context; aspect from mean eastness/northness',
             'halo_m': 120},
    'hwsd2': {'product': 'FAO/IIASA HWSD 2.0 (2023-09-23)', 'temporal_support': 'static',
              'layers_cm': list(hwsd2.HWSD2_LAYERS), 'properties': list(hwsd2.HWSD2_NUMERIC_PROPERTIES),
              'units': 'Per-property units in raster band tags, retained from official database',
              'processing': 'Mode mapping units; share-weighted properties after excluding negative missing codes and renormalizing valid component shares; original component table retained'},
    'mcd12q1': {'product': landcover.COLLECTION, 'temporal_support': 'calendar year',
               'variables': ['LC_Type1'], 'units': ['IGBP class code 1-17'],
               'processing': 'Nearest-neighbour categorical reprojection to exact 500 m context; invalid source classes masked'},
}


def processing_hashes():
    root = Path(__file__).parent
    return {name: checksum(root / name) for name in
            ('context_sources.py', 'processing/srtm.py', 'processing/hwsd2.py',
             'processing/landcover.py', 'grid.py', 'gldas21.py')}


def hwsd_cache_record(prepared_root):
    """Validate prepared global inputs using the official preparation manifest."""
    if prepared_root is None:
        raise ValueError('HWSD2 requires a prepared global cache')
    root = Path(prepared_root)
    doc = json.loads((root / 'prepared.manifest.json').read_text(encoding='utf-8'))
    expected = {'global_raster': 'HWSD2_SMU_global_compressed.tif', 'sqlite_database': 'HWSD2.sqlite'}
    if doc['snapshot_id'] != hwsd2.HWSD2_SNAPSHOT_ID:
        raise ValueError('Wrong HWSD2 global snapshot')
    for key, digest in [('raster', hwsd2.HWSD2_RASTER_SHA256), ('database', hwsd2.HWSD2_DATABASE_SHA256)]:
        if doc['archives'][key]['sha256'] != digest:
            raise ValueError('Wrong HWSD2 archive identity')
    result = {}
    for key, name in expected.items():
        path = root / name
        digest = checksum(path)
        if digest != doc['prepared'][key]['sha256']:
            raise ValueError('HWSD2 prepared cache checksum mismatch')
        result[key] = {'name': name, 'sha256': digest}
    return result


def raw_checkpoint(root, key):
    if not root.exists():
        return None
    if {p.name for p in root.iterdir()} != {'input.tif', 'receipt.json'}:
        raise ValueError('Incomplete raw context checkpoint')
    record = json.loads((root / 'receipt.json').read_text(encoding='utf-8'))
    if record.get('work_key') != key or record.get('sha256') != checksum(root / 'input.tif'):
        raise ValueError('Raw context checkpoint mismatch')
    return record


class EarthEngineContexts:
    def __init__(self, credential_ref):
        if not credential_ref:
            raise ValueError('GEE configuration reference required')
        path = Path(credential_ref)
        if path.suffix.lower() == '.json':
            config = json.loads(path.read_text(encoding='utf-8'))
        else:
            with path.open('rb') as stream:
                config = tomllib.load(stream).get('gee', {})
        if (set(config) - {'project', 'auth_mode'} or not isinstance(config.get('project'), str)
                or not config['project'].strip() or config.get('auth_mode', 'interactive') != 'interactive'):
            raise ValueError('Expected authorized project and interactive GEE configuration')
        import ee
        fetch_with_retry(lambda: ee.Initialize(project=config['project']), retries=0)
        ee.data.setDeadline(60000)
        self.ee = ee

    def fetch(self, unit, context):
        ee = self.ee
        if unit.source_id == 'srtm':
            image = ee.Image(srtm.GEE_SRTM_IMAGE).select('elevation').unmask(srtm.SRTM_SOURCE_NODATA, False).toFloat()
            request = {'bands': ['elevation'], 'region': list(srtm._expanded_wgs84_bounds(context, srtm.SRTM_HALO_M)),
                       'crs': 'EPSG:4326', 'scale': srtm.SRTM_WORKING_RESOLUTION_M,
                       'format': 'GEO_TIFF', 'filePerBand': False}
        else:
            collection = ee.ImageCollection(landcover.COLLECTION).filterDate(
                f'{unit.year}-01-01', f'{unit.year + 1}-01-01').select('LC_Type1')
            count = int(collection.size().getInfo())
            if count == 0:
                return None
            if count != 1:
                raise ValueError('Expected exactly one annual land-cover image')
            image = ee.Image(collection.first())
            projection = image.projection().getInfo()
            from pyproj import Transformer
            b = context.bounds
            bounds = Transformer.from_crs(6933, landcover.NATIVE_CRS, always_xy=True).transform_bounds(
                b.xmin - 1000, b.ymin - 1000, b.xmax + 1000, b.ymax + 1000, densify_pts=41)
            request = {'bands': ['LC_Type1'], 'region': ee.Geometry.Rectangle(bounds, projection['crs'], False),
                       'crs': projection['crs'], 'crs_transform': projection['transform'],
                       'format': 'GEO_TIFF', 'filePerBand': False}
            image = image.unmask(255, False).toUint8()
        url = image.getDownloadURL(request)
        with urlopen(url, timeout=60) as response:
            payload = response.read()
        if not payload:
            raise ValueError('Empty raster download')
        return payload


class ContextAdapter:
    def __init__(self, source_id, *, provider=None, hwsd_cache=None, retries=2):
        self.source_id = source_id
        self.profile_id = PROFILES[source_id]
        self.provider = provider
        self.hwsd_cache = Path(hwsd_cache) if hwsd_cache is not None else None
        if type(retries) is not int or not 0 <= retries <= 3:
            raise ValueError('retries must be between zero and three')
        self.retries = retries

    def key(self, unit):
        anchor_cell_from_id(unit.anchor_id)
        if unit.source_id != self.source_id or unit.profile_id != self.profile_id:
            raise ValueError('Context source/profile mismatch')
        if type(unit.year) is not int or not 1 <= unit.year <= 9998:
            raise ValueError('Invalid context year')
        return f'{self.profile_id}/{unit.anchor_id}/' + (str(unit.year) if self.source_id == 'mcd12q1' else 'static')

    def context(self, unit):
        return context_grid(anchor_cell_from_id(unit.anchor_id), ContextResolution(*RESOLUTIONS[self.source_id]))

    def unavailable(self, unit):
        if self.source_id == 'mcd12q1' and unit.year < 2001:
            return 'outside_product_period'
        # Entire requested context is outside the documented SRTM latitude strip.
        if self.source_id == 'srtm':
            _, south, _, north = srtm._expanded_wgs84_bounds(self.context(unit), 0)
            if south > 60 or north < -56:
                return 'outside_product_extent'
        return None

    def plan(self, unit, *, asset_root):
        key = self.key(unit)
        output = Path(asset_root) / key / 'prepared'
        if output.exists():
            self.validate(self._prepared(unit, output))
            return SourcePlan(unit, 'reusable', 'validated_prepared_source', key, 0, 0)
        reason = self.unavailable(unit)
        if reason:
            return SourcePlan(unit, 'unavailable', reason, key, 0, 0)
        if self.source_id == 'hwsd2':
            if self.hwsd_cache is None:
                return SourcePlan(unit, 'requires_user_action', 'prepare_hwsd2_global_cache', key, 0, None)
            hwsd_cache_record(self.hwsd_cache)
            return SourcePlan(unit, 'retrievable', 'local_global_cache', key, 0, None)
        if raw_checkpoint(Path(asset_root) / key / 'raw', key):
            return SourcePlan(unit, 'retrievable', 'verified_raw_checkpoint; local derivation only', key, 0, 0)
        # Upper bound for metadata/URL/payload requests, excluding authentication.
        calls = (2 if self.source_id == 'srtm' else 4) * (self.retries + 1)
        return SourcePlan(unit, 'retrievable', 'authorized_GEE_required', key, calls, None)

    def _prepared(self, unit, root):
        doc = json.loads((root / 'manifest.json').read_text(encoding='utf-8'))
        files = tuple(root / safe_relative(e['path']) for e in doc['assets'])
        return PreparedSource(unit, files + (root / 'manifest.json',), doc)

    def prepare(self, plan, *, output_root, credential_ref=None):
        unit = plan.unit
        if plan.work_key != self.key(unit):
            raise ValueError('Context work key mismatch')
        final = Path(output_root) / plan.work_key / 'prepared'
        if final.exists():
            result = self._prepared(unit, final)
            self.validate(result)
            return result
        fresh = self.plan(unit, asset_root=output_root)
        if fresh.state == 'requires_user_action':
            raise ValueError(fresh.reason)
        # Verify imports before any provider request.
        import rasterio
        import numpy
        if self.source_id in {'srtm', 'hwsd2'}:
            srtm._gdal_module()
        final.parent.mkdir(parents=True, exist_ok=True)
        with tempfile.TemporaryDirectory(prefix='.context-', dir=final.parent) as temporary:
            scratch = Path(temporary)
            public = scratch / 'public'
            public.mkdir()
            context = self.context(unit)
            reason = self.unavailable(unit)
            raw_files = []
            provenance = {}
            if not reason and self.source_id == 'hwsd2':
                provenance = {'global_inputs': hwsd_cache_record(self.hwsd_cache)}
                try:
                    outputs = hwsd2.extract_hwsd2_tile(
                        global_raster=self.hwsd_cache / 'HWSD2_SMU_global_compressed.tif',
                        sqlite_database=self.hwsd_cache / 'HWSD2.sqlite', context=context,
                        output_root=scratch, snapshot_id=self.profile_id, tile_directory=scratch / 'soil')
                    raw_files = [outputs[k] for k in ('smu_raster', 'properties_raster', 'components_csv')]
                except hwsd2.HWSD2NoSoilDataError:
                    reason = 'no_soil_mapping_units'
            elif not reason:
                # Download once into an immutable raw checkpoint before derivation.
                raw_root = final.parent / 'raw'
                payload_file, receipt = raw_root / 'input.tif', raw_root / 'receipt.json'
                if raw_checkpoint(raw_root, plan.work_key):
                    payload = payload_file.read_bytes()
                elif raw_root.exists():
                    raise ValueError('Incomplete raw context checkpoint; inspect before retry')
                else:
                    provider = self.provider or EarthEngineContexts(credential_ref)
                    payload = fetch_with_retry(lambda: provider.fetch(unit, context), retries=self.retries)
                    if payload is not None:
                        # Validate decoding before persisting a successful download.
                        from rasterio.io import MemoryFile
                        with MemoryFile(payload) as memory, memory.open() as raster:
                            if raster.count != 1 or raster.crs is None:
                                raise ValueError('Expected one georeferenced raw band')
                            raster.read()
                        with tempfile.TemporaryDirectory(prefix='.raw-', dir=final.parent) as stage:
                            staged = Path(stage) / 'raw'
                            staged.mkdir()
                            (staged / 'input.tif').write_bytes(payload)
                            (staged / 'receipt.json').write_text(json.dumps({
                                'work_key': plan.work_key, 'sha256': checksum(staged / 'input.tif')}), encoding='utf-8')
                            if raw_root.exists():
                                raise FileExistsError('Raw checkpoint appeared during retrieval')
                            staged.rename(raw_root)
                if payload is None:
                    reason = 'no_provider_image'
                else:
                    provenance = {'raw_sha256': checksum(payload_file)}
                    raw = scratch / 'derived.tif'
                    if self.source_id == 'srtm':
                        srtm.derive_srtm_terrain(payload_file, raw, context)
                        raw = raw.rename(scratch / 'srtm_terrain_50m_EPSG6933.tif')
                    else:
                        landcover.derive_landcover(payload, raw, context, unit.year)
                        raw = raw.rename(scratch / f'mcd12q1_lc_type1_{unit.year}_500m_EPSG6933.tif')
                    raw_files = [raw]
            for raw in raw_files:
                target = public / raw.name
                if raw.suffix == '.tif':
                    landcover.public_raster(raw, target)
                else:
                    shutil.copyfile(raw, target)
            stats = raster_stats(public, context, self.source_id, unit.year)
            state = 'unavailable' if reason or not stats['valid_values'] else 'partial' if stats['missing_values'] else 'available'
            if state == 'unavailable':
                reason = reason or 'no_valid_values'
                for path in public.iterdir():
                    path.unlink()
            metadata = {'schema': 'benchmark-context-source-v1', 'source_id': self.source_id,
                        'profile_id': self.profile_id, 'anchor_id': unit.anchor_id,
                        'year': unit.year if self.source_id == 'mcd12q1' else None,
                        'state': state, 'reason': reason or ('masked_values' if state == 'partial' else None),
                        'science': SCIENCE[self.source_id], 'missing_representation': 'float32 / IEEE NaN; source masks decoded before conversion',
                        'grid': asdict(context), 'processing_code_sha256': processing_hashes(),
                        'provenance': provenance, 'statistics': stats,
                        'assets': [{'path': p.name, 'sha256': checksum(p), 'bytes': p.stat().st_size}
                                   for p in sorted(public.iterdir())]}
            check_public_metadata(metadata)
            (public / 'manifest.json').write_text(json.dumps(metadata, indent=2) + '\n', encoding='utf-8')
            self.validate(self._prepared(unit, public))
            if final.exists():
                raise FileExistsError('Context output appeared during preparation')
            public.rename(final)
        return self._prepared(unit, final)

    def validate(self, prepared):
        self.key(prepared.unit)
        root = prepared.files[-1].parent
        doc = json.loads(prepared.files[-1].read_text(encoding='utf-8'))
        check_public_metadata(doc)
        expected_year = prepared.unit.year if self.source_id == 'mcd12q1' else None
        if (doc['source_id'], doc['profile_id'], doc['anchor_id'], doc['year']) != (
                self.source_id, self.profile_id, prepared.unit.anchor_id, expected_year):
            raise ValueError('Prepared context identity mismatch')
        if doc['processing_code_sha256'] != processing_hashes() or doc['grid'] != asdict(self.context(prepared.unit)):
            raise ValueError('Prepared context profile/code/grid changed')
        if doc['science'] != json.loads(json.dumps(SCIENCE[self.source_id])):
            raise ValueError('Prepared context scientific profile mismatch')
        names = [a['path'] for a in doc['assets']]
        if len(set(names)) != len(names) or {p.name for p in root.iterdir()} != set(names) | {'manifest.json'}:
            raise ValueError('Prepared context membership mismatch')
        for asset in doc['assets']:
            path = root / safe_relative(asset['path'])
            if path.is_symlink() or checksum(path) != asset['sha256'] or path.stat().st_size != asset['bytes']:
                raise ValueError('Prepared context checksum mismatch')
        stats = raster_stats(root, self.context(prepared.unit), self.source_id, prepared.unit.year)
        if doc['state'] == 'unavailable':
            if names or not doc['reason']:
                raise ValueError('Unavailable context must have reason and no assets')
        else:
            expected_state = 'partial' if stats['missing_values'] else 'available'
            if not stats['valid_values'] or doc['state'] != expected_state or doc['statistics'] != stats:
                raise ValueError('Prepared context availability/statistics mismatch')
            if self.source_id == 'hwsd2':
                expected_names = {'hwsd2_smu_1km_EPSG6933.tif', 'hwsd2_properties_7layers_1km_EPSG6933.tif',
                                  'hwsd2_components_7layers.csv'}
            elif self.source_id == 'srtm':
                expected_names = {'srtm_terrain_50m_EPSG6933.tif'}
            else:
                expected_names = {f'mcd12q1_lc_type1_{prepared.unit.year}_500m_EPSG6933.tif'}
            if set(names) != expected_names:
                raise ValueError('Prepared context file profile mismatch')
        return ValidationResult(True, {'identity': 'passed', 'hashes': 'passed', 'grid_bands_values': 'passed'},
                                (doc['reason'],) if doc['reason'] else ())


def raster_stats(root, context, source_id, year):
    import numpy as np
    import rasterio
    from affine import Affine
    from .processing.hwsd2 import HWSD2_LAYERS, HWSD2_NUMERIC_PROPERTIES
    expected_bands = {
        'srtm': [srtm.SRTM_OUTPUT_BANDS],
        'mcd12q1': [(f'{year}_LC_Type1',)],
        'hwsd2': [('HWSD2_SMU_ID',), tuple(f'{l}_{top}-{bottom}cm_{p}' for l, top, bottom in HWSD2_LAYERS for p in HWSD2_NUMERIC_PROPERTIES)],
    }[source_id]
    valid = missing = 0
    descriptions = []
    for path in sorted(root.glob('*.tif')):
        with rasterio.open(path) as raster:
            transform = Affine(context.exact_spacing_m, 0, context.upper_left_x_m, 0, -context.exact_spacing_m, context.upper_left_y_m)
            if (raster.crs is None or raster.crs.to_epsg() != 6933 or raster.shape != (context.rows, context.columns)
                    or not raster.transform.almost_equals(transform, precision=1e-6)
                    or any(d != 'float32' for d in raster.dtypes)
                    or any(n is None or not np.isnan(n) for n in raster.nodatavals)):
                raise ValueError('Context raster grid/type/mask mismatch')
            descriptions.append(raster.descriptions)
            values = raster.read()
            if np.isinf(values).any():
                raise ValueError('Infinite context value')
            finite = values[np.isfinite(values)]
            if source_id == 'mcd12q1' and not np.isin(finite, np.arange(1, 18)).all():
                raise ValueError('Invalid land-cover class')
            valid += int(np.isfinite(values).sum())
            missing += int(np.isnan(values).sum())
    if descriptions and sorted(descriptions) != sorted(expected_bands):
        raise ValueError('Context source band profile mismatch')
    return {'valid_values': valid, 'missing_values': missing}
