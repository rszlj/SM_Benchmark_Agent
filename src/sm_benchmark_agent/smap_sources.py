"""SMAP v007 legacy GEE sampling, with explicit spatial limitations."""
from datetime import datetime, timezone
import json
import math
import os
from pathlib import Path
import re
import tempfile
import time

from . import periods
from .adapters import SourcePlan, PreparedSource, ValidationResult
from .delivery import checksum
from .grid import anchor_cell_from_id
from .gldas21 import EarthEngineGLDAS, fetch_with_retry, month_bounds, digest, write_json_exclusive
from .smap_profile import SMAP_L4_SOURCE_ID, SMAP_L4_BANDS as BANDS, expected_smap_l4_month_times

PROFILES = {'smap_l4': 'smap-l4-v007-legacy-13km-v1'}
CORE = ('sm_surface', 'sm_rootzone', 'sm_profile')


def code_hashes():
    root = Path(__file__).parent
    return {n: checksum(root / n) for n in ('periods.py', 'smap_sources.py', 'smap_profile.py', 'grid.py', 'gldas21.py')}


def months(unit):
    return [m for m in periods.months(unit) if (unit.year,m)>=(2015,3)
            and periods.month_bounds(unit,m)[1] > datetime(2015,3,31,1,30,tzinfo=timezone.utc)]


def calendar_times(unit):
    return [d for m in months(unit) for d in expected_smap_l4_month_times(unit.year, m) if periods.contains(unit,d)]


def key(unit):
    if unit.source_id != 'smap_l4' or unit.profile_id != PROFILES['smap_l4'] or type(unit.year) is not int or not 1 <= unit.year <= 9998:
        raise ValueError('Invalid SMAP source/profile/year')
    anchor_cell_from_id(unit.anchor_id)
    return f'{unit.profile_id}/{unit.anchor_id}/{unit.year:04d}' + periods.suffix(unit) + ('/period-v2' if unit.start is not None else '')


def profile(unit):
    a = anchor_cell_from_id(unit.anchor_id)
    return {**periods.metadata(unit), 'source_id': unit.source_id, 'profile_id': unit.profile_id, 'anchor_id': unit.anchor_id,
            'year': unit.year, 'collection': SMAP_L4_SOURCE_ID, 'variables': list(BANDS),
            'query_point': [a.centre_longitude, a.centre_latitude], 'sampling_scale_m': 13000,
            'sampling_crs': 'EPSG:4326 (getRegion default)',
            'representation': 'legacy GEE point sampling; native EASE cell equivalence unverified',
            'spatial_validation': 'returned coordinate proximity and consistency only; not native-cell alignment',
            'units_policy': 'provider band units retained without conversion',
            'units_reference': 'https://developers.google.com/earth-engine/datasets/catalog/NASA_SMAP_SPL4SMGP_007',
            'temporal_support': 'three-hourly source time-averaged values; V1 timestamps retained',
            'missing_policy': 'absent calendar slots inserted as null; no value interpolation; provider masks/nonfinite become null',
            'availability_policy': 'calendar and three core soil-moisture bands; ancillary null counts reported separately'}


def normalized_rows(rows, unit, start, end):
    allowed = {int(d.timestamp() * 1000) for d in calendar_times(unit) if start <= d < end}
    lon, lat = profile(unit)['query_point']
    clean, seen, coordinate = [], set(), None
    for r in rows:
        if set(r) != {'id', 'time', 'longitude', 'latitude', *BANDS}:
            raise ValueError('Provider schema mismatch')
        stamp = r['time']
        if type(stamp) not in (int, float) or not math.isfinite(stamp) or stamp not in allowed or stamp in seen:
            raise ValueError('Unexpected or duplicate calendar timestamp')
        if not isinstance(r['id'], str) or not re.fullmatch(r'[A-Za-z0-9_.-]+', r['id']):
            raise ValueError('Invalid provider image identity')
        seen.add(stamp)
        xy = (r['longitude'], r['latitude'])
        if any(type(v) not in (int, float) or not math.isfinite(v) for v in xy) or not -180 <= xy[0] <= 180 or not -90 <= xy[1] <= 90:
            raise ValueError('Invalid provider coordinates')
        # A deliberately loose sanity bound, not an asserted native grid transform.
        if abs((xy[0] - lon + 180) % 360 - 180) > .12 or abs(xy[1] - lat) > .12:
            raise ValueError('Provider point is inconsistent with requested anchor')
        if coordinate is not None and any(abs(a-b) > 1e-7 for a, b in zip(xy, coordinate)):
            raise ValueError('Provider sampling coordinate changed')
        coordinate = xy
        out = dict(id=r['id'], time=int(stamp), longitude=float(xy[0]), latitude=float(xy[1]))
        for b in BANDS:
            v = r[b]
            if v is not None and type(v) not in (int, float):
                raise ValueError('Invalid numeric value')
            out[b] = None if v is None or not math.isfinite(v) else float(v)
        clean.append(out)
    return sorted(clean, key=lambda r: r['time'])


