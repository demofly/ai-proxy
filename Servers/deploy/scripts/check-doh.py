#!/usr/bin/env python3
"""Exercise RFC 8484 on the real access→upstream path, never NAT hairpin."""
import json
import struct
import subprocess
import sys


def check(url, insecure=True, resolve=None):
    query = struct.pack('!6H', 0xA17D, 0x0100, 1, 0, 0, 0)
    query += b'\x07example\x03com\x00' + struct.pack('!2H', 1, 1)
    argv = ['curl', '--silent', '--show-error', '--fail', '--http2',
            '--noproxy', '*', '--connect-timeout', '3', '--max-time', '6',
            '--header', 'Content-Type: application/dns-message',
            '--header', 'Accept: application/dns-message',
            '--data-binary', '@-', '--write-out', '\n%{http_version}']
    if insecure:
        argv += ['--insecure', '--tlsv1.3', '--tls-max', '1.3']
    if resolve:
        argv += ['--resolve', resolve]
    result = subprocess.run(argv + [url], input=query, capture_output=True, timeout=8)
    if result.returncode:
        raise RuntimeError('DoH transport failed: ' + result.stderr.decode(errors='replace')[-400:])
    packet, version = result.stdout.rsplit(b'\n', 1)
    if version != b'2' or len(packet) < 12:
        raise RuntimeError('Expected HTTP/2 and a DNS wire response')
    ident, flags, _, answers, _, _ = struct.unpack('!6H', packet[:12])
    if ident != 0xA17D or not flags & 0x8000 or flags & 0xF or not answers:
        raise RuntimeError('Invalid DNS response or resolver failure')


if __name__ == '__main__':
    if sys.argv[1] == '--public':
        hostname, path = sys.argv[2:]
        check('https://' + hostname + path, insecure=False,
              resolve=hostname + ':443:127.0.0.1')
        print(json.dumps({'verified': 1, 'http': '2', 'certificate': 'trusted'}))
        raise SystemExit(0)
    for endpoint in json.loads(sys.argv[1]):
        check(endpoint['url'], resolve=endpoint['resolve'])
    print(json.dumps({'verified': len(json.loads(sys.argv[1])), 'http': '2', 'transport': 'DoH'}))
