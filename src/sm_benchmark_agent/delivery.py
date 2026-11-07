"""Deterministic, self-contained anchor-year export from an explicit asset plan.

This exporter never discovers, downloads or imputes data. Source adapters must
first supply a reviewed plan with coverage and provenance metadata.
"""
from datetime import datetime, timezone
import hashlib
import json
import os
from pathlib import Path, PurePosixPath
import shutil
import tempfile

from .grid import anchor_cell_from_id

ROLES = {'station_targets', 'raster_inputs', 'source_cell_time_series',
         'static_context', 'annual_context', 'metadata'}
STATES = {'available', 'partial', 'unavailable', 'not processed', 'failed'}


def checksum(path):
    digest = hashlib.sha256()
    with path.open('rb') as stream:
        for block in iter(lambda: stream.read(8 * 1024 * 1024), b''):
            digest.update(block)
    return digest.hexdigest()


def validate_plan(plan, base):
    """Resolve source assets without writing or initiating remote access."""
    anchor_cell_from_id(plan['anchor_id'])
    year = plan['year']
    if not isinstance(year, int) or isinstance(year, bool) or not 1 <= year <= 9999:
        raise ValueError('year must be an integer calendar year')
    if not plan.get('release_id') or not plan.get('processing_version'):
        raise ValueError('release_id and processing_version are required')
    if not plan.get('availability'):
        raise ValueError('Explicit availability records are required')
    for record in plan['availability']:
        if not record.get('source') or record.get('state') not in STATES:
            raise ValueError('Availability requires a source and canonical state')
        if record['state'] != 'available' and not record.get('reason'):
            raise ValueError('Missing/partial availability needs an explicit reason, or unknown')
    assets, destinations = [], set()
    for entry in plan['assets']:
        if entry['role'] not in ROLES:
            raise ValueError('Unknown asset role')
        path = PurePosixPath(entry['destination'])
        if path.is_absolute() or not path.parts or '..' in path.parts or any(':' in p or '\\' in p for p in path.parts):
            raise ValueError('Unsafe destination path')
        name = path.as_posix()
        if name.casefold() in destinations or name.casefold() == 'package_manifest.json':
            raise ValueError('Duplicate/reserved destination')
        destinations.add(name.casefold())
        if not entry.get('source_id'):
            raise ValueError('Source identity/version reference required for each asset')
        source = (base / entry['path']).resolve()
        if not source.is_file():
            raise FileNotFoundError(source)
        assets.append((entry, source, path))
    if not assets:
        raise ValueError('No assets')
    roles = {e['role'] for e, _, _ in assets}
    kinds = {e.get('kind') for e, _, _ in assets if e['role'] == 'metadata'}
    if 'grid' not in kinds:
        raise ValueError('Package-local grid metadata is required')
    if 'station_targets' in roles and not {'stations', 'depths'} <= kinds:
        raise ValueError('Targets require package-local station and depth catalogues')
    if plan.get('station_targets') == 'absent':
        if 'station_targets' in roles or {'stations', 'depths'} & kinds:
            raise ValueError('Gridded-only delivery cannot contain station targets/catalogues')
        if not roles & {'raster_inputs', 'source_cell_time_series', 'static_context', 'annual_context'}:
            raise ValueError('Gridded-only delivery requires at least one input asset')
        if not any(r['source'] == 'ismn' and r['state'] == 'unavailable'
                   and r.get('reason') == 'absent_by_design' for r in plan['availability']):
            raise ValueError('Gridded-only delivery requires explicit ISMN absent_by_design')
    return assets


def export_anchor_year(plan_path, output_root, *, dry_run=True):
    plan_path = Path(plan_path).resolve()
    plan = json.loads(plan_path.read_text(encoding='utf-8'))
    assets = validate_plan(plan, plan_path.parent)
    destination = Path(output_root).resolve() / plan['anchor_id'] / str(plan['year'])
    summary = dict(anchor_id=plan['anchor_id'], year=plan['year'], asset_count=len(assets),
                   bytes=sum(p.stat().st_size for _, p, _ in assets), destination=str(destination))
    if dry_run:
        return dict(summary, status='planned')
    if destination.exists():
        raise FileExistsError(f'Never overwrite an existing delivery: {destination}')
    destination.parent.mkdir(parents=True, exist_ok=True)
    staging = Path(tempfile.mkdtemp(prefix=f'.{plan["year"]}-export-', dir=destination.parent))
    manifest = {k: plan[k] for k in ('anchor_id', 'year', 'release_id', 'processing_version', 'availability')}
    manifest.update(requested_period=plan.get('requested_period'))
    manifest.update(schema='anchor-year-delivery-v1', created_utc=datetime.now(timezone.utc).isoformat(), files=[])
    if plan.get('station_targets') == 'absent':
        manifest['station_targets'] = 'absent_by_design'
    for entry, source, relative in assets:
        target = staging.joinpath(*relative.parts)
        target.parent.mkdir(parents=True, exist_ok=True)
        before = checksum(source)
        if entry.get('sha256') and entry['sha256'] != before:
            raise ValueError(f'Source checksum mismatch: {source}')
        shutil.copyfile(source, target)
        if checksum(target) != before or checksum(source) != before:
            raise ValueError(f'Source changed or copy failed: {source}')
        manifest['files'].append(dict(path=relative.as_posix(), role=entry['role'],
                                      kind=entry.get('kind'), source_id=entry['source_id'],
                                      bytes=target.stat().st_size, sha256=before))
    (staging / 'package_manifest.json').write_text(json.dumps(manifest, indent=2) + '\n', encoding='utf-8')
    verify_delivery(staging)
    os.rename(staging, destination)
    return dict(summary, status='exported', verification='passed')


