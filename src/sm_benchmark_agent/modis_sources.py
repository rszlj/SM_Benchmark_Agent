"""Separate-platform V1 NDVI/LST adapters with bounded annual retrieval."""
from dataclasses import asdict
from datetime import date, datetime, timedelta, timezone
import hashlib
import json
import math
from pathlib import Path
import tempfile
from urllib.request import urlopen

from . import periods
from .adapters import SourcePlan, PreparedSource, ValidationResult
from .context_sources import EarthEngineContexts
from .delivery import checksum
from .gldas21 import fetch_with_retry
from .gldas_workflow import check_public_metadata
from .grid import anchor_cell_from_id, context_grid, ContextResolution
from .processing import ndvi, aqua_ndvi, lst, landcover, srtm

SOURCES = {
    'mod13q1_ndvi': ('MOD13Q1', 'Terra', 'ndvi', 2000),
    'myd13q1_ndvi': ('MYD13Q1', 'Aqua', 'ndvi', 2002),
    'mod11a2_lst': ('MOD11A2', 'Terra', 'lst', 2000),
    'myd11a2_lst': ('MYD11A2', 'Aqua', 'lst', 2002),
}
PROFILES = {s: s.replace('_', '-') + '-v1-separate' for s in SOURCES}
MAX_PAYLOAD = 24 * 1024 * 1024


def code_hashes():
    root = Path(__file__).parent
    return {n: checksum(root / n) for n in ('periods.py', 'modis_sources.py', 'processing/ndvi.py',
        'processing/lst.py', 'processing/aqua_ndvi.py', 'processing/landcover.py', 'processing/srtm.py',
        'grid.py', 'context_sources.py', 'gldas21.py')}


def nominal_dates(source, year, unit=None):
    """Nominal yearly composite starts, not a promise of provider coverage.

    Product-start years may legitimately have fewer composites; report the gap
    relative to this nominal calendar without synthesizing bands.
    """
    _, platform, kind, first_year = SOURCES[source]
    if year < first_year:
        return []
    start = date(year, 1, 9 if kind == 'ndvi' and platform == 'Aqua' else 1)
    step = 16 if kind == 'ndvi' else 8
    return [(start + timedelta(days=i)).isoformat() for i in range(0, 366, step)
            if (start + timedelta(days=i)).year == year
            and (unit is None or periods.contains(unit,datetime.combine(start+timedelta(days=i),datetime.min.time(),timezone.utc)))]


def validate_dates(source, year, dates, unit=None):
    if not isinstance(dates, list) or dates != sorted(set(dates)):
        raise ValueError('Composite dates must be unique and ordered')
    expected = set(nominal_dates(source, year, unit))
    if any(not isinstance(d, str) or d not in expected for d in dates):
        raise ValueError('Unexpected MODIS composite date or year')


def filenames(source, year):
    if SOURCES[source][2] == 'ndvi':
        return [f'{source}_{year}_16day_250m_EPSG6933.tif']
    return [f'{source}_{slot}_{year}_8day_1km_EPSG6933.tif' for slot in ('day', 'night')]


def scientific_profile(source):
    product, platform, kind, _ = SOURCES[source]
    return {'collection': f'MODIS/061/{product}', 'platform': platform,
            'variables': ['NDVI'] if kind == 'ndvi' else ['LST_Day_1km', 'LST_Night_1km'],
            'units': 'dimensionless' if kind == 'ndvi' else 'degree Celsius',
            'scale': 0.0001 if kind == 'ndvi' else 0.02, 'offset': 0 if kind == 'ndvi' else -273.15,
            'temporal_support': '16-day composite' if kind == 'ndvi' else '8-day clear-sky composite',
            'valid_raw_range': [-2000, 10000] if kind == 'ndvi' else [7500, 32767],
            'resampling': 'bilinear', 'gap_policy': 'no temporal filling; no added QC filter',
            'mask_interpolation': 'normalized convolution of values and validity weights, threshold 1e-6' if source == 'myd13q1_ndvi' else 'V1 source-specific NoData handling',
            'source_crs_override': None if source == 'mod13q1_ndvi' else landcover.NATIVE_CRS,
            'retrieval_grid': 'EPSG:4326 at 250 m (V1 Terra gap-fill route)' if source == 'mod13q1_ndvi' else 'native MODIS sinusoidal grid',
            'missing_representation': 'float32 / IEEE NaN'}


