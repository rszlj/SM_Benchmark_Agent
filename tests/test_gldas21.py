from dataclasses import asdict
from datetime import datetime, timezone
import json
from pathlib import Path
import tempfile
import sys
import unittest
from unittest.mock import patch, MagicMock
import zipfile

from sm_benchmark_agent.adapters import SourceUnit, default_registry
from sm_benchmark_agent.gldas21 import (BANDS, PROFILE, START, STEP, GLDAS21Adapter, EarthEngineGLDAS, COLLECTION, TRANSFORM,
                                       ProviderFailure, cell_for, fetch_with_retry, month_bounds,
                                       normalized_rows, work_key)
from sm_benchmark_agent.gldas_workflow import plan_gldas, execute_gldas
from sm_benchmark_agent.grid import anchor_cell_from_id
from sm_benchmark_agent.delivery import checksum

ANCHOR = 'EASE2_M09km_R0304_C2105'


class FakeProvider:
    def __init__(self, fail_month=None, missing=False):
        self.calls = []
        self.fail_month, self.missing = fail_month, missing

    def fetch(self, unit, start, end):
        self.calls.append(start.month)
        if start.month == self.fail_month:
            raise RuntimeError('permission denied project=PRIVATE_PROJECT')
        cell = cell_for(unit)
        rows, stamp = [], max(start, START)
        while stamp < end:
            rows.append({'id': stamp.strftime('A%Y%m%d_%H%M'), 'time': int(stamp.timestamp() * 1000),
                         'longitude': cell['centre_longitude'], 'latitude': cell['centre_latitude'],
                         **{b: float(i * 50) for i, b in enumerate(BANDS)}})
            stamp += STEP
        if self.missing and rows:
            rows = rows[1:]
            rows[0][BANDS[1]] = None
        return rows


