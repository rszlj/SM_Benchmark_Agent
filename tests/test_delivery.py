import json
from pathlib import Path
import shutil
import tempfile
import unittest
from sm_benchmark_agent.delivery import export_anchor_year, verify_delivery, export_gridded_archive


class DeliveryTests(unittest.TestCase):
    def test_long_output_path_and_v1_timeseries_filename(self):
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            source = root / 'input'
            source.write_text('fixture')
            output = root / ('x' * max(1, 100 - len(str(root))))
            plan = dict(anchor_id='EASE2_M09km_R0540_C0257', year=2013,
                        release_id='long-path-test', processing_version='test', station_targets='absent',
                        availability=[{'source': 'ismn', 'state': 'unavailable', 'reason': 'absent_by_design'}],
                        assets=[{'path': str(source), 'destination': 'metadata/grid.json', 'role': 'metadata',
                                 'kind': 'grid', 'source_id': 'grid'},
                                {'path': str(source), 'destination': 'source_cell_time_series/imerg_v07/imerg_v07_2013_native_pixel_half_hourly.parquet',
                                 'role': 'source_cell_time_series', 'source_id': 'imerg_v07'}])
            path = root / 'plan.json'
            path.write_text(json.dumps(plan))
            result = export_gridded_archive(path, output, dry_run=False)
            self.assertEqual(result['status'], 'packaged')
            self.assertTrue(Path(result['destination']).is_file())

    def make_plan(self, root):
        source = root / 'source'
        source.mkdir()
        assets = []
        for name, role, kind in [('targets.csv', 'station_targets', None), ('stations.csv', 'metadata', 'stations'), ('depths.csv', 'metadata', 'depths'), ('grid.json', 'metadata', 'grid'), ('terrain.tif', 'static_context', None)]:
            (source / name).write_text('fixture bytes\n')
            assets.append(dict(path='source/' + name, destination=role + '/' + name, role=role, kind=kind, source_id='test-fixture-v1'))
        plan = dict(anchor_id='EASE2_M09km_R0107_C0307', year=2020, release_id='test', processing_version='test-code-v1', assets=assets, availability=[dict(source='fixture', state='partial', reason='synthetic test')])
        path = root / 'plan.json'
        path.write_text(json.dumps(plan))
        return path, plan

    def test_dry_run_export_relocate_and_detect_corruption(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            path, plan = self.make_plan(root)
            result = export_anchor_year(path, root / 'output')
            self.assertEqual(result['status'], 'planned')
            self.assertFalse((root / 'output').exists())
            result = export_anchor_year(path, root / 'output', dry_run=False)
            package = Path(result['destination'])
            relocated = root / 'relocated'
            shutil.copytree(package, relocated)
            shutil.rmtree(root / 'source')
            self.assertEqual(verify_delivery(relocated)['files'], 5)
            self.assertNotIn(str(root), (relocated / 'package_manifest.json').read_text())
            (relocated / 'static_context/terrain.tif').write_text('corruption')
            with self.assertRaises(ValueError):
                verify_delivery(relocated)

    def test_refuse_overwrite_unsafe_paths_and_missing_catalogues(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            path, plan = self.make_plan(root)
            export_anchor_year(path, root / 'output', dry_run=False)
            with self.assertRaises(FileExistsError):
                export_anchor_year(path, root / 'output', dry_run=False)
            plan['assets'][0]['destination'] = '../escape.csv'
            path.write_text(json.dumps(plan))
            with self.assertRaises(ValueError):
                export_anchor_year(path, root / 'other')
            plan['assets'].pop(0)
            plan['assets'] = [e for e in plan['assets'] if e['kind'] != 'grid']
            path.write_text(json.dumps(plan))
            with self.assertRaisesRegex(ValueError, 'grid metadata'):
                export_anchor_year(path, root / 'other')


if __name__ == '__main__':
    unittest.main()
