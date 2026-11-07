"""V1 ERA5-Land raw18 and IMERG V07 native-cell monthly preparation."""
from datetime import datetime, timedelta, timezone
import json
import math
import os
from pathlib import Path
import re
import tempfile
import time

from . import periods
from .adapters import SourceUnit, SourcePlan, PreparedSource, ValidationResult
from .delivery import checksum
from .grid import anchor_cell_from_id
from .native_cells import era5_land_native_cell, imerg_v07_native_cell
from .gldas21 import EarthEngineGLDAS, fetch_with_retry, month_bounds, digest, write_json_exclusive
from .timeseries_profiles import ERA5_MAP, ERA5_UNITS, ERA5_TRANSFORM, IMERG_BANDS, IMERG_UNITS, IMERG_TRANSFORM, IMERG_SENTINEL

PROFILES = {'era5_land': 'benchmark-raw18-nas-compatible-v1', 'imerg_v07': 'imerg-v07-native-half-hourly-v1'}
COLLECTIONS = {'era5_land': 'ECMWF/ERA5_LAND/HOURLY', 'imerg_v07': 'NASA/GPM_L3/IMERG_V07'}


def code_hashes():
    root = Path(__file__).parent
    return {name: checksum(root / name) for name in
            ('periods.py', 'timeseries_sources.py', 'timeseries_profiles.py', 'native_cells.py', 'grid.py', 'gldas21.py')}


def cell_for(unit):
    a = anchor_cell_from_id(unit.anchor_id)
    function = era5_land_native_cell if unit.source_id == 'era5_land' else imerg_v07_native_cell
    return function(a.centre_longitude, a.centre_latitude)


def step(unit):
    return timedelta(minutes=60 if unit.source_id == 'era5_land' else 30)


def bands(unit):
    return tuple(ERA5_MAP.values()) if unit.source_id == 'era5_land' else IMERG_BANDS


def key(unit):
    if unit.source_id not in PROFILES or unit.profile_id != PROFILES[unit.source_id] or type(unit.year) is not int or not 1 <= unit.year <= 9998:
        raise ValueError('Invalid time-series source/profile/year')
    cell = cell_for(unit)
    return f'{unit.profile_id}/R{cell["row"]:04d}_C{cell["column"]:04d}/{unit.year:04d}' + periods.suffix(unit)


def outside(unit):
    return unit.year < (1950 if unit.source_id == 'era5_land' else 1998)


def profile(unit):
    era = unit.source_id == 'era5_land'
    return {**periods.metadata(unit), 'profile_id': unit.profile_id, 'source_id': unit.source_id, 'year': unit.year,
            'collection': COLLECTIONS[unit.source_id], 'native_cell': cell_for(unit),
            'native_crs': 'EPSG:4326', 'native_transform': list(ERA5_TRANSFORM if era else IMERG_TRANSFORM),
            'selection': 'native cell containing anchor centre; no spatial interpolation',
            'variables': list(ERA5_MAP if era else IMERG_BANDS),
            'provider_band_map': ERA5_MAP if era else {b: b for b in IMERG_BANDS},
            'units': ERA5_UNITS if era else IMERG_UNITS,
            'temporal_support': 'raw hourly values; accumulated fields are not converted' if era else 'raw half-hourly values; no temporal aggregation',
            'missing_policy': 'provider masks and nonfinite values become null; absent timestamps remain absent; no gap filling',
            'representation': 'native source-cell time series'}


