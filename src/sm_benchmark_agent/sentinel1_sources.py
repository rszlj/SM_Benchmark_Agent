"""Bounded V1 Sentinel-1 50 m acquisition preparation and annual validation."""
from dataclasses import asdict
from datetime import datetime, timezone
import json
import os
from pathlib import Path
import re
import tempfile
import time
from urllib.request import urlopen

from . import periods
from .adapters import PreparedSource, SourcePlan, ValidationResult
from .delivery import checksum
from .gldas21 import EarthEngineGLDAS, fetch_with_retry, digest, write_json_exclusive
from .grid import anchor_cell_from_id, context_grid, ContextResolution
from .processing.srtm import _expanded_wgs84_bounds

PROFILE = 'sentinel1-grd-iw-50m-v1'
PROFILES = {'sentinel1': PROFILE}
COLLECTION = 'COPERNICUS/S1_GRD'
MAX_SCENES = 4096
MAX_ACQUISITIONS = 512
MAX_PAYLOAD = 4 * 1024 * 1024
FIELDS = ['system:index', 'system:time_start', 'instrumentMode', 'resolution_meters',
          'transmitterReceiverPolarisation', 'orbitProperties_pass',
          'relativeOrbitNumber_start', 'orbitNumber_start', 'platform_number']


def code_hashes():
    root = Path(__file__).parent
    return {n: checksum(root / n) for n in ('periods.py', 'sentinel1_sources.py', 'processing/sentinel1.py',
            'processing/srtm.py', 'grid.py', 'gldas21.py')}


def grid(unit):
    return context_grid(anchor_cell_from_id(unit.anchor_id), ContextResolution('50 m', 20))


def profile(unit):
    return {**periods.metadata(unit), 'source_id': 'sentinel1', 'profile_id': PROFILE, 'anchor_id': unit.anchor_id,
            'year': unit.year, 'collection': COLLECTION, 'target_grid': asdict(grid(unit)),
            'selection': 'IW, 10 m input resolution, VV present; both passes; VH when common to all slices',
            'grouping': 'platform, absolute orbit, pass; earliest slice time; relative orbit retained',
            'bands': ['VV', 'VH', 'angle'], 'units': {'VV': 'dB', 'VH': 'dB', 'angle': 'degree'},
            'aggregation': {'backscatter': 'linear power mean then 10log10', 'angle': 'arithmetic mean degrees'},
            'temporal_support': 'individual physical overpasses; no temporal compositing',
            'missing_policy': 'masked pixels and absent VH remain NaN; no interpolation or filling'}


def key(unit):
    if unit.source_id != 'sentinel1' or unit.profile_id != PROFILE or type(unit.year) is not int or not 1 <= unit.year <= 9998:
        raise ValueError('Invalid Sentinel-1 unit')
    anchor_cell_from_id(unit.anchor_id)
    return f'{PROFILE}/{unit.anchor_id}/{unit.year}' + periods.suffix(unit)


