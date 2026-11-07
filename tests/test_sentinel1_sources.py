from datetime import datetime, timezone
import json
from pathlib import Path
import tempfile
import unittest
from unittest.mock import patch, MagicMock

import numpy as np
from affine import Affine
from rasterio.io import MemoryFile
import xarray as xr

from sm_benchmark_agent.adapters import SourceUnit
from sm_benchmark_agent.sentinel1_sources import (Sentinel1Adapter, EarthEngineSentinel1, PROFILE, grid,
    acquisitions, digest, MAX_SCENES, MAX_ACQUISITIONS)
from sm_benchmark_agent.sentinel1_workflow import plan_sentinel1, execute_sentinel1
from sm_benchmark_agent.context_sources import ContextAdapter, PROFILES as CONTEXT_PROFILES
from sm_benchmark_agent.context_workflow import plan_contexts, execute_contexts
from sm_benchmark_agent.archives import verify_archive
from test_context_sources import ANCHOR, soil_fixture, RasterProvider


def scenes(year=2015):
    result = []
    for index in range(3):
        dt = datetime(year, 1 if index < 2 else 2, 1, 12, 0, index, tzinfo=timezone.utc)
        result.append({'system:index': f'S1A_fixture_{index}', 'system:time_start': int(dt.timestamp()*1000),
            'instrumentMode': 'IW', 'resolution_meters': 10, 'transmitterReceiverPolarisation': ['VV', 'VH'] if index < 2 else ['VV'],
            'orbitProperties_pass': 'ASCENDING', 'relativeOrbitNumber_start': 45 + index,
            'orbitNumber_start': 5000 if index < 2 else 6000, 'platform_number': 'A'})
    return result


class Provider:
    def __init__(self, *, fail=False, empty=False, masked=False, bad_grid=False):
        self.calls, self.discoveries = [], 0
        self.fail, self.empty, self.masked, self.bad_grid = fail, empty, masked, bad_grid

    def discover(self, unit):
        self.discoveries += 1
        return [] if self.empty else scenes(unit.year)

    def fetch(self, unit, acquisition):
        self.calls.append(acquisition['acquisition_id'])
        if self.fail and len(self.calls) == 2:
            raise RuntimeError('interrupted')
        context = grid(unit)
        data = np.stack([np.full((260, 260), 35 if b == 'angle' else -12, dtype='float32') for b in acquisition['bands']])
        data[:, :2, :2] = -9999
        if self.masked:
            data[:] = -9999
        transform = Affine(context.exact_spacing_m, 0, context.upper_left_x_m + int(self.bad_grid), 0, -context.exact_spacing_m, context.upper_left_y_m)
        with MemoryFile() as memory:
            with memory.open(driver='GTiff', height=260, width=260, count=len(data), dtype='float32', crs='EPSG:6933', transform=transform) as ds:
                ds.write(data)
            return memory.read()