def normalized_rows(rows, unit, start, end):
    cell, names = cell_for(unit), bands(unit)
    era = unit.source_id == 'era5_land'
    columns = {'id', 'time', 'longitude', 'latitude', *names} | (set() if era else {'status'})
    clean, seen = [], set()
    for row in rows:
        if set(row) != columns:
            raise ValueError('Provider schema mismatch')
        stamp = row['time']
        if type(stamp) not in (int, float) or not math.isfinite(stamp):
            raise ValueError('Invalid timestamp')
        dt = datetime.fromtimestamp(stamp / 1000, timezone.utc)
        if not start <= dt < end or dt.second or dt.microsecond or dt.minute % (60 if era else 30):
            raise ValueError('Timestamp outside period or cadence')
        if stamp in seen or not isinstance(row['id'], str) or not re.fullmatch(r'[A-Za-z0-9_.-]+', row['id']):
            raise ValueError('Duplicate timestamp or invalid image identity')
        seen.add(stamp)
        out = {'id': row['id'], 'time': int(stamp)}
        for axis in ('longitude', 'latitude'):
            value = row[axis]
            if type(value) not in (int, float) or not math.isfinite(value) or not math.isclose(value, cell['centre_' + axis], abs_tol=1e-7, rel_tol=0):
                raise ValueError('Provider native-cell mismatch')
            # Retain provider precision, as in V1's IMERG table.
            out[axis] = float(value)
        if not era:
            if row['status'] not in ('permanent', 'provisional', 'unknown'):
                raise ValueError('Unrecognized IMERG status')
            out['status'] = row['status']
        for name in names:
            value = row[name]
            if value is not None and type(value) not in (int, float):
                raise ValueError('Invalid numeric value')
            out[name] = None if value is None or not math.isfinite(value) or (not era and value == IMERG_SENTINEL) else float(value)
        clean.append(out)
    return sorted(clean, key=lambda r: r['time'])


class EarthEngineTimeSeries(EarthEngineGLDAS):
    """Shared official login; at most three server evaluations per cell/month."""
    def fetch(self, unit, start, end):
        ee, cell = self.ee, cell_for(unit)
        source = (ee.ImageCollection(COLLECTIONS[unit.source_id]).filterDate(start.isoformat(), end.isoformat())
                  .sort('system:time_start'))
        count = source.size().getInfo()
        if type(count) is not int or not 0 <= count <= int((end - start) / step(unit)):
            raise ValueError('Unexpected provider image count')
        if not count:
            return []
        statuses = {}
        if unit.source_id == 'imerg_v07':
            status_rows = source.reduceColumns(reducer=ee.Reducer.toList(2), selectors=['system:index', 'status']).get('list').getInfo()
            statuses = dict(status_rows)
            def harmonize(image):
                available = image.bandNames()
                layers = []
                for band in IMERG_BANDS:
                    missing = ee.Image.constant(IMERG_SENTINEL).rename(band).toDouble()
                    present = image.select(band).toDouble().unmask(IMERG_SENTINEL, sameFootprint=False)
                    layers.append(ee.Image(ee.Algorithms.If(available.contains(band), present, missing)))
                return ee.Image.cat(layers).copyProperties(image, image.propertyNames())
            source = source.map(harmonize)
        collection = source.select(list(bands(unit)))
        table = collection.getRegion(ee.Geometry.Point([cell['centre_longitude'], cell['centre_latitude']]),
            crs='EPSG:4326', crsTransform=profile(unit)['native_transform']).getInfo()
        if not table or len(table) - 1 != count or len(set(table[0])) != len(table[0]) or set(table[0]) != {'id', 'time', 'longitude', 'latitude', *bands(unit)}:
            raise ValueError('Unexpected provider table schema/count')
        if any(len(row) != len(table[0]) for row in table[1:]):
            raise ValueError('Invalid provider row width')
        result = [dict(zip(table[0], row)) for row in table[1:]]
        if unit.source_id == 'imerg_v07':
            for row in result:
                row['status'] = statuses.get(row['id']) or 'unknown'
        return result


