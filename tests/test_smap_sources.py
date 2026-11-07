from datetime import datetime, timezone
import json
from pathlib import Path
import tempfile
import unittest
from unittest.mock import patch, MagicMock
import zipfile

import pyarrow.parquet as pq
from sm_benchmark_agent.adapters import SourceUnit
from sm_benchmark_agent.smap_sources import (SMAPL4Adapter, EarthEngineSMAP, PROFILES, BANDS,
    profile, calendar_times, normalized_rows, month_bounds)
from sm_benchmark_agent.smap_workflow import plan_smap, execute_smap
from sm_benchmark_agent.context_sources import ContextAdapter, PROFILES as CONTEXT_PROFILES
from sm_benchmark_agent.context_workflow import plan_contexts, execute_contexts
from sm_benchmark_agent.archives import verify_archive
from test_context_sources import soil_fixture, RasterProvider, ANCHOR


class Provider:
    def __init__(self, fail=None, missing=False, empty=False, masked=False):
        self.calls=[]
        self.fail,self.missing,self.empty,self.masked=fail,missing,empty,masked

    def fetch(self, unit, start, end):
        self.calls.append(start.month)
        if self.fail == start.month:
            raise RuntimeError('interrupted')
        if self.empty:
            return []
        lon,lat=profile(unit)['query_point']
        result=[dict(id=d.strftime('%Y%m%d%H%M'), time=int(d.timestamp()*1000),longitude=lon,latitude=lat,
                     **{b: None if self.masked or 'peat' in b else .25 for b in BANDS})
                for d in calendar_times(unit) if start <= d < end]
        return result[1:] if self.missing else result


