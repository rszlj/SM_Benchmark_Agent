"""Add validated SMAP annual assets to a verified existing multi-source ZIP."""
import argparse
import json
from pathlib import Path
import shutil
import tempfile
import zipfile

from .archives import verify_archive, write_archive
from .delivery import checksum, validate_plan


def merge_smap(base_zip, asset_plan, output_root, *, dry_run=True):
    base_zip, asset_plan = Path(base_zip).resolve(), Path(asset_plan).resolve()
    plan = json.loads(asset_plan.read_text(encoding='utf-8'))
    assets = validate_plan(plan, asset_plan.parent)
    aid, year = plan['anchor_id'], plan['year']
    verify_archive(base_zip, anchor_id=aid, year=year)
    records = [r for r in plan['availability'] if r['source'] != 'ismn']
    if len(records) != 1 or records[0]['source'] != 'smap_l3':
        raise ValueError('This adapter requires a SMAP L3-only prepared asset plan')
    data = [(e, p) for e, p, _ in assets if e['role'] == 'source_cell_time_series']
    meta = [(e, p) for e, p, _ in assets if e['role'] == 'metadata' and e.get('kind') != 'grid']
    if len(data) != 1 or len(meta) != 1 or len(assets) != 3:
        raise ValueError('Expected validated SMAP table, source metadata and grid metadata')
    source = json.loads(meta[0][1].read_text(encoding='utf-8'))
    if (source.get('anchor_id'), source.get('year'), source.get('product'), source.get('version')) != (aid, year, 'SPL3SMP_E', '006'):
        raise ValueError('SMAP source identity mismatch')
    digest = checksum(data[0][1])
    if source.get('sha256') != digest or data[0][0].get('sha256') != digest:
        raise ValueError('SMAP table checksum mismatch')
    # These fields are the public source contract, not local job/debug provenance.
    public_fields = ('source', 'product', 'version', 'anchor_id', 'year', 'units',
        'variables', 'sampling', 'tb_support', 'time_reference', 'time_conversion',
        'quality_policy', 'missing_values', 'requested_dates', 'source_dates',
        'missing_source_dates', 'missing_reason', 'records', 'sha256')
    source = {k: source[k] for k in public_fields if k in source}
    name = f'source_cell_time_series/smap_l3/smap_l3_{year}.parquet'
    provenance = 'metadata/source_manifests/smap_l3.json'
    base_hash = checksum(base_zip)
    identity = {'base_sha256': base_hash, 'smap_sha256': digest,
                'source_metadata': source, 'availability': records[0]}
    destination = Path(output_root).resolve() / 'packages' / aid / f'{year}.zip'
    if destination == base_zip:
        raise ValueError('Output must not overwrite the base package')
    with zipfile.ZipFile(base_zip) as z:
        manifest = json.loads(z.read('package_manifest.json'))
        if any(e.get('source_id') in ('smap_l3', 'SPL3SMP_E.006') or 'smap_l3' in e['path'].lower() for e in manifest['files']):
            raise ValueError('Base already contains SMAP L3; replacement requires a separate reviewed workflow')
        names = set(z.namelist())
        if not {'metadata/availability.json', 'metadata/data_dictionary.json'} <= names:
            raise ValueError('Requires a benchmark multi-source package with availability and dictionary')
        availability = json.loads(z.read('metadata/availability.json'))
        dictionary = json.loads(z.read('metadata/data_dictionary.json'))
    summary = {'anchor_id': aid, 'year': year, 'destination': str(destination),
               'smap_state': records[0]['state'], 'base_input_and_target_files_preserved': True}
    if destination.exists():
        verify_archive(destination, anchor_id=aid, year=year)
        with zipfile.ZipFile(destination) as z:
            if json.loads(z.read('package_manifest.json')).get('extension') != identity:
                raise ValueError('Existing output belongs to another merge')
        return dict(summary, status='reused')
    if dry_run:
        return dict(summary, status='planned')
    destination.parent.mkdir(parents=True, exist_ok=True)
    with tempfile.TemporaryDirectory(prefix='.merge-', dir=destination.parent) as tmp:
        root = Path(tmp)
        with zipfile.ZipFile(base_zip) as z:
            z.extractall(root)  # All member paths and file types verified above.
        if checksum(base_zip) != base_hash:
            raise ValueError('Base changed during merge')
        target = root / name
        target.parent.mkdir(parents=True, exist_ok=True)
        shutil.copyfile(data[0][1], target)
        if checksum(target) != digest:
            raise ValueError('SMAP changed during merge')
        def save(relative, value):
            path = root / relative
            path.parent.mkdir(parents=True, exist_ok=True)
            path.write_text(json.dumps(value, indent=2) + '\n', encoding='utf-8')
        save(provenance, source)
        record = dict(records[0], source_id='smap_l3', product='SPL3SMP_E.006',
                      representation='native source-cell AM/PM time series', files=[name])
        record.pop('source', None)
        availability['sources'] = [r for r in availability['sources'] if r.get('source_id') != 'smap_l3'] + [record]
        dictionary['sources'] = [r for r in dictionary['sources'] if r.get('source_id') != 'smap_l3'] + [
            {'source_id': 'smap_l3', 'product': 'SPL3SMP_E.006', 'metadata': provenance,
             'representation': record['representation'], 'missing_values': 'Parquet null; no imputation'}]
        save('metadata/availability.json', availability)
        save('metadata/data_dictionary.json', dictionary)
        with (root / 'README.md').open('a', encoding='utf-8') as f:
            f.write('\n\n## SMAP L3 extension\nSMAP L3 soil moisture and brightness temperature were added as native-cell AM/PM records.\nSee metadata/source_manifests/smap_l3.json for variables, units and actual dates.\nAvailability is source-specific; an annual package does not imply full-year SMAP coverage.\nExisting station targets and other input data were preserved unchanged.\n')
        manifest['parent_release_id'] = manifest['release_id']
        manifest['release_id'] += '-smap-l3-extension'
        manifest['extension'] = identity
        if 'availability' in manifest:
            manifest['availability'] = [r for r in manifest['availability'] if r.get('source') != 'smap_l3'] + records
        entries = {e['path']: e for e in manifest['files']}
        entries[name] = {'path': name, 'role': 'source_cell_time_series', 'source_id': 'smap_l3'}
        entries[provenance] = {'path': provenance, 'role': 'metadata', 'source_id': 'smap_l3'}
        for path in root.rglob('*'):
            if path.is_file() and path.name != 'package_manifest.json':
                relative = path.relative_to(root).as_posix()
                entry = entries.setdefault(relative, {'path': relative, 'role': 'metadata', 'source_id': 'delivery'})
                entry.update(bytes=path.stat().st_size, sha256=checksum(path))
        manifest['files'] = list(entries.values())
        save('package_manifest.json', manifest)
        write_archive(root, destination)
    return dict(summary, status='packaged', verification=verify_archive(destination))


def main():
    p = argparse.ArgumentParser(description=__doc__)
    p.add_argument('--base-zip', type=Path, required=True)
    p.add_argument('--assets', type=Path, required=True)
    p.add_argument('--output-root', type=Path, required=True)
    p.add_argument('--execute', action='store_true')
    a = p.parse_args()
    print(json.dumps(merge_smap(a.base_zip, a.assets, a.output_root, dry_run=not a.execute), indent=2))


if __name__ == '__main__':
    main()
