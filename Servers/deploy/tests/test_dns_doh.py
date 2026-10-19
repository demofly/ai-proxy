"""Real Unbound HTTP/2, TLS termination and the pinned DoH transport binary."""
import base64
from concurrent.futures import ThreadPoolExecutor
import importlib.util
import json
import os
import re
import runpy
from pathlib import Path
import shutil
import socket
import ssl
import struct
import subprocess
import tempfile
import time
import unittest
from unittest.mock import patch

from jinja2 import Environment, FileSystemLoader, StrictUndefined

ROOT = Path(__file__).resolve().parents[1]
spec = importlib.util.spec_from_file_location('dns_filter', ROOT / 'filter_plugins/dns.py')
dns = importlib.util.module_from_spec(spec)
spec.loader.exec_module(dns)
ENV = Environment(loader=FileSystemLoader(ROOT), undefined=StrictUndefined)
ENV.tests['search'] = lambda value, pattern: re.search(pattern, str(value)) is not None
ENV.filters.update(bool=lambda x: str(x).lower() in ('true', 'yes', '1'), to_json=json.dumps)


class DnsEndpointsTests(unittest.TestCase):
    def test_paths_follow_each_upstream_in_url_and_dns_stamp(self):
        values = dns.dns_doh_upstreams(['a', 'b', 'default'], {
            'a': {'ansible_host': '192.0.2.1', 'dns_doh_path': '/private/dns-query'},
            'b': {'ansible_host': '2001:db8::1', 'dns_doh_path': '/resolve-v2', 'proxy_port': 9443},
            'default': {'ansible_host': '192.0.2.2'}})
        for value, path in zip(values, ('/private/dns-query', '/resolve-v2', '/q')):
            self.assertTrue(value['url'].endswith(path))
            encoded = value['stamp'].removeprefix('sdns://')
            stamp = base64.urlsafe_b64decode(encoded + '=' * (-len(encoded) % 4))
            offset = 9
            offset += 1 + stamp[offset]  # Literal IP.
            self.assertEqual(stamp[offset], 0)  # Empty certificate hash list.
            offset += 1
            offset += 1 + stamp[offset]  # SNI and optional port.
            self.assertEqual(stamp[offset], len(path))
            self.assertEqual(stamp[offset + 1:].decode('ascii'), path)

    def test_invalid_paths_are_rejected_before_deployment(self):
        for path in ('', 'dns-query', '/q?dns=value', '/q#fragment', '/q\nserver:',
                     '/q"', '/q\\extra', '/путь', '/bad%2', '/a/../b', '/' + 'a' * 255, None, 1):
            with self.subTest(path=path), self.assertRaises(ValueError):
                dns.dns_doh_upstreams(['a'], {'a': {'ansible_host': '192.0.2.1', 'dns_doh_path': path}})
        for path in ('/', '/dns-query', '/nested/dns_query-v2', '/resolve%2Ddns'):
            self.assertEqual(dns.validate_doh_path(path), path)

    def test_public_healthcheck_uses_configured_path(self):
        packet = struct.pack('!6H', 0xA17D, 0x8180, 1, 1, 0, 0)
        response = subprocess.CompletedProcess([], 0, packet + b'\n2', b'')
        with patch('sys.argv', ['check-doh.py', '--public', 'dns.example.test', '/public/resolve']), \
                patch('subprocess.run', return_value=response) as run:
            with self.assertRaises(SystemExit) as stopped:
                runpy.run_path(str(ROOT / 'scripts/check-doh.py'), run_name='__main__')
            self.assertEqual(stopped.exception.code, 0)
        argv = run.call_args.args[0]
        self.assertEqual(argv[-1], 'https://dns.example.test/public/resolve')
        self.assertNotIn('--insecure', argv)

    def test_literal_addresses_ports_and_ipv6_without_bootstrap(self):
        values = dns.dns_doh_upstreams(['v4', 'v6'], {
            'v4': {'ansible_host': '192.0.2.1'},
            'v6': {'ansible_host': '2001:db8::1', 'dns_doh_backend_port': 9443, 'behind_nginx': False}})
        self.assertEqual([v['resolve'] for v in values],
                         ['dns.transit.internal:443:192.0.2.1', 'dns.transit.internal:9443:[2001:db8::1]'])
        self.assertTrue(all(v['stamp'].startswith('sdns://') for v in values))
        for value in ('dns.example.com', '127.0.0.1;bad', 'fe80::1%eth0'):
            with self.assertRaises(ValueError):
                dns.dns_doh_upstreams(['a'], {'a': {'ansible_host': value}})
        with self.assertRaises(ValueError):
            dns.dns_doh_upstreams([], {})

    def test_access_uses_only_loopback_bridge_and_no_plaintext_fallback(self):
        conf = ENV.get_template('roles/dns_resolver/templates/dnsproxy.yml.j2').render(
            ansible_managed='test', _dns_doh_upstreams=[dns.doh_endpoint('192.0.2.1')])
        import yaml
        value = yaml.safe_load(conf)
        self.assertTrue(value['insecure'])
        self.assertEqual(value['bootstrap'], [])
        self.assertEqual(value['fallback'], [])
        self.assertFalse(value['cache'])
        self.assertEqual(value['listen-addrs'], ['127.0.0.1'])


