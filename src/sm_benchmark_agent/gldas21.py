"""GLDAS-2.1 four-layer profile, monthly checkpoints and written-output validation."""
from datetime import datetime, timedelta, timezone
import hashlib
import json
import math
import os
from pathlib import Path
import re
import tempfile
import time
import tomllib

from . import periods
from .adapters import PreparedSource, SourcePlan, SourceUnit, ValidationResult
from .delivery import checksum
from .grid import anchor_cell_from_id
from .native_cells import gldas21_native_cell

COLLECTION = 'NASA/GLDAS/V021/NOAH/G025/T3H'
PROFILE = 'gldas21-noah-four-layer-v1'
BANDS = ('SoilMoi0_10cm_inst', 'SoilMoi10_40cm_inst',
         'SoilMoi40_100cm_inst', 'SoilMoi100_200cm_inst')
TRANSFORM = [0.25, 0.0, -180.0, 0.0, -0.25, 90.0]
START = datetime(2000, 1, 1, 3, tzinfo=timezone.utc)
STEP = timedelta(hours=3)


def digest(value):
    return hashlib.sha256(json.dumps(value, sort_keys=True, separators=(',', ':'), allow_nan=False).encode()).hexdigest()


def month_bounds(year, month):
    return (datetime(year, month, 1, tzinfo=timezone.utc),
            datetime(year + (month == 12), month % 12 + 1, 1, tzinfo=timezone.utc))


def cell_for(unit):
    anchor = anchor_cell_from_id(unit.anchor_id)
    return gldas21_native_cell(anchor.centre_longitude, anchor.centre_latitude)


def work_key(unit):
    if unit.source_id != 'gldas21' or unit.profile_id != PROFILE or type(unit.year) is not int or not 1 <= unit.year <= 9998:
        raise ValueError('Invalid GLDAS source/profile/year')
    cell = cell_for(unit)
    return f'{PROFILE}/R{cell["row"]:04d}_C{cell["column"]:04d}/{unit.year:04d}' + periods.suffix(unit)


def profile_metadata(unit):
    return {**periods.metadata(unit), 'profile_id': PROFILE, 'source_id': 'gldas21', 'collection': COLLECTION,
            'product_version': '2.1', 'model': 'Noah', 'year': unit.year,
            'native_cell': cell_for(unit), 'native_crs': 'EPSG:4326',
            'native_transform': TRANSFORM, 'variables': list(BANDS),
            'units': {b: 'kg m-2' for b in BANDS},
            'depth_intervals_m': [[0, .1], [.1, .4], [.4, 1], [1, 2]],
            'selection': 'native cell containing anchor centre; no interpolation',
            'temporal_support': 'instantaneous at interval_start_utc; interval_end_utc marks next 3-hour slot, not averaging support',
            'missing_policy': 'provider masks and NaN become null; no numeric sentinel substitution or gap filling'}


def normalized_rows(rows, unit, start, end):
    """Validate provider rows before persistence. Never fabricate missing timestamps."""
    cell = cell_for(unit)
    result, seen = [], set()
    for record in rows:
        if set(record) != {'id', 'time', 'longitude', 'latitude', *BANDS}:
            raise ValueError('GLDAS provider row schema mismatch')
        stamp = record['time']
        if type(stamp) not in (int, float) or not math.isfinite(stamp):
            raise ValueError('Invalid provider timestamp')
        dt = datetime.fromtimestamp(stamp / 1000, timezone.utc)
        if not max(start, START) <= dt < end or dt.hour % 3 or dt.minute or dt.second or dt.microsecond:
            raise ValueError('Timestamp outside GLDAS interval or cadence')
        if stamp in seen:
            raise ValueError('Duplicate GLDAS timestamp')
        seen.add(stamp)
        if not isinstance(record['id'], str) or not re.fullmatch(r'[A-Za-z0-9_.-]+', record['id']):
            raise ValueError('Invalid provider image identity')
        for axis in ('longitude', 'latitude'):
            if not math.isclose(float(record[axis]), cell['centre_' + axis], rel_tol=0, abs_tol=1e-7):
                raise ValueError('Provider returned the wrong native cell')
        clean = {'id': record['id'], 'time': int(stamp),
                 'longitude': cell['centre_longitude'], 'latitude': cell['centre_latitude']}
        for band in BANDS:
            value = record[band]
            if value is None:
                clean[band] = None
            elif type(value) not in (int, float):
                raise ValueError('Invalid GLDAS numeric value')
            elif math.isnan(value):
                clean[band] = None
            elif not math.isfinite(value):
                raise ValueError('Infinite GLDAS value')
            else:
                clean[band] = float(value)
        result.append(clean)
    return sorted(result, key=lambda r: r['time'])


