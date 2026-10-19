"""The daemon reuses cluster/explicit secrets and keeps standalone migration."""
import copy
import os
from pathlib import Path
import shutil
import subprocess
import tempfile
import unittest

import yaml

DEPLOY = Path(__file__).resolve().parents[1]
A = 'ee' + '11' * 16 + '6d61782e7275'
B = 'ee' + '22' * 16 + '6d61782e7275'


@unittest.skipUnless(shutil.which('ansible-playbook'), 'requires ansible-playbook')
class MTProxySecretReadsTests(unittest.TestCase):
    def test_cluster_explicit_and_standalone_modes(self):
        source = yaml.safe_load((DEPLOY / 'roles/mtproxy/tasks/daemon.yml').read_text())
        start = next(i for i, t in enumerate(source) if t['name'] == 'Проверить наличие конфигурации mtg в формате TOML')
        end = next(i for i, t in enumerate(source) if t['name'] == 'Разместить конфигурацию mtg в формате TOML v2')
        with tempfile.TemporaryDirectory(prefix='aiproxy-secret-reads-') as directory:
            root = Path(directory)
            fake = root / 'mtg'
            fake.write_text(f'#!/bin/sh\necho generated >> "{root / "calls"}"\nprintf "%s\\n" "{A}"\n')
            fake.chmod(0o755)
            for case in ('cluster', 'explicit', 'toml', 'env', 'fresh'):
                with self.subTest(case=case):
                    config = root / case
                    config.mkdir()
                    if case in ('cluster', 'explicit', 'toml'):
                        (config / 'mtg.toml').write_text(f'secret = "{B}"\n')
                    if case == 'env':
                        (config / 'mtg.env').write_text(f'MTG_SECRET={B}\n')
                    tasks = copy.deepcopy(source[start:end])
                    tasks = yaml.safe_load(yaml.safe_dump(tasks, allow_unicode=True).replace(
                        '/etc/mtproxy', str(config)).replace('/usr/local/bin/mtg', str(fake)))
                    expected = A if case in ('cluster', 'explicit', 'fresh') else B
                    checks = ['mtproxy_secret_resolved == expected']
                    if case in ('cluster', 'explicit'):
                        checks += ['mtg_toml_file.skipped', 'mtg_env_file.skipped']
                    tasks.append({'ansible.builtin.assert': {'that': checks, 'quiet': True}})
                    hosts = {'ansible_connection': 'local'}
                    if case == 'cluster':
                        hosts['_mtproxy_cluster_secret'] = A
                    (root / 'inventory.yml').write_text(yaml.safe_dump({'all': {'hosts': {'localhost': hosts}}}))
                    play = [{'hosts': 'localhost', 'gather_facts': False, 'vars': {
                        'mtproxy_secret': A if case == 'explicit' else '',
                        'mtproxy_fake_tls_domain': 'max.ru', 'expected': expected}, 'tasks': tasks}]
                    (root / 'test.yml').write_text(yaml.safe_dump(play, allow_unicode=True))
                    result = subprocess.run(['ansible-playbook', '-i', str(root / 'inventory.yml'), str(root / 'test.yml')],
                                            env=dict(os.environ, ANSIBLE_NOCOLOR='1'),
                                            capture_output=True, text=True, timeout=30)
                    self.assertEqual(result.returncode, 0, result.stdout + result.stderr)
            self.assertEqual((root / 'calls').read_text().splitlines(), ['generated'])
