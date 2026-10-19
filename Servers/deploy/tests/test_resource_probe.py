"""One systemctl query must still validate every configured and live cgroup cap."""
import importlib.util
from pathlib import Path
import subprocess
import tempfile
import unittest
from unittest.mock import patch

spec = importlib.util.spec_from_file_location('resource_probe', Path(__file__).resolve().parents[1] / 'scripts/check-resources.py')
probe = importlib.util.module_from_spec(spec)
spec.loader.exec_module(probe)


class ResourceProbeTests(unittest.TestCase):
    def test_all_units_checked_with_one_systemctl_call(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            (root / 'old.service').mkdir()
            (root / 'old.service/memory.max').write_text(str(64 * 1048576))
            snapshot = f'Id=old.service\nSlice=aiproxy.slice\nMemoryMax={64 * 1048576}\nControlGroup=/old.service\n\nId=inactive.service\nSlice=aiproxy.slice\nMemoryMax={8 * 1048576}\nControlGroup=\n'
            with patch.object(probe.subprocess, 'run', return_value=subprocess.CompletedProcess([], 0, snapshot)) as run:
                result = probe.verify([{'name': 'old.service', 'memory_mb': 64},
                                       {'name': 'inactive.service', 'memory_mb': 8}], cgroup_root=root)
                self.assertEqual(result, {'verified': 2, 'reloaded': False})
                run.assert_called_once()
                (root / 'old.service/memory.max').write_text('max')
                with self.assertRaises(ValueError):
                    probe.verify([{'name': 'old.service', 'memory_mb': 64}], cgroup_root=root)

    def test_missing_unit_or_incorrect_configured_limit_fails(self):
        for snapshot in ('', 'Id=test.service\nSlice=wrong.slice\nMemoryMax=1\nControlGroup=\n'):
            with patch.object(probe.subprocess, 'run', return_value=subprocess.CompletedProcess([], 0, snapshot)):
                with self.assertRaises(ValueError):
                    probe.verify([{'name': 'test.service', 'memory_mb': 64}])

    def test_interrupted_unit_update_is_recovered_before_validation(self):
        old = 'Id=test.service\nMemoryMax=1\nNeedDaemonReload=yes\n'
        new = f'Id=test.service\nSlice=aiproxy.slice\nMemoryMax={64 * 1048576}\nControlGroup=\nNeedDaemonReload=no\n'
        responses = [subprocess.CompletedProcess([], 0, old), subprocess.CompletedProcess([], 0, ''),
                     subprocess.CompletedProcess([], 0, new)]
        with patch.object(probe.subprocess, 'run', side_effect=responses) as run:
            self.assertEqual(probe.verify([{'name': 'test.service', 'memory_mb': 64}]), {'verified': 1, 'reloaded': True})
            self.assertEqual(run.call_args_list[1].args[0], ['systemctl', 'daemon-reload'])