class EarthEngineMODIS(EarthEngineContexts):
    def fetch(self, unit, context):
        ee = self.ee
        product, _, kind, _ = SOURCES[unit.source_id]
        collection_id = f'MODIS/061/{product}'
        collection = ee.ImageCollection(collection_id).filterDate(
            *(d.isoformat() for d in periods.bounds(unit))).sort('system:time_start')
        indexes = collection.aggregate_array('system:index').getInfo()
        times = collection.aggregate_array('system:time_start').getInfo()
        if len(indexes) != len(times) or any(not isinstance(i, str) or '/' in i for i in indexes):
            raise ValueError('Inconsistent MODIS image metadata')
        dates = [datetime.fromtimestamp(t / 1000, timezone.utc).date().isoformat() for t in times]
        validate_dates(unit.source_id, unit.year, dates, unit)
        ids = [f'{collection_id}/{i}' for i in indexes]
        if not dates:
            return {'payload': None, 'dates': [], 'image_ids': []}
        bands = ['NDVI'] if kind == 'ndvi' else ['LST_Day_1km', 'LST_Night_1km']
        images, names = [], []
        for image_id, stamp in zip(ids, dates):
            selected_names = [stamp.replace('-', '_') + '_' + b for b in bands]
            images.append(ee.Image(image_id).select(bands).rename(selected_names))
            names.extend(selected_names)
        stack = images[0]
        for image in images[1:]:
            stack = stack.addBands(image)
        request = {'bands': names, 'format': 'GEO_TIFF', 'filePerBand': False}
        if unit.source_id == 'mod13q1_ndvi':
            bounds = srtm._expanded_wgs84_bounds(context, 250)
            request.update(region=list(bounds), crs='EPSG:4326', scale=250)
            # Conservative equatorial conversion also bounds longitude width at high latitude.
            pixels = (math.ceil((bounds[2] - bounds[0]) * 111320 / 250) + 2) * (math.ceil((bounds[3] - bounds[1]) * 111320 / 250) + 2)
        else:
            projection = images[0].select(0).projection().getInfo()
            from pyproj import Transformer
            b = context.bounds
            bounds = Transformer.from_crs(6933, landcover.NATIVE_CRS, always_xy=True).transform_bounds(
                b.xmin - 1000, b.ymin - 1000, b.xmax + 1000, b.ymax + 1000, densify_pts=41)
            dx, dy = abs(projection['transform'][0]), abs(projection['transform'][4])
            if not dx or not dy:
                raise ValueError('Invalid native MODIS spacing')
            pixels = (math.ceil((bounds[2] - bounds[0]) / dx) + 2) * (math.ceil((bounds[3] - bounds[1]) / dy) + 2)
            request.update(region=ee.Geometry.Rectangle(bounds, projection['crs'], False),
                           crs=projection['crs'], crs_transform=projection['transform'])
        if pixels <= 0 or pixels * len(names) * 2 > MAX_PAYLOAD:
            raise ValueError('MODIS request exceeds conservative 24 MiB uncompressed size limit')
        url = stack.unmask(-3000 if kind == 'ndvi' else -32768, False).toInt16().getDownloadURL(request)
        with urlopen(url, timeout=60) as response:
            payload = response.read(MAX_PAYLOAD + 1)
        if not payload or len(payload) > MAX_PAYLOAD:
            raise ValueError('Empty or oversized MODIS download')
        return {'payload': payload, 'dates': dates, 'image_ids': ids}


