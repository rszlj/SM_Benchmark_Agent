"""Standard-library bootstrap: select, check and run the repository's Python."""
import argparse
import json
import os
from pathlib import Path
import subprocess
import sys
import tempfile
import tomllib

ROOT = Path(__file__).resolve().parents[1]
RECORD = Path('.local/python-environment.json')
MODULES = {'core': ['pyproj'], 'gldas': ['ee', 'pyarrow', 'rasterio'],
           'contexts': ['ee', 'rasterio', 'numpy', 'access_parser', 'osgeo.gdal'],
           'modis': ['ee', 'rasterio', 'numpy', 'osgeo.gdal'],
           'timeseries': ['ee', 'pyarrow', 'rasterio'],
           'smap': ['ee', 'pyarrow', 'rasterio'],
           'sentinel1': ['ee', 'rasterio', 'numpy', 'pandas', 'xarray', 'h5netcdf', 'h5py']}


def resolve_python(root, explicit=None):
    root = Path(root).resolve()
    if explicit is not None:
        path = Path(explicit).expanduser()
        path = path if path.is_absolute() else root / path
        origin = 'explicit'
    elif (root / RECORD).exists():
        doc = json.loads((root / RECORD).read_text(encoding='utf-8'))
        if doc.get('schema') != 'benchmark-python-environment-v1' or doc.get('repository_root') != str(root):
            raise ValueError('Environment record belongs to another checkout; explicitly select again')
        path, origin = Path(doc['python']), 'saved'
        if not path.is_absolute():
            raise ValueError('Saved interpreter must be absolute')
    else:
        candidates = [root / '.venv' / ('Scripts/python.exe' if os.name == 'nt' else 'bin/python'),
                      root / '.conda' / ('python.exe' if os.name == 'nt' else 'bin/python')]
        path = next((p for p in candidates if p.is_file()), None)
        if path is None:
            raise FileNotFoundError('No project environment: create .conda/.venv or select --python PATH; PATH Python is not a target fallback')
        origin = 'project'
    # Keep venv symlink paths: resolving them can accidentally select the base Python.
    path = Path(os.path.abspath(path))
    if not path.is_file():
        raise FileNotFoundError('Selected Python no longer exists; explicitly select a replacement')
    return path, origin


def diagnose(python, root, extras):
    unknown = set(extras) - set(MODULES)
    if unknown:
        raise ValueError('Unknown dependency groups: ' + ', '.join(sorted(unknown)))
    modules = sorted({m for group in {'core', *extras} for m in MODULES[group]})
    code = '''import sys,json,importlib
root,modules=json.loads(sys.argv[1])
sys.path.insert(0,root+'/src')
checks={}
for name in modules:
 try:
  module=importlib.import_module(name)
  if name=='osgeo.gdal':
   ds=module.GetDriverByName('MEM').Create('',1,1,1)
   assert ds is not None
   ds=None
  if name=='pyproj':
   assert module.CRS.from_epsg(6933).to_epsg()==6933
  if name=='rasterio':
   assert module.crs.CRS.from_epsg(6933).to_epsg()==6933
  checks[name]={'status':'passed','version':str(getattr(module,'__version__','unknown'))}
 except Exception as exc: checks[name]={'status':'failed','error_type':type(exc).__name__}
import sm_benchmark_agent
print(json.dumps({'python':sys.executable,'version':list(sys.version_info[:3]),'prefix':sys.prefix,'base_prefix':sys.base_prefix,'package_file':sm_benchmark_agent.__file__,'checks':checks}))
'''
    result = subprocess.run([str(python), '-I', '-c', code, json.dumps([str(root), modules])],
                            cwd=root, capture_output=True, text=True, timeout=90)
    if result.returncode:
        raise RuntimeError('Selected interpreter probe failed; check Python version and installation')
    doc = json.loads(result.stdout)
    doc['warnings_emitted'] = bool(result.stderr.strip())
    doc['supported_python'] = tuple(doc['version']) >= (3, 11, 0)
    doc['ready'] = doc['supported_python'] and all(c['status'] == 'passed' for c in doc['checks'].values())
    return doc


def save(root, python, probe):
    path = root / RECORD
    path.parent.mkdir(parents=True, exist_ok=True)
    doc = {'schema': 'benchmark-python-environment-v1', 'repository_root': str(root),
           'python': str(python), 'python_version': probe['version'], 'prefix': probe['prefix']}
    fd, name = tempfile.mkstemp(dir=path.parent, suffix='.tmp')
    try:
        with os.fdopen(fd, 'w', encoding='utf-8') as f:
            json.dump(doc, f, indent=2)
        os.replace(name, path)
    finally:
        Path(name).unlink(missing_ok=True)


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('action', choices=['select', 'check', 'run'])
    parser.add_argument('--python', help='Explicit interpreter path; select persists this choice')
    parser.add_argument('--extras', default='', help='Comma-separated dependency groups, or all')
    parser.add_argument('--command', help='Registered sm-benchmark-* command for run')
    args, remaining = parser.parse_known_args()
    if remaining and remaining[0] == '--':
        remaining = remaining[1:]
    if remaining and args.action != 'run':
        parser.error('Unexpected arguments')
    try:
        python, origin = resolve_python(ROOT, args.python)
        groups = list(MODULES) if args.extras == 'all' else [g for g in args.extras.split(',') if g]
        if args.action == 'run' and not args.extras:
            defaults = {'sm-benchmark-prepare': list(MODULES), 'sm-benchmark-context': ['contexts'],
                        'sm-benchmark-modis': ['modis'], 'sm-benchmark-smap': ['smap'],
                        'sm-benchmark-timeseries': ['timeseries'], 'sm-benchmark-sentinel1': ['sentinel1']}
            groups = defaults.get(args.command, ['core'])
        probe = diagnose(python, ROOT, groups)
        if origin == 'saved':
            saved = json.loads((ROOT / RECORD).read_text(encoding='utf-8'))
            probe['saved_identity_matches'] = saved['python_version'] == probe['version'] and saved['prefix'] == probe['prefix']
            if args.action == 'run' and not probe['saved_identity_matches']:
                raise ValueError('Saved Python version/prefix changed; check and select again')
        if args.action == 'select':
            if not probe['supported_python']:
                raise ValueError('Python 3.11 or newer is required')
            save(ROOT, python, probe)
        if args.action != 'run':
            print(json.dumps(dict(probe, selection=origin, record=str(ROOT / RECORD)), indent=2))
            return 0 if probe['ready'] else 2
        if not probe['ready']:
            print(json.dumps(probe, indent=2))
            return 2
        project = tomllib.loads((ROOT / 'pyproject.toml').read_text(encoding='utf-8'))['project']
        if args.command not in project['scripts']:
            raise ValueError('run requires a registered --command')
        module, function = project['scripts'][args.command].split(':')
        code = 'import sys,importlib;sys.path.insert(0,sys.argv.pop(1));module=sys.argv.pop(1);function=sys.argv.pop(1);getattr(importlib.import_module(module),function)()'
        return subprocess.run([str(python), '-I', '-c', code, str(ROOT / 'src'), module, function, *remaining], cwd=ROOT).returncode
    except (ValueError, OSError, RuntimeError, subprocess.TimeoutExpired) as exc:
        parser.exit(2, f'{type(exc).__name__}: {exc}\n')


if __name__ == '__main__':
    raise SystemExit(main())