def verify_delivery(root):
    root = Path(root).resolve()
    manifest = json.loads((root / 'package_manifest.json').read_text(encoding='utf-8'))
    for entry in manifest['files']:
        path = (root / entry['path']).resolve()
        if not path.is_relative_to(root) or path.is_symlink():
            raise ValueError('Asset escapes package')
        if path.stat().st_size != entry['bytes'] or checksum(path) != entry['sha256']:
            raise ValueError(f'Delivery integrity failure: {entry["path"]}')
    return dict(status='passed', files=len(manifest['files']))


def export_gridded_archive(plan_path, output_root, *, dry_run=True):
    """Assemble already prepared public assets, without scientific transformations.

    Asset selection, source validation and annual slicing precede this interface.
    This function verifies delivery integrity, not arbitrary source semantics.
    """
    from .archives import write_archive, verify_archive
    plan_path = Path(plan_path).resolve()
    plan = json.loads(plan_path.read_text(encoding='utf-8'))
    if plan.get('station_targets') != 'absent':
        raise ValueError('Explicit station_targets=absent is required')
    assets = validate_plan(plan, plan_path.parent)
    if any(relative.as_posix().casefold() == 'readme.md' for _, _, relative in assets):
        raise ValueError('README.md is generated for gridded-only archives')
    period = plan.get("requested_period")
    if period:
        from .adapters import SourceUnit
        from .periods import bounds
        bounds(SourceUnit("delivery", "delivery", plan["anchor_id"], plan["year"], **period))
    filename = f"{period['start']}_{period['end']}.zip" if period else f"{plan['year']}.zip"
    destination = Path(output_root).resolve() / "packages" / plan["anchor_id"] / filename
    summary = {'anchor_id': plan['anchor_id'], 'year': plan['year'],
               'destination': str(destination), 'asset_count': len(assets),
               'station_targets': 'absent_by_design', 'validation': 'delivery_integrity_only'}
    if dry_run:
        return dict(summary, status='planned')
    if destination.exists():
        raise FileExistsError(destination)
    destination.parent.mkdir(parents=True, exist_ok=True)
    # Avoid repeating packages/anchor below an already nested destination: V1's
    # long time-series filenames otherwise exceed Windows' legacy path limit.
    # write_archive still publishes atomically beside the final ZIP.
    with tempfile.TemporaryDirectory(prefix='.pkg-', dir=Path(output_root).resolve()) as scratch:
        result = export_anchor_year(plan_path, scratch, dry_run=False)
        package = Path(result['destination'])
        readme = package / 'README.md'
        readme.write_text(
            f"# Gridded-only package\n\nRequested period: {period or 'full calendar year'}\n\nAnchor: {plan['anchor_id']}\nYear: {plan['year']}\n\n"
            'Station targets are absent by design. Input files are copied unchanged from an explicit\n'
            'prepared-asset plan. Source availability is recorded in package_manifest.json.\n'
            'This assembly verifies file integrity; source-specific scientific validation must\n'
            'be performed before assembly. No gap filling or temporal interpolation is applied.\n',
            encoding='utf-8')
        manifest_path = package / 'package_manifest.json'
        manifest = json.loads(manifest_path.read_text(encoding='utf-8'))
        manifest['files'].append({'path': 'README.md', 'role': 'metadata', 'source_id': 'delivery',
                                  'bytes': readme.stat().st_size, 'sha256': checksum(readme)})
        manifest_path.write_text(json.dumps(manifest, indent=2) + '\n', encoding='utf-8')
        write_archive(package, destination)
    return dict(summary, status='packaged', verification=verify_archive(destination))
