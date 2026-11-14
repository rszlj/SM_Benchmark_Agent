"""Check user-owned Earthdata .netrc configuration without displaying credentials."""
import argparse
import json
import netrc
import os
from pathlib import Path
import subprocess
import sys


def check_local(path=None):
    path = Path(path) if path else Path.home() / '.netrc'
    if not path.is_file():
        return {'status': 'credential_required', 'reason': 'netrc_missing'}
    if os.name != 'nt' and path.stat().st_mode & 0o077:
        return {'status': 'configuration_error', 'reason': 'netrc_permissions_use_600'}
    try:
        auth = netrc.netrc(str(path)).authenticators('urs.earthdata.nasa.gov')
    except (OSError, netrc.NetrcParseError):
        return {'status': 'configuration_error', 'reason': 'netrc_unreadable_or_invalid'}
    if not auth or not auth[0] or not auth[2]:
        return {'status': 'credential_required', 'reason': 'earthdata_entry_incomplete'}
    return {'status': 'configured', 'online_verified': False, 'method': 'netrc'}


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--online', action='store_true', help='Verify login with Harmony; submits no data jobs')
    args = parser.parse_args()
    result = check_local()
    if args.online and result['status'] == 'configured':
        # A child process bounds login time and captures any library diagnostics.
        # Only status is reported; raw errors can contain authentication details.
        code = "from harmony import Client; import netrc; a=netrc.netrc().authenticators('urs.earthdata.nasa.gov'); c=Client(auth=(a[0],a[2]))"
        import importlib.util
        if importlib.util.find_spec('harmony') is None:
            result = {'status': 'dependency_required', 'reason': 'install_earthdata_extra'}
        else:
            try:
                response = subprocess.run([sys.executable, '-c', code], capture_output=True, timeout=45)
                result = ({'status': 'authenticated', 'online_verified': True} if response.returncode == 0 else
                          {'status': 'verification_failed', 'reason': 'check_login_service_authorization_and_network'})
            except subprocess.TimeoutExpired:
                result = {'status': 'verification_failed', 'reason': 'network_or_login_timeout'}
    print(json.dumps(result))
    return 0 if result['status'] in {'configured', 'authenticated'} else 1


if __name__ == '__main__':
    raise SystemExit(main())
