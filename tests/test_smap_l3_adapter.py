import json
from pathlib import Path
import tempfile
import unittest
from unittest.mock import patch

from sm_benchmark_agent.adapters import SourceUnit
from sm_benchmark_agent.smap_l3_adapter import SMAPL3Adapter, PROFILE
from sm_benchmark_agent.smap_l3 import FIELDS, VARIABLES, TIME_REFERENCE, observation_table
from sm_benchmark_agent.smap_l3_remote import assemble, save, checksum
from sm_benchmark_agent.grid import anchor_cell_from_id


class L3Step:
    """Synthetic provider checkpoint fixture, not online acceptance."""
    def __init__(self, fail=False, null=False):
        self.calls = 0
        self.fail, self.null = fail, null

    def __call__(self, plan, root):
        import pyarrow.parquet as pq
        from datetime import date, timedelta
        self.calls += 1
        if self.fail:
            raise RuntimeError('simulated provider failure')
        for job in plan['jobs']:
            rows = []
            a = anchor_cell_from_id(job['anchors'][0])
            day = date.fromisoformat(job['start'])
            while day.isoformat() < job['end_exclusive']:
                for slot in ('AM', 'PM'):
                    row = {f: None for f in FIELDS}
                    row.update(anchor_id=a.anchor_id, date=day.isoformat(), **{'pass':slot},
                        soil_moisture=None if self.null else .2, EASE_row_index=a.row,
                        EASE_column_index=a.column, tb_h_corrected=250.,
                        source_time_units='seconds since 2000-01-01 11:58:55.816Z', observation_time_utc=None)
                    rows.append(row)
                day += timedelta(days=1)
            folder = root/'jobs'/job['id']
            folder.mkdir(parents=True, exist_ok=True)
            path = folder/'observations.parquet'
            pq.write_table(observation_table(rows),path)
            save(folder/'state.json',{'status':'validated','sha256':checksum(path)})
        return assemble(plan,root)


class L3AdapterTests(unittest.TestCase):
    def test_offline_prepare_resume_corruption_and_coverage(self):
        with tempfile.TemporaryDirectory() as tmp, patch('socket.socket',side_effect=AssertionError('network')):
            root = Path(tmp)/'cache'
            unit = SourceUnit('smap_l3',PROFILE,'EASE2_M09km_R0333_C0792',2015,'2015-04-01','2015-04-30')
            provider = L3Step()
            adapter = SMAPL3Adapter(step=provider,sleep=lambda _:None)
            plan = adapter.plan(unit,asset_root=root)
            self.assertFalse(root.exists())
            out = adapter.prepare(plan,output_root=root,credential_ref=Path('unreadable-gee-secret'))
            self.assertTrue(adapter.validate(out).passed)
            self.assertEqual(out.public_metadata['state'],'available')
            self.assertEqual(out.public_metadata['records'],60)
            self.assertEqual(adapter.plan(unit,asset_root=root).remote_operations,0)
            adapter.prepare(plan,output_root=root)
            self.assertEqual(provider.calls,1)
            out.files[0].write_bytes(b'corrupt')
            with self.assertRaises(ValueError): adapter.plan(unit,asset_root=root)

    def test_failure_and_null_values(self):
        with tempfile.TemporaryDirectory() as tmp:
            unit = SourceUnit('smap_l3',PROFILE,'EASE2_M09km_R0333_C0792',2015,'2015-04-01','2015-04-01')
            provider = L3Step(fail=True,null=True)
            adapter = SMAPL3Adapter(step=provider)
            plan = adapter.plan(unit,asset_root=Path(tmp))
            with self.assertRaises(RuntimeError): adapter.prepare(plan,output_root=Path(tmp))
            provider.fail=False
            out = adapter.prepare(plan,output_root=Path(tmp))
            self.assertEqual(out.public_metadata['state'],'unavailable')
            self.assertEqual(out.public_metadata['null_counts']['soil_moisture'],2)
            outside = SourceUnit('smap_l3',PROFILE,unit.anchor_id,2014)
            self.assertEqual(adapter.plan(outside,asset_root=Path(tmp)).state,'unavailable')


if __name__ == '__main__': unittest.main()
