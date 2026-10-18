"""Render the real transport configuration with native Ansible and legacy inventory."""
import copy
import os
from pathlib import Path
import shutil
import subprocess
import tempfile
import unittest

import yaml

ROOT = Path(__file__).resolve().parents[1]


@unittest.skipUnless(shutil.which('ansible-playbook'), 'requires ansible-playbook')
class ProxyTransitTests(unittest.TestCase):
    def render(self, overrides=None, rejected=False):
        source = yaml.safe_load((ROOT / 'playbook.yml').read_text(encoding='utf-8'))[0]
        defaults = next(task for task in source['pre_tasks']
                        if 'squid_transit_tls' in task.get('ansible.builtin.set_fact', {}))
        validation = next(task for task in source['pre_tasks']
                          if task['name'] == 'Проверить наличие имени TLS-участка')
        package = next(task['ansible.builtin.package']['name'] for task in source['tasks']
                       if task['name'] == 'Установить Squid')
        with tempfile.TemporaryDirectory() as directory:
            tmp = Path(directory)
            inventory = {'all': {'hosts': {'localhost': {'ansible_connection': 'local'}},
                                'children': {
                                    'access_proxies': {'hosts': {'access-test': {'ansible_host': '192.0.2.10'}}},
                                    'upstreams': {'hosts': {'upstream-test': {
                                        'ansible_host': '198.51.100.20', 'proxy_port': 443,
                                        'mtproxy_enabled': True},
                                        'upstream-two': {'ansible_host': '198.51.100.21',
                                                         'proxy_port': 443, 'mtproxy_enabled': True}}}}}}
            (tmp / 'inventory.yml').write_text(yaml.safe_dump(inventory), encoding='utf-8')
            values = dict(enable_caching=False, enable_logging=False, enable_auth=True,
                          nginx_on_443=True, proxy_port=443, squid_workers=1,
                          proxy_role='access', ansible_os_family='Debian', _squid_version_raw={'stdout': '--with-gnutls'})
            values.update(overrides or {})
            pool = [task for task in source['pre_tasks'] if task['name'] in (
                'Определить пул upstream для Squid на access', 'Проверить состав пула upstream для Squid')]
            tasks = copy.deepcopy([defaults, validation] + pool)
            tasks.append({'name': 'Определить пакет Squid по настройкам участка', 'ansible.builtin.copy': {
                'content': package, 'dest': str(tmp / 'package.conf')}})
            for name, template, conditional in (
                ('access', 'templates/squid-access.conf.j2', False),
                ('upstream', 'templates/squid-upstream.conf.j2', False),
                ('terminator', 'roles/mtproxy/templates/nginx-squid-tls-term.conf.j2', True),
                ('sni', 'roles/mtproxy/templates/sni-map.d/squid.conf.j2', True),
            ):
                task = {'name': 'Render ' + name, 'ansible.builtin.template': {
                    'src': str(ROOT / template), 'dest': str(tmp / (name + '.conf'))}}
                if conditional:
                    task['when'] = 'squid_transit_tls | bool'
                tasks.append(task)
            play = [{'name': 'Transport regression', 'hosts': 'localhost', 'gather_facts': False,
                     'become': False, 'vars': values, 'tasks': tasks}]
            (tmp / 'test.yml').write_text(yaml.safe_dump(play, allow_unicode=True), encoding='utf-8')
            env = dict(os.environ, ANSIBLE_FILTER_PLUGINS=str(ROOT / 'filter_plugins'),
                       ANSIBLE_STDOUT_CALLBACK='default', ANSIBLE_NOCOLOR='1')
            result = subprocess.run(['ansible-playbook', '-i', str(tmp / 'inventory.yml'), str(tmp / 'test.yml')],
                                    env=env, capture_output=True, text=True, timeout=60)
            if rejected:
                self.assertNotEqual(result.returncode, 0, result.stdout)
                self.assertIn(rejected if isinstance(rejected, str) else 'Шифрование участка включено', result.stdout)
                self.assertFalse(list(tmp.glob('*.conf')))
                return None
            self.assertEqual(result.returncode, 0, result.stdout + result.stderr)
            return {p.stem: p.read_text(encoding='utf-8') for p in tmp.glob('*.conf')}

    def assert_encrypted(self, rendered, name):
        self.assertEqual(rendered['package'].strip(), 'squid-openssl')
        peer = next(line for line in rendered['access'].splitlines() if line.startswith('cache_peer '))
        self.assertIn(' tls tls-no-default-ca tls-cafile=', peer)
        self.assertIn(' tls-domain=' + name, peer)
        self.assertIn('acl access_proxy src 127.0.0.1/32', rendered['upstream'])
        self.assertIn(name + '  squid_tls_term;', rendered['sni'])
        self.assertIn('proxy_protocol on;', rendered['terminator'])
        self.assertNotIn('\n    set_real_ip_from ', rendered['terminator'])

    def test_explicit_true_encrypts_and_preserves_anonymous_peer(self):
        self.assert_encrypted(self.render({'squid_transit_tls': True}), 'transit.internal')

    def test_custom_transit_name_is_used_for_verification_and_routing(self):
        self.assert_encrypted(self.render({'squid_transit_tls': True, 'squid_tls_sni': 'proxy-transit.test'}), 'proxy-transit.test')

    def assert_plain(self, rendered):
        peer = next(line for line in rendered['access'].splitlines() if line.startswith('cache_peer '))
        self.assertNotIn(' tls ', peer)
        self.assertNotIn('acl access_proxy src 127.0.0.1/32', rendered['upstream'])
        self.assertNotIn('terminator', rendered)
        self.assertNotIn('sni', rendered)

    def test_legacy_inventory_keeps_plain_transport(self):
        rendered = self.render()
        self.assert_plain(rendered)
        self.assertEqual(rendered['package'].strip(), 'squid')

    def test_explicit_false_keeps_plain_transport(self):
        self.assert_plain(self.render({'squid_transit_tls': False}))

    def test_disabling_tls_preserves_installed_openssl_package(self):
        rendered = self.render({'squid_transit_tls': False,
                                '_squid_version_raw': {'stdout': '--with-openssl'}})
        self.assert_plain(rendered)
        self.assertEqual(rendered['package'].strip(), 'squid-openssl')

    def test_access_can_exclude_an_unhealthy_peer_without_changing_other_nodes(self):
        selected = self.render({'squid_transit_tls': True, 'squid_upstream_hosts': ['upstream-two']})
        peers = [line for line in selected['access'].splitlines() if line.startswith('cache_peer ')]
        self.assertEqual(len(peers), 1)
        self.assertIn('198.51.100.21 parent ', peers[0])
        self.assertNotIn('198.51.100.20 parent ', selected['access'])
        defaults = self.render()
        self.assertEqual(sum(line.startswith('cache_peer ') for line in defaults['access'].splitlines()), 2)

    def test_empty_or_unknown_parent_pool_fails_before_rendering(self):
        for pool in ([], ['unknown-upstream'], 'upstream-two', ['upstream-two', 'upstream-two']):
            with self.subTest(pool=pool):
                self.render({'squid_upstream_hosts': pool}, rejected='squid_upstream_hosts должен')

    def test_empty_name_fails_before_rendering_configuration(self):
        self.render({'squid_transit_tls': True, 'squid_tls_sni': ''}, rejected=True)


if __name__ == '__main__':
    unittest.main()
