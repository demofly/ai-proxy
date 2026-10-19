"""Exercise the real port preflight before any service configuration is written."""
import copy
import os
from pathlib import Path
import shutil
import subprocess
import tempfile
import unittest

import yaml

DEPLOY = Path(__file__).resolve().parents[1]


@unittest.skipUnless(shutil.which('ansible-playbook'), 'requires ansible-playbook')
class ProxyPortTests(unittest.TestCase):
    def validate(self, overrides, accepted=True, tags=None):
        values = dict(proxy_role='access', proxy_port=443, nginx_on_443=True,
                      mtproxy_enabled=True, squid_transit_tls=True)
        values.update(overrides)
        with tempfile.TemporaryDirectory() as directory:
            tmp = Path(directory)
            source = yaml.safe_load((DEPLOY / 'playbook.yml').read_text(encoding='utf-8'))[0]
            include = copy.deepcopy(next(t for t in source['pre_tasks']
                                         if t.get('name') == 'Проверить согласованность портов прокси'))
            include['ansible.builtin.include_tasks']['file'] = str(DEPLOY / 'tasks/ports.yml')
            play = [{'hosts': 'localhost', 'connection': 'local', 'gather_facts': False,
                     'vars': values, 'tasks': [
                         include,
                         {'ansible.builtin.copy': {'content': 'validated', 'dest': str(tmp / 'applied')}}]}]
            (tmp / 'test.yml').write_text(yaml.safe_dump(play, allow_unicode=True), encoding='utf-8')
            command = ['ansible-playbook', '-i', 'localhost,', str(tmp / 'test.yml')]
            if tags:
                command += ['--tags', tags]
            result = subprocess.run(command,
                                    env=dict(os.environ, ANSIBLE_NOCOLOR='1'), capture_output=True,
                                    text=True, timeout=30)
            self.assertEqual(result.returncode == 0, accepted, result.stdout + result.stderr)
            self.assertEqual((tmp / 'applied').exists(), accepted)

    def test_custom_local_ports_and_squid_only_router_are_valid(self):
        self.validate({'squid_local_port': 3228, 'squid_mgmt_port': 3229})
        self.validate({'proxy_role': 'upstream', 'mtproxy_enabled': False, 'behind_nginx': True})

    def test_direct_squid_allows_a_different_public_port(self):
        self.validate({'nginx_on_443': False, 'behind_nginx': False,
                       'mtproxy_enabled': False, 'proxy_port': 8443})

    def test_preflight_also_runs_during_tagged_deployment(self):
        self.validate({'proxy_port': 8080}, accepted=False, tags='nginx')

    def test_conflicting_or_malformed_ports_stop_before_apply(self):
        for overrides in ({'proxy_port': 8080}, {'proxy_port': 'invalid'},
                          {'squid_local_port': 3129}, {'squid_mgmt_port': 'invalid'},
                          {'squid_local_port': 65536}, {'behind_nginx': False},
                          {'proxy_role': 'upstream', 'squid_tls_term_port': 4443}):
            with self.subTest(overrides=overrides):
                self.validate(overrides, accepted=False)

    def test_squid_only_upstream_runs_router_without_telegram_configuration(self):
        source = yaml.safe_load((DEPLOY / 'playbook.yml').read_text(encoding='utf-8'))[0]
        include = next(t for t in source['tasks'] if t.get('ansible.builtin.include_role', {}).get('name') == 'mtproxy')
        role_tasks = yaml.safe_load((DEPLOY / 'roles/mtproxy/tasks/main.yml').read_text(encoding='utf-8'))
        names = {'Ограничить доступ к приватному TLS-ключу',
                 'Разместить потоковую конфигурацию TLS-терминатора MTProxy',
                 'Разместить запись MTProxy в карте SNI',
                 'Разместить потоковую конфигурацию TLS-терминатора Squid',
                 'Разместить запись Squid в карте SNI',
                 'Настроить демон MTProxy при включённом Telegram-тракте'}
        tasks = [t for t in role_tasks if t['name'] in names]
        with tempfile.TemporaryDirectory() as directory:
            tmp = Path(directory)
            role = tmp / 'roles/mtproxy'
            (role / 'tasks').mkdir(parents=True)
            (role / 'handlers').mkdir()
            (role / 'handlers/main.yml').write_text(yaml.safe_dump([{
                'name': 'Перечитать конфигурацию nginx для MTProxy',
                'ansible.builtin.debug': {'msg': 'isolated router fixture'}}], allow_unicode=True), encoding='utf-8')
            shutil.copytree(DEPLOY / 'roles/mtproxy/templates', role / 'templates')
            for task in tasks:
                for module in ('ansible.builtin.template', 'ansible.builtin.file'):
                    if module in task:
                        key = 'dest' if module.endswith('template') else 'path'
                        task[module][key] = str(tmp / Path(task[module][key]).name)
            (role / 'tasks/main.yml').write_text(yaml.safe_dump(tasks, allow_unicode=True), encoding='utf-8')
            (role / 'tasks/daemon.yml').write_text('- ansible.builtin.fail: {msg: "Telegram daemon must not run"}\n')
            inventory = {'all': {'children': {
                'upstreams': {'hosts': {'localhost': {'ansible_connection': 'local'}}},
                'access_proxies': {'hosts': {'access-test': {'ansible_host': '192.0.2.10'}}}}}}
            (tmp / 'inventory.yml').write_text(yaml.safe_dump(inventory))
            play = [{'hosts': 'localhost', 'gather_facts': False, 'vars': {
                'proxy_role': 'upstream', 'nginx_on_443': True, 'mtproxy_enabled': False,
                'squid_transit_tls': True, 'squid_tls_sni': 'transit.internal'}, 'tasks': [include]}]
            (tmp / 'test.yml').write_text(yaml.safe_dump(play, allow_unicode=True), encoding='utf-8')
            result = subprocess.run(['ansible-playbook', '-i', str(tmp / 'inventory.yml'), str(tmp / 'test.yml')],
                                    env=dict(os.environ, ANSIBLE_FILTER_PLUGINS=str(DEPLOY / 'filter_plugins')),
                                    capture_output=True, text=True, timeout=30)
            self.assertEqual(result.returncode, 0, result.stdout + result.stderr)
            self.assertIn('TLSv1.3', (tmp / '20-squid-tls-term.conf').read_text())
            self.assertIn('transit.internal', (tmp / 'squid.conf').read_text())
            self.assertFalse((tmp / '10-mtproxy-tls.conf').exists())
            self.assertFalse((tmp / 'mtproxy.conf').exists())


if __name__ == '__main__':
    unittest.main()