@unittest.skipUnless(shutil.which('unbound') and os.environ.get('AIPROXY_TEST_DNSPROXY')
                     and os.environ.get('AIPROXY_TEST_NGINX'), 'native DoH binaries required')
class NativeDohTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.fixture = tempfile.TemporaryDirectory(prefix='aiproxy-doh-')
        cls.root = root = Path(cls.fixture.name)
        root.chmod(0o755)
        cls.processes = []
        cls.addClassCleanup(cls.cleanup)
        held = []
        for _ in range(8):
            sock = socket.socket()
            sock.bind(('127.0.0.1', 0))
            held.append(sock)
        cls.plain_up, cls.doh_up, cls.bridge, cls.plain_access, cls.h2_access, cls.tls, cls.front, cls.private_relay = (
            sock.getsockname()[1] for sock in held)
        for sock in held:
            sock.close()
        subprocess.run(['openssl', 'req', '-x509', '-newkey', 'rsa:2048', '-nodes',
                        '-subj', '/CN=dns.example.test', '-days', '1',
                        '-keyout', str(root/'privkey.pem'), '-out', str(root/'fullchain.pem')],
                       check=True, capture_output=True)
        (root/'openssl.cnf').write_text(ENV.get_template('roles/dns_resolver/templates/openssl-doh.cnf.j2').render(ansible_managed='test'))
        cls.public_path = '/public/dns-query'
        cls.upstream_path = '/private/resolve-v2'
        common = dict(ansible_managed='test', _dns_threads=1, _dns_cache_mb=1,
                      _dns_allowed_clients=['127.0.0.1'], dns_resolver_dnssec=False,
                      dns_doh_enabled=True)
        template = ENV.get_template('roles/dns_resolver/templates/unbound.conf.j2')
        for role, port, doh in (('upstream', cls.plain_up, cls.doh_up),
                                ('access', cls.plain_access, cls.h2_access)):
            values = dict(common, proxy_role=role, dns_resolver_port=port,
                          dns_doh_backend_port=doh, dns_doh_local_port=doh,
                          dns_doh_path=cls.upstream_path if role == 'upstream' else cls.public_path,
                          _dns_forwarders=['127.0.0.1@' + str(cls.bridge)] if role == 'access' else ['192.0.2.99'])
            conf = template.render(values)
            conf = conf.replace('/etc/unbound/tls/doh.key', str(root/'privkey.pem'))
            conf = conf.replace('/etc/unbound/tls/doh.pem', str(root/'fullchain.pem'))
            conf = conf.replace('server:', 'server:\n    username: ""\n    chroot: ""\n'
                                f'    directory: "{root}"\n    pidfile: "{root}/{role}.pid"\n', 1)
            if role == 'upstream':
                conf = conf.replace('server:', 'server:\n    local-zone: "example.com." static\n'
                                    '    local-data: "example.com. 120 IN A 192.0.2.42"', 1)
            file = root/(role + '.conf')
            file.write_text(conf)
            subprocess.run(['unbound-checkconf', str(file)], check=True, capture_output=True)
            cls.start(['unbound', '-d', '-c', str(file)], role, doh,
                      env=dict(os.environ, OPENSSL_CONF=str(root/'openssl.cnf')) if role == 'upstream' else None)
        # One dead endpoint proves successful requests do not wait for all peers.
        cls.config = ENV.get_template('roles/dns_resolver/templates/dnsproxy.yml.j2').render(
            ansible_managed='test', dns_doh_bridge_port=cls.bridge,
            _dns_doh_upstreams=[dns.doh_endpoint('127.0.0.1', cls.front, path=cls.upstream_path),
                                dns.doh_endpoint('127.0.0.1', 1, path=cls.upstream_path)])
        (root/'dnsproxy.yml').write_text(cls.config)
        cls.start([os.environ['AIPROXY_TEST_DNSPROXY'], '--config-path=' + str(root/'dnsproxy.yml')],
                  'bridge', cls.bridge, env=dict(os.environ, GOMEMLIMIT='16MiB', GOGC='50', GOMAXPROCS='1'))
        term = ENV.get_template('roles/nginx/templates/12-aiproxy-doh.conf.j2').render(
            ansible_managed='test', dns_doh_hostname='dns.example.test',
            dns_doh_tls_port=cls.tls, dns_doh_local_port=cls.h2_access)
        term = term.replace('/etc/letsencrypt/live/dns.example.test', str(root))
        relay = ENV.get_template('roles/dns_resolver/templates/13-aiproxy-doh-upstream.conf.j2').render(
            ansible_managed='test', _dns_allowed_clients=['127.0.0.1'],
            dns_doh_relay_port=cls.private_relay, dns_doh_backend_port=cls.doh_up)
        module = os.environ['AIPROXY_TEST_NGINX_STREAM']
        (root/'nginx.conf').write_text(f'''load_module {module};
worker_processes 1;
pid {root}/nginx.pid;
error_log {root}/nginx.log;
events {{ worker_connections 512; }}
stream {{
    {term}
    {relay}
    map $ssl_preread_server_name $doh_fixture_backend {{
        dns.example.test aiproxy_doh;
        dns.transit.internal aiproxy_doh_upstream;
        default 127.0.0.1:1;
    }}
    server {{
        listen 127.0.0.1:{cls.front};
        ssl_preread on;
        proxy_pass $doh_fixture_backend;
        proxy_protocol on;
    }}
}}
''')
        cls.start([os.environ['AIPROXY_TEST_NGINX'], '-c', str(root/'nginx.conf'),
                   '-g', 'daemon off;'], 'nginx', cls.front)

    @classmethod
    def start(cls, argv, name, port, **kwargs):
        log = open(cls.root/(name + '.log'), 'ab')
        process = subprocess.Popen(argv, stdout=log, stderr=log, **kwargs)
        cls.processes.append((process, log))
        for _ in range(100):
            try:
                with socket.create_connection(('127.0.0.1', port), timeout=.1):
                    return
            except OSError:
                if process.poll() is not None:
                    raise RuntimeError((cls.root/(name + '.log')).read_text())
                time.sleep(.03)
        raise RuntimeError('No listener: ' + name)

    @classmethod
    def cleanup(cls):
        for process, log in reversed(cls.processes):
            process.terminate()
            try:
                process.wait(timeout=5)
            except subprocess.TimeoutExpired:
                process.kill()
                process.wait()
            log.close()
        cls.fixture.cleanup()

    @staticmethod
    def query(ident=1234):
        return struct.pack('!6H', ident, 0x0100, 1, 0, 0, 0) + b'\x07example\x03com\0\0\1\0\1'

    def exchange(self, method='POST', path=None, insecure=True, upstream=False):
        if path is None:
            path = self.upstream_path if upstream else self.public_path
        port = self.doh_up if upstream else self.front
        command = ['curl', '--silent', '--show-error', '--http2', '--noproxy', '*',
                   '--max-time', '5', '--write-out', '\n%{http_code}:%{http_version}',
                   '--resolve', f'dns.example.test:{port}:127.0.0.1']
        if insecure:
            command.append('--insecure')
        data = self.query()
        if method == 'GET':
            command += ['--get', '--data-urlencode', 'dns=' + base64.urlsafe_b64encode(data).rstrip(b'=').decode()]
        else:
            command += ['-H', 'Content-Type: application/dns-message', '--data-binary', '@-']
        return subprocess.run(command + [f'https://dns.example.test:{port}{path}'],
                              input=data, capture_output=True, timeout=7)

    def test_public_get_and_post_through_router_and_tls_terminator(self):
        for method in ('GET', 'POST'):
            result = self.exchange(method)
            self.assertEqual(result.returncode, 0, result.stderr)
            packet, status = result.stdout.rsplit(b'\n', 1)
            self.assertEqual(status, b'200:2')
            self.assertEqual(packet[:2], self.query()[:2])
            self.assertGreater(struct.unpack('!H', packet[6:8])[0], 0)
            self.assertIn(socket.inet_aton('192.0.2.42'), packet)

    def test_upstream_self_signed_cert_is_rejected_without_insecure(self):
        self.assertEqual(self.exchange(upstream=True, insecure=False).returncode, 60)
        self.assertEqual(self.exchange(upstream=True).returncode, 0)

    def test_transit_accepts_only_tls13(self):
        context = ssl.SSLContext(ssl.PROTOCOL_TLS_CLIENT)
        context.check_hostname = False
        context.verify_mode = ssl.CERT_NONE
        context.minimum_version = context.maximum_version = ssl.TLSVersion.TLSv1_3
        with socket.create_connection(('127.0.0.1', self.front), timeout=3) as tcp:
            with context.wrap_socket(tcp, server_hostname='dns.transit.internal') as tls:
                self.assertEqual(tls.version(), 'TLSv1.3')
        context.minimum_version = context.maximum_version = ssl.TLSVersion.TLSv1_2
        with socket.create_connection(('127.0.0.1', self.front), timeout=3) as tcp:
            with self.assertRaises(ssl.SSLError):
                context.wrap_socket(tcp, server_hostname='dns.transit.internal')

    @classmethod
    def bridge_query(cls, ident=1234):
        with socket.socket(socket.AF_INET, socket.SOCK_DGRAM) as client:
            client.settimeout(5)
            client.sendto(cls.query(ident), ('127.0.0.1', cls.bridge))
            return client.recv(65535)

    @classmethod
    def transit_connections(cls):
        output = subprocess.check_output(['ss', '-H', '-tnp', f'dport = :{cls.front}'], text=True)
        pid = cls.processes[2][0].pid
        return {tuple(line.split()[3:5]) for line in output.splitlines()
                if line.startswith('ESTAB') and f'pid={pid},' in line}

    def test_http2_connections_are_reused_between_dns_queries(self):
        self.bridge_query()
        before = self.transit_connections()
        self.assertTrue(before)
        for ident in range(5000, 5020):
            self.assertEqual(self.bridge_query(ident)[:2], struct.pack('!H', ident))
        self.assertEqual(before, self.transit_connections())

    def test_wrong_http_endpoint_is_not_a_dns_endpoint(self):
        for upstream in (False, True):
            for path in ('/q', '/wrong'):
                with self.subTest(upstream=upstream, path=path):
                    response = self.exchange(path=path, upstream=upstream)
                    self.assertNotIn(b'200:2', response.stdout)

    def test_transit_healthcheck_uses_configured_path(self):
        endpoints = [dns.doh_endpoint('127.0.0.1', self.front, path=self.upstream_path)]
        result = subprocess.run(['python3', str(ROOT / 'scripts/check-doh.py'), json.dumps(endpoints)],
                                capture_output=True, timeout=10)
        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertEqual(json.loads(result.stdout)['verified'], 1)

    def test_parallel_local_dns_and_one_failed_doh_peer(self):
        def run(ident):
            query = self.query(ident)
            with socket.socket(socket.AF_INET, socket.SOCK_DGRAM) as client:
                client.settimeout(5)
                client.sendto(query, ('127.0.0.1', self.plain_access))
                answer = client.recv(65535)
                self.assertEqual(answer[:2], query[:2])
                self.assertIn(socket.inet_aton('192.0.2.42'), answer)
        with ThreadPoolExecutor(max_workers=16) as pool:
            list(pool.map(run, range(1000, 1064)))


if __name__ == '__main__':
    unittest.main()