def write_json_exclusive(path, document):
    path = Path(path)
    path.parent.mkdir(parents=True, exist_ok=True)
    fd, name = tempfile.mkstemp(prefix='.write-', suffix='.part', dir=path.parent)
    try:
        with os.fdopen(fd, 'w', encoding='utf-8') as stream:
            json.dump(document, stream, indent=2, allow_nan=False)
            stream.write('\n')
        os.link(name, path)
    finally:
        Path(name).unlink(missing_ok=True)


class ProviderFailure(RuntimeError):
    """Sanitized provider failure; raw messages may contain project information."""


def fetch_with_retry(fetch, *, retries=2, sleep=time.sleep):
    for attempt in range(retries + 1):
        try:
            return fetch()
        except Exception as exc:
            message = str(exc).lower()
            if any(word in message for word in ('401', '403', '429', 'permission', 'credential', 'auth', 'quota', 'rate limit')):
                raise ProviderFailure('Provider authentication, permission or quota failure; no account switching') from None
            transient = any(word in message for word in ('timeout', 'timed out', '500', '502', '503', '504', 'temporar', 'connection reset'))
            if not transient or attempt == retries:
                raise ProviderFailure('Provider request failed; completed monthly checkpoints are retained') from None
            sleep(min(2 ** attempt, 8))


class EarthEngineGLDAS:
    def __init__(self, credential_ref):
        if credential_ref is None:
            raise ValueError('A user-owned GEE configuration reference is required')
        path = Path(credential_ref)
        if path.suffix.lower() == '.json':
            gee = json.loads(path.read_text(encoding='utf-8'))
        else:
            with path.open('rb') as stream:
                gee = tomllib.load(stream).get('gee', {})
        if set(gee) - {'project', 'auth_mode'} or not isinstance(gee.get('project'), str) or not gee['project'].strip():
            raise ValueError('GEE configuration requires project and optional auth_mode; OAuth remains with Earth Engine')
        if gee.get('auth_mode', 'interactive') != 'interactive':
            raise ValueError('This pilot requires existing official interactive Earth Engine credentials')
        import ee
        self.ee = ee
        # User runs official earthengine authenticate separately. Never launch it
        # or select a different account/project from an unattended adapter.
        fetch_with_retry(lambda: ee.Initialize(project=gee['project']), retries=0)
        ee.data.setDeadline(60000)

    def fetch(self, unit, start, end):
        ee, cell = self.ee, cell_for(unit)
        collection = (ee.ImageCollection(COLLECTION).filterDate(start.isoformat(), end.isoformat())
                      .select(list(BANDS)).sort('system:time_start'))
        rows = collection.getRegion(ee.Geometry.Point([cell['centre_longitude'], cell['centre_latitude']]),
                                    crs='EPSG:4326', crsTransform=TRANSFORM).getInfo()
        if not rows or set(rows[0]) != {'id', 'longitude', 'latitude', 'time', *BANDS}:
            raise ValueError('Unexpected GEE response schema')
        if any(len(row) != len(rows[0]) for row in rows[1:]):
            raise ValueError('Unexpected GEE row width')
        return [dict(zip(rows[0], row)) for row in rows[1:]]


