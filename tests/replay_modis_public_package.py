"""Replay explicit local MODIS raw inputs against a V1 ZIP, with network blocked.

The private input plan maps each source to path, optional ZIP member, and the
ordered dates of its raw stack (one band/date for NDVI, paired day/night for LST).
It is never included in output metadata. The output directory must be new.
"""
import argparse
import json
from pathlib import Path
import shutil
import tempfile
from unittest.mock import patch
import zipfile

import numpy as np
from rasterio.io import MemoryFile

from sm_benchmark_agent.archives import verify_archive
from sm_benchmark_agent.delivery import checksum
from sm_benchmark_agent.modis_sources import MODISAdapter, PROFILES, SOURCES, scientific_profile
from sm_benchmark_agent.modis_workflow import plan_modis, execute_modis, workflow_hashes


def replay(args):
    reference = verify_archive(args.reference_zip)
    anchor, year = reference['anchor_id'], reference['year']
    inputs = json.loads(args.input_plan.read_text(encoding='utf-8'))
    if set(inputs) != set(PROFILES):
        raise ValueError('Replay requires explicit raw inputs for all four MODIS sources')
    args.output.mkdir(parents=True, exist_ok=False)

    class ReplayProvider:
        calls = []
        def fetch(self, unit, context):
            self.calls.append(unit.source_id)
            entry = inputs[unit.source_id]
            raw_path = args.input_plan.parent / entry['path']
            if entry.get('member'):
                with zipfile.ZipFile(raw_path) as archive:
                    payload = archive.read(entry['member'])
            else:
                payload = raw_path.read_bytes()
            dates = entry['dates']
            if dates != sorted(set(dates)):
                raise ValueError('Raw replay dates must be ordered and unique')
            indices = [i for i, d in enumerate(dates) if d.startswith(f'{year}-')]
            factor = 1 if SOURCES[unit.source_id][2] == 'ndvi' else 2
            bands = [factor * i + j + 1 for i in indices for j in range(factor)]
            with MemoryFile(payload) as memory, memory.open() as source:
                if source.count != factor * len(dates):
                    raise ValueError('Replay date list must describe the full raw stack')
                profile = source.profile.copy()
                profile.update(count=len(bands))
                with MemoryFile() as result:
                    with result.open(**profile) as target:
                        target.write(source.read(bands))
                    subset = result.read()
            selected = [dates[i] for i in indices]
            return {'payload': subset, 'dates': selected,
                    'image_ids': [scientific_profile(unit.source_id)['collection'] + '/' + d.replace('-', '_') for d in selected]}

    provider = ReplayProvider()
    adapters = {s: MODISAdapter(s, provider=provider) for s in PROFILES}
    request = {'spatial': {'anchor_ids': [anchor]}, 'years': [year], 'sources': list(PROFILES),
               'station_targets': 'absent', 'output_root': str(args.output / 'delivery')}
    kwargs = dict(context_plan=args.context_plan, asset_root=args.output / 'cache', adapters=adapters)
    with patch('socket.socket', side_effect=AssertionError('Replay must not access a provider')):
        plan = plan_modis(request, **kwargs)
        result = execute_modis(plan, accepted_plan_id=plan['plan_id'], adapters=adapters)
        plan = plan_modis(request, **kwargs)
        assert execute_modis(plan, accepted_plan_id=plan['plan_id'], adapters=adapters)['status'] == 'reused'
        assert len(provider.calls) == 4
    comparisons = []
    with tempfile.TemporaryDirectory(prefix='modis-relocation-') as temporary:
        moved = Path(temporary) / 'annual.zip'
        shutil.copyfile(result['archive'], moved)
        verification = verify_archive(moved, anchor_id=anchor, year=year)
        with zipfile.ZipFile(moved) as actual, zipfile.ZipFile(args.reference_zip) as expected:
            for name in actual.namelist():
                if not name.endswith('.tif') or not any(f'annual/{s}/' in name for s in PROFILES):
                    continue
                with MemoryFile(actual.read(name)) as am, am.open() as a, MemoryFile(expected.read(name)) as bm, bm.open() as b:
                    av, bv = a.read(), b.read()
                    comparisons.append({'file': name, 'shape': list(av.shape),
                        'equal_values_and_masks': bool(np.array_equal(av, bv, equal_nan=True)),
                        'equal_band_dates': a.descriptions == b.descriptions,
                        'equal_grid': a.crs == b.crs and a.transform == b.transform})
    report = {'mode': 'offline raw-input replay; no provider requests', 'anchor_id': anchor, 'year': year,
              'reference_archive_sha256': checksum(args.reference_zip), 'comparisons': comparisons,
              'resume': 'reused', 'relocation': verification, 'processing_code_sha256': workflow_hashes(),
              'scope': 'One known V1 anchor/year; not live-provider or new-location acceptance'}
    (args.output / 'validation.json').write_text(json.dumps(report, indent=2) + '\n', encoding='utf-8')
    assert len(comparisons) == 6 and all(all(v for k, v in c.items() if k.startswith('equal_')) for c in comparisons)
    return report


if __name__ == '__main__':
    parser = argparse.ArgumentParser(description=__doc__)
    for key in ('reference-zip', 'context-plan', 'input-plan', 'output'):
        parser.add_argument('--' + key, type=Path, required=True)
    print(json.dumps(replay(parser.parse_args()), indent=2))
