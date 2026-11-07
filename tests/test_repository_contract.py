import csv
import gzip
import hashlib
import json
from pathlib import Path
import tempfile
import unittest
from unittest.mock import patch

from sm_benchmark_agent.adapters import AdapterRegistry
from sm_benchmark_agent.catalogue import ReleaseCatalogue
from sm_benchmark_agent.extension_agent import plan_extension

ROOT = Path(__file__).resolve().parents[1]


class RepositoryContractTests(unittest.TestCase):
    def test_v1_catalogue_counts_integrity_and_no_data(self):
        catalogue = ReleaseCatalogue(ROOT / 'data/v1')
        self.assertEqual(len(catalogue.rows), 19982)
        self.assertEqual(len(catalogue.package_anchors), 1679)
        self.assertEqual(catalogue.release['station_inventory_anchor_count'], 1822)
        self.assertIsNone(catalogue.release['download_base_url'])
        self.assertFalse(list((ROOT / 'data').rglob('*.zip')))
        provenance = json.loads((ROOT / 'docs/migration-provenance.json').read_text())
        digest = hashlib.sha256((ROOT / 'data/v1/catalog.csv.gz').read_bytes()).hexdigest()
        self.assertEqual(digest, provenance['catalogue_sha256'])
        for row in catalogue.rows.values():
            self.assertEqual(row['error'], '')
            self.assertEqual(row['build_status'], 'complete')
            self.assertTrue(row['archive_path'].startswith('packages/'))
            self.assertNotIn(':', row['archive_path'])
            self.assertEqual(len(row['archive_sha256']), 64)

    def test_offline_catalogue_match_is_distinct_from_local_availability(self):
        with tempfile.TemporaryDirectory() as directory, patch('socket.socket', side_effect=AssertionError('No network')):
            root = Path(directory)
            catalogue = ReleaseCatalogue(ROOT / 'data/v1', package_root=root)
            request = {'spatial': {'anchor_ids': ['EASE2_M09km_R0304_C2105']},
                       'years': [2001], 'sources': ['era5_land'], 'output_root': str(root / 'out')}
            plan = plan_extension(request, catalogue)
            unit = plan['units'][0]
            self.assertTrue(unit['catalogue_match'])
            self.assertEqual(unit['state'], 'requires_user_action')
            self.assertEqual(unit['archive_bytes'], 1471016)
            self.assertEqual(plan['estimates']['known_copy_bytes'], 0)
            self.assertFalse((root / 'out').exists())
            self.assertEqual(catalogue.archive_path(catalogue.package(unit['anchor_id'], 2001)),
                             root / unit['archive_path'])

    def test_unimplemented_adapter_is_not_silently_registered(self):
        with self.assertRaisesRegex(NotImplementedError, 'No reviewed preparation adapter'):
            AdapterRegistry().require('gldas21')


if __name__ == '__main__':
    unittest.main()
