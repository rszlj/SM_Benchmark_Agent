"""Portable public ZIP writing and integrity verification, without source discovery."""
import hashlib
import json
import os
from pathlib import Path, PurePosixPath
import stat
import tempfile
import zipfile

from .grid import anchor_cell_from_id


def safe_relative(name):
    path = PurePosixPath(name)
    if (not name or path.is_absolute() or '..' in path.parts
            or '\\' in name or ':' in name or path.as_posix() != name):
        raise ValueError('Unsafe package path')
    return path


def verify_archive(path, *, anchor_id=None, year=None, sha256=None):
    """Check identities, complete manifest membership, CRC, sizes and SHA-256."""
    if sha256 is not None:
        with Path(path).open('rb') as stream:
            if hashlib.file_digest(stream, 'sha256').hexdigest() != sha256:
                raise ValueError('Archive checksum mismatch')
    with zipfile.ZipFile(path) as archive:
        infos = archive.infolist()
        names = [i.filename for i in infos]
        if len({n.casefold() for n in names}) != len(names):
            raise ValueError('Duplicate ZIP member')
        for info in infos:
            safe_relative(info.filename)
            if info.is_dir() or stat.S_ISLNK(info.external_attr >> 16):
                raise ValueError('Only regular package files are supported')
        manifest = json.loads(archive.read('package_manifest.json'))
        if manifest.get('schema') not in {'anchor-year-delivery-v1', 'anchor-year-delivery-v2'}:
            raise ValueError('Unsupported delivery schema')
        anchor_cell_from_id(manifest['anchor_id'])
        if type(manifest['year']) is not int or not 1 <= manifest['year'] <= 9999:
            raise ValueError('Invalid package year')
        if anchor_id is not None and manifest['anchor_id'] != anchor_id:
            raise ValueError('Package anchor mismatch')
        if year is not None and manifest['year'] != year:
            raise ValueError('Package year mismatch')
        entries = manifest['files']
        listed = [e['path'] for e in entries]
        if len(set(listed)) != len(listed) or set(names) != set(listed) | {'package_manifest.json'}:
            raise ValueError('Manifest membership mismatch')
        if 'package_manifest.json' in listed:
            raise ValueError('Manifest cannot list itself')
        for entry in entries:
            safe_relative(entry['path'])
            if archive.getinfo(entry['path']).file_size != entry['bytes']:
                raise ValueError('Archive member size mismatch')
            with archive.open(entry['path']) as stream:
                if hashlib.file_digest(stream, 'sha256').hexdigest() != entry['sha256']:
                    raise ValueError('Archive member checksum mismatch')
        # Reading every member above checks CRC; also read the manifest to EOF.
        return {'files': len(names), 'listed_files': len(entries),
                'anchor_id': manifest['anchor_id'], 'year': manifest['year']}


def write_archive(package, destination):
    """Verify a staged ZIP before publishing it; never overwrite a delivery."""
    package, destination = Path(package), Path(destination)
    destination.parent.mkdir(parents=True, exist_ok=True)
    if destination.exists():
        raise FileExistsError(destination)
    fd, name = tempfile.mkstemp(suffix='.zip.part', dir=destination.parent)
    os.close(fd)
    temporary = Path(name)
    try:
        with zipfile.ZipFile(temporary, 'w', compression=zipfile.ZIP_STORED, allowZip64=True) as archive:
            for path in sorted(package.rglob('*')):
                if path.is_symlink():
                    raise ValueError('Package symlinks are forbidden')
                if path.is_file():
                    archive.write(path, path.relative_to(package).as_posix())
        verify_archive(temporary)
        # Same-directory hard link is atomic and refuses an existing destination.
        os.link(temporary, destination)
    finally:
        temporary.unlink(missing_ok=True)