class GLDAS21Tests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.root = Path(self.temp.name)
        self.unit = SourceUnit('gldas21', PROFILE, ANCHOR, 2001)

    def test_monthly_resume_science_and_no_credentials_in_metadata(self):
        provider = FakeProvider(fail_month=3)
        adapter = GLDAS21Adapter(provider=provider)
        plan = adapter.plan(self.unit, asset_root=self.root)
        self.assertEqual(plan.remote_operations, 36)
        with patch('socket.socket', side_effect=AssertionError('Network forbidden')):
            with self.assertRaises(ProviderFailure) as raised:
                adapter.prepare(plan, output_root=self.root)
            self.assertNotIn('PRIVATE_PROJECT', str(raised.exception))
            self.assertEqual(provider.calls, [1, 2, 3])
            provider.fail_month = None
            provider.calls.clear()
            prepared = adapter.prepare(adapter.plan(self.unit, asset_root=self.root), output_root=self.root)
            self.assertEqual(provider.calls, list(range(3, 13)))
            self.assertTrue(adapter.validate(prepared).passed)
            self.assertEqual(prepared.public_metadata['record_count'], 2920)
            self.assertEqual(prepared.public_metadata['state'], 'available')
            provider.calls.clear()
            adapter.prepare(adapter.plan(self.unit, asset_root=self.root), output_root=self.root)
            self.assertEqual(provider.calls, [])
            self.assertNotIn(str(self.root), prepared.files[1].read_text())
            self.assertNotIn('project', prepared.files[1].read_text().lower())
        import pyarrow.parquet as pq
        table = pq.read_table(prepared.files[0])
        self.assertEqual(table[BANDS[0]][0].as_py(), 0.0)
        self.assertEqual(table[BANDS[3]][0].as_py(), 150.0)
        prepared.files[0].write_bytes(b'corrupt')
        with self.assertRaises(ValueError):
            adapter.plan(self.unit, asset_root=self.root)

    def test_partial_values_and_source_start(self):
        unit = SourceUnit('gldas21', PROFILE, ANCHOR, 2000)
        adapter = GLDAS21Adapter(provider=FakeProvider(missing=True))
        prepared = adapter.prepare(adapter.plan(unit, asset_root=self.root), output_root=self.root)
        metadata = prepared.public_metadata
        self.assertEqual(metadata['expected_record_count'], 2927)
        self.assertEqual(metadata['missing_timestamp_count'], 12)
        self.assertEqual(metadata['null_counts'][BANDS[1]], 12)
        self.assertEqual(metadata['state'], 'partial')
        unavailable = adapter.plan(SourceUnit('gldas21', PROFILE, ANCHOR, 1999), asset_root=self.root)
        self.assertEqual(unavailable.state, 'unavailable')

    def test_native_cell_work_deduplication(self):
        other = SourceUnit('gldas21', PROFILE, 'EASE2_M09km_R0304_C2106', 2001)
        self.assertEqual(work_key(self.unit), work_key(other))
        self.assertEqual(default_registry().require('gldas21').profile_id, PROFILE)

    def test_reject_duplicate_timestamp_wrong_cell_and_inf_keep_numeric_values(self):
        bounds = month_bounds(2001, 1)
        row = FakeProvider().fetch(self.unit, *bounds)[0]
        for rows in [[row, row], [dict(row, longitude=0)], [dict(row, **{BANDS[0]: float('inf')})]]:
            with self.assertRaises(ValueError):
                normalized_rows(rows, self.unit, *bounds)
        row[BANDS[0]] = -32768
        self.assertEqual(normalized_rows([row], self.unit, *bounds)[0][BANDS[0]], -32768)
        row[BANDS[0]] = float('nan')
        self.assertIsNone(normalized_rows([row], self.unit, *bounds)[0][BANDS[0]])

    def test_bounded_retry_and_quota_stop(self):
        waits, calls = [], []
        def transient():
            calls.append(1)
            if len(calls) < 3:
                raise RuntimeError('503 temporary')
            return 'ok'
        self.assertEqual(fetch_with_retry(transient, sleep=waits.append), 'ok')
        self.assertEqual(waits, [1, 2])
        waits.clear()
        with self.assertRaises(ProviderFailure):
            fetch_with_retry(lambda: (_ for _ in ()).throw(RuntimeError('429 quota PROJECT_PRIVATE')), sleep=waits.append)
        self.assertEqual(waits, [])

    def test_actual_provider_request_shape_without_network(self):
        credential = self.root / 'credentials.toml'
        credential.write_text('[gee]\nproject="TEST_PRIVATE_PROJECT"\n')
        ee = MagicMock()
        collection = ee.ImageCollection.return_value
        collection.filterDate.return_value = collection
        collection.select.return_value = collection
        collection.sort.return_value = collection
        row = FakeProvider().fetch(self.unit, *month_bounds(2001, 1))[0]
        header = ['id', 'longitude', 'latitude', 'time', *BANDS]
        collection.getRegion.return_value.getInfo.return_value = [header, [row[k] for k in header]]
        with patch.dict(sys.modules, {'ee': ee}), patch('socket.socket', side_effect=AssertionError('No network')):
            provider = EarthEngineGLDAS(credential)
            result = provider.fetch(self.unit, *month_bounds(2001, 1))
        self.assertEqual(result, [row])
        ee.Initialize.assert_called_once_with(project='TEST_PRIVATE_PROJECT')
        ee.ImageCollection.assert_called_once_with(COLLECTION)
        collection.select.assert_called_once_with(list(BANDS))
        self.assertEqual(collection.getRegion.call_args.kwargs, {'crs': 'EPSG:4326', 'crsTransform': TRANSFORM})

    def test_existing_generated_json_config_and_auth_mode_boundary(self):
        path = self.root / 'gee-config.json'
        path.write_text(json.dumps({'project': 'PRIVATE_FIXTURE', 'auth_mode': 'interactive'}))
        ee = MagicMock()
        with patch.dict(sys.modules, {'ee': ee}):
            EarthEngineGLDAS(path)
            ee.Initialize.assert_called_once_with(project='PRIVATE_FIXTURE')
            path.write_text(json.dumps({'project': 'PRIVATE_FIXTURE', 'auth_mode': 'service_account'}))
            with self.assertRaises(ValueError):
                EarthEngineGLDAS(path)
            self.assertEqual(ee.Initialize.call_count, 1)

    def test_all_masked_is_not_available_and_corrupt_checkpoint_is_not_retrieved(self):
        class Masked(FakeProvider):
            def fetch(self, unit, start, end):
                return [dict(r, **{b: None for b in BANDS}) for r in super().fetch(unit, start, end)]
        adapter = GLDAS21Adapter(provider=Masked())
        prepared = adapter.prepare(adapter.plan(self.unit, asset_root=self.root), output_root=self.root)
        self.assertEqual(prepared.public_metadata['state'], 'unavailable')
        self.assertEqual(prepared.public_metadata['reason'], 'no_valid_values')
        other_root = self.root / 'corruption'
        provider = FakeProvider(fail_month=2)
        adapter = GLDAS21Adapter(provider=provider)
        with self.assertRaises(ProviderFailure):
            adapter.prepare(adapter.plan(self.unit, asset_root=other_root), output_root=other_root)
        path = other_root / work_key(self.unit) / '01.json'
        doc = json.loads(path.read_text())
        doc['payload']['rows'][0][BANDS[0]] = 1.0
        path.write_text(json.dumps(doc))
        with self.assertRaises(ValueError):
            adapter.plan(self.unit, asset_root=other_root)
        self.assertEqual(provider.calls, [1, 2])

    def test_private_context_metadata_rejected_before_provider(self):
        context = self.context_plan()
        doc = json.loads(context.read_text())
        path = self.root / 'srtm.json'
        meta = json.loads(path.read_text())
        meta['project'] = 'PRIVATE_CONTEXT_PROJECT'
        path.write_text(json.dumps(meta))
        next(a for a in doc['assets'] if a['source_id'] == 'srtm')['sha256'] = checksum(path)
        context.write_text(json.dumps(doc))
        request = {'spatial': {'anchor_ids': [ANCHOR]}, 'years': [2001],
                   'sources': ['gldas21', 'srtm', 'hwsd2', 'mcd12q1'], 'station_targets': 'absent',
                   'output_root': str(self.root / 'out')}
        provider = FakeProvider()
        with self.assertRaisesRegex(ValueError, 'Private provider fields'):
            plan_gldas(request, context_plan=context, asset_root=self.root / 'cache', adapter=GLDAS21Adapter(provider=provider))
        self.assertEqual(provider.calls, [])

    def context_plan(self):
        anchor = anchor_cell_from_id(ANCHOR)
        grid = self.root / 'grid.json'
        grid.write_text(json.dumps({'anchor': asdict(anchor)}))
        assets = [{'path': 'grid.json', 'destination': 'metadata/grid.json', 'role': 'metadata',
                   'kind': 'grid', 'source_id': 'grid', 'sha256': checksum(grid)}]
        availability = [{'source': 'ismn', 'state': 'unavailable', 'reason': 'absent_by_design'}]
        # Fixture context states are explicit, not a claim about real product coverage.
        for source in ['srtm', 'hwsd2', 'mcd12q1']:
            path = self.root / f'{source}.json'
            path.write_text(json.dumps({'source_id': source, 'anchor_id': ANCHOR, 'year': 2001,
                                        'state': 'unavailable', 'files': []}))
            assets.append({'path': path.name, 'destination': f'metadata/source_manifests/{source}.json',
                           'role': 'metadata', 'source_id': source, 'sha256': checksum(path)})
            availability.append({'source': source, 'state': 'unavailable', 'reason': 'synthetic unavailable fixture'})
        doc = {'anchor_id': ANCHOR, 'year': 2001, 'release_id': 'test-extension-v1',
               'processing_version': 'test', 'station_targets': 'absent', 'assets': assets, 'availability': availability}
        path = self.root / 'context.json'
        path.write_text(json.dumps(doc))
        return path

    def test_plan_gate_full_assembly_relocation_and_resume(self):
        # An explicit grid-only context is valid when all context sources are
        # unavailable. GLDAS supplies the actual input asset at assembly time.
        context = self.context_plan()
        request = {'spatial': {'anchor_ids': [ANCHOR]}, 'years': [2001],
                   'sources': ['gldas21', 'srtm', 'hwsd2', 'mcd12q1'], 'station_targets': 'absent',
                   'output_root': str(self.root / 'output')}
        provider = FakeProvider()
        adapter = GLDAS21Adapter(provider=provider)
        with patch('socket.socket', side_effect=AssertionError('Network forbidden')):
            plan = plan_gldas(request, context_plan=context, asset_root=self.root / 'cache', adapter=adapter)
            self.assertEqual(provider.calls, [])
            with self.assertRaises(ValueError):
                execute_gldas(plan, accepted_plan_id='wrong', adapter=adapter)
            result = execute_gldas(plan, accepted_plan_id=plan['plan_id'], adapter=adapter)
            self.assertEqual(result['status'], 'packaged')
            provider.calls.clear()
            new_plan = plan_gldas(request, context_plan=context, asset_root=self.root / 'cache', adapter=adapter)
            self.assertEqual(execute_gldas(new_plan, accepted_plan_id=new_plan['plan_id'], adapter=adapter)['status'], 'reused')
            self.assertEqual(provider.calls, [])
        with zipfile.ZipFile(result['archive']) as archive:
            manifest = json.loads(archive.read('package_manifest.json'))
            self.assertEqual(manifest['station_targets'], 'absent_by_design')
            for name in archive.namelist():
                if name.endswith('.json'):
                    self.assertNotIn(str(self.root), archive.read(name).decode())


if __name__ == '__main__':
    unittest.main()
