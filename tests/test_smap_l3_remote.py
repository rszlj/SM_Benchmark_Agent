import json
from pathlib import Path
import shutil
import tempfile
import unittest
from unittest.mock import patch
from concurrent.futures import Future
from sm_benchmark_agent.smap_l3_remote import make_plan, prepare_step, save
from sm_benchmark_agent.grid import anchor_cell_from_id
from sm_benchmark_agent.smap_l3 import FIELDS
from sm_benchmark_agent.delivery import export_gridded_archive


class RemoteTests(unittest.TestCase):
    def request(self, root):
        return {'spatial':{'anchor_ids':['EASE2_M09km_R0333_C0792']},
                'start':'2015-03-31','end':'2015-03-31','sources':['smap_l3'],
                'station_targets':'absent','output_root':str(root)}

    def test_offline_scope(self):
        with tempfile.TemporaryDirectory() as d, patch('socket.socket',side_effect=AssertionError('network')):
            root=Path(d)/'output'
            plan=make_plan(self.request(root))
            self.assertFalse(root.exists())
            self.assertEqual(plan['job_count'],1)
            self.assertEqual(len(plan['variables']),30)
            self.assertEqual(plan['jobs'][0]['end_exclusive'],'2015-04-01')
            request=self.request(root)
            request.update(start='2014-01-01',end='2014-12-31')
            self.assertEqual(make_plan(request)['job_count'],0)

    def test_download_resume_annual_and_package(self):
        import h5py
        import numpy as np
        with tempfile.TemporaryDirectory() as d:
            root=Path(d)/'output'; root.mkdir()
            plan=make_plan(self.request(root))
            a=anchor_cell_from_id(plan['jobs'][0]['anchors'][0])
            source=Path(d)/'SMAP_L3_SM_P_E_20150331_fixture.nc4'
            with h5py.File(source,'w') as f:
                f['x_global']=[a.centre_x_m]; f['y_global']=[a.centre_y_m]
                for slot,suffix in [('AM',''),('PM','_pm')]:
                    for field in FIELDS:
                        val={'EASE_row_index':a.row,'EASE_column_index':a.column,
                             'tb_time_seconds':481100000.0}.get(field,0)
                        ds=f.create_dataset(f'Soil_Moisture_Retrieval_Data_{slot}/{field}{suffix}',data=np.array([[val]]))
                        ds.attrs['_FillValue']=-9999
                        ds.attrs['units']='seconds since 2000-01-01 11:58:55.816Z'
            class FakeClient:
                submissions=0
                def submit(self,request):
                    self.submissions+=1; return 'fake-job'
                def status(self,job):
                    return {'status':'successful','progress':100,'num_input_granules':1}
                def result_urls(self,job):
                    return ['fake']
                def download(self,url,directory,overwrite):
                    dest=Path(directory)/source.name
                    shutil.copyfile(source,dest)
                    result=Future(); result.set_result(str(dest)); return result
            client=FakeClient()
            with patch('socket.socket',side_effect=AssertionError('network')):
                self.assertEqual(prepare_step(plan,root,lambda:client)['status'],'validated')
                result=prepare_step(plan,root,lambda:(_ for _ in ()).throw(AssertionError('cache must not authenticate')))
            self.assertEqual(result['status'],'complete')
            self.assertEqual(client.submissions,1)
            folder=root/'annual'/a.anchor_id/'2015'
            manifest=json.loads((folder/'source.json').read_text())
            self.assertEqual(manifest['records'],2)
            self.assertNotIn('job_id',manifest)
            assets=json.loads((folder/'assets.json').read_text())
            self.assertEqual(assets['availability'][0]['state'],'partial')
            export_gridded_archive(folder/'assets.json',Path(d)/'delivered',dry_run=False)
            self.assertEqual(len(list((Path(d)/'delivered').rglob('*.zip'))),1)
            monthly=root/'jobs'/plan['jobs'][0]['id']/'observations.parquet'
            monthly.write_bytes(b'corrupt')
            with self.assertRaisesRegex(ValueError,'Corrupt'):
                prepare_step(plan,root,lambda:client)

    def test_uncertain_submission_is_not_repeated(self):
        with tempfile.TemporaryDirectory() as d:
            root=Path(d); plan=make_plan(self.request(root))
            save(root/'jobs'/plan['jobs'][0]['id']/'state.json',{'status':'submitting','job_id':None})
            with self.assertRaisesRegex(RuntimeError,'Uncertain'):
                prepare_step(plan,root,lambda:object())
