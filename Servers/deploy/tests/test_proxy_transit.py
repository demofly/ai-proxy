# [AITS] 2026-11-06T15:50:29Z
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
    def render(self, overrides=None, rejected=False, upstream_overrides=None):
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
            for host in inventory['all']['children']['upstreams']['hosts'].values():
                host.update(upstream_overrides or {})
            (tmp / 'inventory.yml').write_text(yaml.safe_dump(inventory), encoding='utf-8')
            values = dict(enable_caching=False, enable_logging=False, enable_auth=True,
                          nginx_on_443=True, proxy_port=443, squid_workers=1,
                          proxy_role='access', ansible_os_family='Debian', _squid_version_raw={'stdout': '--with-gnutls'})
            values.update(overrides or {})
            # AI-GENERATED — NOT REVIEWED: SECTION START
            pool = [task for task in source['pre_tasks'] if task['name'] in (
                'Проверить отсутствие упразднённого перечня upstream для Squid',
                'Определить пулы upstream для Squid на access',
                'Показать состав пулов upstream для Squid')]
            self.assertEqual(len(pool), 3)
            # AI-GENERATED — NOT REVIEWED: SECTION END
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

    def test_direct_tls_parent_uses_its_configured_public_port(self):
        rendered = self.render({'squid_transit_tls': True}, upstream_overrides={
            'proxy_port': 8443, 'mtproxy_enabled': False, 'behind_nginx': False})
        peers = [line for line in rendered['access'].splitlines() if line.startswith('cache_peer ')]
        self.assertTrue(all(' parent 8443 0 ' in line and ' tls ' in line for line in peers))

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

    # AI-GENERATED — NOT REVIEWED: SECTION START
    @staticmethod
    def lines(rendered, prefix):
        return [line for line in rendered['access'].splitlines() if line.startswith(prefix)]

    def test_pool_with_only_second_upstream_renders_one_peer_with_access_rule(self):
        selected = self.render({'squid_transit_tls': True,
                                'proxy_pools': [{'name': 'solo', 'groups': ['all'], 'upstreams': ['upstream-two']}]})
        peers = self.lines(selected, 'cache_peer ')
        self.assertEqual(len(peers), 1)
        self.assertIn('198.51.100.21 parent ', peers[0])
        self.assertNotIn('198.51.100.20 parent ', selected['access'])
        self.assertEqual(self.lines(selected, 'cache_peer_access '),
                         ['cache_peer_access upstream-two allow aiproxy_pool_solo',
                          'cache_peer_access upstream-two deny all'])
        defaults = self.render()
        self.assertEqual(len(self.lines(defaults, 'cache_peer ')), 2)

    def test_default_pools_route_everyone_to_all_upstreams(self):
        access = self.render()['access']
        self.assertIn('acl aiproxy_pool_default proxy_auth REQUIRED', access)
        self.assertIn('http_access deny authenticated !aiproxy_routed all', access)
        self.assertNotIn('aiproxy_pool_reserve', access)

    def test_user_outside_every_pool_gets_explicit_denial(self):
        rendered = self.render({'proxy_user_groups': {'team': ['alice']},
                                'proxy_pools': [{'name': 'only', 'groups': ['team'], 'upstreams': 'all'}]})['access']
        self.assertIn('acl aiproxy_pool_only proxy_auth alice', rendered)
        self.assertIn('acl aiproxy_routed proxy_auth alice', rendered)
        self.assertIn('http_access deny authenticated !aiproxy_routed all', rendered)
        self.assertLess(rendered.index('!aiproxy_routed all'), rendered.index('http_access allow authenticated'))

    def test_pool_without_upstreams_generates_no_peer_access(self):
        rendered = self.render({'proxy_user_groups': {'team': ['alice'], 'idle': ['bob']},
                                'proxy_pools': [{'name': 'live', 'groups': ['team'], 'upstreams': ['upstream-test']},
                                                {'name': 'empty', 'groups': ['idle'], 'upstreams': []}]})['access']
        self.assertNotIn('aiproxy_pool_empty', rendered)
        self.assertNotIn('bob', rendered)
        self.assertIn('cache_peer_access upstream-test allow aiproxy_pool_live', rendered)
        self.assertNotIn('upstream-two', rendered)

    def test_no_active_pool_denies_everything_before_allow_rules(self):
        rendered = self.render({'proxy_pools': [{'name': 'empty', 'groups': [], 'upstreams': []}]})['access']
        self.assertNotIn('aiproxy_routed', rendered)
        self.assertNotIn('cache_peer ', rendered)
        self.assertLess(rendered.index('http_access deny all'), rendered.index('http_access allow authenticated'))

    def test_without_auth_pools_generate_no_acl(self):
        rendered = self.render({'enable_auth': False})['access']
        self.assertNotIn('proxy_auth', rendered)
        self.assertNotIn('cache_peer_access', rendered)
        self.assertEqual(len([x for x in rendered.splitlines() if x.startswith('cache_peer ')]), 2)

    def test_long_user_list_is_split_into_same_name_acl_lines(self):
        users = ['user%02d' % number for number in range(45)]
        rendered = self.render({'proxy_user_groups': {'big': users},
                                'proxy_pools': [{'name': 'big', 'groups': ['big'], 'upstreams': 'all'}]})['access']
        self.assertEqual(rendered.count('acl aiproxy_pool_big proxy_auth '), 3)

    def test_removed_upstream_list_fails_with_migration_message(self):
        self.render({'squid_upstream_hosts': ['upstream-two']}, rejected='перенесён в proxy_pools')

    def test_pool_model_error_fails_before_rendering(self):
        cases = ({'proxy_pools': [{'name': 'bad', 'groups': ['nobody'], 'upstreams': 'all'}]},
                 {'proxy_pools': [{'name': 'bad', 'groups': [], 'upstreams': ['unknown-upstream']}]},
                 {'proxy_pools': 'default'})
        for values in cases:
            with self.subTest(values=values):
                self.render(values, rejected='Пул' if 'proxy_pools' in values and isinstance(values['proxy_pools'], list)
                            else 'proxy_pools должен')

    def test_pool_without_users_never_gets_acl_or_peer_access(self):
        # Пул с upstream, но без пользователей: acl не выпускается, значит и cache_peer_access
        # на него запрещён — иначе Squid не стартует («ACL not found»).
        rendered = self.render({'proxy_user_groups': {'empty': []},
                                'proxy_pools': [{'name': 'spare', 'groups': [], 'upstreams': 'all'},
                                                {'name': 'gz', 'groups': ['empty'], 'upstreams': 'all'}]})['access']
        self.assertNotIn('aiproxy_pool_', rendered)
        self.assertNotIn('cache_peer_access', rendered)

    def test_shared_upstream_lists_every_active_pool_then_denies_the_rest(self):
        rendered = self.render({'proxy_user_groups': {'team': ['alice'], 'other': ['bob']},
                                'proxy_pools': [
                                    {'name': 'p1', 'groups': ['team'], 'upstreams': ['upstream-test', 'upstream-two']},
                                    {'name': 'p2', 'groups': ['other'], 'upstreams': ['upstream-two']}]})
        self.assertEqual(self.lines(rendered, 'cache_peer_access '), [
            'cache_peer_access upstream-test allow aiproxy_pool_p1',
            'cache_peer_access upstream-test deny all',
            'cache_peer_access upstream-two allow aiproxy_pool_p1',
            'cache_peer_access upstream-two allow aiproxy_pool_p2',
            'cache_peer_access upstream-two deny all'])

    def test_routed_acl_is_the_union_of_users_of_all_active_pools(self):
        rendered = self.render({'proxy_user_groups': {'team': ['alice', 'carol'], 'other': ['bob', 'carol']},
                                'proxy_pools': [
                                    {'name': 'p1', 'groups': ['team'], 'upstreams': ['upstream-test']},
                                    {'name': 'p2', 'groups': ['other'], 'upstreams': ['upstream-two']}]})
        self.assertEqual(self.lines(rendered, 'acl aiproxy_routed '),
                         ['acl aiproxy_routed proxy_auth alice bob carol'])

    def test_direct_fallback_keeps_connect_on_peers_and_pools(self):
        # Без nonhierarchical_direct off Squid отправляет CONNECT напрямую в обход пиров и пулов.
        fallback = self.render({'allow_direct_fallback': True})['access']
        self.assertIn('\nnonhierarchical_direct off\n', fallback)
        self.assertIn('\nprefer_direct off\n', fallback)
        self.assertNotIn('never_direct allow all', fallback)
        strict = self.render()['access']
        self.assertIn('never_direct allow all', strict)
        self.assertNotIn('nonhierarchical_direct', strict)

    def run_group_user_check(self, passwd_text, groups):
        """Прогоняет задачу playbook.yml «пользователи групп есть в файле паролей» на синтетических данных."""
        source = yaml.safe_load((ROOT / 'playbook.yml').read_text(encoding='utf-8'))[0]
        # AI-GENERATED — NOT REVIEWED: SECTION START
        # Проверка стоит в pre_tasks: отказ раньше первой задачи, меняющей узел, при любом наборе тегов.
        names = [task['name'] for task in source['pre_tasks']]
        check_index = names.index('Проверить, что пользователи групп есть в файле паролей')
        self.assertLess(check_index, names.index('Определить домен fake-TLS MTProxy с учётом inventory'))
        check = copy.deepcopy(source['pre_tasks'][check_index])
        self.assertIn('always', check['tags'])
        # AI-GENERATED — NOT REVIEWED: SECTION END
        self.assertNotIn('run_once', check)  # run_once берёт условие по первому узлу игры
        import base64
        content = base64.b64encode(passwd_text.encode()).decode()
        play = [{'name': 'Group users check', 'hosts': 'localhost', 'gather_facts': False, 'become': False,
                 'vars': {'proxy_role': 'access', 'enable_auth': True, 'proxy_user_groups': groups,
                          '_passwd_local': {'content': content}},
                 'tasks': [check]}]
        with tempfile.TemporaryDirectory() as directory:
            tmp = Path(directory)
            (tmp / 'inventory.yml').write_text(yaml.safe_dump(
                {'all': {'hosts': {'localhost': {'ansible_connection': 'local'}}}}), encoding='utf-8')
            (tmp / 'test.yml').write_text(yaml.safe_dump(play, allow_unicode=True), encoding='utf-8')
            env = dict(os.environ, ANSIBLE_FILTER_PLUGINS=str(ROOT / 'filter_plugins'),
                       ANSIBLE_STDOUT_CALLBACK='default', ANSIBLE_NOCOLOR='1')
            return subprocess.run(['ansible-playbook', '-i', str(tmp / 'inventory.yml'), str(tmp / 'test.yml')],
                                  env=env, capture_output=True, text=True, timeout=60)

    def test_group_users_present_in_password_file_pass(self):
        result = self.run_group_user_check('alice:x\n# bob:x\ncarol:y\n', {'a': ['alice'], 'b': ['carol']})
        self.assertEqual(result.returncode, 0, result.stdout + result.stderr)
        self.assertIn('Все пользователи групп есть в файле паролей', result.stdout)

    def test_group_users_missing_from_password_file_fail_naming_them(self):
        result = self.run_group_user_check('alice:x\n# bob:x\n', {'a': ['alice', 'bob', 'zed']})
        self.assertNotEqual(result.returncode, 0)
        self.assertIn('нет записей для пользователей из proxy_user_groups: bob, zed.',
                      ' '.join(result.stdout.split()))
    # AI-GENERATED — NOT REVIEWED: SECTION END

    def test_empty_name_fails_before_rendering_configuration(self):
        self.render({'squid_transit_tls': True, 'squid_tls_sni': ''}, rejected=True)


if __name__ == '__main__':
    unittest.main()