class EarthEngineSMAP(EarthEngineGLDAS):
    def fetch(self, unit, start, end):
        ee = self.ee
        collection = (ee.ImageCollection(SMAP_L4_SOURCE_ID).filterDate(start.isoformat(), end.isoformat())
                      .select(list(BANDS)).sort('system:time_start'))
        count = collection.size().getInfo()
        limit = len([d for d in calendar_times(unit) if start <= d < end])
        if type(count) is not int or not 0 <= count <= limit:
            raise ValueError('Unexpected provider image count')
        if not count:
            return []
        table = collection.getRegion(ee.Geometry.Point(profile(unit)['query_point']), scale=13000).getInfo()
        if not table or len(table)-1 != count or len(set(table[0])) != len(table[0]) or set(table[0]) != {'id', 'time', 'longitude', 'latitude', *BANDS}:
            raise ValueError('Unexpected provider table schema/count')
        if any(len(r) != len(table[0]) for r in table[1:]):
            raise ValueError('Invalid provider row width')
        return [dict(zip(table[0], r)) for r in table[1:]]


def to_table(rows, unit):
    import pyarrow as pa
    lookup = {r['time']: r for r in rows}
    times = calendar_times(unit)
    columns = {'time_utc': pa.array(times, type=pa.timestamp('ms', tz='UTC'))}
    for b in BANDS:
        columns[b] = pa.array([lookup.get(int(d.timestamp()*1000), {}).get(b) for d in times], type=pa.float32())
    return pa.table(columns).replace_schema_metadata({b'benchmark_profile': json.dumps(profile(unit), sort_keys=True).encode()})