def acquisitions(records, unit):
    from .processing.sentinel1 import Sentinel1Slice, group_sentinel1_slices
    if not isinstance(records, list) or len(records) > MAX_SCENES:
        raise ValueError('Discovery exceeds scene limit')
    clean, seen = [], set()
    for row in records:
        if set(row) != set(FIELDS):
            raise ValueError('Discovery property schema mismatch')
        name = row['system:index']
        if not isinstance(name, str) or not re.fullmatch(r'[A-Za-z0-9_-]{1,135}', name) or name in seen:
            raise ValueError('Invalid or duplicate scene identity')
        seen.add(name)
        stamp = row['system:time_start']
        if type(stamp) is not int or not periods.contains(unit, datetime.fromtimestamp(stamp / 1000, timezone.utc)):
            raise ValueError('Scene timestamp outside requested year')
        if row['instrumentMode'] != 'IW' or row['resolution_meters'] != 10:
            raise ValueError('Unexpected scene mode/resolution')
        pol = row['transmitterReceiverPolarisation']
        if not isinstance(pol, list) or 'VV' not in pol or len(pol) != len(set(pol)) or set(pol) - {'VV', 'VH'}:
            raise ValueError('Unexpected scene polarization')
        if row['orbitProperties_pass'] not in ('ASCENDING', 'DESCENDING') or row['platform_number'] not in ('A', 'B', 'C', 'D'):
            raise ValueError('Invalid pass/platform')
        for name, maximum in [('relativeOrbitNumber_start', 175), ('orbitNumber_start', 999999)]:
            if type(row[name]) is not int or not 1 <= row[name] <= maximum:
                raise ValueError('Invalid orbit number')
        clean.append(dict(row))
    if unit.year < 2014 and clean:
        raise ValueError('Scenes before product period')
    slices = [Sentinel1Slice(COLLECTION + '/' + r['system:index'], r['system:time_start'],
              r['orbitProperties_pass'], r['relativeOrbitNumber_start'], r['orbitNumber_start'], r['platform_number']) for r in clean]
    grouped = group_sentinel1_slices(slices)
    if len(grouped) > MAX_ACQUISITIONS:
        raise ValueError('Discovery exceeds acquisition limit; review a bounded scope')
    by_id = {COLLECTION + '/' + r['system:index']: r for r in clean}
    result = []
    for group in grouped:
        d = asdict(group)
        d['scene_ids'] = list(d['scene_ids'])
        d['bands'] = ['VV'] + (['VH'] if all('VH' in by_id[s]['transmitterReceiverPolarisation'] for s in group.scene_ids) else []) + ['angle']
        result.append(d)
    return result


class EarthEngineSentinel1(EarthEngineGLDAS):
    def discover(self, unit):
        ee = self.ee
        bounds = _expanded_wgs84_bounds(grid(unit), 0)
        collection = (ee.ImageCollection(COLLECTION).filterBounds(ee.Geometry.Rectangle(bounds))
            .filterDate(*(d.isoformat() for d in periods.bounds(unit)))
            .filter(ee.Filter.eq('instrumentMode', 'IW')).filter(ee.Filter.eq('resolution_meters', 10))
            .filter(ee.Filter.listContains('transmitterReceiverPolarisation', 'VV')).sort('system:time_start'))
        # A single bounded metadata evaluation; no query during offline plan.
        return collection.toList(MAX_SCENES + 1).map(lambda im: ee.Image(im).toDictionary(FIELDS)).getInfo()

    def fetch(self, unit, acquisition):
        from pyproj import CRS
        ee, context = self.ee, grid(unit)
        images = [ee.Image(s) for s in acquisition['scene_ids']]
        image = ee.ImageCollection(images).mosaic().setDefaultProjection(images[0].select('VV').projection())
        radar = [b for b in acquisition['bands'] if b != 'angle']
        linear = ee.Image.constant(10.0).pow(image.select(radar).divide(10.0)).rename(radar).addBands(image.select('angle'))
        averaged = linear.reduceResolution(reducer=ee.Reducer.mean(), bestEffort=False, maxPixels=256)
        export = (averaged.select(radar).log10().multiply(10.0).addBands(averaged.select('angle'))
                  .select(acquisition['bands']).unmask(-9999.0, False).toFloat())
        url = export.getDownloadURL({'bands': acquisition['bands'], 'dimensions': [context.columns, context.rows],
            'crs': CRS.from_epsg(6933).to_wkt(version='WKT1_GDAL'),
            'crs_transform': [context.exact_spacing_m, 0, context.upper_left_x_m, 0, -context.exact_spacing_m, context.upper_left_y_m],
            'format': 'GEO_TIFF', 'filePerBand': False})
        with urlopen(url, timeout=60) as response:
            payload = response.read(MAX_PAYLOAD + 1)
        if not payload or len(payload) > MAX_PAYLOAD:
            raise ValueError('Invalid or excessive acquisition payload')
        return payload


