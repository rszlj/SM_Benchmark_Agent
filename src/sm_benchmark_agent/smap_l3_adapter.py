"""SMAP L3 V006 adapter for the unified multi-source workflow."""
from datetime import date, timedelta
import json
import math
import os
from pathlib import Path
import time

from .adapters import SourcePlan, PreparedSource, ValidationResult
from . import periods
from .delivery import checksum
from .extension_agent import identity
from .grid import anchor_cell_from_id
from .smap_l3 import FIELDS, VARIABLES, observation_table, j2000_utc
from .smap_l3_remote import make_plan, prepare_step, save

PROFILE = 'smap-l3-enhanced-v006-native-am-pm-tb-v1'


def work_key(unit):
    if unit.source_id != 'smap_l3' or unit.profile_id != PROFILE:
        raise ValueError('Unknown SMAP L3 profile')
    anchor_cell_from_id(unit.anchor_id)
    periods.bounds(unit)
    return f'{PROFILE}/{unit.anchor_id}/{unit.year}' + periods.suffix(unit)


def requested_days(unit):
    start, end = periods.bounds(unit)
    day = max(start.date(), date(2015, 3, 31))
    result = []
    while day < end.date():
        result.append(day.isoformat())
        day += timedelta(days=1)
    return result


class SMAPL3Adapter:
    source_id, profile_id, retries = 'smap_l3', PROFILE, 2

    def __init__(self, *, step=None, sleep=time.sleep, max_polls=180):
        self.step = step or prepare_step
        self.sleep, self.max_polls = sleep, max_polls

    def _paths(self, unit, root):
        # Keep physical cache paths short enough for Windows granule filenames.
        folder = Path(root) / 'smap_l3' / identity(work_key(unit))[:24]
        return folder, folder/'smap_l3.parquet', folder/'public.json'

    def _load(self, unit, root):
        _, table, metadata = self._paths(unit, root)
        return PreparedSource(unit, (table, metadata), json.loads(metadata.read_text(encoding='utf-8')))

    def plan(self, unit, *, asset_root):
        folder, table, metadata = self._paths(unit, asset_root)
        if not requested_days(unit):
            return SourcePlan(unit, 'unavailable', 'outside_product_temporal_coverage', work_key(unit), 0, 0)
        if unit.year >= date.today().year:
            return SourcePlan(unit, 'requires_user_action', 'completed_calendar_years_only', work_key(unit), 0, None)
        if metadata.exists():
            self.validate(self._load(unit, asset_root))
            return SourcePlan(unit, 'reusable', 'validated_local_assets', work_key(unit), 0, table.stat().st_size)
        return SourcePlan(unit, 'retrievable', 'Earthdata_Harmony_required', work_key(unit), None, None)

    def prepare(self, plan, *, output_root, credential_ref=None):
        unit = plan.unit
        current = self.plan(unit, asset_root=output_root)
        if current.state == 'reusable':
            return self._load(unit, output_root)
        if current.state != 'retrievable':
            raise ValueError('SMAP L3 is not retrievable for this scope')
        # credential_ref belongs to GEE in a mixed request. Earthdata uses the
        # user's home .netrc; never read the GEE file or embed it in source plans.
        folder, table, metadata_path = self._paths(unit, output_root)
        folder.mkdir(parents=True, exist_ok=True)
        remote_root = folder/'harmony'
        request = {'spatial': {'anchor_ids': [unit.anchor_id]}, 'sources': ['smap_l3'],
                   'station_targets': 'absent', 'output_root': str(remote_root), 'max_packages': 1}
        request.update({'start': unit.start, 'end': unit.end} if unit.start else {'years': [unit.year]})
        remote = make_plan(request)
        lock = folder/'worker.lock'
        with lock.open('x') as f:
            f.write(str(os.getpid()))
        try:
            for _ in range(self.max_polls):
                status = self.step(remote, remote_root)
                if status['status'] == 'complete':
                    break
                if status['status'] == 'running':
                    self.sleep(30)
            else:
                raise TimeoutError('Bounded polling ended; resume the saved jobs')
            import pyarrow.parquet as pq
            annual = remote_root/'annual'/unit.anchor_id/str(unit.year)
            source = json.loads((annual/'source.json').read_text(encoding='utf-8'))
            source_table = annual/'smap_l3.parquet'
            if checksum(source_table) != source['sha256']:
                raise ValueError('SMAP source table changed')
            rows = pq.read_table(source_table).to_pylist()
            pq.write_table(observation_table(rows), table.with_suffix('.part'), compression='zstd')
            table.with_suffix('.part').replace(table)
            days = requested_days(unit)
            present = sorted({r['date'] for r in rows})
            missing = sorted(set(days) - set(present))
            nulls = {field: sum(r[field] is None for r in rows) for field in FIELDS}
            valid = sum(r['soil_moisture'] is not None for r in rows)
            state = 'unavailable' if not valid else ('partial' if missing or nulls['soil_moisture'] else 'available')
            meta = {k: source[k] for k in ('product', 'version', 'units', 'variables', 'sampling',
                    'tb_support', 'time_reference', 'time_conversion', 'quality_policy', 'missing_values')}
            meta.update(source_id='smap_l3', profile_id=PROFILE, anchor_id=unit.anchor_id, year=unit.year,
                        **periods.metadata(unit), state=state,
                        reason=None if state == 'available' else 'missing_source_dates_or_null_soil_moisture',
                        requested_dates=days, source_dates=present, missing_source_dates=missing,
                        records=len(rows), null_counts=nulls, sha256=checksum(table))
            prepared = PreparedSource(unit, (table, metadata_path), meta)
            self.validate(prepared)
            save(metadata_path, meta)
            return prepared
        finally:
            lock.unlink()

    def validate(self, prepared):
        import pyarrow.parquet as pq
        unit, meta = prepared.unit, dict(prepared.public_metadata)
        work_key(unit)
        a = anchor_cell_from_id(unit.anchor_id)
        table = pq.read_table(prepared.files[0])
        if table.schema != observation_table([]).schema or checksum(prepared.files[0]) != meta['sha256']:
            raise ValueError('SMAP schema or checksum mismatch')
        if (meta['source_id'], meta['profile_id'], meta['anchor_id'], meta['year'], meta['product'], meta['version']) != (
                'smap_l3', PROFILE, unit.anchor_id, unit.year, 'SPL3SMP_E', '006') or meta['variables'] != list(VARIABLES):
            raise ValueError('SMAP identity mismatch')
        if meta['units'] != {'soil_moisture': 'm3/m3', 'tb': 'K'} or meta['time_conversion'] != 'J2000 TDB to UTC':
            raise ValueError('SMAP unit/time metadata mismatch')
        rows = table.to_pylist()
        expected, seen = set(requested_days(unit)), set()
        for r in rows:
            key = r['date'], r['pass']
            if r['anchor_id'] != unit.anchor_id or r['date'] not in expected or r['pass'] not in ('AM', 'PM') or key in seen:
                raise ValueError('SMAP scope or duplicate record')
            seen.add(key)
            for field in FIELDS:
                if r[field] is not None and not math.isfinite(r[field]):
                    raise ValueError('Nonfinite value must be null')
            for field, value in [('EASE_row_index', a.row), ('EASE_column_index', a.column)]:
                if r[field] is not None and r[field] != value:
                    raise ValueError('Wrong native source cell')
            if r['soil_moisture'] is not None and (r['EASE_row_index'] is None or r['EASE_column_index'] is None):
                raise ValueError('Missing native cell identity')
            if r['observation_time_utc'] != j2000_utc(r['tb_time_seconds']):
                raise ValueError('Incorrect observation timestamp')
            if r['source_time_units'] != 'seconds since 2000-01-01 11:58:55.816Z':
                raise ValueError('Incorrect source time units')
        present = {d for d, _ in seen}
        missing = sorted(expected - present)
        nulls = {f: sum(r[f] is None for r in rows) for f in FIELDS}
        valid = len(rows) - nulls['soil_moisture']
        state = 'unavailable' if not valid else ('partial' if missing or nulls['soil_moisture'] else 'available')
        if (len(seen) != 2*len(present) or meta['records'] != len(rows) or
                meta['requested_dates'] != sorted(expected) or meta['source_dates'] != sorted(present) or
                meta['missing_source_dates'] != missing or meta['null_counts'] != nulls or meta['state'] != state):
            raise ValueError('SMAP availability metadata mismatch')
        return ValidationResult(True, {'schema': 'passed', 'native_cell': 'passed', 'period': 'passed',
            'time_conversion': 'passed', 'nulls_and_coverage': 'passed'}, tuple(missing))