class SMAPL4Adapter:
    source_id, profile_id = 'smap_l4', PROFILES['smap_l4']

    def __init__(self, source_id='smap_l4', *, provider=None, retries=2, sleep=time.sleep):
        if source_id != self.source_id or type(retries) is not int or not 0 <= retries <= 3:
            raise ValueError('Invalid source or retry count')
        self.provider, self.retries, self.sleep = provider, retries, sleep

    def _prepared(self, unit, directory):
        meta = json.loads((directory / 'manifest.json').read_text(encoding='utf-8'))
        return PreparedSource(unit, (directory / 'data.parquet', directory / 'manifest.json'), meta)

    def _checkpoint(self, path, unit, month):
        doc = json.loads(path.read_text(encoding='utf-8'))
        p = doc['payload']
        if doc['sha256'] != digest(p) or p['work_key'] != key(unit) or p['month'] != month or p['profile'] != profile(unit) or p['processing_code_sha256'] != code_hashes():
            raise ValueError('Checkpoint integrity/profile/code mismatch')
        return normalized_rows(p['rows'], unit, *periods.month_bounds(unit, month))

    def plan(self, unit, *, asset_root):
        work = key(unit)
        root = Path(asset_root) / work
        if (root / 'annual').exists():
            self.validate(self._prepared(unit, root / 'annual'))
            return SourcePlan(unit, 'reusable', 'validated_prepared_source', work, 0, 0)
        if not calendar_times(unit):
            return SourcePlan(unit, 'unavailable', 'outside_product_period', work, 0, 0)
        pending = 0
        for month in months(unit):
            path = root / f'{month:02d}.json'
            if path.exists():
                self._checkpoint(path, unit, month)
            else:
                pending += 1
        return SourcePlan(unit, 'retrievable', 'v007 coverage checked during execution; legacy sampling, native equivalence unverified', work, pending*2*(1+self.retries), None)

    def prepare(self, plan, *, output_root, credential_ref=None):
        import pyarrow.parquet as pq
        unit = plan.unit
        if plan.work_key != key(unit):
            raise ValueError('Changed work identity')
        root = Path(output_root) / plan.work_key
        annual = root / 'annual'
        if annual.exists():
            prepared = self._prepared(unit, annual)
            self.validate(prepared)
            return prepared
        rows, provider = [], self.provider
        for month in months(unit):
            path = root / f'{month:02d}.json'
            if not path.exists():
                if provider is None:
                    provider = EarthEngineSMAP(credential_ref)
                start, end = periods.month_bounds(unit, month)
                if (unit.year, month) == (2015, 3):
                    start = max(start, datetime(2015, 3, 31, tzinfo=timezone.utc))
                raw = fetch_with_retry(lambda: provider.fetch(unit, start, end), retries=self.retries, sleep=self.sleep)
                clean = normalized_rows(raw, unit, start, end)
                payload = dict(work_key=plan.work_key, month=month, profile=profile(unit), processing_code_sha256=code_hashes(), rows=clean)
                write_json_exclusive(path, {'payload': payload, 'sha256': digest(payload)})
            rows.extend(self._checkpoint(path, unit, month))
        rows = normalized_rows(rows, unit, datetime(unit.year, 1, 1, tzinfo=timezone.utc), datetime(unit.year+1, 1, 1, tzinfo=timezone.utc))
        records = [{k: r[k] for k in ('id', 'time', 'longitude', 'latitude')} for r in rows]
        root.mkdir(parents=True, exist_ok=True)
        with tempfile.TemporaryDirectory(prefix='.annual-', dir=root) as temporary:
            stage = Path(temporary) / 'annual'
            stage.mkdir()
            pq.write_table(to_table(rows, unit), stage/'data.parquet', compression='zstd', compression_level=7)
            meta = self._metadata(stage/'data.parquet', unit, records)
            write_json_exclusive(stage/'manifest.json', meta)
            self.validate(self._prepared(unit, stage))
            os.rename(stage, annual)
        return self._prepared(unit, annual)

    def _metadata(self, path, unit, records):
        import pyarrow.parquet as pq
        table = pq.read_table(path)
        empty = to_table([], unit)
        if not table.schema.equals(empty.schema, check_metadata=True) or table['time_utc'] != empty['time_utc']:
            raise ValueError('Written schema/profile/calendar mismatch')
        expected = {int(d.timestamp()*1000) for d in calendar_times(unit)}
        rows = []
        if any(set(r) != {'id', 'time', 'longitude', 'latitude'} for r in records):
            raise ValueError('Invalid provider receipt')
        receipt = {r['time']: r for r in records}
        if len(receipt) != len(records) or set(receipt) - expected:
            raise ValueError('Duplicate or out-of-calendar receipt')
        for r in table.to_pylist():
            stamp = int(r.pop('time_utc').timestamp()*1000)
            if any(v is not None and not math.isfinite(v) for v in r.values()):
                raise ValueError('Written nonfinite value')
            if stamp in receipt:
                rows.append(dict(receipt[stamp], **r))
            elif any(v is not None for v in r.values()):
                raise ValueError('Values without provider record')
        clean = normalized_rows(rows, unit, datetime(unit.year,1,1,tzinfo=timezone.utc), datetime(unit.year+1,1,1,tzinfo=timezone.utc))
        if rows != clean or records != [{k:r[k] for k in ('id','time','longitude','latitude')} for r in clean]:
            raise ValueError('Unsorted provider records')
        missing = sorted(expected - set(receipt))
        nulls = {b: table[b].null_count for b in BANDS}
        no_values = not records or all(nulls[b] == table.num_rows for b in CORE)
        incomplete = bool(missing) or any(nulls[b] for b in CORE)
        state = 'unavailable' if no_values else 'partial' if incomplete else 'available'
        reason = ('outside_product_period' if unit.year < 2015 else 'no_provider_records' if not records else 'no_valid_core_values') if no_values else 'missing_timestamps_or_core_values' if incomplete else None
        return dict(profile(unit), schema='benchmark-public-source-manifest-v2', file='data.parquet',
                    sha256=checksum(path), processing_code_sha256=code_hashes(), provider_records=records,
                    record_count=table.num_rows, provider_record_count=len(records), expected_record_count=len(expected),
                    missing_timestamp_count=len(missing), missing_timestamps_ms=missing, null_counts=nulls, state=state, reason=reason)

    def validate(self, prepared):
        key(prepared.unit)
        data, manifest = prepared.files
        if {p.name for p in data.parent.iterdir()} != {'data.parquet','manifest.json'}:
            raise ValueError('Unexpected prepared files')
        meta = json.loads(manifest.read_text(encoding='utf-8'))
        if meta != self._metadata(data, prepared.unit, meta['provider_records']) or meta != prepared.public_metadata:
            raise ValueError('Prepared integrity/profile/code mismatch')
        gaps = ('native_cell_equivalence_unverified',) + (() if meta['state']=='available' else (meta['reason'],))
        return ValidationResult(True, {'integrity':'passed','schema':'passed','calendar':'passed','sampling_coordinate_sanity':'passed','native_cell_alignment':'unverified','unit_conversion':'none'}, gaps)
