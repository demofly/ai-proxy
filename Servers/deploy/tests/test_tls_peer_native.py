"""Exercise real Squid TLS peers on loopback; no public network or live services.

Set AIPROXY_TEST_SQUID to an OpenSSL Squid binary.
The daemon uses temporary config/log/PID files and an ephemeral loopback port.
"""
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

import test_proxy_transit


def headers(connection):
    result = b''
    while b'\r\n\r\n' not in result:
        block = connection.recv(4096)
        if not block:
            raise ConnectionError('connection closed before complete headers')
        result += block
        if len(result) > 65536:
            raise ValueError('oversized headers')
    return result


@unittest.skipUnless(os.environ.get('AIPROXY_TEST_SQUID') and shutil.which('openssl')
                     and shutil.which('ansible-playbook'),
                     'set AIPROXY_TEST_SQUID for native daemon tests')
class NativeTlsPeerTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.binary = os.environ['AIPROXY_TEST_SQUID']
        cls.peer_line = next(line for line in test_proxy_transit.ProxyTransitTests().render({
            'squid_transit_tls': True, 'squid_tls_sni': 'transit.test'})['access'].splitlines()
            if line.startswith('cache_peer '))

    def exercise(self, certificate_name='transit.test', wrong_ca=False):
        with tempfile.TemporaryDirectory(prefix='aiproxy-tls-') as directory:
            tmp = Path(directory)
            # Squid drops privileges; give it access only to its isolated fixture.
            tmp.chmod(0o777)
            def certificate(stem, name):
                subprocess.run(['openssl', 'req', '-x509', '-newkey', 'ec', '-pkeyopt',
                                'ec_paramgen_curve:prime256v1', '-nodes', '-days', '1',
                                '-subj', '/CN=' + name, '-addext', 'subjectAltName=DNS:' + name,
                                '-keyout', str(tmp / (stem + '.key')),
                                '-out', str(tmp / (stem + '.crt'))],
                               capture_output=True, check=True, timeout=10)
            certificate('ca', 'fixture-ca.test')
            subprocess.run(['openssl', 'req', '-new', '-newkey', 'ec', '-pkeyopt',
                            'ec_paramgen_curve:prime256v1', '-nodes',
                            '-subj', '/CN=' + certificate_name,
                            '-keyout', str(tmp / 'peer.key'), '-out', str(tmp / 'peer.csr')],
                           capture_output=True, check=True, timeout=10)
            (tmp / 'extensions').write_text('subjectAltName=DNS:' + certificate_name)
            subprocess.run(['openssl', 'x509', '-req', '-in', str(tmp / 'peer.csr'),
                            '-CA', str(tmp / 'ca.crt'), '-CAkey', str(tmp / 'ca.key'),
                            '-CAcreateserial', '-days', '1', '-extfile', str(tmp / 'extensions'),
                            '-out', str(tmp / 'peer.crt')], capture_output=True, check=True, timeout=10)
            ca = tmp / 'ca.crt'
            if wrong_ca:
                certificate('other', 'unrelated.test')
                ca = tmp / 'other.crt'
            ctx = ssl.SSLContext(ssl.PROTOCOL_TLS_SERVER)
            ctx.minimum_version = ssl.TLSVersion.TLSv1_3
            ctx.load_cert_chain(tmp / 'peer.crt', tmp / 'peer.key')
            names, requests = queue.Queue(), queue.Queue()
            def sni(connection, name, context):
                names.put(name)
                # Production nginx routes to the terminator only with matching SNI.
                if name != 'transit.test':
                    return ssl.ALERT_DESCRIPTION_UNRECOGNIZED_NAME
            ctx.sni_callback = sni
            listener = socket.socket()
            listener.bind(('127.0.0.1', 0))
            listener.listen()
            listener.settimeout(0.2)
            stopped = threading.Event()
            def serve():
                while not stopped.is_set():
                    try:
                        raw, _ = listener.accept()
                    except socket.timeout:
                        continue
                    except OSError:
                        break
                    try:
                        with raw:
                            raw.settimeout(3)
                            # Squid also opens/closes bare TCP probes for peer health.
                            if not raw.recv(1, socket.MSG_PEEK):
                                continue
                            with ctx.wrap_socket(raw, server_side=True) as connection:
                                requests.put(headers(connection).split(b'\r\n')[0])
                                connection.sendall(b'HTTP/1.1 200 Connection established\r\n\r\n')
                                connection.sendall(b'echo:' + connection.recv(32))
                    except (OSError, ssl.SSLError):
                        pass
            worker = threading.Thread(target=serve, daemon=True)
            worker.start()
            with socket.socket() as reservation:
                reservation.bind(('127.0.0.1', 0))
                port = reservation.getsockname()[1]
            # Keep all production TLS options; substitute only fixture addresses/CA.
            peer = self.peer_line.replace('198.51.100.20 parent 443',
                    '127.0.0.1 parent ' + str(listener.getsockname()[1])).replace(
                    '/etc/squid/upstream-transit-ca.crt', str(ca))
            (tmp / 'mime.conf').write_text('')
            config = tmp / 'squid.conf'
            config.write_text(f'''http_port 127.0.0.1:{port}
pid_filename {tmp}/squid.pid
cache_log {tmp}/cache.log
access_log none
cache_store_log none
cache_effective_user nobody
cache_effective_group nogroup
mime_table {tmp}/mime.conf
icon_directory {tmp}
error_directory {tmp}
unlinkd_program /bin/true
cache_mem 0 MB
shutdown_lifetime 0 seconds
visible_hostname regression.test
http_access allow all
{peer}
never_direct allow all
''')
            parse = subprocess.run([self.binary, '-k', 'parse', '-f', str(config)],
                                   capture_output=True, text=True, timeout=10)
            self.assertEqual(parse.returncode, 0, parse.stderr)
            try:
                with (tmp / 'process.log').open('w') as log:
                    process = subprocess.Popen([self.binary, '-N', '-f', str(config), '-d', '1'],
                                               stdout=log, stderr=log)
                    try:
                        for _ in range(80):
                            try:
                                connection = socket.create_connection(('127.0.0.1', port), timeout=.2)
                                break
                            except OSError:
                                self.assertIsNone(process.poll(),
                                    (tmp / 'process.log').read_text(errors='replace'))
                                time.sleep(.05)
                        else:
                            self.fail('Squid did not start listening')
                        with connection:
                            connection.settimeout(8)
                            connection.sendall(b'CONNECT origin.test:443 HTTP/1.1\r\n'
                                               b'Host: origin.test:443\r\n\r\n')
                            response = headers(connection).split(b'\r\n')[0]
                            if wrong_ca or certificate_name != 'transit.test':
                                self.assertNotIn(b' 200 ', response)
                                self.assertTrue(requests.empty(), 'untrusted peer received CONNECT')
                            else:
                                self.assertIn(b' 200 ', response)
                                connection.sendall(b'probe')
                                self.assertEqual(connection.recv(32), b'echo:probe')
                                self.assertEqual(requests.get(timeout=1), b'CONNECT origin.test:443 HTTP/1.1')
                            self.assertEqual(names.get(timeout=1), 'transit.test')
                    finally:
                        process.terminate()
                        try:
                            process.wait(timeout=5)
                        except subprocess.TimeoutExpired:
                            process.kill()
                            process.wait(timeout=3)
            finally:
                stopped.set()
                listener.close()
                worker.join(timeout=4)
                self.assertFalse(worker.is_alive(), 'TLS fixture did not stop')

    def test_connect_uses_configured_sni_and_transfers_bytes(self):
        self.exercise()

    def test_untrusted_peer_never_receives_connect(self):
        self.exercise(wrong_ca=True)

    def test_wrong_certificate_name_never_receives_connect(self):
        self.exercise(certificate_name='wrong.test')


if __name__ == '__main__':
    unittest.main()