class GLDAS21Adapter:
    source_id, profile_id = 'gldas21', PROFILE

    def __init__(self, *, provider=None, retries=2, sleep=time.sleep):
        if type(retries) is not int or not 0 <= retries <= 3:
            raise ValueError('retries must be between 0 and 3')
        self.provider, self.retries, self.sleep = provider, retries, sleep

    def plan(self, unit, *, asset_root):
        key = work_key(unit)
        if unit.year < 2000:
            return SourcePlan(unit, 'unavailable', 'outside_product_period', key, 0, 0)
        annual = Path(asset_root) / key / 'annual'
        if annual.exists():
            self.validate(self._prepared(unit, annual))
            return SourcePlan(unit, 'reusable', 'validated_prepared_source', key, 0, 0)
        pending = 0
        for month in periods.months(unit):
            path = Path(asset_root) / key / f'{month:02d}.json'
            if path.exists():
                self._checkpoint(path, unit, month)
            else:
                pending += 1
        return SourcePlan(unit, 'retrievable', 'registered_route; actual provider coverage checked on execution', key,
                          pending * (1 + self.retries), None)

    def _checkpoint(self, path, unit, month):
        doc = json.loads(path.read_text(encoding='utf-8'))
        payload = doc['payload']
        if doc['sha256'] != digest(payload) or payload['work_key'] != work_key(unit) or payload['month'] != month:
            raise ValueError('Monthly checkpoint integrity/identity failure')
        return normalized_rows(payload['rows'], unit, *periods.month_bounds(unit, month))

    def _prepared(self, unit, annual):
        metadata = json.loads((annual / 'manifest.json').read_text(encoding='utf-8'))
        return PreparedSource(unit, (annual / 'data.parquet', annual / 'manifest.json'), metadata)

    def prepare(self, plan, *, output_root, credential_ref=None):
        # Resolve output-format dependencies before any provider request.
        import pyarrow as pa
        import pyarrow.parquet as pq
        unit = plan.unit
        if plan.work_key != work_key(unit) or unit.year < 2000:
            raise ValueError('Invalid or unavailable GLDAS plan')
        directory = Path(output_root) / plan.work_key
        annual = directory / 'annual'
        if annual.exists():
            prepared = self._prepared(unit, annual)
            self.validate(prepared)
            return prepared
        provider, rows = self.provider, []
        for month in periods.months(unit):
            checkpoint = directory / f'{month:02d}.json'
            if not checkpoint.exists():
                if provider is None:
                    provider = EarthEngineGLDAS(credential_ref)
                start, end = periods.month_bounds(unit, month)
                raw = fetch_with_retry(lambda: provider.fetch(unit, start, end), retries=self.retries, sleep=self.sleep)
                normalized = normalized_rows(raw, unit, start, end)
                payload = {'work_key': plan.work_key, 'month': month, 'rows': normalized}
                write_json_exclusive(checkpoint, {'payload': payload, 'sha256': digest(payload)})
            rows.extend(self._checkpoint(checkpoint, unit, month))
        starts = [datetime.fromtimestamp(r['time'] / 1000, timezone.utc) for r in rows]
        columns = {'source_image_id': pa.array([r['id'] for r in rows], type=pa.string()),
                   'interval_start_utc': pa.array(starts, type=pa.timestamp('us', tz='UTC')),
                   'interval_end_utc': pa.array([s + STEP for s in starts], type=pa.timestamp('us', tz='UTC')),
                   'native_longitude': pa.array([r['longitude'] for r in rows], type=pa.float64()),
                   'native_latitude': pa.array([r['latitude'] for r in rows], type=pa.float64()),
                   **{b: pa.array([r[b] for r in rows], type=pa.float64()) for b in BANDS}}
        profile = profile_metadata(unit)
        table = pa.table(columns).replace_schema_metadata({b'benchmark_profile': json.dumps(profile, sort_keys=True).encode()})
        directory.mkdir(parents=True, exist_ok=True)
        with tempfile.TemporaryDirectory(prefix='.annual-', dir=directory) as temporary:
            staging = Path(temporary) / 'annual'
            staging.mkdir()
            pq.write_table(table, staging / 'data.parquet', compression='zstd')
            stats = self._inspect(staging / 'data.parquet', unit)
            metadata = dict(profile, **stats, sha256=checksum(staging / 'data.parquet'),
                            file='data.parquet', schema='benchmark-public-source-manifest-v2')
            write_json_exclusive(staging / 'manifest.json', metadata)
            prepared = self._prepared(unit, staging)
            self.validate(prepared)
            os.rename(staging, annual)
        return self._prepared(unit, annual)

    def _inspect(self, path, unit):
        import pyarrow as pa
        import pyarrow.parquet as pq
        table = pq.read_table(path)
        expected = ['source_image_id', 'interval_start_utc', 'interval_end_utc',
                    'native_longitude', 'native_latitude', *BANDS]
        if table.column_names != expected:
            raise ValueError('Written GLDAS columns mismatch')
        profile = json.loads((table.schema.metadata or {})[b'benchmark_profile'])
        if profile != profile_metadata(unit):
            raise ValueError('Written profile/grid/units/source identity mismatch')
        for field in table.schema:
            wanted = pa.string() if field.name == 'source_image_id' else pa.timestamp('us', tz='UTC') if field.name.startswith('interval_') else pa.float64()
            if field.type != wanted:
                raise ValueError('Written GLDAS column dtype mismatch')
        original = table.to_pylist()
        records = []
        for row in original:
            stamp = row['interval_start_utc']
            if stamp is None or row['interval_end_utc'] != stamp + STEP:
                raise ValueError('Written GLDAS time label mismatch')
            records.append({'id': row['source_image_id'], 'time': stamp.timestamp() * 1000,
                            'longitude': row['native_longitude'], 'latitude': row['native_latitude'],
                            **{b: row[b] for b in BANDS}})
        clean = normalized_rows(records, unit, *periods.bounds(unit))
        if records != clean:
            raise ValueError('Written GLDAS rows are unsorted or use NaN instead of null')
        expected_count = max(0, int((periods.bounds(unit)[1] - max(START, periods.bounds(unit)[0])) / STEP))
        nulls = {b: table[b].null_count for b in BANDS}
        values = {b: [r[b] for r in clean if r[b] is not None] for b in BANDS}
        no_values = not any(values.values())
        state = 'unavailable' if no_values else 'partial' if len(clean) != expected_count or any(nulls.values()) else 'available'
        return {'state': state, 'reason': 'no_valid_values' if no_values else 'missing_timestamps_or_values' if state == 'partial' else None,
                'record_count': len(clean), 'expected_record_count': expected_count,
                'missing_timestamp_count': expected_count - len(clean), 'null_counts': nulls,
                'range_diagnostics': {b: {'min': min(v) if v else None, 'max': max(v) if v else None,
                                          'negative_count': sum(x < 0 for x in v)} for b, v in values.items()}}

    def validate(self, prepared):
        data, manifest = prepared.files
        metadata = json.loads(manifest.read_text(encoding='utf-8'))
        if metadata != prepared.public_metadata or metadata['sha256'] != checksum(data):
            raise ValueError('Prepared GLDAS integrity mismatch')
        expected = dict(profile_metadata(prepared.unit), **self._inspect(data, prepared.unit),
                        sha256=checksum(data), file='data.parquet', schema='benchmark-public-source-manifest-v2')
        if metadata != expected:
            raise ValueError('Prepared GLDAS metadata mismatch')
        gaps = () if metadata['state'] == 'available' else (metadata['reason'],)
        return ValidationResult(True, {k: 'passed' for k in ('integrity', 'schema', 'source', 'units', 'native_grid', 'timestamps', 'null_semantics')}, gaps)
