"""Render actual ingress templates; optionally exercise nginx on isolated loopback ports.

Native tests require AIPROXY_TEST_NGINX and AIPROXY_TEST_NGINX_STREAM.
No system service, public port or production certificate is used.
"""
import copy
import os
from pathlib import Path
import queue
import shutil
import socket
import ssl
import subprocess
import tempfile
import threading
import time
import unittest

import yaml

ROOT = Path(__file__).resolve().parents[1]


def render(directory, overrides=None, templates=True):
    values = {'proxy_role': 'access', 'enable_auth': True,
              'https_proxy_enabled': True, 'https_proxy_hostname': 'proxy.example.test',
              'https_proxy_certificate': str(directory / 'proxy.crt'),
              'https_proxy_certificate_key': str(directory / 'proxy.key'),
              'sni_router_access_log': str(directory / 'access.log')}
    values.update(overrides or {})
    source = yaml.safe_load((ROOT / 'playbook.yml').read_text(encoding='utf-8'))[0]
    tasks = copy.deepcopy([t for t in source['pre_tasks'] if t['name'] in (
        'Проверить параметры клиентского HTTPS-прокси',
        'Проверить параметры выпуска сертификата HTTPS-прокси')])
    if templates:
        for name, path in (
            ('router', 'templates/00-sni-router.conf.j2'),
            ('terminator', 'roles/nginx/templates/11-aiproxy-https-proxy.conf.j2'),
            ('sni', 'roles/nginx/templates/sni-map.d/aiproxy-https-proxy.conf.j2'),
            ('capacity', 'templates/10-aiproxy-capacity.conf.j2'),
        ):
            tasks.append({'ansible.builtin.template': {
                'src': str(ROOT / path), 'dest': str(directory / (name + '.conf'))}})
    play = [{'hosts': 'localhost', 'gather_facts': False, 'become': False,
             'connection': 'local', 'vars': values, 'tasks': tasks}]
    path = directory / 'render.yml'
    path.write_text(yaml.safe_dump(play, allow_unicode=True), encoding='utf-8')
    return subprocess.run(['ansible-playbook', '-i', 'localhost,', str(path)],
                          env=dict(os.environ, ANSIBLE_FILTER_PLUGINS=str(ROOT / 'filter_plugins'),
                                   ANSIBLE_NOCOLOR='1'),
                          capture_output=True, text=True, timeout=60)


@unittest.skipUnless(shutil.which('ansible-playbook'), 'requires ansible-playbook')
class HttpsProxyValidationTests(unittest.TestCase):
    def test_unsafe_ingress_settings_fail_before_rendering(self):
        for overrides in ({'enable_auth': False}, {'proxy_role': 'upstream'},
                          {'behind_nginx': False}, {'https_proxy_hostname': 'max.ru'},
                          {'https_proxy_hostname': 'bad;name.test'},
                          {'https_proxy_local_port': 3128},
                          {'https_proxy_certificate_key': '/key; injected'}):
            with self.subTest(overrides=overrides), tempfile.TemporaryDirectory() as tmp:
                result = render(Path(tmp), overrides)
                self.assertNotEqual(result.returncode, 0, result.stdout)
                self.assertIn('HTTPS-прокси требует access', result.stdout)
                self.assertFalse(list(Path(tmp).glob('*.conf')))

    def test_old_inventory_without_client_tls_is_accepted(self):
        with tempfile.TemporaryDirectory() as tmp:
            result = render(Path(tmp), {'https_proxy_enabled': False,
                                        'https_proxy_hostname': '', 'enable_auth': False}, templates=False)
            self.assertEqual(result.returncode, 0, result.stdout + result.stderr)

    def test_acme_requires_contact_and_standard_certificate_paths(self):
        with tempfile.TemporaryDirectory() as tmp:
            result = render(Path(tmp), {'https_proxy_acme_enabled': True}, templates=False)
            self.assertNotEqual(result.returncode, 0, result.stdout)
            self.assertIn('Автоматический ACME требует', result.stdout)


def free_port():
    with socket.socket() as reservation:
        reservation.bind(('127.0.0.1', 0))
        return reservation.getsockname()[1]


def read_until(connection, delimiter):
    data = b''
    while not data.endswith(delimiter):
        block = connection.recv(1)
        if not block:
            raise ConnectionError('closed before header')
        data += block
        if len(data) > 65536:
            raise ValueError('oversized header')
    return data


@unittest.skipUnless(os.environ.get('AIPROXY_TEST_NGINX')
                     and os.environ.get('AIPROXY_TEST_NGINX_STREAM')
                     and shutil.which('openssl') and shutil.which('ansible-playbook'),
                     'set nginx binary/module variables for native ingress tests')
class NativeHttpsProxyTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.fixture = tempfile.TemporaryDirectory(prefix='aiproxy-https-')
        cls.tmp = tmp = Path(cls.fixture.name)
        subprocess.run(['openssl', 'req', '-x509', '-newkey', 'ec', '-pkeyopt',
                        'ec_paramgen_curve:prime256v1', '-nodes', '-days', '1',
                        '-subj', '/CN=proxy.example.test',
                        '-addext', 'subjectAltName=DNS:proxy.example.test',
                        '-keyout', str(tmp / 'proxy.key'), '-out', str(tmp / 'proxy.crt')],
                       capture_output=True, check=True, timeout=10)
        cls.listener = socket.socket()
        cls.listener.bind(('127.0.0.1', 0))
        cls.listener.listen()
        cls.listener.settimeout(.2)
        cls.backend = cls.listener.getsockname()[1]
        cls.port, local_port = free_port(), free_port()
        result = render(tmp, {'https_proxy_local_port': local_port,
                              'squid_local_port': cls.backend})
        if result.returncode:
            raise AssertionError(result.stdout + result.stderr)
        (tmp / 'maps').mkdir()
        (tmp / 'maps/client.conf').write_text((tmp / 'sni.conf').read_text())
        (tmp / 'extensions').mkdir()
        router = (tmp / 'router.conf').read_text().replace(
            'listen 443 ', f'listen 127.0.0.1:{cls.port} ').replace(
            '    listen [::]:443 so_keepalive=60s:10s:3;\n', '').replace(
            '127.0.0.1:3128;', f'127.0.0.1:{cls.backend};').replace(
            '/etc/nginx/stream.d/sni-map.d/*.conf', str(tmp / 'maps/*.conf')).replace(
            '/etc/nginx/stream.d/router.d/*.conf', str(tmp / 'extensions/*.conf'))
        cls.config = tmp / 'nginx.conf'
        cls.config.write_text(
            f"load_module {os.environ['AIPROXY_TEST_NGINX_STREAM']};\n"
            f"pid {tmp}/nginx.pid;\nerror_log {tmp}/error.log;\n"
            "worker_processes 1;\nevents { worker_connections 128; }\nstream {\n"
            + (tmp / 'capacity.conf').read_text() + router
            + (tmp / 'terminator.conf').read_text() + '\n}\n')
        cls.received = queue.Queue()
        cls.stopped = threading.Event()

        def serve():
            while not cls.stopped.is_set():
                try:
                    conn, _ = cls.listener.accept()
                except socket.timeout:
                    continue
                except OSError:
                    break
                try:
                    with conn:
                        conn.settimeout(3)
                        proxy = read_until(conn, b'\r\n')
                        request = read_until(conn, b'\r\n\r\n')
                        cls.received.put((proxy, request))
                        conn.sendall(b'HTTP/1.1 200 Connection established\r\n\r\n')
                        while True:
                            payload = conn.recv(16384)
                            if not payload:
                                break
                            conn.sendall(payload)
                except (OSError, ConnectionError):
                    pass
        cls.worker = threading.Thread(target=serve, daemon=True)
        cls.worker.start()
        command = [os.environ['AIPROXY_TEST_NGINX'], '-p', str(tmp), '-c', str(cls.config)]
        parsed = subprocess.run(command + ['-t'], capture_output=True, text=True, timeout=10)
        if parsed.returncode:
            raise AssertionError(parsed.stderr)
        cls.process = subprocess.Popen(command + ['-g', 'daemon off;'],
                                       stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
        for _ in range(100):
            if cls.process.poll() is not None:
                raise AssertionError((tmp / 'error.log').read_text())
            if (tmp / 'nginx.pid').exists():
                time.sleep(.05)
                break
            time.sleep(.02)
        cls.addClassCleanup(cls.cleanup)

    @classmethod
    def cleanup(cls):
        cls.process.terminate()
        cls.process.wait(timeout=10)
        cls.stopped.set()
        cls.listener.close()
        cls.worker.join(timeout=4)
        cls.fixture.cleanup()

    def connect(self, tls=True, name='proxy.example.test'):
        raw = socket.create_connection(('127.0.0.1', self.port), timeout=3,
                                       source_address=('127.0.0.2', 0))
        if not tls:
            return raw
        context = ssl.create_default_context(cafile=str(self.tmp / 'proxy.crt'))
        context.set_alpn_protocols(['h2', 'http/1.1'])
        return context.wrap_socket(raw, server_hostname=name)

    def check_tunnel(self, tls):
        with self.connect(tls=tls) as client:
            if tls:
                self.assertEqual(client.selected_alpn_protocol(), 'http/1.1')
            client.sendall(b'CONNECT origin.test:443 HTTP/1.1\r\nHost: origin.test:443\r\n\r\n')
            self.assertIn(b' 200 ', read_until(client, b'\r\n\r\n'))
            proxy, request = self.received.get(timeout=3)
            self.assertIn(b'PROXY TCP4 127.0.0.2 ', proxy)
            self.assertTrue(request.startswith(b'CONNECT origin.test:443 HTTP/1.1'))
            for size in (1, 16384, 65536, 7):
                payload = os.urandom(size)
                client.sendall(payload)
                response = b''
                while len(response) < size:
                    block = client.recv(size - len(response))
                    self.assertTrue(block)
                    response += block
                self.assertEqual(response, payload)

    def test_https_tunnel_preserves_client_ip_and_segmented_bytes(self):
        self.check_tunnel(tls=True)

    def test_existing_plain_http_fallback_stays_available(self):
        self.check_tunnel(tls=False)

    def test_wrong_certificate_name_is_rejected(self):
        # Connect straight to the TLS terminator with its PROXY preface, so an
        # unknown SNI cannot be sent to the router's intentionally plain fallback.
        content = (self.tmp / 'terminator.conf').read_text()
        import re
        port = int(re.search(r'listen 127\.0\.0\.1:(\d+)', content)[1])
        with socket.create_connection(('127.0.0.1', port), timeout=3) as raw:
            raw.sendall(b'PROXY TCP4 127.0.0.2 127.0.0.1 12345 443\r\n')
            context = ssl.create_default_context(cafile=str(self.tmp / 'proxy.crt'))
            with self.assertRaises(ssl.SSLCertVerificationError):
                context.wrap_socket(raw, server_hostname='wrong.example.test')

    def transaction(self, existing, occupied=False):
        """Run the real Ansible rollback block against isolated config files."""
        with tempfile.TemporaryDirectory(prefix='aiproxy-rollback-') as directory:
            tmp = Path(directory)
            (tmp / 'maps').mkdir()
            targets = [tmp / '11-aiproxy-https-proxy.conf', tmp / 'maps/aiproxy-https-proxy.conf']
            if existing:
                for target in targets:
                    target.write_text('# previous valid fragment\n')
            config = tmp / 'nginx.conf'
            config.write_text(
                f"load_module {os.environ['AIPROXY_TEST_NGINX_STREAM']};\n"
                f"error_log {tmp}/error.log;\nevents {{}}\nstream {{\n"
                "limit_conn_zone $server_addr zone=aiproxy_transit:32k;\n"
                f"map $ssl_preread_server_name $backend {{ include {tmp}/maps/*.conf; default ''; }}\n"
                f"include {tmp}/11-aiproxy-https-proxy.conf;\n}}\n")
            # The empty-old-state test needs an optional include instead.
            config.write_text(config.read_text().replace(
                f'include {tmp}/11-aiproxy-https-proxy.conf;', f'include {tmp}/*-https-proxy.conf;'))
            source = yaml.safe_load((ROOT / 'roles/nginx/tasks/https-proxy.yml').read_text(encoding='utf-8'))
            start = next(i for i, task in enumerate(source)
                         if task['name'] == 'Сохранить прежние фрагменты HTTPS-прокси для отката')

            def rewrite(value):
                if isinstance(value, dict):
                    return {key: rewrite(child) for key, child in value.items()}
                if isinstance(value, list):
                    return [rewrite(child) for child in value]
                if not isinstance(value, str):
                    return value
                if value == 'nginx -t':
                    return f'{os.environ["AIPROXY_TEST_NGINX"]} -p {tmp} -c {config} -t'
                value = value.replace('/etc/nginx/stream.d/sni-map.d/', str(tmp / 'maps') + '/')
                value = value.replace('/etc/nginx/stream.d/', str(tmp) + '/')
                for name in ('11-aiproxy-https-proxy.conf.j2', 'sni-map.d/aiproxy-https-proxy.conf.j2'):
                    if value == name:
                        value = str(ROOT / 'roles/nginx/templates' / name)
                return value
            tasks = rewrite(source[start:])
            values = {'https_proxy_enabled': True, 'https_proxy_hostname': 'proxy.example.test',
                      'https_proxy_certificate': str(self.tmp / 'proxy.crt'),
                      'https_proxy_certificate_key': str(tmp / 'missing.key'),
                      'https_proxy_local_port': self.backend if occupied else free_port()}
            play = [{'hosts': 'localhost', 'gather_facts': False, 'connection': 'local',
                     'vars': values, 'tasks': tasks,
                     'handlers': [{'name': 'Перечитать конфигурацию nginx',
                                   'ansible.builtin.fail': {'msg': 'must not reload invalid config'}}]}]
            path = tmp / 'transaction.yml'
            path.write_text(yaml.safe_dump(play, allow_unicode=True), encoding='utf-8')
            result = subprocess.run(['ansible-playbook', '-i', 'localhost,', str(path)],
                                    env=dict(os.environ, ANSIBLE_FILTER_PLUGINS=str(ROOT / 'filter_plugins')),
                                    capture_output=True, text=True, timeout=45)
            self.assertNotEqual(result.returncode, 0, result.stdout)
            self.assertNotIn('must not reload invalid config', result.stdout)
            if occupied:
                self.assertIn('Локальный порт HTTPS-прокси занят', result.stdout)
            else:
                self.assertIn('HTTPS-прокси не прошёл nginx -t', result.stdout)
            for target in targets:
                if existing:
                    self.assertEqual(target.read_text(), '# previous valid fragment\n')
                else:
                    self.assertFalse(target.exists())

    def test_invalid_tls_fragments_are_rolled_back_without_reload(self):
        for existing in (True, False):
            with self.subTest(existing=existing):
                self.transaction(existing)

    def test_foreign_listener_is_rejected_before_replacing_fragments(self):
        self.transaction(existing=True, occupied=True)


if __name__ == '__main__':
    unittest.main()
