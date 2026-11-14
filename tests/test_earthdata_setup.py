import json
from pathlib import Path
import tempfile
import unittest
from sm_benchmark_agent.earthdata_setup import check_local


class EarthdataSetupTests(unittest.TestCase):
    def test_local_checks_do_not_disclose_credentials(self):
        with tempfile.TemporaryDirectory() as root:
            path = Path(root) / '.netrc'
            self.assertEqual(check_local(path)['status'], 'credential_required')
            path.write_text('machine urs.earthdata.nasa.gov login private-user password private-secret\n')
            path.chmod(0o600)
            result = check_local(path)
            self.assertEqual(result['status'], 'configured')
            self.assertNotIn('private-user', json.dumps(result))
            self.assertNotIn('private-secret', json.dumps(result))
            path.write_text('machine another.example login x password y\n')
            self.assertEqual(check_local(path)['status'], 'credential_required')
            path.write_text('unknown-token private-secret\n')
            self.assertEqual(check_local(path)['status'], 'configuration_error')