def inspect_raster(path, unit, acquisition, *, attach=False):
    import numpy as np
    import rasterio
    from affine import Affine
    context = grid(unit)
    transform = Affine(context.exact_spacing_m, 0, context.upper_left_x_m, 0, -context.exact_spacing_m, context.upper_left_y_m)
    with rasterio.open(path, 'r+' if attach else 'r') as src:
        if (src.crs is None or src.crs.to_epsg() != 6933 or (src.height, src.width, src.count) !=
                (260, 260, len(acquisition['bands'])) or not src.transform.almost_equals(transform, precision=1e-6)
                or any(t != 'float32' for t in src.dtypes)):
            raise ValueError('Acquisition raster grid/schema mismatch')
        if attach:
            if src.nodata is None:
                src.nodata = -9999.0
            for i, b in enumerate(acquisition['bands'], 1):
                if src.descriptions[i-1] not in (None, '', b):
                    raise ValueError('Acquisition band order mismatch')
                src.set_band_description(i, b)
        if tuple(src.descriptions) != tuple(acquisition['bands']) or src.nodata is None:
            raise ValueError('Acquisition band/mask metadata mismatch')
        values = src.read(masked=True).filled(np.nan)
        if np.isinf(values).any() or (np.isfinite(values) & (values == -9999)).any():
            raise ValueError('Invalid unmasked acquisition values')
        return {'valid_pixel_counts': {b: int(np.isfinite(values[i]).sum()) for i, b in enumerate(acquisition['bands'])}}


