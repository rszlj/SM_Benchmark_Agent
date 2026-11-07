import json
from pathlib import Path
import tempfile
import unittest
from unittest.mock import patch
import zipfile

from sm_benchmark_agent.multi_workflow import plan_multi, execute_multi, SOURCES, destination
from sm_benchmark_agent.context_sources import ContextAdapter, PROFILES as CP
from sm_benchmark_agent.context_workflow import plan_contexts, execute_contexts
from sm_benchmark_agent.gldas21 import GLDAS21Adapter
from sm_benchmark_agent.modis_sources import MODISAdapter, PROFILES as MP
from sm_benchmark_agent.timeseries_sources import TimeSeriesAdapter
from sm_benchmark_agent.sentinel1_sources import Sentinel1Adapter
from sm_benchmark_agent.smap_sources import SMAPL4Adapter
from sm_benchmark_agent.archives import verify_archive
from sm_benchmark_agent.adapters import SourceUnit
from sm_benchmark_agent.delivery import checksum
from test_context_sources import ANCHOR, soil_fixture, RasterProvider
from test_gldas21 import FakeProvider
from test_modis_sources import MODISProvider
from test_timeseries_sources import Provider as TSProvider
from test_sentinel1_sources import Provider as S1Provider
from test_smap_sources import Provider as SMProvider


