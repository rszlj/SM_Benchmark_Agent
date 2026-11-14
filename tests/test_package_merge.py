import json
from pathlib import Path
import tempfile
import unittest
import zipfile

from sm_benchmark_agent.archives import write_archive
from sm_benchmark_agent.delivery import checksum
from sm_benchmark_agent.package_merge import merge_smap


class MergeTests(unittest.TestCase):
    def test_merge_preserves_targets_and_other_inputs_and_resumes(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            base = root / 'base'
            base.mkdir()
            aid = 'EASE2_M09km_R0333_C0792'
            def save(path, value):
                path.parent.mkdir(parents=True, exist_ok=True)
                path.write_text(json.dumps(value), encoding='utf-8')
            save(base/'metadata/availability.json', {'sources': [{'source_id':'ismn','state':'available'}]})
            save(base/'metadata/data_dictionary.json', {'sources': []})
            (base/'targets').mkdir()
            (base/'targets/observations.csv').write_text('date,value\n2015-01-01,0.2\n')
            (base/'other.bin').write_bytes(b'unchanged input')
            (base/'README.md').write_text('Original package\n')
            files = [{'path': p.relative_to(base).as_posix(), 'bytes':p.stat().st_size,
                      'sha256':checksum(p), 'source_id':'ismn'} for p in base.rglob('*') if p.is_file()]
            save(base/'package_manifest.json', {'schema':'anchor-year-delivery-v2',
                 'anchor_id':aid, 'year':2015, 'release_id':'test', 'files':files})
            archive = root/'base.zip'
            write_archive(base, archive)
            original = checksum(archive)
            # Integrity fixture; scientific table validation belongs to the adapter.
            (root/'table.parquet').write_bytes(b'prepared table fixture')
            sha = checksum(root/'table.parquet')
            save(root/'source.json', {'anchor_id':aid,'year':2015,'product':'SPL3SMP_E','version':'006','sha256':sha})
            save(root/'grid.json', {'anchor_id':aid})
            plan = {'anchor_id':aid,'year':2015,'release_id':'test','processing_version':'test',
                'station_targets':'absent','availability':[
                    {'source':'smap_l3','state':'partial','reason':'partial_calendar_scope'},
                    {'source':'ismn','state':'unavailable','reason':'absent_by_design'}],
                'assets':[
                    {'path':'table.parquet','destination':'inputs/table.parquet','role':'source_cell_time_series','source_id':'SPL3SMP_E.006','sha256':sha},
                    {'path':'source.json','destination':'metadata/source.json','role':'metadata','source_id':'SPL3SMP_E.006'},
                    {'path':'grid.json','destination':'metadata/grid.json','role':'metadata','kind':'grid','source_id':'EASE2'}]}
            path = root/'assets.json'
            save(path, plan)
            out = root/'out'
            self.assertEqual(merge_smap(archive,path,out)['status'], 'planned')
            self.assertFalse(out.exists())
            result = merge_smap(archive,path,out,dry_run=False)
            self.assertEqual(checksum(archive), original)
            with zipfile.ZipFile(result['destination']) as z:
                self.assertEqual(z.read('targets/observations.csv'), (base/'targets/observations.csv').read_bytes())
                self.assertEqual(z.read('other.bin'), b'unchanged input')
                avail = json.loads(z.read('metadata/availability.json'))['sources']
                self.assertEqual(avail[0]['state'], 'available')
                self.assertEqual(avail[-1]['state'], 'partial')
                self.assertNotIn('station_targets',json.loads(z.read('package_manifest.json')))
            self.assertEqual(merge_smap(archive,path,out,dry_run=False)['status'], 'reused')
            with self.assertRaises(ValueError):
                merge_smap(result['destination'],path,root/'other')
            plan['year'] = 2016
            save(path, plan)
            with self.assertRaises(ValueError):
                merge_smap(archive,path,root/'wrong')
            plan['year'] = 2015
            save(path, plan)
            (root/'table.parquet').write_bytes(b'corrupt')
            with self.assertRaises(ValueError):
                merge_smap(archive,path,root/'corrupt')


if __name__ == '__main__':
    unittest.main()
