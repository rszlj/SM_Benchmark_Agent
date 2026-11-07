from datetime import timedelta
import json
from pathlib import Path
import tempfile
import unittest
from unittest.mock import patch, MagicMock
import zipfile

import pyarrow.parquet as pq

from sm_benchmark_agent.adapters import SourceUnit, default_registry
from sm_benchmark_agent.timeseries_sources import (PROFILES, TimeSeriesAdapter, EarthEngineTimeSeries,
    cell_for, bands, step, month_bounds, normalized_rows, IMERG_SENTINEL)
from sm_benchmark_agent.timeseries_workflow import plan_timeseries, execute_timeseries
from sm_benchmark_agent.context_sources import ContextAdapter, PROFILES as CONTEXT_PROFILES
from sm_benchmark_agent.context_workflow import plan_contexts, execute_contexts
from sm_benchmark_agent.archives import verify_archive
from test_context_sources import soil_fixture, RasterProvider, ANCHOR


class Provider:
    def __init__(self, *, fail=None, empty=False, masked=False, missing=False, provisional=False):
        self.calls = []
        self.fail, self.empty, self.masked = fail, empty, masked
        self.missing, self.provisional = missing, provisional

    def fetch(self, unit, start, end):
        self.calls.append((unit.source_id, start.month))
        if start.month == self.fail:
            raise RuntimeError('interrupted')
        if self.empty:
            return []
        cell, records = cell_for(unit), []
        dt = start
        while dt < end:
            row = {'id': dt.strftime('%Y%m%d%H%M%S'), 'time': dt.timestamp() * 1000,
                   'longitude': cell['centre_longitude'], 'latitude': cell['centre_latitude'],
                   **{b: None if self.masked else 0.25 for b in bands(unit)}}
            if unit.source_id == 'imerg_v07':
                row['status'] = 'provisional' if self.provisional else 'permanent'
                row['MWprecipitation'] = IMERG_SENTINEL
            records.append(row)
            dt += step(unit)
        return records[1:] if self.missing else records


class TimeSeriesTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.root = Path(self.temp.name)
        self.network = patch('socket.socket', side_effect=AssertionError('No network'))
        self.network.start()
        self.addCleanup(self.network.stop)

    def unit(self, source='era5_land', year=2013):
        return SourceUnit(source, PROFILES[source], ANCHOR, year)

    def test_profiles_schema_values_masks_and_registry(self):
        for source in PROFILES:
            unit = self.unit(source)
            provider = Provider()
            adapter = TimeSeriesAdapter(source, provider=provider)
            self.assertEqual(default_registry().require(source).profile_id, unit.profile_id)
            plan = adapter.plan(unit, asset_root=self.root)
            self.assertEqual(provider.calls, [])
            self.assertEqual(plan.remote_operations, 72 if source == 'era5_land' else 108)
            output = adapter.prepare(plan, output_root=self.root)
            table = pq.read_table(output.files[0])
            self.assertEqual(table.num_rows, 8760 if source == 'era5_land' else 17520)
            self.assertEqual(output.public_metadata['state'], 'available')
            if source == 'era5_land':
                self.assertEqual(table['total_precipitation'][0].as_py(), .25)
                self.assertNotIn('total_precipitation_hourly', table.column_names)
                self.assertEqual(str(table['2m_temperature'].type), 'float')
            else:
                self.assertEqual(table['MWprecipitation'].null_count, 17520)
                self.assertEqual(table['precipitation'][0].as_py(), .25)
            with patch('sm_benchmark_agent.timeseries_sources.EarthEngineTimeSeries', side_effect=AssertionError('No login')):
                fresh = TimeSeriesAdapter(source)
                self.assertEqual(fresh.plan(unit, asset_root=self.root).state, 'reusable')
                fresh.validate(fresh.prepare(plan, output_root=self.root))
            self.assertEqual(len(provider.calls), 12)

    def test_interrupt_resume_and_corruption(self):
        provider = Provider(fail=3)
        adapter = TimeSeriesAdapter('era5_land', provider=provider)
        unit = self.unit()
        plan = adapter.plan(unit, asset_root=self.root)
        with self.assertRaises(RuntimeError):
            adapter.prepare(plan, output_root=self.root)
        provider.fail = None
        plan = adapter.plan(unit, asset_root=self.root)
        self.assertEqual(plan.remote_operations, 60)
        output = adapter.prepare(plan, output_root=self.root)
        self.assertEqual(provider.calls.count(('era5_land', 1)), 1)
        self.assertEqual(provider.calls.count(('era5_land', 2)), 1)
        output.files[0].write_bytes(b'broken')
        with self.assertRaises(Exception):
            adapter.plan(unit, asset_root=self.root)
        other = self.root / 'raw-corrupt'
        adapter.provider = Provider(fail=2)
        with self.assertRaises(RuntimeError):
            adapter.prepare(adapter.plan(unit, asset_root=other), output_root=other)
        path = next(other.rglob('01.json'))
        doc = json.loads(path.read_text())
        doc['payload']['rows'][0]['time'] += 1
        path.write_text(json.dumps(doc))
        with self.assertRaises(ValueError):
            adapter.plan(unit, asset_root=other)

    def test_gap_status_empty_outside_and_masked(self):
        for label, provider, year, state, reason in [
            ('gap', Provider(missing=True), 2013, 'partial', None),
            ('provisional', Provider(provisional=True), 2013, 'partial', None),
            ('empty', Provider(empty=True), 2013, 'unavailable', 'no_provider_records'),
            ('masked', Provider(masked=True), 2013, 'unavailable', 'no_valid_values'),
            ('outside', Provider(), 1997, 'unavailable', 'outside_product_period')]:
            adapter, unit = TimeSeriesAdapter('imerg_v07', provider=provider), self.unit('imerg_v07', year)
            root = self.root / label
            output = adapter.prepare(adapter.plan(unit, asset_root=root), output_root=root)
            self.assertEqual(output.public_metadata['state'], state)
            if reason:
                self.assertEqual(output.public_metadata['reason'], reason)
            if label == 'gap':
                self.assertEqual(output.public_metadata['missing_timestamp_count'], 12)
                self.assertEqual(pq.read_table(output.files[0]).num_rows, 17508)
            if label == 'outside':
                self.assertEqual(provider.calls, [])

    def test_reject_wrong_cell_duplicate_and_off_cadence(self):
        unit = self.unit()
        start, end = month_bounds(2013, 1)
        row = Provider().fetch(unit, start, start + timedelta(hours=1))[0]
        for records in [[row, row], [dict(row, time=row['time'] + 1000)], [dict(row, latitude=0)], [dict(row, id='private/path')]]:
            with self.assertRaises(ValueError):
                normalized_rows(records, unit, start, end)

    def test_provider_native_transform_and_missing_band_harmonization(self):
        for source in PROFILES:
            unit = self.unit(source)
            start, end = month_bounds(2013, 1)
            row = Provider().fetch(unit, start, start + step(unit))[0]
            status = row.pop('status', None)
            ee = MagicMock()
            collection = ee.ImageCollection.return_value
            for name in ('filterDate', 'sort', 'select', 'map'):
                getattr(collection, name).return_value = collection
            collection.size.return_value.getInfo.return_value = 1
            collection.getRegion.return_value.getInfo.return_value = [list(row), list(row.values())]
            collection.reduceColumns.return_value.get.return_value.getInfo.return_value = [[row['id'], status]]
            provider = object.__new__(EarthEngineTimeSeries)
            provider.ee = ee
            result = provider.fetch(unit, start, end)
            self.assertEqual(len(result), 1)
            transform = collection.getRegion.call_args.kwargs['crsTransform']
            self.assertEqual(transform[2], -180.05 if source == 'era5_land' else -180.0)
            if source == 'imerg_v07':
                collection.map.call_args.args[0](MagicMock())
                self.assertEqual(result[0]['status'], 'permanent')
                self.assertEqual(ee.Algorithms.If.call_count, 9)

    def test_delivery_plan_resume_and_relocation(self):
        soil = soil_fixture(self.root / 'soil')
        adapters = {s: ContextAdapter(s, provider=RasterProvider(), hwsd_cache=soil) for s in CONTEXT_PROFILES}
        request = {'spatial': {'anchor_ids': [ANCHOR]}, 'years': [2013], 'station_targets': 'absent',
                   'sources': list(CONTEXT_PROFILES), 'output_root': str(self.root / 'contexts')}
        plan = plan_contexts(request, asset_root=self.root / 'cc', release_id='timeseries-fixture-v1', hwsd_cache=soil, adapters=adapters)
        context = execute_contexts(plan, accepted_plan_id=plan['plan_id'], adapters=adapters)['context_plan']
        provider = Provider()
        adapters = {s: TimeSeriesAdapter(s, provider=provider) for s in PROFILES}
        request.update(sources=list(PROFILES), output_root=str(self.root / 'delivery'))
        kwargs = dict(context_plan=context, asset_root=self.root / 'cache', adapters=adapters)
        plan = plan_timeseries(request, **kwargs)
        with self.assertRaises(ValueError):
            execute_timeseries(plan, accepted_plan_id='wrong', adapters=adapters)
        result = execute_timeseries(plan, accepted_plan_id=plan['plan_id'], adapters=adapters)
        moved = self.root / 'moved.zip'
        moved.write_bytes(Path(result['archive']).read_bytes())
        verify_archive(moved)
        with zipfile.ZipFile(moved) as archive:
            self.assertEqual(len([n for n in archive.namelist() if n.endswith('.parquet')]), 2)
        plan = plan_timeseries(request, **kwargs)
        self.assertEqual(execute_timeseries(plan, accepted_plan_id=plan['plan_id'], adapters=adapters)['status'], 'reused')
        self.assertEqual(len(provider.calls), 24)
