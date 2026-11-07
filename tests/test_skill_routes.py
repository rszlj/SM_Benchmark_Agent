"""Check skill routing against executable capabilities, not prose snapshots."""
import json
import importlib
from pathlib import Path
import re
import tempfile
import tomllib
import unittest
from unittest.mock import patch

from sm_benchmark_agent.adapters import default_registry, SourceUnit
from sm_benchmark_agent.catalogue import SOURCE_COLUMNS
from sm_benchmark_agent.context_workflow import plan_contexts

ROOT = Path(__file__).resolve().parents[1]


class SkillRouteTests(unittest.TestCase):
    def setUp(self):
        self.index = json.loads((ROOT / 'skills/source-index.json').read_text(encoding='utf-8'))

    def test_index_covers_catalogue_and_matches_real_adapters(self):
        supported, missing = self.index['sources'], self.index['unimplemented']
        self.assertFalse(set(supported) & set(missing))
        self.assertEqual(set(supported) | set(missing), set(SOURCE_COLUMNS))
        registry = default_registry()
        for source in SOURCE_COLUMNS:
            if source in supported:
                self.assertEqual(registry.require(source).profile_id, supported[source]['profile_id'])
            else:
                with self.assertRaises(NotImplementedError):
                    registry.require(source)

    def test_integrated_route_matches_supported_sources_and_entrypoint(self):
        from sm_benchmark_agent.multi_workflow import SOURCES
        route = self.index['integrated_workflow']
        self.assertEqual(set(route['sources']), SOURCES)
        with (ROOT / 'pyproject.toml').open('rb') as f:
            project = tomllib.load(f)['project']
        module, function = project['scripts'][route['command']].split(':')
        self.assertTrue(callable(getattr(importlib.import_module(module), function)))
        self.assertTrue((ROOT / route['guide']).is_file())
        example = json.loads((ROOT / route['example']).read_text())
        self.assertLessEqual(set(example['sources']), SOURCES)
        self.assertEqual(example['station_targets'], 'absent')

    def test_skills_are_unique_and_references_resolve_inside_checkout(self):
        paths = [ROOT / r['skill'] for r in self.index['sources'].values()]
        self.assertEqual(len(paths), len(set(paths)))
        coordinator = ROOT / 'skills/extend-soil-moisture-benchmark/SKILL.md'
        self.assertEqual(set(ROOT.glob('skills/*/SKILL.md')), set(paths) | {coordinator})
        for p in paths + [coordinator]:
            text = p.read_text(encoding='utf-8')
            front = text.split('---', 2)[1]
            name = re.search(r'^name: (.+)$', front, re.M).group(1)
            self.assertEqual(name, p.parent.name)
        files = list(ROOT.glob('skills/**/*.md')) + [ROOT / 'docs/skill-layout.md']
        for p in files:
            for target in re.findall(r'\[[^\]]+\]\(([^)]+)\)', p.read_text(encoding='utf-8')):
                if target.startswith(('http://', 'https://')):
                    continue
                relative, _, fragment = target.partition('#')
                resolved = (p.parent / relative).resolve() if relative else p
                self.assertTrue(resolved.is_relative_to(ROOT), (p, target))
                self.assertTrue(resolved.is_file(), (p, target))
                if fragment:
                    headers = re.findall(r'^#+ (.+)$', resolved.read_text(encoding='utf-8'), re.M)
                    anchors = {re.sub(r'[^\w\- ]', '', h.lower()).replace(' ', '-') for h in headers}
                    self.assertIn(fragment, anchors, (p, target))

    def test_workflows_resolve_installed_entrypoints_extras_and_examples(self):
        with (ROOT / 'pyproject.toml').open('rb') as f:
            project = tomllib.load(f)['project']
        for name, route in self.index['workflows'].items():
            self.assertIn(route['command'], project['scripts'], name)
            module, function = project['scripts'][route['command']].split(':')
            self.assertTrue(callable(getattr(importlib.import_module(module), function)))
            self.assertIn(route['extra'], project['optional-dependencies'], name)
            self.assertTrue((ROOT / route['guide']).is_file())
            example = json.loads((ROOT / route['example']).read_text(encoding='utf-8'))
            self.assertEqual(example['station_targets'], 'absent')
            families = {self.index['sources'][s]['workflow'] for s in example['sources']}
            self.assertIn(name, families)
            self.assertLessEqual(families, {name, 'contexts'} if route['requires_context'] else {name})
        self.assertEqual(self.index['workflows']['gldas']['selector'], ['--workflow', 'gldas'])
        self.assertEqual(self.index['workflows']['contexts']['subcommand'], 'prepare')

    def test_all_indexed_adapters_plan_offline_without_creating_cache(self):
        with tempfile.TemporaryDirectory() as temp, patch('socket.socket', side_effect=AssertionError('Offline only')):
            root = Path(temp) / 'not-created'
            registry = default_registry()
            for source, route in self.index['sources'].items():
                unit = SourceUnit(source, route['profile_id'], 'EASE2_M09km_R0540_C0257', 2015)
                plan = registry.require(source).plan(unit, asset_root=root)
                self.assertEqual(plan.unit, unit)
                self.assertIn(plan.state, {'retrievable', 'requires_user_action', 'unavailable'})
                self.assertFalse(root.exists())

    def test_route_families_keep_product_identity_and_context_bundle(self):
        sources = self.index['sources']
        self.assertNotEqual(sources['mod13q1_ndvi']['skill'], sources['myd13q1_ndvi']['skill'])
        self.assertEqual(sources['mod13q1_ndvi']['workflow'], sources['myd13q1_ndvi']['workflow'])
        self.assertEqual(sources['era5_land']['workflow'], sources['imerg_v07']['workflow'])
        self.assertNotEqual(sources['sentinel1']['workflow'], sources['era5_land']['workflow'])
        self.assertEqual(set(self.index['context_prerequisites']), set(self.index['workflows']['contexts']['included_sources']))
        request = {'spatial': {'anchor_ids': ['EASE2_M09km_R0540_C0257']}, 'years': [2015],
                   'sources': ['srtm'], 'station_targets': 'absent', 'output_root': 'unused'}
        with tempfile.TemporaryDirectory() as temp, patch('socket.socket', side_effect=AssertionError('Offline only')):
            with self.assertRaisesRegex(ValueError, 'exactly SRTM'):
                plan_contexts(request, asset_root=Path(temp), release_id='skill-route-test')


if __name__ == '__main__':
    unittest.main()
