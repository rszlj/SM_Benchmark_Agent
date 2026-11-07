import importlib.util
import json
import os
from pathlib import Path
import subprocess
import sys
import tempfile
import unittest
from unittest.mock import patch

ROOT = Path(__file__).resolve().parents[1]
spec = importlib.util.spec_from_file_location('python_env', ROOT/'scripts/python_env.py')
env = importlib.util.module_from_spec(spec)
spec.loader.exec_module(env)


class EnvironmentTests(unittest.TestCase):
    def test_missing_dependency_is_not_ready(self):
        with patch.dict(env.MODULES, {'missing-test': ['benchmark_nonexistent_dependency_test']}):
            probe=env.diagnose(Path(sys.executable),ROOT,['missing-test'])
        self.assertFalse(probe['ready'])
        self.assertEqual(probe['checks']['benchmark_nonexistent_dependency_test']['error_type'],'ModuleNotFoundError')

    def test_missing_environment_does_not_fall_back_to_path(self):
        with tempfile.TemporaryDirectory() as temp:
            with self.assertRaises(FileNotFoundError): env.resolve_python(Path(temp))

    def test_explicit_saved_priority_and_stale_path(self):
        with tempfile.TemporaryDirectory(prefix='environment space ') as temp:
            root=Path(temp).resolve()
            target=Path(sys.executable)
            probe={'version':list(sys.version_info[:3]),'prefix':sys.prefix}
            env.save(root,target,probe)
            self.assertEqual(env.resolve_python(root),(target,'saved'))
            self.assertEqual(env.resolve_python(root,str(target)),(target,'explicit'))
            doc=json.loads((root/env.RECORD).read_text());doc['python']=str(root/'missing-python')
            (root/env.RECORD).write_text(json.dumps(doc))
            with self.assertRaises(FileNotFoundError):env.resolve_python(root)
            self.assertEqual(env.resolve_python(root,str(target))[1],'explicit')

    def test_moved_checkout_and_local_precedence(self):
        with tempfile.TemporaryDirectory() as temp:
            root=Path(temp).resolve()
            local=root/'.venv'/('Scripts/python.exe' if os.name=='nt' else 'bin/python')
            local.parent.mkdir(parents=True);local.touch()
            self.assertEqual(env.resolve_python(root),(local,'project'))
            env.save(root,Path(sys.executable),{'version':[3,11,0],'prefix':'old'})
            doc=json.loads((root/env.RECORD).read_text());doc['repository_root']='another checkout'
            (root/env.RECORD).write_text(json.dumps(doc))
            with self.assertRaises(ValueError):env.resolve_python(root)

    def test_probe_and_launcher_use_explicit_interpreter_and_current_checkout(self):
        probe=env.diagnose(Path(sys.executable),ROOT,[])
        self.assertTrue(probe['ready'])
        self.assertEqual(Path(probe['python']),Path(sys.executable))
        self.assertTrue(Path(probe['package_file']).is_relative_to(ROOT/'src'))
        result=subprocess.run([sys.executable,'-I',str(ROOT/'scripts/python_env.py'),'run',
            '--python',sys.executable,'--extras','core','--command','sm-benchmark-prepare','--','--help'],
            cwd=ROOT.parent,capture_output=True,text=True)
        self.assertEqual(result.returncode,0,result.stderr)
        self.assertIn('--context-plan',result.stdout)
