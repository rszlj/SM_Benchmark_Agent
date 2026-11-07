from dataclasses import replace
from contextlib import closing
import json
from pathlib import Path
import shutil
import sqlite3
import tempfile
import unittest
from unittest.mock import patch, MagicMock
import sys

import numpy as np
import rasterio
from rasterio.io import MemoryFile
from rasterio.transform import from_bounds

from sm_benchmark_agent.adapters import SourceUnit
from sm_benchmark_agent.context_sources import ContextAdapter, PROFILES, hwsd_cache_record, EarthEngineContexts
from sm_benchmark_agent.context_workflow import plan_contexts, execute_contexts
from sm_benchmark_agent.delivery import checksum
from sm_benchmark_agent.gldas_workflow import checked_context
from sm_benchmark_agent.grid import anchor_cell, context_grid, ContextResolution
from sm_benchmark_agent.processing import hwsd2, landcover


ANCHOR = anchor_cell(-86.9023, 32.3182).anchor_id


class RasterProvider:
    def __init__(self):
        self.calls = []

    def fetch(self, unit, context):
        self.calls.append(unit.source_id)
        # Exact context fixture; retrieval/projection calls are tested separately.
        values = np.full((context.rows, context.columns), 5, dtype='float32')
        if unit.source_id == 'srtm':
            values += np.arange(context.columns, dtype='float32')[None, :]
        else:
            values[0, 0] = 255
        with MemoryFile() as memory:
            with memory.open(driver='GTiff', height=context.rows, width=context.columns,
                             count=1, dtype='float32', crs='EPSG:6933', nodata=255 if unit.source_id == 'mcd12q1' else -32768,
                             transform=from_bounds(*[context.bounds.xmin, context.bounds.ymin,
                                                    context.bounds.xmax, context.bounds.ymax], context.columns, context.rows)) as dst:
                dst.write(values, 1)
            return memory.read()


def soil_fixture(root):
    root.mkdir()
    context = context_grid(anchor_cell(-86.9023, 32.3182), ContextResolution('1 km', 1))
    raster = root / 'HWSD2_SMU_global_compressed.tif'
    with rasterio.open(raster, 'w', driver='GTiff', width=13, height=13, count=1,
                       dtype='uint16', crs='EPSG:6933', nodata=65535,
                       transform=from_bounds(context.bounds.xmin, context.bounds.ymin,
                                             context.bounds.xmax, context.bounds.ymax, 13, 13)) as dst:
        dst.write(np.full((13, 13), 100, dtype='uint16'), 1)
    database = root / 'HWSD2.sqlite'
    with closing(sqlite3.connect(database)) as db:
        props = ','.join(f'"{p}" REAL' for p in hwsd2.HWSD2_NUMERIC_PROPERTIES)
        db.execute('CREATE TABLE HWSD2_LAYERS (HWSD2_SMU_ID INTEGER, LAYER TEXT, SEQUENCE INTEGER, SHARE REAL, TOPDEP INTEGER, BOTDEP INTEGER,' + props + ')')
        db.execute('CREATE TABLE HWSD2_LAYERS_METADATA (FIELD TEXT, UNIT TEXT, DESCRIPTION TEXT)')
        db.executemany('INSERT INTO HWSD2_LAYERS_METADATA VALUES (?,?,?)', [(p, 'fixture-unit', p) for p in hwsd2.HWSD2_NUMERIC_PROPERTIES])
        for layer, top, bottom in hwsd2.HWSD2_LAYERS:
            for sequence, share, value in [(1, 25, -9), (2, 75, 3)]:
                row = [100, layer, sequence, share, top, bottom] + [value] * 20
                db.execute('INSERT INTO HWSD2_LAYERS VALUES (' + ','.join('?' for _ in row) + ')', row)
        db.commit()
    # Synthetic manifest exercises integrity, not proof of an official download.
    doc = {'snapshot_id': hwsd2.HWSD2_SNAPSHOT_ID,
           'archives': {'raster': {'sha256': hwsd2.HWSD2_RASTER_SHA256}, 'database': {'sha256': hwsd2.HWSD2_DATABASE_SHA256}},
           'prepared': {'global_raster': {'sha256': checksum(raster)}, 'sqlite_database': {'sha256': checksum(database)}}}
    (root / 'prepared.manifest.json').write_text(json.dumps(doc))
    return root


