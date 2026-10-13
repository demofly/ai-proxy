import importlib.util
from pathlib import Path
import unittest
from unittest.mock import patch
import subprocess
import tempfile

ROOT = Path(__file__).resolve().parents[1]
spec = importlib.util.spec_from_file_location('shared_ports', ROOT / 'scripts/apply-shared-ports.py')
ports = importlib.util.module_from_spec(spec)
spec.loader.exec_module(ports)


class SharedPortsTests(unittest.TestCase):
    def setUp(self):
        self.contract = ports.validate_contract({'tcp': [443, 7881], 'udp': [3478],
                                                'udp_ranges': [{'start': 55000, 'end': 60000}]})

    def test_rejects_shell_injection_and_invalid_ranges(self):
        for data in ({'tcp': ['443; flush ruleset']}, {'tcp': [True]},
                     {'udp_ranges': [{'start': 60000, 'end': 55000}]}):
            with self.subTest(data=data), self.assertRaises(ValueError):
                ports.validate_contract(data)

    def test_both_backends_open_media_ports_without_flushing_the_host(self):
        nft = '\n'.join(ports.nft_rules(self.contract))
        ipt = ports.iptables_rules(self.contract)
        self.assertIn('7881', nft)
        self.assertIn('55000-60000', nft)
        self.assertIn('55000:60000', ipt)
        self.assertNotIn(':INPUT', ipt)
        self.assertNotIn('flush ruleset', nft)

    def test_nft_updates_the_actual_owner_chain_and_persists(self):
        calls = []
        def fake_run(argv, text=None, required=True):
            calls.append((argv, text))
            if argv[:3] == ['nft', '-j', 'list']:
                return subprocess.CompletedProcess(argv, 0, '{"nftables": []}', '')
            return subprocess.CompletedProcess(argv, 0, 'chain matrix_services {}', '')
        with tempfile.TemporaryDirectory() as d, patch.object(ports, 'ROOT', Path(d)), patch.object(ports, 'run', fake_run):
            self.assertTrue(ports.apply(self.contract, 'nftables'))
            saved = (Path(d) / 'matrix-ports.nft').read_text()
            self.assertIn('55000-60000', saved)
        batches = [text for argv, text in calls if argv == ['nft', '-f', '-']]
        self.assertIn('insert rule inet filter input jump matrix_services', batches[0])
        self.assertNotIn('flush table', batches[0])

    def test_existing_nft_jump_is_not_duplicated(self):
        calls = []
        def fake_run(argv, text=None, required=True):
            calls.append((argv, text))
            out = '{"nftables": [{"rule": {"expr": [{"jump": {"target": "matrix_services"}}]}}]}' if '-j' in argv else 'chain matrix_services {}'
            return subprocess.CompletedProcess(argv, 0, out, '')
        with tempfile.TemporaryDirectory() as d, patch.object(ports, 'ROOT', Path(d)), patch.object(ports, 'run', fake_run):
            ports.apply(self.contract, 'nftables')
            ports.apply(self.contract, 'nftables')
        self.assertFalse(any(text and 'insert rule' in text for _, text in calls))


if __name__ == '__main__':
    unittest.main()