def to_table(rows, unit):
    import pyarrow as pa
    era = unit.source_id == 'era5_land'
    starts = [datetime.fromtimestamp(r['time'] / 1000, timezone.utc) for r in rows]
    columns = {} if era else {
        'source_image_id': pa.array([r['id'] for r in rows], type=pa.string()),
        'source_status': pa.array([r['status'] for r in rows], type=pa.string())}
    dtype = pa.timestamp('ms' if era else 'us', tz='UTC')
    columns.update(interval_start_utc=pa.array(starts, type=dtype),
                   interval_end_utc=pa.array([d + step(unit) for d in starts], type=dtype))
    if not era:
        columns.update({f'native_{a}': pa.array([r[a] for r in rows], type=pa.float64()) for a in ('longitude', 'latitude')})
    for name, band in profile(unit)['provider_band_map'].items():
        columns[name] = pa.array([r[band] for r in rows], type=pa.float32() if era else pa.float64())
    return pa.table(columns).replace_schema_metadata({b'benchmark_profile': json.dumps(profile(unit), sort_keys=True).encode()})


class TimeSeriesAdapter:
    def __init__(self, source_id, *, provider=None, retries=2, sleep=time.sleep):
        self.source_id, self.profile_id = source_id, PROFILES[source_id]
        if type(retries) is not int or not 0 <= retries <= 3:
            raise ValueError('Retries must be between 0 and 3')
        self.provider, self.retries, self.sleep = provider, retries, sleep

    def _key(self, unit):
        if unit.source_id != self.source_id:
            raise ValueError('Wrong source adapter')
        return key(unit)

    def _prepared(self, unit, directory):
        meta = json.loads((directory / 'manifest.json').read_text(encoding='utf-8'))
        return PreparedSource(unit, (directory / 'data.parquet', directory / 'manifest.json'), meta)

    def _checkpoint(self, path, unit, month):
        doc = json.loads(path.read_text(encoding='utf-8'))
        payload = doc['payload']
        if (doc['sha256'] != digest(payload) or payload['work_key'] != key(unit) or payload['month'] != month
                or payload['profile'] != profile(unit) or payload['processing_code_sha256'] != code_hashes()):
            raise ValueError('Checkpoint integrity/profile/code mismatch')
        return normalized_rows(payload['rows'], unit, *periods.month_bounds(unit, month))

    def plan(self, unit, *, asset_root):
        work = self._key(unit)
        root = Path(asset_root) / work
        if (root / 'annual').exists():
            self.validate(self._prepared(unit, root / 'annual'))
            return SourcePlan(unit, 'reusable', 'validated_prepared_source', work, 0, 0)
        if outside(unit):
            return SourcePlan(unit, 'unavailable', 'outside_product_period', work, 0, 0)
        pending = 0
        for month in periods.months(unit):
            path = root / f'{month:02d}.json'
            if path.exists():
                self._checkpoint(path, unit, month)
            else:
                pending += 1
        return SourcePlan(unit, 'retrievable', 'actual coverage checked on execution', work,
                          pending * (2 if unit.source_id == 'era5_land' else 3) * (1 + self.retries), None)

    def prepare(self, plan, *, output_root, credential_ref=None):
        import pyarrow.parquet as pq
        unit = plan.unit
        if plan.work_key != self._key(unit):
            raise ValueError('Changed work identity')
        root = Path(output_root) / plan.work_key
        annual = root / 'annual'
        if annual.exists():
            output = self._prepared(unit, annual)
            self.validate(output)
            return output
        rows, provider = [], self.provider
        if not outside(unit):
            for month in periods.months(unit):
                path = root / f'{month:02d}.json'
                if not path.exists():
                    if provider is None:
                        provider = EarthEngineTimeSeries(credential_ref)
                    start, end = periods.month_bounds(unit, month)
                    raw = fetch_with_retry(lambda: provider.fetch(unit, start, end), retries=self.retries, sleep=self.sleep)
                    clean = normalized_rows(raw, unit, start, end)
                    payload = {'work_key': plan.work_key, 'month': month, 'profile': profile(unit),
                               'processing_code_sha256': code_hashes(), 'rows': clean}
                    write_json_exclusive(path, {'payload': payload, 'sha256': digest(payload)})
                rows.extend(self._checkpoint(path, unit, month))
        table = to_table(rows, unit)
        root.mkdir(parents=True, exist_ok=True)
        with tempfile.TemporaryDirectory(prefix='.annual-', dir=root) as temporary:
            stage = Path(temporary) / 'annual'
            stage.mkdir()
            pq.write_table(table, stage / 'data.parquet', compression='zstd', compression_level=7)
            meta = dict(profile(unit), **self._inspect(stage / 'data.parquet', unit),
                        sha256=checksum(stage / 'data.parquet'), file='data.parquet',
                        processing_code_sha256=code_hashes(), schema='benchmark-public-source-manifest-v2')
            write_json_exclusive(stage / 'manifest.json', meta)
            self.validate(self._prepared(unit, stage))
            os.rename(stage, annual)
        return self._prepared(unit, annual)

    def _inspect(self, path, unit):
        import pyarrow.parquet as pq
        table = pq.read_table(path)
        if table.schema != to_table([], unit).schema or table.schema.metadata != to_table([], unit).schema.metadata:
            raise ValueError('Written table profile/schema mismatch')
        rows = []
        era, cell = unit.source_id == 'era5_land', cell_for(unit)
        mapping = profile(unit)['provider_band_map']
        for index, row in enumerate(table.to_pylist()):
            dt = row['interval_start_utc']
            if dt is None or row['interval_end_utc'] != dt + step(unit):
                raise ValueError('Written time support mismatch')
            r = {'id': str(index) if era else row['source_image_id'], 'time': dt.timestamp() * 1000,
                 'longitude': cell['centre_longitude'] if era else row['native_longitude'],
                 'latitude': cell['centre_latitude'] if era else row['native_latitude'],
                 **{b: row[n] for n, b in mapping.items()}}
            if not era:
                r['status'] = row['source_status']
            rows.append(r)
        clean = normalized_rows(rows, unit, *periods.bounds(unit))
        if rows != clean or (outside(unit) and rows):
            raise ValueError('Written rows unsorted, nonfinite, sentinel or outside coverage')
        expected = 0 if outside(unit) else int((periods.bounds(unit)[1] - periods.bounds(unit)[0]) / step(unit))
        nulls = {b: table[b].null_count for b in profile(unit)['variables']}
        statuses = [] if era else sorted(set(table['source_status'].to_pylist()))
        no_values = not rows or all(n == len(rows) for n in nulls.values())
        # IMERG ancillary microwave/IR gaps are normal; V1 availability is based
        # on timestamps and provider status. Report every band's nulls separately.
        incomplete = len(rows) != expected or (any(nulls.values()) if era else statuses != ['permanent'] or nulls['precipitation'] > 0)
        state = 'unavailable' if no_values else 'partial' if incomplete else 'available'
        reason = ('outside_product_period' if outside(unit) else 'no_provider_records' if not rows else 'no_valid_values') if no_values else 'missing_timestamps_values_or_final_status' if incomplete else None
        return {'state': state, 'reason': reason, 'record_count': len(rows), 'expected_record_count': expected,
                'missing_timestamp_count': expected - len(rows), 'null_counts': nulls, 'source_statuses': statuses}

    def validate(self, prepared):
        self._key(prepared.unit)
        data, manifest = prepared.files
        if {p.name for p in data.parent.iterdir()} != {'data.parquet', 'manifest.json'}:
            raise ValueError('Unexpected prepared files')
        metadata = json.loads(manifest.read_text(encoding='utf-8'))
        expected = dict(profile(prepared.unit), **self._inspect(data, prepared.unit), sha256=checksum(data),
                        file='data.parquet', processing_code_sha256=code_hashes(), schema='benchmark-public-source-manifest-v2')
        if metadata != expected or metadata != prepared.public_metadata:
            raise ValueError('Prepared integrity/profile/code mismatch')
        gaps = () if metadata['state'] == 'available' else (metadata['reason'],)
        return ValidationResult(True, {n: 'passed' for n in ('integrity', 'schema', 'native_cell', 'timestamps', 'units', 'nulls', 'source_status')}, gaps)
