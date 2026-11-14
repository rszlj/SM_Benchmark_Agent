"""Portable, bounded SMAP L3 acquisition and annual source-asset assembly."""
import argparse
from collections import defaultdict
from dataclasses import asdict
from datetime import date, datetime, timedelta, timezone
import hashlib
import json
import os
from pathlib import Path
import tempfile
import time

from .extension_agent import normalize_request, identity
from .grid import anchor_cell_from_id, context_grid, ContextResolution
from .earthdata_setup import check_local
from .smap_l3 import COLLECTION, VARIABLES, decode_subset, observation_table, TIME_REFERENCE


def save(path, value):
    path.parent.mkdir(parents=True, exist_ok=True)
    tmp = path.with_suffix(path.suffix + '.part')
    tmp.write_text(json.dumps(value, indent=2, allow_nan=False)+'\n', encoding='utf-8')
    tmp.replace(path)


def checksum(path):
    h=hashlib.sha256()
    with path.open('rb') as f:
        for block in iter(lambda:f.read(8*1024*1024),b''):
            h.update(block)
    return h.hexdigest()


def make_plan(request):
    n=normalize_request(request)
    if n['sources']!=['smap_l3'] or n['station_targets']!='absent':
        raise ValueError('Source preparation requires only smap_l3 and station_targets=absent; station targets are linked later')
    if n['credential_ref']:
        raise ValueError('This adapter uses home .netrc; credential_ref is not supported')
    if n['years'][-1] >= date.today().year:
        raise ValueError('This release supports completed calendar years only')
    jobs=[]
    for year in n['years']:
        if year<2015:
            continue
        groups=defaultdict(list)
        for aid in n['anchor_ids']:
            a=anchor_cell_from_id(aid)
            groups[min(3,int((a.centre_longitude+180)//90))].append(aid)
        for month in range(1,13):
            start=max(date(year,month,1),date(2015,3,31))
            end=date(year+1,1,1) if month==12 else date(year,month+1,1)
            # This source-preparation command honors explicit dates; main ZIP planner
            # continues to use full calendar-year delivery units.
            if n['requested_period']:
                start=max(start,date.fromisoformat(n['requested_period']['start']))
                end=min(end,date.fromisoformat(n['requested_period']['end'])+timedelta(days=1))
            if start>=end:
                continue
            for sector,anchors in sorted(groups.items()):
                for offset in range(0,len(anchors),900):
                    jobs.append({'id':f'{year}-{month:02d}-s{sector}-b{offset//900}',
                        'start':str(start),'end_exclusive':str(end),'anchors':anchors[offset:offset+900]})
    result={'schema':'smap-l3-remote-plan-v1','request':n,'collection':COLLECTION,
            'product':'SPL3SMP_E','version':'006','variables':list(VARIABLES),
            'jobs':jobs,'job_count':len(jobs),'concurrency':1,
            'scope':'Source assets only; explicit dates may yield partial calendar years',
            'output_root':str(Path(n['output_root']).resolve())}
    return dict(result,plan_id=identity(result))


def prepare_step(plan, root, client_factory=None):
    import pyarrow.parquet as pq
    from harmony import Client, Collection, Request
    for job in plan['jobs']:
        folder=root/'jobs'/job['id']
        folder.mkdir(parents=True,exist_ok=True)
        statefile=folder/'state.json'
        state=json.loads(statefile.read_text()) if statefile.exists() else None
        output=folder/'observations.parquet'
        if state and state['status']=='validated':
            if not output.is_file() or checksum(output)!=state['sha256']:
                raise ValueError('Corrupt cached monthly asset')
            continue
        client=client_factory() if client_factory else Client(download_timeout=(30,180))
        anchors=[anchor_cell_from_id(a) for a in job['anchors']]
        if state is None:
            polygons=[]
            for a in anchors:
                x,y=a.centre_longitude,a.centre_latitude
                polygons.append([[[x-.01,y-.01],[x+.01,y-.01],[x+.01,y+.01],[x-.01,y+.01],[x-.01,y-.01]]])
            shape=folder/'anchors.geojson'
            save(shape,{'type':'FeatureCollection','features':[{'type':'Feature','properties':{},
                'geometry':{'type':'MultiPolygon','coordinates':polygons}}]})
            start=datetime.fromisoformat(job['start']).replace(tzinfo=timezone.utc)
            end=datetime.fromisoformat(job['end_exclusive']).replace(tzinfo=timezone.utc)
            req=Request(Collection(id=COLLECTION),shape=str(shape),variables=list(VARIABLES),
                temporal={'start':start,'stop':end-timedelta(microseconds=1)},
                format='application/netcdf',ignore_errors=False,labels=['benchmark-smap-l3'])
            save(statefile,{'status':'submitting','job_id':None})
            job_id=client.submit(req)
            if not isinstance(job_id,str):
                raise RuntimeError('Unexpected submission result; reconcile remote jobs')
            state={'status':'submitted','job_id':job_id}
            save(statefile,state)
        if not state.get('job_id'):
            raise RuntimeError('Uncertain previous submission; reconcile remote jobs before resuming')
        status=client.status(state['job_id'])
        state.update({k:status[k] for k in ['status','progress','num_input_granules']})
        save(statefile,state)
        if state['status'] in {'failed','canceled','paused'}:
            raise RuntimeError('Remote job requires review: '+state['status'])
        if state['status']!='successful':
            return {'status':'running','unit':job['id'],'progress':state['progress']}
        records=[]
        count=0
        downloads=folder/'downloads'
        downloads.mkdir(exist_ok=True)
        for url in client.result_urls(state['job_id']):
            # Unverified partial files never become reusable downloads.
            with tempfile.TemporaryDirectory(dir=folder,prefix='download-') as temp:
                file=Path(client.download(url,directory=temp,overwrite=False).result())
                rows=decode_subset(file,anchors)
                destination=downloads/file.name
                if destination.exists():
                    if checksum(destination)!=checksum(file):
                        raise ValueError('Conflicting source bytes')
                else:
                    file.replace(destination)
            records.extend(rows)
            count+=1
        days={r['date'] for r in records}
        keys={(r['anchor_id'],r['date'],r['pass']) for r in records}
        if (not records or count!=state['num_input_granules'] or len(days)!=count or
            len(keys)!=len(records) or len(records)!=len(days)*len(anchors)*2 or
            any(not job['start']<=d<job['end_exclusive'] for d in days)):
            raise ValueError('Returned granule/date/anchor/pass coverage failed validation')
        pq.write_table(observation_table(records),output.with_suffix('.part'),compression='zstd')
        output.with_suffix('.part').replace(output)
        state.update(status='validated',sha256=checksum(output),source_dates=sorted(days),records=len(records))
        save(statefile,state)
        return {'status':'validated','unit':job['id'],'records':len(records)}
    return assemble(plan,root)


def assemble(plan,root):
    import pyarrow.parquet as pq
    groups=defaultdict(list)
    for job in plan['jobs']:
        folder=root/'jobs'/job['id']
        state=json.loads((folder/'state.json').read_text())
        asset=folder/'observations.parquet'
        if state['status']!='validated' or checksum(asset)!=state['sha256']:
            raise ValueError('Monthly asset not validated')
        for record in pq.read_table(asset).to_pylist():
            groups[record['anchor_id'],int(record['date'][:4])].append(record)
    catalogue=[]
    for (aid,year),records in sorted(groups.items()):
        records.sort(key=lambda r:(r['date'],r['pass']))
        folder=root/'annual'/aid/str(year)
        folder.mkdir(parents=True,exist_ok=True)
        target=folder/'smap_l3.parquet'
        pq.write_table(observation_table(records),target.with_suffix('.part'),compression='zstd')
        target.with_suffix('.part').replace(target)
        planned=set()
        for j in plan['jobs']:
            if aid not in j['anchors'] or not j['start'].startswith(str(year)):
                continue
            d=date.fromisoformat(j['start'])
            while str(d)<j['end_exclusive']:
                planned.add(str(d)); d+=timedelta(days=1)
        actual={r['date'] for r in records}
        metadata={'source':'smap_l3','product':'SPL3SMP_E','version':'006','anchor_id':aid,'year':year,
            'units':{'soil_moisture':'m3/m3','tb':'K'},'variables':list(VARIABLES),
            'sampling':'native EASE2 source cell at anchor centre; AM/PM separate',
            'tb_support':'Native support retained; uncorrected TB is sourced from the 36 km Earth grid',
            'time_reference':TIME_REFERENCE,'time_conversion':'J2000 TDB to UTC',
            'quality_policy':'provider flags retained; no additional quality screening',
            'missing_values':'Parquet null; no imputation', 'requested_dates':sorted(planned),
            'source_dates':sorted(actual),'missing_source_dates':sorted(planned-actual),
            'missing_reason':'not returned by source query; cause not inferred',
            'records':len(records),'sha256':checksum(target)}
        save(folder/'source.json',metadata)
        a=anchor_cell_from_id(aid)
        save(folder/'grid.json',{'anchor':asdict(a),'context':asdict(context_grid(a,ContextResolution('1 km',1)))})
        full_start=max(date(year,1,1),date(2015,3,31))
        full_end=date(year+1,1,1)
        full_days=(full_end-full_start).days
        complete=len(planned)==full_days and not planned-actual
        availability={'source':'smap_l3','state':'available' if complete else 'partial',
            'reason':None if complete else 'partial_calendar_scope_or_unreturned_source_dates'}
        assetplan={'anchor_id':aid,'year':year,'release_id':'smap-l3-extension',
            'processing_version':'smap-l3-native-v1','station_targets':'absent',
            'availability':[availability,{'source':'ismn','state':'unavailable','reason':'absent_by_design'}],
            'assets':[{'path':'smap_l3.parquet','destination':'inputs/smap_l3.parquet',
                'role':'source_cell_time_series','source_id':'SPL3SMP_E.006','sha256':checksum(target)},
                {'path':'source.json','destination':'metadata/smap_l3.json','role':'metadata','source_id':'SPL3SMP_E.006'},
                {'path':'grid.json','destination':'metadata/grid.json','role':'metadata','kind':'grid','source_id':'EASE2'}]}
        save(folder/'assets.json',assetplan)
        catalogue.append({'anchor_id':aid,'year':year,'path':target.relative_to(root).as_posix(),
                          'sha256':checksum(target),'availability':availability})
    save(root/'assets_catalog.json',{'schema':'smap-l3-assets-v1','assets':catalogue,
        'outside_product_years':[y for y in plan['request']['years'] if y<2015]})
    return {'status':'complete','annual_assets':len(catalogue),'catalog':'assets_catalog.json'}


def main():
    parser=argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--request',type=Path,required=True)
    parser.add_argument('--execute',action='store_true')
    parser.add_argument('--accept-plan')
    parser.add_argument('--watch',action='store_true')
    args=parser.parse_args()
    plan=make_plan(json.loads(args.request.read_text(encoding='utf-8')))
    if not args.execute:
        print(json.dumps(plan,indent=2)); return
    if args.accept_plan!=plan['plan_id']:
        parser.error('Exact reviewed plan_id required')
    if plan['jobs'] and check_local()['status']!='configured':
        parser.error('Earthdata home .netrc required; run sm-benchmark-earthdata-check')
    root=Path(plan['output_root'])
    root.mkdir(parents=True,exist_ok=True)
    path=root/'plan.json'
    if path.exists() and json.loads(path.read_text())['plan_id']!=plan['plan_id']:
        parser.error('Output directory belongs to another plan')
    lock=root/'worker.lock'
    with lock.open('x') as f:
        f.write(str(os.getpid()))
    try:
        save(path,plan)
        while True:
            result=prepare_step(plan,root)
            print(json.dumps(result),flush=True)
            if not args.watch or result['status']=='complete':
                break
            time.sleep(30)
    except Exception as exc:
        save(root/'error.json',{'error_type':type(exc).__name__,'status':'review_required'})
        parser.exit(2,f'{type(exc).__name__}: preparation stopped; inspect saved job states. No automatic resubmission.\n')
    finally:
        lock.unlink()


if __name__=='__main__':
    main()