class MultiTests(unittest.TestCase):
    def setUp(self):
        t=tempfile.TemporaryDirectory()
        self.addCleanup(t.cleanup)
        self.root=Path(t.name)
        p=patch('socket.socket', side_effect=AssertionError('No network'))
        p.start(); self.addCleanup(p.stop)

    def setup_scope(self, year=2015):
        soil=soil_fixture(self.root/'soil')
        adapters={s:ContextAdapter(s,provider=RasterProvider(),hwsd_cache=soil) for s in CP}
        req={'spatial':{'anchor_ids':[ANCHOR]},'years':[year], 'station_targets':'absent',
             'sources':list(CP),'output_root':str(self.root/'contexts')}
        p=plan_contexts(req,asset_root=self.root/'cc',release_id='multi-test-v1',hwsd_cache=soil,adapters=adapters)
        context=execute_contexts(p,accepted_plan_id=p['plan_id'],adapters=adapters)['context_plan']
        req.update(sources=sorted(SOURCES),output_root=str(self.root/'delivery'))
        return req,dict(context_plan=context,asset_root=self.root/'cache')

    def test_all_sources_failure_resume_relocation_and_scope_conflict(self):
        req,kwargs=self.setup_scope()
        ts=TSProvider()
        sm=SMProvider(fail=5)
        mod=MODISProvider()
        adapters={'gldas21':GLDAS21Adapter(provider=FakeProvider()),
                  'era5_land':TimeSeriesAdapter('era5_land',provider=ts),
                  'imerg_v07':TimeSeriesAdapter('imerg_v07',provider=ts),
                  'sentinel1':Sentinel1Adapter(provider=S1Provider()),
                  'smap_l4':SMAPL4Adapter(provider=sm),
                  **{s:MODISAdapter(s,provider=mod) for s in MP}}
        plan=plan_multi(req,adapters=adapters,**kwargs)
        with self.assertRaises(ValueError):
            execute_multi(plan,accepted_plan_id='bad',adapters=adapters)
        with self.assertRaises(RuntimeError):
            execute_multi(plan,accepted_plan_id=plan['plan_id'],adapters=adapters)
        self.assertFalse(list((self.root/'delivery').rglob('*.zip')))
        self.assertEqual(len(ts.calls),24)
        self.assertEqual(len(mod.calls),4)
        sm.fail=None
        result=execute_multi(plan,accepted_plan_id=plan['plan_id'],adapters=adapters)
        self.assertEqual(len(ts.calls),24)
        self.assertEqual(len(mod.calls),4)
        self.assertEqual(sm.calls.count(3),1)
        moved=self.root/'relocated.zip';moved.write_bytes(Path(result['archive']).read_bytes())
        verify_archive(moved)
        with zipfile.ZipFile(moved) as z:
            names=z.namelist()
            self.assertEqual(len([n for n in names if n.endswith('.parquet')]),4)
            for source,adapter in adapters.items():
                item=next(s for s in plan['sources'] if s['unit']['source_id']==source)
                unit=SourceUnit(**item['unit'])
                prepared=adapter.prepare(adapter.plan(unit,asset_root=kwargs['asset_root']),output_root=kwargs['asset_root'])
                for path in prepared.files[:-1]:
                    name,_=destination(source,path,2015)
                    self.assertEqual(z.read(name),path.read_bytes())
                self.assertIn(f'metadata/source_manifests/{source}.json',names)
            provenance=json.loads(z.read('metadata/multi_extension.json'))
            self.assertEqual(set(provenance['validation']),SOURCES)
            self.assertIn('smap_l4',provenance['limitations'])
        fresh=plan_multi(req,adapters=adapters,**kwargs)
        self.assertEqual(execute_multi(fresh,accepted_plan_id=fresh['plan_id'],adapters=adapters)['status'],'reused')
        before=checksum(Path(result['archive']))
        req['sources']=['era5_land']
        other=plan_multi(req,adapters=adapters,**kwargs)
        with self.assertRaises(FileExistsError):
            execute_multi(other,accepted_plan_id=other['plan_id'],adapters=adapters)
        self.assertEqual(checksum(Path(result['archive'])),before)

    def test_unavailable_is_reported_and_ismn_rejected(self):
        req,kwargs=self.setup_scope(2013)
        req['sources']=['smap_l4','sentinel1']
        plan=plan_multi(req,**kwargs)
        result=execute_multi(plan,accepted_plan_id=plan['plan_id'])
        self.assertEqual({a['source'] for a in result['availability'] if a['state']=='unavailable'}, {'ismn','smap_l4','sentinel1'})
        req['sources']=['ismn']
        with self.assertRaises(ValueError):plan_multi(req,**kwargs)

    def test_changed_context_or_code_rejected_before_work(self):
        req,kwargs=self.setup_scope()
        req['sources']=['smap_l4']
        plan=plan_multi(req,**kwargs)
        with patch('sm_benchmark_agent.multi_workflow.workflow_hashes',return_value={}):
            with self.assertRaises(ValueError):execute_multi(plan,accepted_plan_id=plan['plan_id'])
        p=Path(kwargs['context_plan']);p.write_text(p.read_text()+' ')
        with self.assertRaises(ValueError):execute_multi(plan,accepted_plan_id=plan['plan_id'])

    def test_exact_period_all_source_families(self):
        from sm_benchmark_agent import periods
        from sm_benchmark_agent.modis_sources import nominal_dates
        from test_sentinel1_sources import scenes
        from datetime import datetime, timezone
        import pyarrow.parquet as pq
        import pyarrow as pa
        class PeriodMODIS(MODISProvider):
            def fetch(self,unit,context):
                with patch('test_modis_sources.nominal_dates',side_effect=lambda source,year:nominal_dates(source,year,unit)):
                    return super().fetch(unit,context)
        class PeriodS1(S1Provider):
            def discover(self,unit):
                rows=scenes(unit.year)
                for row in rows:
                    dt=datetime.fromtimestamp(row['system:time_start']/1000,timezone.utc)
                    row['system:time_start']=int(dt.replace(month=4).timestamp()*1000)
                return rows
        req,kwargs=self.setup_scope()
        req.pop('years'); req.update(start='2015-04-01',end='2015-04-30')
        ts=TSProvider(); gp=FakeProvider(); sm=SMProvider()
        adapters={'gldas21':GLDAS21Adapter(provider=gp),
                  'era5_land':TimeSeriesAdapter('era5_land',provider=ts),
                  'imerg_v07':TimeSeriesAdapter('imerg_v07',provider=ts),
                  'sentinel1':Sentinel1Adapter(provider=PeriodS1()),
                  'smap_l4':SMAPL4Adapter(provider=sm),
                  **{s:MODISAdapter(s,provider=PeriodMODIS()) for s in MP}}
        plan=plan_multi(req,adapters=adapters,**kwargs)
        self.assertTrue(all('/period-2015-04-01_2015-04-30' in s['work_key'] for s in plan['sources']))
        result=execute_multi(plan,accepted_plan_id=plan['plan_id'],adapters=adapters)
        self.assertEqual(Path(result['archive']).name,'2015-04-01_2015-04-30.zip')
        self.assertEqual(gp.calls,[4]);self.assertEqual(sm.calls,[4])
        self.assertEqual(ts.calls,[('era5_land',4),('imerg_v07',4)])
        with zipfile.ZipFile(result['archive']) as z:
            self.assertEqual(json.loads(z.read('package_manifest.json'))['requested_period'],{'start':'2015-04-01','end':'2015-04-30'})
            for source,count in [('gldas21',240),('era5_land',720),('imerg_v07',1440),('smap_l4',240)]:
                name=next(n for n in z.namelist() if n.startswith('source_cell_time_series/'+source+'/'))
                self.assertEqual(pq.read_table(pa.BufferReader(z.read(name))).num_rows,count)
            for source in MP:
                meta=json.loads(z.read(f'metadata/source_manifests/{source}.json'))
                self.assertTrue(all(d.startswith('2015-04') for d in meta['dates']))
                self.assertEqual(meta['nominal_missing_dates'],[])
        # A day-specific request must not alias the month or annual cache.
        req.update(start='2015-04-13',end='2015-04-13',sources=['era5_land'])
        day=plan_multi(req,adapters=adapters,**kwargs)
        result=execute_multi(day,accepted_plan_id=day['plan_id'],adapters=adapters)
        with zipfile.ZipFile(result['archive']) as z:
            name=next(n for n in z.namelist() if n.endswith('.parquet'))
            self.assertEqual(pq.read_table(pa.BufferReader(z.read(name))).num_rows,24)
