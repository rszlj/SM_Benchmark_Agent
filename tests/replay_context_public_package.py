"""Offline raw-input replay against an explicit V1 ZIP; no provider calls.

Supply the original SRTM tile, the land-cover ZIP/member/band for that year,
and the verified prepared HWSD2 global cache. Never modifies those inputs.
"""
import argparse
import json
from pathlib import Path
import shutil
import tempfile
from unittest.mock import patch
import zipfile

import numpy as np
import rasterio
from rasterio.io import MemoryFile

from sm_benchmark_agent.archives import verify_archive
from sm_benchmark_agent.context_sources import ContextAdapter, PROFILES, processing_hashes
from sm_benchmark_agent.context_workflow import plan_contexts, execute_contexts
from sm_benchmark_agent.delivery import checksum
from sm_benchmark_agent.gldas_workflow import checked_context


def replay(args):
    reference = verify_archive(args.reference_zip)
    anchor, year = reference['anchor_id'], reference['year']
    args.output.mkdir(parents=True, exist_ok=False)

    class ReplayProvider:
        def fetch(self, unit, context):
            if unit.source_id == 'srtm':
                return args.srtm_raw.read_bytes()
            with zipfile.ZipFile(args.landcover_zip) as archive:
                payload = archive.read(args.landcover_member)
            with MemoryFile(payload) as memory, memory.open() as source:
                profile = source.profile.copy()
                profile.update(count=1)
                with MemoryFile() as out:
                    with out.open(**profile) as target:
                        target.write(source.read(args.landcover_band), 1)
                    return out.read()

    adapters = {s: ContextAdapter(s, provider=ReplayProvider(), hwsd_cache=args.hwsd_cache) for s in PROFILES}
    request = {'spatial': {'anchor_ids': [anchor]}, 'years': [year], 'sources': list(PROFILES),
               'station_targets': 'absent', 'output_root': str(args.output / 'delivery')}
    kwargs = dict(asset_root=args.output / 'cache', release_id='context-offline-replay-v1',
                  hwsd_cache=args.hwsd_cache, adapters=adapters)
    with patch('socket.socket', side_effect=AssertionError('Replay must be offline')):
        plan = plan_contexts(request, **kwargs)
        result = execute_contexts(plan, accepted_plan_id=plan['plan_id'], adapters=adapters)
        plan = plan_contexts(request, **kwargs)
        assert execute_contexts(plan, accepted_plan_id=plan['plan_id'], adapters=adapters)['status'] == 'reused'
    path = Path(result['context_plan'])
    doc = json.loads(path.read_text())
    comparisons = []
    with zipfile.ZipFile(args.reference_zip) as archive:
        for asset in doc['assets']:
            name = asset['destination']
            target = path.parent / asset['path']
            if name.endswith('.tif'):
                with rasterio.open(target) as actual, MemoryFile(archive.read(name)) as memory, memory.open() as expected:
                    comparisons.append({'file': name, 'equal_values_and_masks': bool(np.array_equal(actual.read(), expected.read(), equal_nan=True)),
                                        'same_grid': actual.transform == expected.transform and actual.crs == expected.crs,
                                        'shape': list(actual.read().shape)})
            elif name.endswith('.csv'):
                comparisons.append({'file': name, 'equal_csv_bytes': target.read_bytes() == archive.read(name)})
    with tempfile.TemporaryDirectory(prefix='context-relocation-') as temporary:
        moved = Path(temporary) / 'context'
        shutil.copytree(path.parent, moved)
        checked_context(moved / 'context.json', anchor, year)
    report = {'mode': 'offline raw-input replay; no provider requests', 'anchor_id': anchor, 'year': year,
              'reference_zip_sha256': checksum(args.reference_zip), 'comparisons': comparisons,
              'resume': 'reused', 'relocated_context_validation': 'passed',
              'processing_code_sha256': processing_hashes(),
              'scope': 'Known V1 reference; not a new-location or live-provider acceptance'}
    (args.output / 'validation.json').write_text(json.dumps(report, indent=2) + '\n')
    assert comparisons and all(all(v for k, v in item.items() if k.startswith(('equal_', 'same_'))) for item in comparisons)
    return report


if __name__ == '__main__':
    parser = argparse.ArgumentParser(description=__doc__)
    for name in ['reference-zip', 'srtm-raw', 'landcover-zip', 'hwsd-cache', 'output']:
        parser.add_argument('--' + name, type=Path, required=True)
    parser.add_argument('--landcover-member', required=True)
    parser.add_argument('--landcover-band', type=int, required=True)
    print(json.dumps(replay(parser.parse_args()), indent=2))
