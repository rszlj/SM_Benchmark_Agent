"""Replay explicit local 50 m acquisitions; not raw/provider acquisition acceptance.

Private index: list of raster/manifest paths plus anchor_id/year. Metadata must
contain unambiguous scene identities/times/orbits; never infer missing provenance.
"""
import argparse
from datetime import datetime, timezone
import json
from pathlib import Path
import tempfile
from unittest.mock import patch
import zipfile
import numpy as np
import xarray as xr

from sm_benchmark_agent.sentinel1_sources import Sentinel1Adapter, acquisitions, FIELDS
from sm_benchmark_agent.sentinel1_workflow import plan_sentinel1, execute_sentinel1, workflow_hashes
from sm_benchmark_agent.archives import verify_archive
from sm_benchmark_agent.delivery import checksum


def replay(source, index, output):
    verification = verify_archive(source)
    anchor, year = verification['anchor_id'], verification['year']
    output = Path(output).resolve()
    output.mkdir(parents=True, exist_ok=False)
    rows = json.loads(Path(index).read_text(encoding='utf-8'))
    records, files, input_hashes = [], {}, []
    for row in rows:
        if row['anchor_id'] != anchor or row['year'] != year:
            raise ValueError('Replay input identity mismatch')
        document = json.loads(Path(row['manifest']).read_text(encoding='utf-8'))
        props = document.get('scene_properties')
        if props:
            for identity, properties in zip(document['scene_ids'], props, strict=True):
                records.append({**{n: properties[n] for n in FIELDS if n != 'system:index'}, 'system:index': identity.rsplit('/', 1)[-1]})
        else:
            # Explicit local-derived metadata is sufficient only for one scene.
            if len(document['scene_ids']) != 1:
                raise ValueError('Multi-slice replay requires individual scene properties')
            records.append({'system:index': document['scene_ids'][0].rsplit('/', 1)[-1],
                'system:time_start': int(datetime.fromisoformat(document['time_start_utc']).timestamp()*1000),
                'instrumentMode': 'IW', 'resolution_meters': 10,
                'transmitterReceiverPolarisation': [b for b in document['bands'] if b != 'angle'],
                'orbitProperties_pass': document['orbit_pass'], 'relativeOrbitNumber_start': document['relative_orbit'],
                'orbitNumber_start': document['absolute_orbit'], 'platform_number': document['platform']})
        files[tuple(document['scene_ids'])] = Path(row['raster'])
        input_hashes.append({'raster_sha256': checksum(Path(row['raster'])), 'manifest_sha256': checksum(Path(row['manifest']))})
    with zipfile.ZipFile(source) as archive:
        manifest = json.loads(archive.read('package_manifest.json'))
        assets = []
        for entry in manifest['files']:
            name = entry['path']
            if not (name.startswith(('static/srtm/', 'static/hwsd2/', 'annual/mcd12q1/')) or name in
                    {'metadata/grid.json', 'metadata/source_manifests/srtm.json',
                     'metadata/source_manifests/hwsd2.json', 'metadata/source_manifests/mcd12q1.json'}):
                continue
            target = output / 'context' / name
            target.parent.mkdir(parents=True, exist_ok=True)
            target.write_bytes(archive.read(name))
            assets.append({'path': target.relative_to(output).as_posix(), 'destination': name,
                           'role': 'static_context' if name.startswith('static/') else 'annual_context' if name.startswith('annual/') else 'metadata',
                           'kind': 'grid' if name == 'metadata/grid.json' else None,
                           'source_id': Path(name).stem if name.startswith('metadata/source_manifests/') else entry['source_id'],
                           'sha256': entry['sha256']})
        states = []
        for name in ['srtm', 'hwsd2', 'mcd12q1']:
            meta = json.loads(archive.read(f'metadata/source_manifests/{name}.json'))
            states.append({'source': name, 'state': meta['state'], 'reason': meta.get('reason', 'public prepared context')})
    context = {'anchor_id': anchor, 'year': year, 'release_id': 'sentinel1-offline-replay-v1',
               'processing_version': 'public-context-v1', 'station_targets': 'absent', 'assets': assets,
               'availability': states + [{'source': 'ismn', 'state': 'unavailable', 'reason': 'absent_by_design'}]}
    context_path = output / 'context.json'
    context_path.write_text(json.dumps(context), encoding='utf-8')

    class Provider:
        discoveries, downloads = 0, 0
        def discover(self, unit):
            self.discoveries += 1
            return records
        def fetch(self, unit, acquisition):
            self.downloads += 1
            return files[tuple(acquisition['scene_ids'])].read_bytes()

    provider = Provider()
    adapters = {'sentinel1': Sentinel1Adapter(provider=provider)}
    request = {'spatial': {'anchor_ids': [anchor]}, 'years': [year], 'sources': ['sentinel1'],
               'station_targets': 'absent', 'output_root': str(output / 'delivery')}
    kwargs = dict(context_plan=context_path, asset_root=output / 'cache', adapters=adapters)
    with patch('socket.socket', side_effect=AssertionError('Replay is offline')):
        plan = plan_sentinel1(request, **kwargs)
        result = execute_sentinel1(plan, accepted_plan_id=plan['plan_id'], adapters=adapters)
        plan = plan_sentinel1(request, **kwargs)
        assert execute_sentinel1(plan, accepted_plan_id=plan['plan_id'], adapters=adapters)['status'] == 'reused'
        assert provider.discoveries == 1 and provider.downloads == len(files)
    name = f'annual/sentinel1/sentinel1_{year}_50m_EPSG6933.nc'
    comparisons = {}
    with tempfile.TemporaryDirectory() as temp:
        temp = Path(temp)
        moved = temp / 'annual.zip'; moved.write_bytes(Path(result['archive']).read_bytes())
        relocated = verify_archive(moved)
        for label, path in [('actual', moved), ('reference', source)]:
            with zipfile.ZipFile(path) as archive:
                (temp / f'{label}.nc').write_bytes(archive.read(name))
        with xr.open_dataset(temp / 'actual.nc', engine='h5netcdf') as a, xr.open_dataset(temp / 'reference.nc', engine='h5netcdf') as b:
            assert set(a.variables) == set(b.variables)
            for n in a.variables:
                av, bv = a[n].values, b[n].values
                equal = np.array_equal(av, bv, equal_nan=True) if av.dtype.kind in 'fc' else np.array_equal(av, bv)
                comparisons[n] = bool(equal and a[n].dims == b[n].dims and a[n].attrs == b[n].attrs)
    report = {'date': datetime.now(timezone.utc).isoformat(), 'mode': 'Offline prepared 50 m acquisition replay; network blocked',
              'scope': 'One V1 anchor/year; not raw SAR aggregation, live GEE or full discovery completeness acceptance',
              'anchor_id': anchor, 'year': year, 'acquisition_count': len(files),
              'source_archive_sha256': checksum(Path(source)), 'input_sha256': input_hashes,
              'variables_values_masks_dimensions_attributes_equal': comparisons, 'resume': 'reused',
              'relocation': relocated, 'processing_code_sha256': workflow_hashes()}
    (output / 'validation.json').write_text(json.dumps(report, indent=2)+'\n', encoding='utf-8')
    assert all(comparisons.values())
    return report


if __name__ == '__main__':
    parser = argparse.ArgumentParser(description=__doc__)
    for name in ('source-zip', 'input-index', 'output'):
        parser.add_argument('--' + name, type=Path, required=True)
    args = parser.parse_args()
    print(json.dumps(replay(args.source_zip, args.input_index, args.output), indent=2))