class MODISAdapter:
    def __init__(self, source_id, *, provider=None, retries=2):
        self.source_id, self.profile_id = source_id, PROFILES[source_id]
        self.provider = provider
        if type(retries) is not int or not 0 <= retries <= 3:
            raise ValueError('retries must be between zero and three')
        self.retries = retries

    def key(self, unit):
        anchor_cell_from_id(unit.anchor_id)
        if (unit.source_id, unit.profile_id) != (self.source_id, self.profile_id):
            raise ValueError('MODIS source/profile mismatch')
        if type(unit.year) is not int or not 1 <= unit.year <= 9998:
            raise ValueError('Invalid year')
        return f'{self.profile_id}/{unit.anchor_id}/{unit.year}' + periods.suffix(unit)

    def context(self, unit):
        resolution = ('250 m', 4) if SOURCES[self.source_id][2] == 'ndvi' else ('1 km', 1)
        return context_grid(anchor_cell_from_id(unit.anchor_id), ContextResolution(*resolution))

    def raw(self, root, unit):
        if not root.exists():
            return None
        doc = json.loads((root / 'receipt.json').read_text(encoding='utf-8'))
        if doc['work_key'] != self.key(unit) or doc['science'] != scientific_profile(self.source_id):
            raise ValueError('Wrong MODIS raw checkpoint identity')
        validate_dates(self.source_id, unit.year, doc['dates'], unit)
        expected = {'receipt.json', 'input.tif'} if doc['dates'] else {'receipt.json'}
        if {p.name for p in root.iterdir()} != expected:
            raise ValueError('Incomplete MODIS raw checkpoint')
        if doc['dates'] and checksum(root / 'input.tif') != doc['sha256']:
            raise ValueError('Corrupt MODIS raw checkpoint')
        self.validate_image_ids(doc['image_ids'], doc['dates'])
        return doc

    def validate_image_ids(self, image_ids, dates):
        prefix = scientific_profile(self.source_id)['collection'] + '/'
        if (len(image_ids) != len(dates) or len(set(image_ids)) != len(image_ids)
                or any(not isinstance(i, str) or not i.startswith(prefix) or '/' in i[len(prefix):]
                       or not i[len(prefix):] for i in image_ids)):
            raise ValueError('Unexpected MODIS source image identities')

    def plan(self, unit, *, asset_root):
        key = self.key(unit)
        root = Path(asset_root) / key
        if (root / 'prepared').exists():
            self.validate(self._prepared(unit, root / 'prepared'))
            return SourcePlan(unit, 'reusable', 'verified_prepared_MODIS', key, 0, 0)
        if unit.year < SOURCES[self.source_id][3]:
            return SourcePlan(unit, 'unavailable', 'outside_product_period', key, 0, 0)
        if self.raw(root / 'raw', unit) is not None:
            return SourcePlan(unit, 'retrievable', 'verified_raw_checkpoint; local processing only', key, 0, 0)
        return SourcePlan(unit, 'retrievable', 'authorized_GEE_required', key,
                          (4 if self.source_id == 'mod13q1_ndvi' else 5) * (self.retries + 1), None)

    def _prepared(self, unit, root):
        doc = json.loads((root / 'manifest.json').read_text(encoding='utf-8'))
        # Only canonical filenames can be referenced by the manifest.
        if any(a['path'] not in filenames(self.source_id, unit.year) for a in doc['assets']):
            raise ValueError('Invalid MODIS prepared asset path')
        return PreparedSource(unit, tuple(root / a['path'] for a in doc['assets']) + (root / 'manifest.json',), doc)

    def prepare(self, plan, *, output_root, credential_ref=None):
        unit = plan.unit
        root = Path(output_root) / self.key(unit)
        if plan.work_key != self.key(unit):
            raise ValueError('MODIS work key changed')
        final = root / 'prepared'
        if final.exists():
            result = self._prepared(unit, final)
            self.validate(result)
            return result
        # Fail missing scientific dependencies before network access.
        import numpy as np
        import rasterio
        from rasterio.io import MemoryFile
        kind = SOURCES[self.source_id][2]
        if kind == 'lst':
            srtm._gdal_module()
        root.mkdir(parents=True, exist_ok=True)
        reason = 'outside_product_period' if unit.year < SOURCES[self.source_id][3] else None
        receipt = None
        if not reason:
            receipt = self.raw(root / 'raw', unit)
            if receipt is None:
                provider = self.provider or EarthEngineMODIS(credential_ref)
                response = fetch_with_retry(lambda: provider.fetch(unit, self.context(unit)), retries=self.retries)
                dates, image_ids, payload = response['dates'], response['image_ids'], response['payload']
                validate_dates(self.source_id, unit.year, dates, unit)
                self.validate_image_ids(image_ids, dates)
                if bool(dates) != bool(payload):
                    raise ValueError('MODIS dates/payload mismatch')
                if payload:
                    if len(payload) > MAX_PAYLOAD:
                        raise ValueError('Oversized raw MODIS input')
                    with MemoryFile(payload) as memory, memory.open() as raster:
                        if raster.crs is None or raster.count != len(dates) * (1 if kind == 'ndvi' else 2):
                            raise ValueError('MODIS raw band count/CRS mismatch')
                        raster.read()
                receipt = {'work_key': self.key(unit), 'science': scientific_profile(self.source_id),
                           'dates': dates, 'image_ids': image_ids, 'sha256': hashlib.sha256(payload).hexdigest() if payload else None}
                check_public_metadata(receipt)
                with tempfile.TemporaryDirectory(prefix='.r-', dir=root) as temporary:
                    stage = Path(temporary) / 'raw'
                    stage.mkdir()
                    if payload:
                        (stage / 'input.tif').write_bytes(payload)
                    (stage / 'receipt.json').write_text(json.dumps(receipt, indent=2), encoding='utf-8')
                    if (root / 'raw').exists():
                        raise FileExistsError('MODIS raw checkpoint appeared during retrieval')
                    stage.rename(root / 'raw')
            if not receipt['dates']:
                reason = 'no_provider_images'
        dates = receipt['dates'] if receipt else []
        with tempfile.TemporaryDirectory(prefix='.p-', dir=root) as temporary:
            stage = Path(temporary)
            public = stage / 'public'
            public.mkdir()
            if not reason:
                derived = stage / 'derived'
                derived.mkdir()
                if kind == 'ndvi':
                    target = derived / filenames(self.source_id, unit.year)[0]
                    if self.source_id == 'myd13q1_ndvi':
                        aqua_ndvi.derive_aqua_ndvi((root / 'raw/input.tif').read_bytes(), target,
                                                 self.context(unit), [date.fromisoformat(d) for d in dates])
                    else:
                        ndvi.derive_mod13q1_ndvi_bytes(payload=(root / 'raw/input.tif').read_bytes(), target=target,
                            context=self.context(unit), dates=[date.fromisoformat(d) for d in dates],
                            provenance={}, platform='Terra')
                    outputs = [target]
                else:
                    result = lst.derive_mod11a2_lst(raw_chunks={'annual': root / 'raw/input.tif'},
                        dates_by_chunk={'annual': dates}, context=self.context(unit), output_root=derived,
                        product=SOURCES[self.source_id][0].lower(), year=unit.year,
                        tile_directory=derived, working_root=stage / 'work')
                    outputs = [Path(result[slot]) for slot in ('day', 'night')]
                for output in outputs:
                    landcover.public_raster(output, public / output.name)
            stats = self.statistics(public, unit, dates)
            gaps = sorted(set(nominal_dates(self.source_id, unit.year, unit)) - set(dates))
            state = 'unavailable' if reason or not stats['valid_values'] else 'partial' if gaps or stats['missing_values'] else 'available'
            if state == 'unavailable':
                reason = reason or 'no_valid_values'
                for path in public.iterdir():
                    path.unlink()
            else:
                reason = 'missing_composites_or_masked_values' if state == 'partial' else None
            doc = {**periods.metadata(unit), 'schema': 'benchmark-modis-source-v1', 'source_id': self.source_id, 'profile_id': self.profile_id,
                   'anchor_id': unit.anchor_id, 'year': unit.year, 'science': scientific_profile(self.source_id),
                   'grid': asdict(self.context(unit)), 'dates': dates, 'nominal_missing_dates': gaps,
                   'state': state, 'reason': reason, 'statistics': stats, 'processing_code_sha256': code_hashes(),
                   'image_ids': receipt['image_ids'] if receipt else [], 'raw_sha256': receipt['sha256'] if receipt else None,
                   'assets': [{'path': p.name, 'sha256': checksum(p), 'bytes': p.stat().st_size} for p in sorted(public.iterdir())]}
            check_public_metadata(doc)
            (public / 'manifest.json').write_text(json.dumps(doc, indent=2) + '\n', encoding='utf-8')
            self.validate(self._prepared(unit, public))
            if final.exists():
                raise FileExistsError('MODIS prepared output appeared during processing')
            public.rename(final)
        return self._prepared(unit, final)

    def statistics(self, root, unit, dates):
        import numpy as np
        import rasterio
        from affine import Affine
        grid = self.context(unit)
        valid = missing = 0
        for path in sorted(root.glob('*.tif')):
            with rasterio.open(path) as raster:
                transform = Affine(grid.exact_spacing_m, 0, grid.upper_left_x_m, 0, -grid.exact_spacing_m, grid.upper_left_y_m)
                expected_descriptions = tuple(f'{d}_{SOURCES[self.source_id][1]}' if SOURCES[self.source_id][2] == 'ndvi' else d for d in dates)
                if (not dates or raster.crs is None or raster.crs.to_epsg() != 6933 or raster.shape != (grid.rows, grid.columns)
                        or not raster.transform.almost_equals(transform, precision=1e-6) or raster.descriptions != expected_descriptions
                        or any(d != 'float32' for d in raster.dtypes) or any(n is None or not np.isnan(n) for n in raster.nodatavals)):
                    raise ValueError('MODIS raster grid/dates/type/mask mismatch')
                values = raster.read()
                if np.isinf(values).any():
                    raise ValueError('Infinite MODIS raster value')
                finite = values[np.isfinite(values)]
                low, high = (-0.2, 1.0) if SOURCES[self.source_id][2] == 'ndvi' else (-123.15, 382.19)
                if np.any(finite < low - 0.001) or np.any(finite > high + 0.001):
                    raise ValueError('MODIS values outside scaled source range')
                valid += int(finite.size)
                missing += int(np.isnan(values).sum())
        return {'valid_values': valid, 'missing_values': missing}

    def validate(self, prepared):
        unit = prepared.unit
        self.key(unit)
        root = prepared.files[-1].parent
        doc = json.loads(prepared.files[-1].read_text(encoding='utf-8'))
        check_public_metadata(doc)
        if (doc['source_id'], doc['profile_id'], doc['anchor_id'], doc['year']) != (self.source_id, self.profile_id, unit.anchor_id, unit.year):
            raise ValueError('MODIS prepared identity mismatch')
        if any(doc.get(k)!=v for k,v in periods.metadata(unit).items()) or doc['science'] != scientific_profile(self.source_id) or doc['processing_code_sha256'] != code_hashes() or doc['grid'] != asdict(self.context(unit)):
            raise ValueError('MODIS science/code/grid mismatch')
        validate_dates(self.source_id, unit.year, doc['dates'], unit)
        self.validate_image_ids(doc['image_ids'], doc['dates'])
        if doc['nominal_missing_dates'] != sorted(set(nominal_dates(self.source_id, unit.year, unit)) - set(doc['dates'])):
            raise ValueError('MODIS calendar gap mismatch')
        names = [a['path'] for a in doc['assets']]
        if len(set(names)) != len(names) or {p.name for p in root.iterdir()} != set(names) | {'manifest.json'}:
            raise ValueError('MODIS prepared membership mismatch')
        if any(n not in filenames(self.source_id, unit.year) for n in names):
            raise ValueError('Unexpected MODIS asset')
        for asset in doc['assets']:
            path = root / asset['path']
            if path.is_symlink() or checksum(path) != asset['sha256'] or path.stat().st_size != asset['bytes']:
                raise ValueError('MODIS prepared checksum mismatch')
        stats = self.statistics(root, unit, doc['dates'])
        if doc['state'] == 'unavailable':
            if names or doc['reason'] not in {'outside_product_period', 'no_provider_images', 'no_valid_values'}:
                raise ValueError('Invalid unavailable MODIS output')
        else:
            state = 'partial' if stats['missing_values'] or doc['nominal_missing_dates'] else 'available'
            if (set(names) != set(filenames(self.source_id, unit.year)) or not stats['valid_values']
                    or stats != doc['statistics'] or state != doc['state']):
                raise ValueError('MODIS availability/statistics mismatch')
        return ValidationResult(True, {'identity': 'passed', 'grid_time_values_masks': 'passed', 'hashes': 'passed'},
                                (doc['reason'],) if doc['reason'] else ())