class ContextTests(unittest.TestCase):
    def setUp(self):
        temp = tempfile.TemporaryDirectory()
        self.addCleanup(temp.cleanup)
        self.root = Path(temp.name)
        guard = patch('socket.socket', side_effect=AssertionError('Offline test must not access network'))
        guard.start()
        self.addCleanup(guard.stop)

    def unit(self, source='mcd12q1', year=2013):
        return SourceUnit(source, PROFILES[source], ANCHOR, year)

    def test_landcover_checkpoint_resume_values_and_corruption(self):
        provider = RasterProvider()
        adapter = ContextAdapter('mcd12q1', provider=provider)
        unit = self.unit()
        plan = adapter.plan(unit, asset_root=self.root)
        with patch.object(landcover, 'derive_landcover', side_effect=RuntimeError('Interrupted after raw checkpoint')):
            with self.assertRaises(RuntimeError):
                adapter.prepare(plan, output_root=self.root)
        self.assertEqual(len(provider.calls), 1)
        with patch('sm_benchmark_agent.context_sources.EarthEngineContexts', side_effect=AssertionError('Cached raw must not initialize GEE')):
            resumed = ContextAdapter('mcd12q1').prepare(plan, output_root=self.root)
        with rasterio.open(resumed.files[0]) as raster:
            values = raster.read(1)
            self.assertTrue(np.isnan(values[0, 0]))
            self.assertEqual(values[1, 1], 5)
            self.assertEqual(raster.descriptions, ('2013_LC_Type1',))
        self.assertEqual(adapter.plan(unit, asset_root=self.root).state, 'reusable')
        resumed.files[0].write_bytes(b'corrupt')
        with self.assertRaises(ValueError):
            adapter.plan(unit, asset_root=self.root)
        self.assertEqual(len(provider.calls), 1)

    def test_three_source_context_assembly_relocation_and_static_reuse(self):
        soil = soil_fixture(self.root / 'global')
        provider = RasterProvider()
        adapters = {s: ContextAdapter(s, provider=provider, hwsd_cache=soil) for s in PROFILES}
        request = {'spatial': {'anchor_ids': [ANCHOR]}, 'years': [2013], 'sources': list(PROFILES),
                   'station_targets': 'absent', 'output_root': str(self.root / 'out')}
        kwargs = dict(asset_root=self.root / 'cache', release_id='fixture-extension-v1', hwsd_cache=soil, adapters=adapters)
        plan = plan_contexts(request, **kwargs)
        self.assertEqual(provider.calls, [])
        with self.assertRaises(ValueError):
            execute_contexts(plan, accepted_plan_id='wrong', adapters=adapters)
        result = execute_contexts(plan, accepted_plan_id=plan['plan_id'], adapters=adapters)
        path = Path(result['context_plan'])
        doc = checked_context(path, ANCHOR, 2013)
        self.assertEqual(len(doc['assets']), 9)
        props = next(a for a in doc['assets'] if 'properties_7layers' in a['destination'])
        with rasterio.open(props['path']) as raster:
            self.assertEqual(raster.count, 140)
            np.testing.assert_array_equal(raster.read(1), 3)
        for p in path.parent.rglob('*.json'):
            self.assertNotIn(str(self.root), p.read_text())
            self.assertNotIn('"project":', p.read_text())
            self.assertNotIn('PRIVATE_FIXTURE', p.read_text())
        relocated = self.root / 'relocated'
        shutil.copytree(path.parent, relocated)
        checked_context(relocated / 'context.json', ANCHOR, 2013)
        plan2 = plan_contexts(request, **kwargs)
        self.assertEqual(execute_contexts(plan2, accepted_plan_id=plan2['plan_id'], adapters=adapters)['status'], 'reused')
        for source in ['srtm', 'hwsd2']:
            self.assertEqual(adapters[source].plan(self.unit(source, 2014), asset_root=kwargs['asset_root']).state, 'reusable')
        self.assertEqual(provider.calls, ['srtm', 'mcd12q1'])

    def test_unavailable_and_missing_prerequisites_are_distinct(self):
        adapter = ContextAdapter('mcd12q1', provider=RasterProvider())
        plan = adapter.plan(self.unit(year=2000), asset_root=self.root)
        self.assertEqual(plan.state, 'unavailable')
        prepared = adapter.prepare(plan, output_root=self.root)
        self.assertEqual(prepared.public_metadata['reason'], 'outside_product_period')
        self.assertEqual(adapter.provider.calls, [])
        self.assertEqual(ContextAdapter('hwsd2').plan(self.unit('hwsd2'), asset_root=self.root).state, 'requires_user_action')
        outside = replace(self.unit('srtm'), anchor_id=anchor_cell(0, 70).anchor_id)
        self.assertEqual(ContextAdapter('srtm').plan(outside, asset_root=self.root).state, 'unavailable')

    def test_global_cache_corruption_and_wrong_identity(self):
        soil = soil_fixture(self.root / 'global')
        self.assertIn('global_raster', hwsd_cache_record(soil))
        (soil / 'HWSD2.sqlite').write_bytes(b'corrupt')
        with self.assertRaises(ValueError):
            hwsd_cache_record(soil)

    def test_provider_request_profiles_and_no_implicit_login(self):
        config = self.root / 'gee-config.json'
        config.write_text(json.dumps({'project': 'PRIVATE_FIXTURE', 'auth_mode': 'interactive'}))
        ee = MagicMock()
        image = ee.Image.return_value
        for method in ['select', 'unmask', 'toFloat', 'toUint8']:
            getattr(image, method).return_value = image
        collection = ee.ImageCollection.return_value
        collection.filterDate.return_value = collection
        collection.select.return_value = collection
        collection.size.return_value.getInfo.return_value = 1
        image.projection.return_value.getInfo.return_value = {'crs': landcover.NATIVE_CRS, 'transform': [500, 0, 0, 0, -500, 0]}
        response = MagicMock()
        response.__enter__.return_value.read.return_value = b'fixture-payload'
        with patch.dict(sys.modules, {'ee': ee}), patch('sm_benchmark_agent.context_sources.urlopen', return_value=response):
            provider = EarthEngineContexts(config)
            for source in ['srtm', 'mcd12q1']:
                unit = self.unit(source)
                self.assertEqual(provider.fetch(unit, ContextAdapter(source).context(unit)), b'fixture-payload')
                params = image.getDownloadURL.call_args.args[0]
                self.assertEqual(params['bands'], ['elevation'] if source == 'srtm' else ['LC_Type1'])
            collection.filterDate.assert_called_with('2013-01-01', '2014-01-01')
            ee.Initialize.assert_called_once_with(project='PRIVATE_FIXTURE')
            ee.Authenticate.assert_not_called()
            collection.size.return_value.getInfo.return_value = 0
            self.assertIsNone(provider.fetch(self.unit(), ContextAdapter('mcd12q1').context(self.unit())))

    def test_public_conversion_preserves_numeric_values_and_source_mask(self):
        source, target = self.root / 'input.tif', self.root / 'output.tif'
        with rasterio.open(source, 'w', driver='GTiff', height=1, width=4, count=1,
                           dtype='float32', nodata=-9999, crs='EPSG:6933',
                           transform=from_bounds(0, 0, 4, 1, 4, 1)) as dst:
            dst.write(np.array([[0, -32768, 65535, -9999]], dtype='float32'), 1)
            dst.update_tags(project='PRIVATE_FIXTURE', resampling='nearest')
        landcover.public_raster(source, target)
        with rasterio.open(target) as raster:
            values = raster.read(1)
            np.testing.assert_array_equal(values[0, :3], [0, -32768, 65535])
            self.assertTrue(np.isnan(values[0, 3]))
            self.assertNotIn('project', raster.tags())


if __name__ == '__main__':
    unittest.main()
