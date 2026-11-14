import unittest
from sm_benchmark_agent.smap_l3 import j2000_utc


class TimeTests(unittest.TestCase):
    def test_native_subset_missing_flags_and_zero(self):
        import tempfile
        from pathlib import Path
        import h5py
        import numpy as np
        from sm_benchmark_agent.grid import anchor_cell_from_id
        from sm_benchmark_agent.smap_l3 import decode_subset, FIELDS
        a=anchor_cell_from_id('EASE2_M09km_R0333_C0792')
        with tempfile.TemporaryDirectory() as directory:
            path=Path(directory)/'SMAP_L3_SM_P_E_20200601_fixture.nc4'
            with h5py.File(path,'w') as f:
                f.create_dataset('x_global',data=[a.centre_x_m])
                f.create_dataset('y_global',data=[a.centre_y_m])
                for slot,suffix in [('AM',''),('PM','_pm')]:
                    for field in FIELDS:
                        value={'EASE_row_index':a.row,'EASE_column_index':a.column,
                               'tb_time_seconds':644289326.4685507}.get(field,0)
                        if slot=='PM' and field not in ['retrieval_qual_flag','surface_flag']:
                            value=-9999
                        ds=f.create_dataset(f'Soil_Moisture_Retrieval_Data_{slot}/{field}{suffix}',data=np.array([[value]],dtype=float))
                        ds.attrs['_FillValue']=-9999
                        ds.attrs['units']='seconds since 2000-01-01 11:58:55.816Z'
            records=decode_subset(path,[a])
            self.assertEqual(records[0]['soil_moisture'],0)
            self.assertEqual(records[0]['tb_h_corrected'],0)
            self.assertIsNone(records[1]['tb_v_uncorrected'])
            self.assertIsNone(records[1]['soil_moisture'])
            self.assertEqual(records[1]['retrieval_qual_flag'],0)
            self.assertIsNone(records[1]['observation_time_utc'])
            with h5py.File(path,'r+') as f:
                f['Soil_Moisture_Retrieval_Data_AM/EASE_row_index'][0,0]=334
            with self.assertRaisesRegex(ValueError,'mismatch'):
                decode_subset(path,[a])

    def test_j2000_epoch(self):
        self.assertIsNone(j2000_utc(None))
        # TDB and TT differ by less than 2 ms; TT-UTC was 64.184 s at J2000.
        from datetime import datetime, timezone
        actual = datetime.fromisoformat(j2000_utc(0).replace('Z','+00:00'))
        expected = datetime(2000,1,1,11,58,55,816000,tzinfo=timezone.utc)
        self.assertLess(abs((actual-expected).total_seconds()), .002)

    def test_leap_seconds_are_not_fixed_epoch_arithmetic(self):
        from astropy.time import Time
        target = Time('2020-06-01T12:00:00', scale='utc')
        seconds = (target.tdb-Time('2000-01-01T12:00:00',scale='tdb')).sec
        self.assertEqual(j2000_utc(seconds),'2020-06-01T12:00:00.000000Z')
