"""Offline real-data replay, not a live provider acceptance test.

Run with an explicit verified V1 ZIP and a new output directory. Existing public
GLDAS rows stand in for monthly provider responses; all values must survive the
new adapter and package writer unchanged. No credentials are read.
"""
import argparse
import json
from pathlib import Path
import shutil
import tempfile
from unittest.mock import patch
import zipfile

import pyarrow as pa
import pyarrow.parquet as pq

from sm_benchmark_agent.archives import verify_archive
from sm_benchmark_agent.delivery import checksum
from sm_benchmark_agent.gldas21 import GLDAS21Adapter, BANDS
from sm_benchmark_agent.gldas_workflow import plan_gldas, execute_gldas


def replay(source, output):
    verify_archive(source)
    output = Path(output).resolve()
    output.mkdir(parents=True, exist_ok=False)
    with zipfile.ZipFile(source) as archive:
        manifest = json.loads(archive.read('package_manifest.json'))
        anchor, year = manifest['anchor_id'], manifest['year']
        data_name = f'source_cell_time_series/gldas21/gldas21_{year}_native_pixel_3hourly.parquet'
        table = pq.read_table(pa.BufferReader(archive.read(data_name)))
        original_rows = table.to_pylist()
        assets = []
        for entry in manifest['files']:
            name = entry['path']
            if not (name.startswith(('static/srtm/', 'static/hwsd2/', 'annual/mcd12q1/')) or name in
                    {'metadata/grid.json', 'metadata/source_manifests/srtm.json',
                     'metadata/source_manifests/hwsd2.json', 'metadata/source_manifests/mcd12q1.json'}):
                continue
            target = output / 'prepared-context' / name
            target.parent.mkdir(parents=True, exist_ok=True)
            target.write_bytes(archive.read(name))
            assets.append({'path': target.relative_to(output).as_posix(), 'destination': name,
                           'role': 'static_context' if name.startswith('static/') else
                           'annual_context' if name.startswith('annual/') else 'metadata',
                           'kind': 'grid' if name == 'metadata/grid.json' else None,
                           'source_id': Path(name).stem if name.startswith('metadata/source_manifests/') else entry['source_id'],
                           'sha256': entry['sha256']})
        states = []
        for name in ['srtm', 'hwsd2', 'mcd12q1']:
            meta = json.loads(archive.read(f'metadata/source_manifests/{name}.json'))
            states.append({'source': name, 'state': meta['state'], 'reason': meta.get('reason', 'public prepared context')})
    context = {'anchor_id': anchor, 'year': year, 'release_id': 'gldas-offline-replay-v1',
               'processing_version': 'public-context-v1', 'station_targets': 'absent', 'assets': assets,
               'availability': states + [{'source': 'ismn', 'state': 'unavailable', 'reason': 'absent_by_design'}]}
    context_path = output / 'context.json'
    context_path.write_text(json.dumps(context, indent=2) + '\n', encoding='utf-8')
    request = {'spatial': {'anchor_ids': [anchor]}, 'years': [year],
               'sources': ['gldas21', 'srtm', 'hwsd2', 'mcd12q1'], 'station_targets': 'absent',
               'output_root': str(output / 'delivery')}

    class ReplayProvider:
        calls = 0
        def fetch(self, unit, start, end):
            self.calls += 1
            return [{'id': r['source_image_id'], 'time': int(r['interval_start_utc'].timestamp() * 1000),
                     'longitude': r['native_longitude'], 'latitude': r['native_latitude'],
                     **{b: r[b] for b in BANDS}} for r in original_rows if start <= r['interval_start_utc'] < end]

    provider = ReplayProvider()
    adapter = GLDAS21Adapter(provider=provider)
    with patch('socket.socket', side_effect=AssertionError('Replay must be offline')):
        plan = plan_gldas(request, context_plan=context_path, asset_root=output / 'cache', adapter=adapter)
        result = execute_gldas(plan, accepted_plan_id=plan['plan_id'], adapter=adapter)
        new_plan = plan_gldas(request, context_plan=context_path, asset_root=output / 'cache', adapter=adapter)
        resumed = execute_gldas(new_plan, accepted_plan_id=new_plan['plan_id'], adapter=adapter)
        assert provider.calls == 12 and resumed['status'] == 'reused'
        with tempfile.TemporaryDirectory(prefix='gldas-replay-relocation-') as temporary:
            relocated = Path(temporary) / 'package.zip'
            shutil.copyfile(result['archive'], relocated)
            verification = verify_archive(relocated)
            with zipfile.ZipFile(relocated) as archive:
                written = pq.read_table(pa.BufferReader(archive.read(data_name)))
                assert written.to_pylist() == original_rows
                # Actual context rasters are decoded from the relocated ZIP.
                from rasterio.io import MemoryFile
                raster_count = 0
                for name in archive.namelist():
                    if name.endswith('.tif'):
                        with MemoryFile(archive.read(name)) as memory, memory.open() as raster:
                            raster.read()
                            raster_count += 1
    result['archive'] = Path(result['archive']).relative_to(output).as_posix()
    report = {'mode': 'offline_real_data_replay; no live provider calls',
              'source_archive_sha256': checksum(Path(source)), 'anchor_id': anchor, 'year': year,
              'row_count': len(original_rows), 'all_rows_values_nulls_and_timestamps_equal': True,
              'relocated_rasters_opened': raster_count, 'resume': resumed['status'],
              'verification': verification, 'result': result}
    (output / 'replay.json').write_text(json.dumps(report, indent=2) + '\n', encoding='utf-8')
    return report


if __name__ == '__main__':
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--source-zip', type=Path, required=True)
    parser.add_argument('--output', type=Path, required=True)
    args = parser.parse_args()
    print(json.dumps(replay(args.source_zip, args.output), indent=2))