class SMAPTests(unittest.TestCase):
    def setUp(self):
        temp=tempfile.TemporaryDirectory()
        self.addCleanup(temp.cleanup)
        self.root=Path(temp.name)
        p=patch('socket.socket',side_effect=AssertionError('No network'))
        p.start()
        self.addCleanup(p.stop)
        self.unit=SourceUnit('smap_l4',PROFILES['smap_l4'],ANCHOR,2015)

    def test_calendar_values_and_resume(self):
        provider=Provider(fail=5)
        adapter=SMAPL4Adapter(provider=provider)
        plan=adapter.plan(self.unit,asset_root=self.root)
        self.assertEqual(plan.remote_operations,60)
        self.assertEqual(provider.calls,[])
        with self.assertRaises(RuntimeError):
            adapter.prepare(plan,output_root=self.root)
        provider.fail=None
        plan=adapter.plan(self.unit,asset_root=self.root)
        self.assertEqual(plan.remote_operations,48)
        result=adapter.prepare(plan,output_root=self.root)
        table=pq.read_table(result.files[0])
        self.assertEqual(table.num_rows,2208)
        self.assertEqual(table['time_utc'][0].as_py(),datetime(2015,3,31,1,30,tzinfo=timezone.utc))
        self.assertEqual(table['sm_surface'][0].as_py(),.25)
        self.assertEqual(result.public_metadata['state'],'available')
        self.assertEqual(provider.calls.count(3),1)
        self.assertEqual(adapter.plan(self.unit,asset_root=self.root).state,'reusable')
        self.assertIn('native_cell_equivalence_unverified',adapter.validate(result).gaps)
        result.files[0].write_bytes(b'broken')
        with self.assertRaises(Exception):
            adapter.plan(self.unit,asset_root=self.root)

    def test_gap_empty_mask_and_outside(self):
        for label,p,year,state in [('gap',Provider(missing=True),2015,'partial'),
                ('empty',Provider(empty=True),2015,'unavailable'),
                ('mask',Provider(masked=True),2015,'unavailable'),
                ('outside',Provider(),2014,'unavailable')]:
            unit=SourceUnit('smap_l4',PROFILES['smap_l4'],ANCHOR,year)
            a=SMAPL4Adapter(provider=p)
            root=self.root/label
            out=a.prepare(a.plan(unit,asset_root=root),output_root=root)
            self.assertEqual(out.public_metadata['state'],state)
            if label=='gap':
                self.assertEqual(out.public_metadata['missing_timestamp_count'],10)
                self.assertEqual(pq.read_table(out.files[0]).num_rows,2208)
                self.assertIsNone(pq.read_table(out.files[0])['sm_surface'][0].as_py())
            if label=='outside':
                self.assertEqual(p.calls,[])

    def test_schema_time_and_spatial_mismatch(self):
        start,end=month_bounds(2015,3)
        r=Provider().fetch(self.unit,start,end)[0]
        cases=[[r,r],[dict(r,time=r['time']+1000)],[dict(r,longitude=0)],
               [dict(r,id='private/path')],[dict(r,sm_surface='bad')]]
        for rows in cases:
            with self.assertRaises(ValueError):
                normalized_rows(rows,self.unit,start,end)

    def test_checkpoint_corruption(self):
        a=SMAPL4Adapter(provider=Provider(fail=4))
        with self.assertRaises(RuntimeError):
            a.prepare(a.plan(self.unit,asset_root=self.root),output_root=self.root)
        p=next(self.root.rglob('03.json'))
        d=json.loads(p.read_text())
        d['payload']['rows'][0]['sm_surface']=10
        p.write_text(json.dumps(d))
        with self.assertRaises(ValueError):
            a.plan(self.unit,asset_root=self.root)

    def test_legacy_provider_query(self):
        start,end=month_bounds(2015,3)
        r=Provider().fetch(self.unit,start,end)[0]
        ee=MagicMock()
        c=ee.ImageCollection.return_value
        for n in ('filterDate','select','sort'):
            getattr(c,n).return_value=c
        c.size.return_value.getInfo.return_value=1
        c.getRegion.return_value.getInfo.return_value=[list(r),list(r.values())]
        p=object.__new__(EarthEngineSMAP)
        p.ee=ee
        self.assertEqual(p.fetch(self.unit,start,end),[r])
        self.assertEqual(c.getRegion.call_args.kwargs,{'scale':13000})
        ee.ImageCollection.assert_called_once_with('NASA/SMAP/SPL4SMGP/007')

    def test_delivery_and_plan_binding(self):
        soil=soil_fixture(self.root/'soil')
        contexts={s:ContextAdapter(s,provider=RasterProvider(),hwsd_cache=soil) for s in CONTEXT_PROFILES}
        req={'spatial':{'anchor_ids':[ANCHOR]},'years':[2015],'station_targets':'absent',
             'sources':list(CONTEXT_PROFILES),'output_root':str(self.root/'contexts')}
        cp=plan_contexts(req,asset_root=self.root/'cc',release_id='smap-test-v1',hwsd_cache=soil,adapters=contexts)
        context=execute_contexts(cp,accepted_plan_id=cp['plan_id'],adapters=contexts)['context_plan']
        req.update(sources=['smap_l4'],output_root=str(self.root/'delivery'))
        p=Provider()
        adapters={'smap_l4':SMAPL4Adapter(provider=p)}
        kwargs=dict(context_plan=context,asset_root=self.root/'cache',adapters=adapters)
        plan=plan_smap(req,**kwargs)
        with self.assertRaises(ValueError):
            execute_smap(plan,accepted_plan_id='wrong',adapters=adapters)
        result=execute_smap(plan,accepted_plan_id=plan['plan_id'],adapters=adapters)
        moved=self.root/'moved.zip'
        moved.write_bytes(Path(result['archive']).read_bytes())
        verify_archive(moved)
        with zipfile.ZipFile(moved) as z:
            self.assertIn('source_cell_time_series/smap_l4/smap_l4_3hourly.parquet',z.namelist())
        plan=plan_smap(req,**kwargs)
        self.assertEqual(execute_smap(plan,accepted_plan_id=plan['plan_id'],adapters=adapters)['status'],'reused')
        self.assertEqual(len(p.calls),10)
