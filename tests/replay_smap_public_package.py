"""Offline SMAP preprocessed-table replay; synthetic receipts do not validate sampling."""
import argparse
import json
from pathlib import Path
import shutil
import tempfile
from unittest.mock import patch
import zipfile

import pyarrow as pa
import pyarrow.parquet as pq

from sm_benchmark_agent.smap_sources import PROFILES, SMAPL4Adapter, profile
from sm_benchmark_agent.smap_workflow import plan_smap, execute_smap, workflow_hashes
from sm_benchmark_agent.archives import verify_archive
from sm_benchmark_agent.delivery import checksum


def replay(args):
    ref = verify_archive(args.reference_zip)
    anchor, year = ref['anchor_id'], ref['year']
    inputs = json.loads(args.input_plan.read_text(encoding='utf-8'))
    if set(inputs) != set(PROFILES):
        raise ValueError('SMAP input table required')
    tables = {s: pq.read_table(p).to_pylist() for s, p in inputs.items()}
    args.output.mkdir(parents=True, exist_ok=False)

    class Provider:
        calls = []
        def fetch(self, unit, start, end):
            self.calls.append((unit.source_id, start.month))
            lon, lat = profile(unit)['query_point']
            result = []
            for r in tables[unit.source_id]:
                dt = r['time_utc']
                if start <= dt < end:
                    result.append({'id': dt.strftime('%Y%m%d%H%M%S'), 'time': int(dt.timestamp()*1000),
                                   'longitude': lon, 'latitude': lat,
                                   **{k:v for k,v in r.items() if k != 'time_utc'}})
            return result

    provider = Provider()
    adapters = {s: SMAPL4Adapter(s, provider=provider) for s in PROFILES}
    request = {'spatial': {'anchor_ids': [anchor]}, 'years': [year], 'sources': list(PROFILES),
               'station_targets': 'absent', 'output_root': str(args.output / 'delivery')}
    kwargs = dict(context_plan=args.context_plan, asset_root=args.output / 'cache', adapters=adapters)
    with patch('socket.socket', side_effect=AssertionError('No network in replay')):
        plan = plan_smap(request, **kwargs)
        result = execute_smap(plan, accepted_plan_id=plan['plan_id'], adapters=adapters)
        plan = plan_smap(request, **kwargs)
        assert execute_smap(plan, accepted_plan_id=plan['plan_id'], adapters=adapters)['status'] == 'reused'
        assert len(provider.calls) == (10 if year == 2015 else 12)
    comparisons = []
    with tempfile.TemporaryDirectory() as temp:
        moved = Path(temp) / 'annual.zip'
        shutil.copyfile(result['archive'], moved)
        verification = verify_archive(moved, anchor_id=anchor, year=year)
        with zipfile.ZipFile(moved) as actual, zipfile.ZipFile(args.reference_zip) as expected:
            for source in PROFILES:
                name = next(n for n in actual.namelist() if n.startswith(f'source_cell_time_series/{source}/'))
                a, b = [pq.read_table(pa.BufferReader(z.read(name))).replace_schema_metadata(None) for z in (actual, expected)]
                meta = json.loads(actual.read(f'metadata/source_manifests/{source}.json'))
                comparisons.append({'source': source, 'rows': a.num_rows, 'equal_schema': a.schema == b.schema,
                                    'equal_values_timestamps_nulls': a.equals(b), 'state': meta['state'],
                                    'null_counts': meta['null_counts']})
    report = {'date': '2026-11-08', 'mode': 'Offline preprocessed source-table replay; network blocked',
              'scope': 'One known V1 anchor/year; not raw-provider, live or new-location acceptance',
              'provider_receipts': 'Synthetic timestamp IDs and anchor-centre coordinates for replay only; source table has no receipts. Spatial equivalence is NOT tested',
              'anchor_id': anchor, 'year': year, 'reference_archive_sha256': checksum(args.reference_zip),
              'input_sha256': {s: checksum(Path(p)) for s, p in inputs.items()},
              'comparisons': comparisons, 'resume': 'reused', 'relocation': verification,
              'processing_code_sha256': workflow_hashes()}
    (args.output / 'validation.json').write_text(json.dumps(report, indent=2) + '\n', encoding='utf-8')
    assert all(r['equal_schema'] and r['equal_values_timestamps_nulls'] for r in comparisons)
    return report


if __name__ == '__main__':
    parser = argparse.ArgumentParser(description=__doc__)
    for key in ('reference-zip', 'context-plan', 'input-plan', 'output'):
        parser.add_argument('--' + key, type=Path, required=True)
    print(json.dumps(replay(parser.parse_args()), indent=2))
