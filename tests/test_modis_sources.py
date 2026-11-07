from datetime import date, datetime, timezone
import json
from pathlib import Path
import shutil
import sys
import tempfile
import unittest
from unittest.mock import patch, MagicMock
import zipfile

import numpy as np
from pyproj import Transformer
import rasterio
from rasterio.io import MemoryFile
from rasterio.transform import from_bounds

from sm_benchmark_agent.adapters import SourceUnit, default_registry
from sm_benchmark_agent.archives import verify_archive
from sm_benchmark_agent.context_sources import ContextAdapter, PROFILES as CONTEXT_PROFILES
from sm_benchmark_agent.context_workflow import plan_contexts, execute_contexts
from sm_benchmark_agent.modis_sources import MODISAdapter, EarthEngineMODIS, PROFILES, SOURCES, nominal_dates, scientific_profile
from sm_benchmark_agent.modis_workflow import plan_modis, execute_modis
from sm_benchmark_agent.processing import ndvi, landcover
from test_context_sources import soil_fixture, RasterProvider, ANCHOR


class MODISProvider:
    def __init__(self, *, empty=False, masked=False, bad_dates=False):
        self.calls = []
        self.empty, self.masked, self.bad_dates = empty, masked, bad_dates

    def fetch(self, unit, context):
        self.calls.append(unit.source_id)
        dates = nominal_dates(unit.source_id, unit.year)
        if self.empty:
            return {'dates': [], 'image_ids': [], 'payload': None}
        science = scientific_profile(unit.source_id)
        kind = SOURCES[unit.source_id][2]
        crs = 'EPSG:4326' if unit.source_id == 'mod13q1_ndvi' else landcover.NATIVE_CRS
        b = context.bounds
        bounds = Transformer.from_crs(6933, crs, always_xy=True).transform_bounds(
            b.xmin - 1500, b.ymin - 1500, b.xmax + 1500, b.ymax + 1500, densify_pts=21)
        count = len(dates) * (1 if kind == 'ndvi' else 2)
        values = np.full((count, 64, 64), 5000 if kind == 'ndvi' else 15000, dtype='int16')
        missing = -3000 if kind == 'ndvi' else -32768
        if kind == 'lst':
            values[1::2] = 14500
        else:
            values[0] = 0
        values[:, 20:44, 20:44] = missing
        if self.masked:
            values[:] = missing
        with MemoryFile() as memory:
            with memory.open(driver='GTiff', width=64, height=64, count=count, dtype='int16',
                             crs=crs, transform=from_bounds(*bounds, 64, 64), nodata=missing) as output:
                output.write(values)
            payload = memory.read()
        if self.bad_dates:
            dates[1] = dates[0]
        return {'dates': dates, 'image_ids': [science['collection'] + '/' + d.replace('-', '_') for d in dates], 'payload': payload}


class MODISTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.root = Path(self.temp.name)
        guard = patch('socket.socket', side_effect=AssertionError('Offline MODIS tests'))
        guard.start()
        self.addCleanup(guard.stop)

    def unit(self, source='mod13q1_ndvi', year=2013):
        return SourceUnit(source, PROFILES[source], ANCHOR, year)

    def test_four_profiles_keep_platform_dates_day_night_and_masks(self):
        provider = MODISProvider()
        for source in PROFILES:
            adapter = MODISAdapter(source, provider=provider)
            self.assertEqual(default_registry().require(source).profile_id, adapter.profile_id)
            unit = self.unit(source)
            prepared = adapter.prepare(adapter.plan(unit, asset_root=self.root), output_root=self.root)
            self.assertTrue(adapter.validate(prepared).passed)
            self.assertEqual(prepared.public_metadata['state'], 'partial')
            self.assertEqual(prepared.public_metadata['nominal_missing_dates'], [])
            for path in prepared.files[:-1]:
                with rasterio.open(path) as raster:
                    self.assertEqual(raster.count, 23 if source.endswith('ndvi') else 46)
                    self.assertTrue(np.isnan(raster.read()).any())
                    self.assertEqual(raster.tags(1)['platform'], SOURCES[source][1])
                    if source.endswith('ndvi'):
                        self.assertEqual(float(np.nanmax(raster.read(1))), 0)
                        self.assertAlmostEqual(float(np.nanmax(raster.read(2))), .5, places=5)
                    else:
                        self.assertAlmostEqual(float(np.nanmax(raster.read(1))), 26.85 if '_day_' in path.name else 16.85, places=3)
            self.assertNotIn(str(self.root), prepared.files[-1].read_text())
        self.assertEqual(nominal_dates('mod13q1_ndvi', 2013)[0], '2013-01-01')
        self.assertEqual(nominal_dates('myd13q1_ndvi', 2013)[0], '2013-01-09')

    def test_interruption_uses_raw_without_login_and_rejects_corruption(self):
        provider = MODISProvider()
        adapter = MODISAdapter('mod13q1_ndvi', provider=provider)
        unit = self.unit()
        plan = adapter.plan(unit, asset_root=self.root)
        with patch.object(ndvi, 'derive_mod13q1_ndvi_bytes', side_effect=RuntimeError('interrupted')):
            with self.assertRaises(RuntimeError):
                adapter.prepare(plan, output_root=self.root)
        self.assertEqual(adapter.plan(unit, asset_root=self.root).remote_operations, 0)
        with patch('sm_benchmark_agent.modis_sources.EarthEngineMODIS', side_effect=AssertionError('No login for cached inputs')):
            prepared = MODISAdapter('mod13q1_ndvi').prepare(plan, output_root=self.root)
        self.assertEqual(provider.calls, ['mod13q1_ndvi'])
        prepared.files[0].write_bytes(b'corrupt')
        with self.assertRaises(ValueError):
            adapter.plan(unit, asset_root=self.root)

    def test_outside_period_empty_and_masked_are_distinct(self):
        for kind in ['outside', 'empty', 'masked']:
            adapter = MODISAdapter('myd13q1_ndvi', provider=MODISProvider(empty=kind == 'empty', masked=kind == 'masked'))
            unit = self.unit('myd13q1_ndvi', 2001 if kind == 'outside' else 2013)
            root = self.root / kind
            prepared = adapter.prepare(adapter.plan(unit, asset_root=root), output_root=root)
            self.assertEqual(prepared.public_metadata['state'], 'unavailable')
            self.assertEqual(prepared.public_metadata['reason'], {'outside': 'outside_product_period', 'empty': 'no_provider_images', 'masked': 'no_valid_values'}[kind])
            self.assertEqual(len(prepared.files), 1)
            if kind == 'outside':
                self.assertEqual(adapter.provider.calls, [])
            with patch('sm_benchmark_agent.modis_sources.EarthEngineMODIS', side_effect=AssertionError('No login')):
                self.assertEqual(adapter.plan(unit, asset_root=root).state, 'reusable')

    def test_bad_dates_and_corrupt_raw_fail_before_derivation(self):
        adapter = MODISAdapter('mod13q1_ndvi', provider=MODISProvider(bad_dates=True))
        unit = self.unit()
        with self.assertRaises(ValueError):
            adapter.prepare(adapter.plan(unit, asset_root=self.root), output_root=self.root)
        self.assertFalse((self.root / adapter.key(unit) / 'raw').exists())
        adapter.provider = MODISProvider()
        with patch.object(ndvi, 'derive_mod13q1_ndvi_bytes', side_effect=RuntimeError('stop')):
            with self.assertRaises(RuntimeError):
                adapter.prepare(adapter.plan(unit, asset_root=self.root), output_root=self.root)
        (self.root / adapter.key(unit) / 'raw/input.tif').write_bytes(b'corrupt')
        with self.assertRaises(ValueError):
            adapter.plan(unit, asset_root=self.root)

    def test_annual_delivery_six_files_relocation_and_resume(self):
        soil = soil_fixture(self.root / 'soil')
        context_adapters = {s: ContextAdapter(s, provider=RasterProvider(), hwsd_cache=soil) for s in CONTEXT_PROFILES}
        request = {'spatial': {'anchor_ids': [ANCHOR]}, 'years': [2013], 'station_targets': 'absent',
                   'sources': list(CONTEXT_PROFILES), 'output_root': str(self.root / 'context-out')}
        plan = plan_contexts(request, asset_root=self.root / 'context-cache', release_id='modis-fixture-v1', hwsd_cache=soil, adapters=context_adapters)
        context = execute_contexts(plan, accepted_plan_id=plan['plan_id'], adapters=context_adapters)['context_plan']
        request.update(sources=list(PROFILES), output_root=str(self.root / 'delivery'))
        provider = MODISProvider()
        adapters = {s: MODISAdapter(s, provider=provider) for s in PROFILES}
        kwargs = dict(context_plan=context, asset_root=self.root / 'cache', adapters=adapters)
        plan = plan_modis(request, **kwargs)
        self.assertEqual(provider.calls, [])
        with self.assertRaises(ValueError):
            execute_modis(plan, accepted_plan_id='wrong', adapters=adapters)
        result = execute_modis(plan, accepted_plan_id=plan['plan_id'], adapters=adapters)
        relocated = self.root / 'relocated.zip'
        shutil.copyfile(result['archive'], relocated)
        verify_archive(relocated, anchor_id=ANCHOR, year=2013)
        with zipfile.ZipFile(relocated) as archive:
            files = [n for n in archive.namelist() if n.endswith('.tif') and any('/' + s + '/' in n for s in PROFILES)]
            self.assertEqual(len(files), 6)
            self.assertEqual(json.loads(archive.read('package_manifest.json'))['station_targets'], 'absent_by_design')
        plan = plan_modis(request, **kwargs)
        self.assertEqual(execute_modis(plan, accepted_plan_id=plan['plan_id'], adapters=adapters)['status'], 'reused')
        self.assertEqual(len(provider.calls), 4)

    def test_provider_request_preserves_terra_wgs84_and_aqua_native_routes(self):
        ee = MagicMock()
        collection = ee.ImageCollection.return_value
        collection.filterDate.return_value = collection
        collection.sort.return_value = collection
        image = ee.Image.return_value
        for name in ['select', 'rename', 'addBands', 'unmask', 'toInt16']:
            getattr(image, name).return_value = image
        image.projection.return_value.getInfo.return_value = {'crs': landcover.NATIVE_CRS, 'transform': [250, 0, 0, 0, -250, 0]}
        provider = object.__new__(EarthEngineMODIS)
        provider.ee = ee
        response = MagicMock()
        response.__enter__.return_value.read.return_value = b'fixture'
        for source in PROFILES:
            dates = nominal_dates(source, 2013)[:2]
            def aggregate(name):
                result = MagicMock()
                result.getInfo.return_value = [d.replace('-', '_') for d in dates] if name == 'system:index' else [int(datetime.fromisoformat(d).replace(tzinfo=timezone.utc).timestamp() * 1000) for d in dates]
                return result
            collection.aggregate_array.side_effect = aggregate
            with patch('sm_benchmark_agent.modis_sources.urlopen', return_value=response):
                result = provider.fetch(self.unit(source), MODISAdapter(source).context(self.unit(source)))
            self.assertEqual(result['dates'], dates)
            params = image.getDownloadURL.call_args.args[0]
            self.assertEqual(params['crs'], 'EPSG:4326' if source == 'mod13q1_ndvi' else landcover.NATIVE_CRS)
            self.assertEqual(len(params['bands']), 2 if source.endswith('ndvi') else 4)
            self.assertTrue(all(SOURCES[source][0] in i for i in result['image_ids']))


if __name__ == '__main__':
    unittest.main()
