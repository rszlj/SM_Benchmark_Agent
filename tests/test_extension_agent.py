import csv
from contextlib import closing
import gzip
import hashlib
import json
from pathlib import Path
import shutil
import sqlite3
import tempfile
import unittest
from unittest.mock import patch
import zipfile

from sm_benchmark_agent.archives import verify_archive, write_archive
from sm_benchmark_agent.catalogue import ReleaseCatalogue, SOURCE_COLUMNS
from sm_benchmark_agent.delivery import export_gridded_archive
from sm_benchmark_agent.extension_agent import normalize_request, plan_extension, execute_reuse

ANCHOR = 'EASE2_M09km_R0304_C2105'


class ExtensionAgentTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.root = Path(self.temp.name)
        package = self.root / 'fixture'
        package.mkdir()
        data = b'zero,missing\n0,\n'
        (package / 'data.csv').write_bytes(data)
        self.manifest = {'schema': 'anchor-year-delivery-v2', 'anchor_id': ANCHOR,
                         'year': 2001, 'release_id': 'fixture', 'files': [
                             {'path': 'data.csv', 'bytes': len(data), 'sha256': hashlib.sha256(data).hexdigest()}]}
        (package / 'package_manifest.json').write_text(json.dumps(self.manifest))
        self.release = self.root / 'release'
        archive = self.release / 'packages' / ANCHOR / '2001.zip'
        write_archive(package, archive)
        (self.release / 'release.json').write_text(json.dumps({'release_id': 'fixture'}))
        self.row = dict(anchor_id=ANCHOR, year=2001, build_status='complete', station_count=1,
                        archive_path=f'packages/{ANCHOR}/2001.zip', archive_bytes=archive.stat().st_size,
                        archive_sha256=hashlib.sha256(archive.read_bytes()).hexdigest(),
                        **{c: 'partial' if c == 'era5_land' else 'unavailable_by_design'
                           for c in SOURCE_COLUMNS.values() if c})
        with gzip.open(self.release / 'catalog.csv.gz', 'wt', newline='') as stream:
            writer = csv.DictWriter(stream, fieldnames=list(self.row))
            writer.writeheader()
            writer.writerow(self.row)
        self.catalogue = ReleaseCatalogue(self.release)
        self.request = {'spatial': {'anchor_ids': [ANCHOR]}, 'years': [2001],
                        'sources': ['era5_land'], 'output_root': str(self.root / 'output')}

    def test_reuse_resume_relocation_no_network(self):
        with patch('socket.socket', side_effect=AssertionError('Network forbidden')):
            plan = plan_extension(self.request, self.catalogue)
            self.assertFalse((self.root / 'output').exists())
            self.assertEqual(plan['units'][0]['sources']['era5_land']['state'], 'partial')
            with self.assertRaises(ValueError):
                execute_reuse(plan, self.catalogue, accepted_plan_id='wrong')
            result = execute_reuse(plan, self.catalogue, accepted_plan_id=plan['plan_id'])
            self.assertEqual(result['packages'][0]['status'], 'verified')
            result = execute_reuse(plan, self.catalogue, accepted_plan_id=plan['plan_id'])
            self.assertEqual(result['packages'][0]['status'], 'reused')
            relocated = self.root / 'relocated.zip'
            shutil.copyfile(self.root / 'output' / result['packages'][0]['archive_path'], relocated)
            shutil.rmtree(self.release)
            self.assertEqual(verify_archive(relocated)['year'], 2001)

    def test_corruption_is_failed_without_overwrite(self):
        plan = plan_extension(self.request, self.catalogue)
        result = execute_reuse(plan, self.catalogue, accepted_plan_id=plan['plan_id'])
        target = self.root / 'output' / result['packages'][0]['archive_path']
        target.write_bytes(b'corrupt')
        with self.assertRaises(ValueError):
            execute_reuse(plan, self.catalogue, accepted_plan_id=plan['plan_id'])
        self.assertEqual(target.read_bytes(), b'corrupt')
        with closing(sqlite3.connect(self.root / 'output/extension_state.sqlite')) as db:
            self.assertEqual(db.execute('SELECT status FROM units').fetchone()[0], 'failed')

    def test_interrupted_copy_can_resume(self):
        plan = plan_extension(self.request, self.catalogue)
        with patch('sm_benchmark_agent.extension_agent.shutil.copyfile', side_effect=OSError('interrupted')):
            with self.assertRaises(OSError):
                execute_reuse(plan, self.catalogue, accepted_plan_id=plan['plan_id'])
        self.assertFalse(list((self.root / 'output').rglob('*.part')))
        self.assertEqual(execute_reuse(plan, self.catalogue, accepted_plan_id=plan['plan_id'])['status'], 'complete')

    def test_point_bbox_dates_limits_and_stable_ids(self):
        request = dict(self.request, spatial={'points': [[147.5348, -35.32395]]})
        request.pop('years')
        request.update(start='2020-12-31', end='2021-01-01', sources=['gldas21', 'era5_land'])
        plan = plan_extension(request, self.catalogue)
        self.assertEqual(plan['request']['anchor_ids'], ['EASE2_M09km_R1281_C3508'])
        self.assertEqual(plan['request']['years'], [2020, 2021])
        self.assertEqual(plan['geometry'][0]['context']['rows'], 13)
        self.assertIn('gldas21', plan['geometry'][0]['native_cells'])
        self.assertEqual(normalize_request(request)['request_id'],
                         normalize_request(dict(request, sources=['era5_land', 'gldas21', 'era5_land']))['request_id'])
        bbox = dict(self.request, spatial={'bbox': [16.5, 38.5, 16.6, 38.6]})
        self.assertGreater(len(normalize_request(bbox)['anchor_ids']), 1)
        with self.assertRaisesRegex(ValueError, 'scope'):
            normalize_request(dict(bbox, max_packages=1))
        with self.assertRaises(ValueError):
            normalize_request(dict(self.request, sources=['invented']))
        with self.assertRaises(ValueError):
            normalize_request(dict(self.request, spatial={'bbox': [179, 0, -179, 1]}))

    def test_absent_targets_and_missing_packages_cannot_reuse(self):
        for request in [dict(self.request, station_targets='absent'), dict(self.request, years=[1999])]:
            plan = plan_extension(request, self.catalogue)
            self.assertEqual(plan['units'][0]['state'], 'requires_user_action')
            with self.assertRaises(ValueError):
                execute_reuse(plan, self.catalogue, accepted_plan_id=plan['plan_id'])
        self.assertEqual(self.catalogue.package_anchors, [ANCHOR])
        self.assertIsNone(self.catalogue.station_inventory_anchors)
        self.assertEqual(self.catalogue.package_years(ANCHOR), [2001])

    def test_zip_rejects_unlisted_and_unsafe_members(self):
        path = self.root / 'bad.zip'
        for name in ['unlisted.txt', '../escape.txt']:
            with zipfile.ZipFile(path, 'w') as archive:
                archive.writestr('package_manifest.json', json.dumps(self.manifest))
                archive.writestr('data.csv', b'zero,missing\n0,\n')
                archive.writestr(name, 'extra')
            with self.assertRaises(ValueError):
                verify_archive(path)

    def test_gridded_only_explicit_assets_keep_zero_missing(self):
        (self.root / 'grid.json').write_text('{}')
        plan = {'anchor_id': ANCHOR, 'year': 2001, 'release_id': 'fixture', 'processing_version': 'fixture',
                'station_targets': 'absent', 'availability': [
                    {'source': 'ismn', 'state': 'unavailable', 'reason': 'absent_by_design'},
                    {'source': 'fixture', 'state': 'partial', 'reason': 'synthetic fixture'}],
                'assets': [
                    {'path': 'grid.json', 'destination': 'metadata/grid.json', 'role': 'metadata',
                     'kind': 'grid', 'source_id': 'fixture'},
                    {'path': 'fixture/data.csv', 'destination': 'source_cell_time_series/data.csv',
                     'role': 'source_cell_time_series', 'source_id': 'fixture'}]}
        path = self.root / 'assets.json'
        path.write_text(json.dumps(plan))
        preview = export_gridded_archive(path, self.root / 'gridded')
        self.assertFalse((self.root / 'gridded').exists())
        result = export_gridded_archive(path, self.root / 'gridded', dry_run=False)
        self.assertEqual(verify_archive(result['destination'])['listed_files'], 3)
        with zipfile.ZipFile(result['destination']) as archive:
            manifest = json.loads(archive.read('package_manifest.json'))
            self.assertEqual(manifest['station_targets'], 'absent_by_design')
            self.assertEqual(archive.read('source_cell_time_series/data.csv'), b'zero,missing\n0,\n')
            self.assertNotIn(str(self.root), json.dumps(manifest))
        with self.assertRaises(FileExistsError):
            export_gridded_archive(path, self.root / 'gridded', dry_run=False)


if __name__ == '__main__':
    unittest.main()
