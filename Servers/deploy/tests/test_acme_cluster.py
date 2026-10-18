"""HTTP-01 on either frontend, simultaneous tokens and bounded peer forwarding."""
import copy
from concurrent.futures import ThreadPoolExecutor
import http.client
import importlib.util
import json
import os
from pathlib import Path
import shutil
import socket
import subprocess
import tempfile
import time
import unittest

import yaml

ROOT = Path(__file__).resolve().parents[1]
spec = importlib.util.spec_from_file_location('acme', ROOT / 'filter_plugins/acme.py')
acme = importlib.util.module_from_spec(spec)
spec.loader.exec_module(acme)


class AcmeClusterTests(unittest.TestCase):
    def setUp(self):
        self.nodes = {'one': {'https_proxy_enabled': True, 'https_proxy_acme_enabled': True,
                             'https_proxy_hostname': 'proxy.example.test', 'ansible_host': '192.0.2.10'},
                      'two': {'https_proxy_enabled': True, 'https_proxy_acme_enabled': True,
                             'https_proxy_hostname': 'PROXY.EXAMPLE.TEST', 'ansible_host': '192.0.2.11'}}

    def test_two_nodes_and_single_node(self):
        plan = acme.https_proxy_acme_cluster(list(self.nodes), self.nodes, 'one')
        self.assertEqual(plan['error'], '')
        self.assertEqual(plan['nodes'], ['one', 'two'])
        self.assertEqual(plan['peers'], [{'name': 'two', 'address': '192.0.2.11', 'endpoint': '192.0.2.11:80'}])
        self.assertEqual(acme.https_proxy_acme_cluster(['one'], self.nodes, 'one')['peers'], [])

    def test_disabled_and_different_hostname_are_not_peers(self):
        for change in ({'https_proxy_enabled': False}, {'https_proxy_hostname': 'other.example.test'}):
            with self.subTest(change=change):
                nodes = copy.deepcopy(self.nodes)
                nodes['two'].update(change)
                self.assertEqual(acme.https_proxy_acme_cluster(list(nodes), nodes, 'one')['peers'], [])

    def test_ipv6_address_override_without_resolving_the_shared_hostname(self):
        self.nodes['two'].update(ansible_host='ssh.example.test', https_proxy_acme_address='2001:db8::2')
        plan = acme.https_proxy_acme_cluster(list(self.nodes), self.nodes, 'one')
        self.assertEqual(plan['error'], '')
        self.assertEqual(plan['peers'][0]['endpoint'], '[2001:db8::2]:80')

    def test_mixed_ownership_duplicate_ip_and_nonliteral_address_are_rejected(self):
        for change in ({'https_proxy_acme_enabled': False}, {'ansible_host': '192.0.2.10'},
                       {'ansible_host': 'shared.example.test'}, {'https_proxy_acme_address': 'x;bad'},
                       {'https_proxy_acme_address': 'fe80::1%eth0'}):
            with self.subTest(change=change):
                nodes = copy.deepcopy(self.nodes)
                nodes['two'].update(change)
                self.assertTrue(acme.https_proxy_acme_cluster(list(nodes), nodes, 'one')['error'])


@unittest.skipUnless(os.environ.get('AIPROXY_TEST_NGINX') and shutil.which('ansible-playbook'),
                     'set AIPROXY_TEST_NGINX for native HTTP-01 tests')
class NativeAcmeClusterTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.fixture = tempfile.TemporaryDirectory(prefix='aiproxy-acme-')
        cls.tmp = tmp = Path(cls.fixture.name)
        tmp.chmod(0o755)
        cls.processes = []
        cls.addClassCleanup(cls.cleanup)
        with socket.socket() as reservation:
            reservation.bind(('127.0.0.2', 0))
            cls.port = reservation.getsockname()[1]
        cls.addresses = {'one': '127.0.0.2', 'two': '127.0.0.3'}
        hosts = {}
        for name, address in cls.addresses.items():
            root = tmp / name / 'www'
            (root / '.well-known/acme-challenge').mkdir(parents=True)
            hosts[name] = {'ansible_host': address, 'ansible_connection': 'local',
                           'https_proxy_acme_webroot': str(root)}
        values = {'https_proxy_enabled': True, 'https_proxy_acme_enabled': True,
                  'https_proxy_hostname': 'proxy.example.test',
                  'https_proxy_acme_email': 'admin@example.test',
                  'enable_auth': True, 'proxy_role': 'access'}
        inventory = {'all': {'children': {'access_proxies': {'hosts': hosts, 'vars': values}}}}
        (tmp / 'inventory.yml').write_text(yaml.safe_dump(inventory))
        source = yaml.safe_load((ROOT / 'playbook.yml').read_text(encoding='utf-8'))[0]
        tasks = copy.deepcopy([task for task in source['pre_tasks'] if task['name'] in (
            'Проверить параметры клиентского HTTPS-прокси',
            'Проверить параметры выпуска сертификата HTTPS-прокси',
            'Определить участников ACME для общего HTTPS-имени', 'Проверить состав участников ACME')])
        tasks.append({'ansible.builtin.template': {
            'src': str(ROOT / 'roles/nginx/templates/aiproxy-https-acme.conf.j2'),
            'dest': str(tmp / '{{ inventory_hostname }}/site.conf')}})
        play = [{'hosts': 'access_proxies', 'gather_facts': False, 'strategy': 'linear',
                 'tasks': tasks}]
        (tmp / 'render.yml').write_text(yaml.safe_dump(play, allow_unicode=True), encoding='utf-8')
        result = subprocess.run(['ansible-playbook', '-i', str(tmp / 'inventory.yml'), str(tmp / 'render.yml')],
                                env=dict(os.environ, ANSIBLE_FILTER_PLUGINS=str(ROOT / 'filter_plugins')),
                                capture_output=True, text=True, timeout=45)
        if result.returncode:
            raise AssertionError(result.stdout + result.stderr)
        for name, address in cls.addresses.items():
            directory = tmp / name
            site = (directory / 'site.conf').read_text().replace(
                'listen 80;', f'listen {address}:{cls.port};').replace('    listen [::]:80;\n', '')
            for peer in cls.addresses.values():
                site = site.replace(peer + ':80;', peer + ':' + str(cls.port) + ';')
            config = directory / 'nginx.conf'
            config.write_text(f'pid {directory}/nginx.pid;\nerror_log {directory}/error.log;\n'
                              'worker_processes 1;\nevents { worker_connections 64; }\nhttp {\n'
                              'access_log off;\n'
                              f'client_body_temp_path {directory}/body;\n'
                              f'proxy_temp_path {directory}/proxy;\n'
                              f'fastcgi_temp_path {directory}/fastcgi;\n'
                              f'uwsgi_temp_path {directory}/uwsgi;\n'
                              f'scgi_temp_path {directory}/scgi;\n'
                              f'server {{ listen {address}:{cls.port} default_server; return 410; }}\n'
                              + site + '\n}\n')
            cmd = [os.environ['AIPROXY_TEST_NGINX'], '-p', str(directory), '-c', str(config)]
            parsed = subprocess.run(cmd + ['-t'], capture_output=True, text=True, timeout=10)
            if parsed.returncode:
                raise AssertionError(parsed.stderr)
            process = subprocess.Popen(cmd + ['-g', 'daemon off;'], stdout=subprocess.DEVNULL,
                                       stderr=subprocess.DEVNULL)
            cls.processes.append(process)
            for _ in range(100):
                if process.poll() is not None:
                    raise AssertionError((directory / 'error.log').read_text())
                if (directory / 'nginx.pid').exists():
                    time.sleep(.05)
                    break
                time.sleep(.02)
        cls.token('one', 'alpha').write_text('account-one-authorization')
        cls.token('two', 'beta').write_text('account-two-authorization')

    @classmethod
    def cleanup(cls):
        for process in cls.processes:
            if process.poll() is None:
                process.terminate()
            process.wait(timeout=10)
        cls.fixture.cleanup()

    @classmethod
    def token(cls, owner, name):
        return cls.tmp / owner / 'www/.well-known/acme-challenge' / name

    def request(self, node, token, method='GET', headers=None):
        connection = http.client.HTTPConnection(self.addresses[node], self.port, timeout=3)
        try:
            connection.request(method, '/.well-known/acme-challenge/' + token,
                               headers={'Host': 'proxy.example.test', **(headers or {})})
            response = connection.getresponse()
            return response.status, response.read(), response.getheader('Cache-Control')
        finally:
            connection.close()

    def test_simultaneous_authorizations_work_through_either_ip(self):
        cases = [(node, token) for node in self.addresses for token in ('alpha', 'beta')]
        with ThreadPoolExecutor(max_workers=4) as workers:
            results = list(workers.map(lambda case: self.request(*case), cases))
        for (_, token), (status, body, cache) in zip(cases, results):
            self.assertEqual(status, 200)
            self.assertEqual(body, b'account-one-authorization' if token == 'alpha' else b'account-two-authorization')
            self.assertEqual(cache, 'no-store')

    def test_missing_token_terminates_without_a_forwarding_loop(self):
        for node in self.addresses:
            self.assertEqual(self.request(node, 'missing')[0], 404)
        self.assertEqual(self.request('two', 'alpha', headers={'X-AIProxy-ACME-Hop': '1'})[0], 404)
        self.assertEqual(self.request('two', 'beta', headers={'X-AIProxy-ACME-Hop': '1'})[0], 200)

    def test_certbot_cleanup_is_visible_on_both_ips_without_negative_cache(self):
        path = self.token('one', 'alpha')
        path.unlink()
        try:
            for node in self.addresses:
                self.assertEqual(self.request(node, 'alpha')[0], 404)
        finally:
            path.write_text('account-one-authorization')
        self.assertEqual(self.request('two', 'alpha')[0], 200)

    def test_only_challenge_get_and_head_are_delegated(self):
        self.assertEqual(self.request('two', 'alpha', method='HEAD')[:2], (200, b''))
        self.assertEqual(self.request('two', 'alpha', method='POST')[0], 403)
        self.assertEqual(self.request('two', 'alpha', headers={'Host': 'matrix.example.test'})[0], 410)


if __name__ == '__main__':
    unittest.main()