class Sentinel1Adapter:
    source_id, profile_id = 'sentinel1', PROFILE

    def __init__(self, source_id='sentinel1', *, provider=None, retries=2, sleep=time.sleep):
        if source_id != self.source_id or type(retries) is not int or not 0 <= retries <= 3:
            raise ValueError('Invalid source/retry limit')
        self.provider, self.retries, self.sleep = provider, retries, sleep

    def _discovery(self, path, unit):
        doc = json.loads(path.read_text(encoding='utf-8'))
        p = doc['payload']
        if doc['sha256'] != digest(p) or p['profile'] != profile(unit) or p['processing_code_sha256'] != code_hashes():
            raise ValueError('Discovery checkpoint identity/integrity/code mismatch')
        return acquisitions(p['scenes'], unit)

    def _acquisition(self, directory, unit, acquisition):
        doc = json.loads((directory / 'manifest.json').read_text(encoding='utf-8'))
        expected = dict(acquisition, profile=profile(unit), processing_code_sha256=code_hashes(),
                        sha256=checksum(directory / 'input.tif'), **inspect_raster(directory / 'input.tif', unit, acquisition))
        if doc != expected or {p.name for p in directory.iterdir()} != {'input.tif', 'manifest.json'}:
            raise ValueError('Acquisition checkpoint integrity mismatch')
        return directory / 'input.tif', directory / 'manifest.json'

    def _prepared(self, unit, directory):
        doc = json.loads((directory / 'manifest.json').read_text(encoding='utf-8'))
        return PreparedSource(unit, tuple(directory / n for n in doc['assets']) + (directory / 'manifest.json',), doc)

    def plan(self, unit, *, asset_root):
        work = key(unit)
        root = Path(asset_root) / work
        if (root / 'annual').exists():
            self.validate(self._prepared(unit, root / 'annual'))
            return SourcePlan(unit, 'reusable', 'validated_prepared_source', work, 0, 0)
        if unit.year < 2014:
            return SourcePlan(unit, 'unavailable', 'outside_product_period', work, 0, 0)
        discovery = root / 'discovery.json'
        pending = MAX_ACQUISITIONS
        if discovery.exists():
            items = self._discovery(discovery, unit)
            pending = 0
            for a in items:
                directory = root / 'acquisitions' / digest(a)[:16]
                if directory.exists():
                    self._acquisition(directory, unit, a)
                else:
                    pending += 1
        return SourcePlan(unit, 'retrievable', 'bounded discovery and acquisition; actual coverage unknown', work,
                          (int(not discovery.exists()) + pending * 2) * (self.retries + 1), pending * MAX_PAYLOAD * (self.retries + 1))

    def prepare(self, plan, *, output_root, credential_ref=None):
        from .processing.sentinel1 import stack_sentinel1
        import h5netcdf  # Resolve NetCDF dependencies before contacting provider.
        unit = plan.unit
        if plan.work_key != key(unit):
            raise ValueError('Plan identity mismatch')
        root = Path(output_root) / plan.work_key
        annual = root / 'annual'
        if annual.exists():
            result = self._prepared(unit, annual)
            self.validate(result)
            return result
        root.mkdir(parents=True, exist_ok=True)
        discovery = root / 'discovery.json'
        provider = self.provider
        if not discovery.exists():
            if unit.year < 2014:
                records = []
            else:
                if provider is None:
                    provider = EarthEngineSentinel1(credential_ref)
                records = fetch_with_retry(lambda: provider.discover(unit), retries=self.retries, sleep=self.sleep)
            acquisitions(records, unit)
            p = {'profile': profile(unit), 'processing_code_sha256': code_hashes(), 'scenes': records}
            write_json_exclusive(discovery, {'payload': p, 'sha256': digest(p)})
        items = self._discovery(discovery, unit)
        scene_records = json.loads(discovery.read_text(encoding='utf-8'))['payload']['scenes']
        pairs = []
        for a in items:
            target = root / 'acquisitions' / digest(a)[:16]
            if not target.exists():
                if provider is None:
                    provider = EarthEngineSentinel1(credential_ref)
                payload = fetch_with_retry(lambda: provider.fetch(unit, a), retries=self.retries, sleep=self.sleep)
                if not isinstance(payload, bytes) or not 0 < len(payload) <= MAX_PAYLOAD:
                    raise ValueError('Invalid acquisition payload size')
                target.parent.mkdir(parents=True, exist_ok=True)
                with tempfile.TemporaryDirectory(prefix='.a-', dir=target.parent) as temporary:
                    stage = Path(temporary) / 'ready'
                    stage.mkdir()
                    (stage / 'input.tif').write_bytes(payload)
                    stats = inspect_raster(stage / 'input.tif', unit, a, attach=True)
                    write_json_exclusive(stage / 'manifest.json', dict(a, profile=profile(unit), processing_code_sha256=code_hashes(),
                                         sha256=checksum(stage / 'input.tif'), **stats))
                    self._acquisition(stage, unit, a)
                    os.rename(stage, target)
            pairs.append(self._acquisition(target, unit, a))
        with tempfile.TemporaryDirectory(prefix='.year-', dir=root) as temporary:
            stage = Path(temporary) / 'ready'
            stage.mkdir()
            name = f'sentinel1_{unit.year}_50m_EPSG6933.nc'
            assets = {}
            if items:
                result = stack_sentinel1(pairs, stage / name)
                if result['excluded_acquisition_count'] or result['acquisition_count'] != len(items):
                    raise ValueError('Annual assembly excluded an acquisition')
                stats = self._inspect(stage / name, unit, items)
                assets[name] = checksum(stage / name)
            else:
                stats = {'state': 'unavailable', 'reason': 'outside_product_period' if unit.year < 2014 else 'no_provider_acquisitions',
                         'acquisition_count': 0, 'valid_pixel_counts': {n: 0 for n in ('vv', 'vh', 'incidence_angle')}}
            meta = dict(profile(unit), **stats, assets=assets, acquisitions=items, scenes=scene_records,
                        processing_code_sha256=code_hashes(), schema='benchmark-public-source-manifest-v2')
            write_json_exclusive(stage / 'manifest.json', meta)
            self.validate(self._prepared(unit, stage))
            os.rename(stage, annual)
        return self._prepared(unit, annual)

    def _inspect(self, path, unit, items):
        import numpy as np
        import xarray as xr
        from pyproj import CRS
        context = grid(unit)
        counts = {}
        with xr.open_dataset(path, engine='h5netcdf') as ds:
            required = {'vv', 'vh', 'incidence_angle', 'platform', 'orbit_pass', 'absolute_orbit', 'relative_orbit', 'acquisition_id', 'source_scene_id', 'crs'}
            if set(ds.data_vars) != required or dict(ds.sizes) != {'time': len(items), 'y': 260, 'x': 260}:
                raise ValueError('Annual schema mismatch')
            for axis, origin, spacing in [('x', context.upper_left_x_m, context.exact_spacing_m), ('y', context.upper_left_y_m, -context.exact_spacing_m)]:
                if not np.array_equal(ds[axis].values, origin + (np.arange(260) + .5) * spacing):
                    raise ValueError('Annual grid mismatch')
            if CRS.from_wkt(ds.crs.attrs['spatial_ref']).to_epsg() != 6933 or ds.crs.attrs['epsg_code'] != 'EPSG:6933':
                raise ValueError('Annual CRS mismatch')
            times = np.array([np.datetime64(int(datetime.fromisoformat(a['time_start_utc']).timestamp() * 1000), 'ms') for a in items])
            if not np.array_equal(ds.time.values, times):
                raise ValueError('Annual timestamps mismatch')
            for name in ('platform', 'orbit_pass', 'absolute_orbit', 'relative_orbit', 'acquisition_id', 'source_scene_id'):
                expected = [a['scene_ids'][0] if name == 'source_scene_id' else a[name] for a in items]
                if ds[name].values.tolist() != expected:
                    raise ValueError('Annual acquisition identity mismatch')
            for name in ('vv', 'vh', 'incidence_angle'):
                arr = ds[name]
                if arr.dims != ('time', 'y', 'x') or arr.dtype != np.dtype('float32') or arr.attrs.get('units') != ('degree' if name == 'incidence_angle' else 'dB') or arr.attrs.get('grid_mapping') != 'crs' or not np.isnan(arr.encoding.get('_FillValue', 0)):
                    raise ValueError('Annual band schema/units mismatch')
                values = arr.values
                if np.isinf(values).any() or (np.isfinite(values) & (values == -9999)).any():
                    raise ValueError('Annual invalid numeric representation')
                if name == 'vh' and any('VH' not in a['bands'] and np.isfinite(values[i]).any() for i, a in enumerate(items)):
                    raise ValueError('Missing polarization was fabricated')
                counts[name] = int(np.isfinite(values).sum())
        no_values = counts['vv'] == 0
        partial = any(n != len(items) * 260 * 260 for n in counts.values())
        return {'state': 'unavailable' if no_values else 'partial' if partial else 'available',
                'reason': 'no_valid_backscatter' if no_values else 'masked_pixels_or_missing_polarization' if partial else None,
                'acquisition_count': len(items), 'valid_pixel_counts': counts}

    def validate(self, prepared):
        key(prepared.unit)
        meta = json.loads(prepared.files[-1].read_text(encoding='utf-8'))
        if meta != prepared.public_metadata or any(meta[k] != v for k, v in profile(prepared.unit).items()) or meta['processing_code_sha256'] != code_hashes():
            raise ValueError('Prepared identity/profile/code mismatch')
        if acquisitions(meta['scenes'], prepared.unit) != meta['acquisitions']:
            raise ValueError('Prepared discovery/grouping mismatch')
        directory = prepared.files[-1].parent
        expected_name = f'sentinel1_{prepared.unit.year}_50m_EPSG6933.nc'
        if set(meta['assets']) != ({expected_name} if meta['acquisitions'] else set()) or {p.name for p in directory.iterdir()} != set(meta['assets']) | {'manifest.json'}:
            raise ValueError('Prepared file membership mismatch')
        for name, sha in meta['assets'].items():
            if checksum(directory / name) != sha:
                raise ValueError('Prepared checksum mismatch')
        if meta['acquisitions']:
            stats = self._inspect(directory / expected_name, prepared.unit, meta['acquisitions'])
        else:
            stats = {'state': 'unavailable', 'reason': 'outside_product_period' if prepared.unit.year < 2014 else 'no_provider_acquisitions',
                     'acquisition_count': 0, 'valid_pixel_counts': {n: 0 for n in ('vv', 'vh', 'incidence_angle')}}
        expected = dict(profile(prepared.unit), **stats, assets=meta['assets'], acquisitions=meta['acquisitions'], scenes=meta['scenes'],
                        processing_code_sha256=code_hashes(), schema='benchmark-public-source-manifest-v2')
        if meta != expected:
            raise ValueError('Prepared statistics mismatch')
        return ValidationResult(True, {n: 'passed' for n in ('integrity', 'grid', 'units', 'time', 'acquisition_identity', 'masks')},
                                () if meta['state'] == 'available' else (meta['reason'],))