class Sentinel1Tests(unittest.TestCase):
    def setUp(self):
        self.temporary = tempfile.TemporaryDirectory()
        self.addCleanup(self.temporary.cleanup)
        self.root = Path(self.temporary.name)
        self.unit = SourceUnit('sentinel1', PROFILE, ANCHOR, 2015)
        network = patch('socket.socket', side_effect=AssertionError('No network'))
        network.start()
        self.addCleanup(network.stop)

    def test_groups_keep_relative_orbit_variation_and_vv_only(self):
        groups = acquisitions(list(reversed(scenes())), self.unit)
        self.assertEqual(len(groups), 2)
        self.assertEqual(groups[0]['relative_orbit'], 45)
        self.assertEqual(len(groups[0]['scene_ids']), 2)
        self.assertEqual(groups[1]['bands'], ['VV', 'angle'])
        for field, value in [('system:time_start', 0), ('orbitProperties_pass', 'invalid'), ('instrumentMode', 'EW')]:
            rows = scenes(); rows[0][field] = value
            with self.assertRaises(ValueError):
                acquisitions(rows, self.unit)
        with self.assertRaises(ValueError):
            acquisitions([scenes()[0]]*(MAX_SCENES+1), self.unit)

    def test_prepare_masks_netcdf_metadata_and_offline_reuse(self):
        provider = Provider()
        adapter = Sentinel1Adapter(provider=provider)
        plan = adapter.plan(self.unit, asset_root=self.root)
        self.assertEqual(provider.discoveries, 0)
        self.assertEqual(plan.remote_operations, (1+MAX_ACQUISITIONS*2)*3)
        result = adapter.prepare(plan, output_root=self.root)
        self.assertEqual(result.public_metadata['state'], 'partial')
        with xr.open_dataset(result.files[0], engine='h5netcdf') as ds:
            self.assertEqual(ds.sizes['time'], 2)
            self.assertTrue(np.isnan(ds.vh.values[1]).all())
            self.assertEqual(ds.vv.values[0, 3, 3], -12)
            self.assertTrue(np.isnan(ds.vv.values[0, 0, 0]))
            self.assertEqual(ds.absolute_orbit.values.tolist(), [5000, 6000])
        with patch('sm_benchmark_agent.sentinel1_sources.EarthEngineSentinel1', side_effect=AssertionError('No login')):
            fresh = Sentinel1Adapter()
            self.assertEqual(fresh.plan(self.unit, asset_root=self.root).state, 'reusable')
            fresh.validate(fresh.prepare(plan, output_root=self.root))
        self.assertEqual(len(provider.calls), 2)

    def test_interrupted_acquisition_resumes_and_rejects_corruption(self):
        provider = Provider(fail=True)
        adapter = Sentinel1Adapter(provider=provider)
        plan = adapter.plan(self.unit, asset_root=self.root)
        with self.assertRaises(RuntimeError):
            adapter.prepare(plan, output_root=self.root)
        plan = adapter.plan(self.unit, asset_root=self.root)
        self.assertEqual(plan.remote_operations, 6)
        provider.fail = False
        result = adapter.prepare(plan, output_root=self.root)
        self.assertEqual(provider.discoveries, 1)
        self.assertEqual(provider.calls.count(provider.calls[0]), 1)
        result.files[0].write_bytes(b'corrupt')
        with self.assertRaises(Exception):
            adapter.plan(self.unit, asset_root=self.root)

    def test_wrong_grid_and_corrupt_discovery_rejected(self):
        adapter = Sentinel1Adapter(provider=Provider(bad_grid=True))
        plan = adapter.plan(self.unit, asset_root=self.root)
        with self.assertRaises(ValueError):
            adapter.prepare(plan, output_root=self.root)
        self.assertFalse((self.root / plan.work_key / 'annual').exists())
        path = self.root / plan.work_key / 'discovery.json'
        doc = json.loads(path.read_text()); doc['payload']['scenes'][0]['orbitNumber_start'] = 1
        path.write_text(json.dumps(doc))
        with self.assertRaises(ValueError):
            adapter.plan(self.unit, asset_root=self.root)

    def test_empty_masked_and_before_product(self):
        for label, year, provider, reason in [('empty', 2015, Provider(empty=True), 'no_provider_acquisitions'),
            ('masked', 2015, Provider(masked=True), 'no_valid_backscatter'),
            ('outside', 2013, Provider(), 'outside_product_period')]:
            unit = SourceUnit('sentinel1', PROFILE, ANCHOR, year)
            adapter = Sentinel1Adapter(provider=provider)
            root = self.root / label
            result = adapter.prepare(adapter.plan(unit, asset_root=root), output_root=root)
            self.assertEqual(result.public_metadata['state'], 'unavailable')
            self.assertEqual(result.public_metadata['reason'], reason)
            if label == 'outside':
                self.assertEqual(provider.discoveries, 0)

    def test_provider_discovery_and_power_mean_request(self):
        ee = MagicMock()
        collection = ee.ImageCollection.return_value
        for name in ('filterBounds', 'filterDate', 'filter', 'sort'):
            getattr(collection, name).return_value = collection
        collection.toList.return_value.map.return_value.getInfo.return_value = scenes()
        image = ee.Image.return_value
        ee.Image.constant.return_value = image
        collection.mosaic.return_value = image
        for name in ('select', 'setDefaultProjection', 'divide', 'pow', 'rename', 'addBands', 'reduceResolution', 'log10', 'multiply', 'unmask', 'toFloat'):
            getattr(image, name).return_value = image
        provider = object.__new__(EarthEngineSentinel1); provider.ee = ee
        self.assertEqual(len(provider.discover(self.unit)), 3)
        collection.toList.assert_called_once_with(MAX_SCENES + 1)
        ee.Filter.listContains.assert_called_once_with('transmitterReceiverPolarisation', 'VV')
        response = MagicMock(); response.__enter__.return_value.read.return_value = b'fixture'
        with patch('sm_benchmark_agent.sentinel1_sources.urlopen', return_value=response):
            provider.fetch(self.unit, acquisitions(scenes(), self.unit)[0])
        self.assertEqual(image.reduceResolution.call_args.kwargs['maxPixels'], 256)
        self.assertFalse(image.reduceResolution.call_args.kwargs['bestEffort'])
        image.divide.assert_called_with(10.0); image.log10.assert_called_once(); image.multiply.assert_called_with(10.0)
        self.assertEqual(image.getDownloadURL.call_args.args[0]['dimensions'], [260, 260])

    def test_annual_delivery_relocation_and_reuse(self):
        soil = soil_fixture(self.root / 'soil')
        adapters = {s: ContextAdapter(s, provider=RasterProvider(), hwsd_cache=soil) for s in CONTEXT_PROFILES}
        request = {'spatial': {'anchor_ids': [ANCHOR]}, 'years': [2015], 'station_targets': 'absent',
                   'sources': list(CONTEXT_PROFILES), 'output_root': str(self.root / 'contexts')}
        plan = plan_contexts(request, asset_root=self.root / 'cc', release_id='s1-fixture-v1', hwsd_cache=soil, adapters=adapters)
        context = execute_contexts(plan, accepted_plan_id=plan['plan_id'], adapters=adapters)['context_plan']
        provider = Provider(); adapters = {'sentinel1': Sentinel1Adapter(provider=provider)}
        request.update(sources=['sentinel1'], output_root=str(self.root / 'delivery'))
        kwargs = dict(context_plan=context, asset_root=self.root / 'cache', adapters=adapters)
        plan = plan_sentinel1(request, **kwargs)
        with self.assertRaises(ValueError):
            execute_sentinel1(plan, accepted_plan_id='wrong', adapters=adapters)
        result = execute_sentinel1(plan, accepted_plan_id=plan['plan_id'], adapters=adapters)
        moved = self.root / 'moved.zip'; moved.write_bytes(Path(result['archive']).read_bytes())
        verify_archive(moved)
        plan = plan_sentinel1(request, **kwargs)
        self.assertEqual(execute_sentinel1(plan, accepted_plan_id=plan['plan_id'], adapters=adapters)['status'], 'reused')
        self.assertEqual(provider.discoveries, 1)
