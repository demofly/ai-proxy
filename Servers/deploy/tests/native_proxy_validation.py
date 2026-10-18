"""Native Linux regression: rendered Squid/nginx/mtg, idle relay and cgroup caps.

Requires prepare_native_validation.py, then run as root in an isolated network:
  unshare -n python3 native_proxy_validation.py --cache /home/user/.cache/ai-proxy-validation
No production endpoint is contacted. The origin is a local TLS echo server;
Telegram relay timing is tested with an opaque echo backend (not Telegram DCs).
"""
import argparse
from concurrent.futures import ThreadPoolExecutor
import crypt
import importlib.util
import json
import os
from pathlib import Path
import pwd
import shutil
import socket
import socketserver
import ssl
import subprocess
import tempfile
import threading
import time
import urllib.request

import jinja2
import yaml

DEPLOY = Path(__file__).resolve().parents[1]
spec = importlib.util.spec_from_file_location('resources', DEPLOY/'filter_plugins/resources.py')
resources = importlib.util.module_from_spec(spec)
spec.loader.exec_module(resources)
mtproxy_spec = importlib.util.spec_from_file_location('mtproxy_policy', DEPLOY/'filter_plugins/mtproxy.py')
mtproxy_policy = importlib.util.module_from_spec(mtproxy_spec)
mtproxy_spec.loader.exec_module(mtproxy_policy)
ENV = jinja2.Environment(trim_blocks=True, keep_trailing_newline=True)
ENV.filters.update(bool=resources.as_bool, squid_duration_seconds=resources.squid_duration_seconds,
                   mtproxy_nodes=mtproxy_policy.mtproxy_nodes)


def render(template, values):
    return ENV.from_string((DEPLOY/template).read_text()).render(values)


def wait_port(port):
    for _ in range(100):
        try:
            with socket.create_connection(('127.0.0.1', port), timeout=.1):
                return
        except OSError:
            time.sleep(.1)
    raise RuntimeError(f'Port {port} did not start')


def main():
    args = argparse.ArgumentParser()
    args.add_argument('--cache', type=Path, required=True)
    args.add_argument('--idle-seconds', type=int, default=70)
    args.add_argument('--ram-mib', type=int, default=961)
    opts = args.parse_args()
    cache = opts.cache
    work = Path(tempfile.mkdtemp(prefix=f'run-{os.getpid()}-', dir=cache))
    work.chmod(0o777)
    subprocess.run(['ip', 'link', 'set', 'lo', 'up'], check=True)
    lib = cache/'root/usr/lib/x86_64-linux-gnu'
    env = dict(os.environ, LD_LIBRARY_PATH=str(lib))
    squid = cache/'root/usr/sbin/squid'
    nginx = cache/'root/usr/sbin/nginx'
    mtg = next((cache/'mtg').glob('*/mtg'))
    enabled = ['squid', 'unbound', 'nginx', 'mtg', 'crowdsec', 'crowdsec_bouncer', 'haveged', 'health']
    minimum = resources.proxy_memory_plan(0, enabled)['minimum_mb']
    budget = resources.proxy_memory_budget(opts.ram_mib, minimum_mb=minimum)
    plan = resources.proxy_memory_plan(budget['mb'], enabled)
    assert plan['fits'], plan
    limits = plan['limits']
    concurrency = min(100, (limits['mtg']-16)*8, (4096-256)//4)
    transit_capacity = min(96, (limits['squid']-24)*6)
    print('Host RAM MiB:', opts.ram_mib, 'budget:', budget, 'service limits:', limits, flush=True)
    cgroup = Path('/sys/fs/cgroup')/f'aiproxytest{os.getpid()}'
    cgroup.mkdir()
    (cgroup/'memory.max').write_text(str(budget['bytes']))
    (cgroup/'memory.swap.max').write_text('0')
    (cgroup/'cgroup.subtree_control').write_text('+memory')
    processes = []
    peaks = {}

    def launch(name, command, limit, environment=None):
        group = cgroup/name
        group.mkdir()
        (group/'memory.max').write_text(str(limit*1048576))
        (group/'memory.swap.max').write_text('0')
        def place():
            (group/'cgroup.procs').write_text(str(os.getpid()))
        logfile = open(work/f'{name}.log', 'w')
        proc = subprocess.Popen([str(x) for x in command], env=environment or env,
                                stdout=logfile, stderr=subprocess.STDOUT, preexec_fn=place)
        logfile.close()
        processes.append((name, proc, group))
        return proc

    def checked(command):
        result = subprocess.run([str(x) for x in command], env=env, capture_output=True, text=True)
        if result.returncode:
            raise RuntimeError(result.stderr[-5000:]+result.stdout[-1000:])

    checked(['openssl', 'req', '-x509', '-newkey', 'ec', '-pkeyopt', 'ec_paramgen_curve:prime256v1',
             '-keyout', work/'key.pem', '-out', work/'cert.pem', '-days', '1', '-nodes',
             '-subj', '/CN=transit.internal', '-addext', 'subjectAltName=DNS:transit.internal'])
    passwd = work/'passwd'
    passwd.write_text('native:'+crypt.crypt('test-password', crypt.mksalt(crypt.METHOD_SHA512))+'\n')
    common = dict(ansible_managed='Native isolated fixture', inventory_hostname='test', ansible_host='127.0.0.1',
                  cpu_cores=1, ansible_processor_vcpus=1, squid_workers=1, fd_limit=65535,
                  squid_fd_limit=min(65535, max(4096, (limits['squid']-16)*256)),
                  enable_caching=False, enable_logging=False, nginx_on_443=True, squid_transit_tls=True,
                  mem_squid_mb=limits['squid'], squid_tls_sni='transit.internal', allowed_domains=[], allowed_domain_patterns=[],
                  groups={'access_proxies':['access'], 'upstreams':['up']},
                  hostvars={'access': {'ansible_host':'127.0.0.1'},
                            'up':{'ansible_host':'127.0.0.1', 'squid_port':443, 'mtproxy_enabled':True}},
                  squid_local_port=3128, squid_mgmt_port=3129, enable_auth=False,
                  mtproxy_local_port=2083, squid_tls_term_port=4444,
                  mtproxy_tls_port=4443, mtproxy_relay_port=9443, mtproxy_hostname='public-proxy.example',
                  mtproxy_fake_tls_domain='max.ru', mtproxy_enabled=True, proxy_max_connections=96,
                  proxy_effective_max_connections=transit_capacity)
    # End-user and access-node identities intentionally do not reach upstream Squid.
    upstream = render('templates/squid-upstream.conf.j2', common)
    access_values = dict(common, squid_local_port=3228, squid_mgmt_port=3229, enable_auth=True,
                         enable_caching=True, enable_logging=True)
    access = render('templates/squid-access.conf.j2', access_values)
    access = access.replace('/usr/lib/squid/basic_ncsa_auth', str(cache/'root/usr/lib/squid/basic_ncsa_auth'))
    access = access.replace('/etc/squid/passwd', str(passwd))
    access = access.replace('/etc/squid/upstream-transit-ca.crt', str(work/'cert.pem'))
    for name, text in [('up', upstream), ('access', access)]:
        spool = work/f'{name}-spool'
        spool.mkdir(mode=0o777)
        spool.chmod(0o777)
        text = text.replace('/var/spool/squid', str(spool))
        text = text.replace('/var/log/squid/access.log', str(work/f'{name}-access.log'))
        text = text.replace('/var/log/squid/cache.log', str(work/f'{name}-cache.log'))
        text += f'\npid_filename {work}/{name}.pid\n'
        text += f'coredump_dir {work}\nerror_directory {cache}/root/usr/share/squid/errors/templates\n'
        text += f'icon_directory {cache}/root/usr/share/squid/icons\n'
        text += f'mime_table {cache}/root/usr/share/squid/mime.conf\n'
        text += f'unlinkd_program {cache}/root/usr/lib/squid/unlinkd\n'
        text += f'logfile_daemon {cache}/root/usr/lib/squid/log_file_daemon\n'
        text += f'cache_effective_user {pwd.getpwuid(cache.stat().st_uid).pw_name}\n'
        text += 'pinger_enable off\n'
        text += f'\ncache_log {work}/{name}-cache.log\n'
        (work/f'{name}.conf').write_text(text)
        checked([squid, '-k', 'parse', '-f', work/f'{name}.conf'])
        if name == 'access':
            checked([squid, '-N', '-z', '-f', work/f'{name}.conf'])

    # Actual one-list ACL variants must parse, not merely contain expected text.
    for values in [dict(access_values, allowed_domains=['.example.com']),
                   dict(access_values, allowed_domain_patterns=[r'\.example\.com$'])]:
        text = render('templates/squid-access.conf.j2', values)
        text = text.replace('/usr/lib/squid/basic_ncsa_auth', str(cache/'root/usr/lib/squid/basic_ncsa_auth'))
        text = text.replace('/etc/squid/passwd', str(passwd)).replace('/etc/squid/upstream-transit-ca.crt', str(work/'cert.pem'))
        (work/'variant.conf').write_text(text)
        checked([squid, '-k', 'parse', '-f', work/'variant.conf'])

    router = render('templates/00-sni-router.conf.j2', common)
    router = router.replace('include /etc/nginx/stream.d/sni-map.d/*.conf;',
        render('roles/mtproxy/templates/sni-map.d/squid.conf.j2',common)
        +render('roles/mtproxy/templates/sni-map.d/mtproxy.conf.j2',common))
    router = router.replace('include /etc/nginx/stream.d/router.d/*.conf;', '')
    router = router.replace('/var/log/nginx/sni-router.log', str(work/'sni.log'))
    term = render('roles/mtproxy/templates/nginx-squid-tls-term.conf.j2', common)
    mtterm = render('roles/mtproxy/templates/nginx-mtproxy-stream.conf.j2', common)
    relay = render('roles/nginx/templates/10-aiproxy-upstreams.conf.j2', common)
    # Separate access relay listener, same encrypted two-hop MTProxy relay path.
    relay = relay.replace(' listen 127.0.0.1:9443 proxy_protocol;', ' listen 127.0.0.1:9443;')
    bodies = router+term+mtterm+relay+render('templates/10-aiproxy-capacity.conf.j2', common)
    for cert in ['squid-transit', 'mtproxy']:
        bodies = bodies.replace(f'/etc/nginx/ssl/{cert}.crt', str(work/'cert.pem'))
        bodies = bodies.replace(f'/etc/nginx/ssl/{cert}.key', str(work/'key.pem'))
    nginx_conf = (f'load_module {cache}/root/usr/lib/nginx/modules/ngx_stream_module.so;\n'
                  f'pid {work}/nginx.pid;\nerror_log {work}/nginx-error.log;\n'
                  'worker_processes 1;\nevents { worker_connections 512; }\nstream {\n'+bodies+'\n}\n')
    (work/'nginx.conf').write_text(nginx_conf)
    checked([nginx, '-t', '-c', work/'nginx.conf', '-p', work])

    class Echo(socketserver.BaseRequestHandler):
        def handle(self):
            try:
                while data := self.request.recv(4096):
                    self.request.sendall(data)
            except OSError:
                pass
    class Server(socketserver.ThreadingTCPServer):
        allow_reuse_address = True
        daemon_threads = True
    echo = Server(('127.0.0.1', 2083), Echo)
    threading.Thread(target=echo.serve_forever, daemon=True).start()
    origin = Server(('127.0.0.1', 18443), Echo)
    server_ctx = ssl.SSLContext(ssl.PROTOCOL_TLS_SERVER)
    server_ctx.load_cert_chain(work/'cert.pem', work/'key.pem')
    origin.socket = server_ctx.wrap_socket(origin.socket, server_side=True)
    threading.Thread(target=origin.serve_forever, daemon=True).start()
    try:
        cs_distribution = next((cache/'crowdsec').glob('crowdsec-v*'))
        cs_config = yaml.safe_load((cache/'crowdsec-test/config.yaml').read_text())
        cs_config['db_config']['max_open_conns'] = 1
        (cache/'crowdsec-test/config.yaml').write_text(yaml.safe_dump(cs_config))
        launch('crowdsec', [cs_distribution/'cmd/crowdsec/crowdsec', '-c',
                           cache/'crowdsec-test/config.yaml'], limits['crowdsec'],
               dict(os.environ, GOMEMLIMIT=f"{min(int(limits['crowdsec']*.65), limits['crowdsec']-64)}MiB"))
        wait_port(18080)
        bouncer = next(p for p in (cache/'bouncer').rglob('crowdsec-firewall-bouncer') if p.is_file())
        launch('bouncer', [bouncer, '-c', cache/'crowdsec-test/bouncer.yaml'], limits['crowdsec_bouncer'],
               dict(os.environ, GOMEMLIMIT=f"{int(limits['crowdsec_bouncer']*.65)}MiB"))
        dns_values = dict(common, proxy_role='upstream', ansible_host='127.0.0.2', _dns_threads=1, _dns_cache_mb=1,
                          dns_resolver_port=1053, dns_resolver_dnssec=False,
                          _dns_allowed_clients=['192.0.2.1'], _dns_forwarders=['127.0.0.1@2053'])
        unbound_conf = render('roles/dns_resolver/templates/unbound.conf.j2', dns_values)
        unbound_conf += f'\nserver:\n    username: ""\n    chroot: ""\n    directory: "{work}"\n    pidfile: "{work}/unbound.pid"\n'
        (work/'unbound.conf').write_text(unbound_conf)
        checked([cache/'root/usr/sbin/unbound-checkconf', work/'unbound.conf'])
        launch('unbound', [cache/'root/usr/sbin/unbound', '-d', '-c', work/'unbound.conf'], limits['unbound'])
        wait_port(1053)
        for _ in range(100):
            if 'Starting tail' in (work/'crowdsec.log').read_text():
                break
            time.sleep(.1)
        else:
            raise RuntimeError('CrowdSec acquisition did not become ready')
        with (cache/'crowdsec-test/auth.log').open('a') as log:
            for i in range(2000):
                log.write(time.strftime('%b %d %H:%M:%S')+f' test sshd[1234]: Failed password for invalid user probe from 198.51.100.{i%200+1} port 12345 ssh2\n')
        launch('squid-up', [squid, '-n', 'aiproxytestup', '-N', '-f', work/'up.conf'], limits['squid'])
        launch('squid-access', [squid, '-n', 'aiproxytestaccess', '-N', '-f', work/'access.conf'], limits['squid'])
        launch('nginx', [nginx, '-c', work/'nginx.conf', '-p', work, '-g', 'daemon off;'], limits['nginx'])
        wait_port(3128)
        wait_port(3228)
        wait_port(9443)
        ctx = ssl._create_unverified_context()
        # Matrix can expose 443 publicly. An untrusted peer must be rejected at
        # our terminators even when the outer router/firewall accepts its TCP.
        for sni in ('transit.internal', 'max.ru', 'public-proxy.example'):
            raw = socket.socket()
            raw.settimeout(5)
            raw.bind(('127.0.0.2', 0))
            raw.connect(('127.0.0.1', 443))
            with ctx.wrap_socket(raw, server_hostname=sni) as denied:
                denied.sendall(b'CONNECT 127.0.0.1:18443 HTTP/1.1\r\nHost: origin.test\r\n\r\n')
                try:
                    reply = denied.recv(1024)
                except (ConnectionResetError, ssl.SSLError):
                    reply = b''
                assert not reply, (sni, reply)
        print('Private TLS terminators reject untrusted sources on shared public 443', flush=True)
        def tunnel():
            sock = socket.create_connection(('127.0.0.1', 3228), timeout=10)
            sock.sendall(b'PROXY TCP4 198.51.100.10 127.0.0.1 50000 3228\r\n'
                         b'CONNECT 127.0.0.1:18443 HTTP/1.1\r\nHost: 127.0.0.1:18443\r\n'
                         b'Proxy-Authorization: Basic bmF0aXZlOnRlc3QtcGFzc3dvcmQ=\r\n\r\n')
            header = b''
            while not header.endswith(b'\r\n\r\n'):
                chunk = sock.recv(1)
                if not chunk:
                    raise RuntimeError(header)
                header += chunk
            assert b' 200 ' in header, header
            return ctx.wrap_socket(sock, server_hostname='origin.test')

        def stream(_):
            with tunnel() as sock:
                payload = b'encrypted-range-payload'*1024
                for _ in range(12):
                    sock.sendall(payload)
                    received = b''
                    while len(received) < len(payload):
                        received += sock.recv(len(payload)-len(received))
                    assert received == payload
            return len(payload)*12
        with ThreadPoolExecutor(max_workers=min(48, transit_capacity)) as pool:
            count = sum(pool.map(stream, range(96)))
        print('CONNECT: 96 authenticated TLS tunnels, verified payload bytes', count, flush=True)
        # A graceful reload must not break a neighboring active tunnel.
        with tunnel() as sock:
            checked([nginx, '-s', 'reload', '-c', work/'nginx.conf', '-p', work])
            sock.sendall(b'after-reload')
            assert sock.recv(100) == b'after-reload'
        # Reproduce the former 60s relay cutoff without requiring Telegram DCs.
        with socket.create_connection(('127.0.0.1', 9443), timeout=10) as relay_sock:
            relay_sock.sendall(b'before-mobile-sleep')
            assert relay_sock.recv(100) == b'before-mobile-sleep'
            time.sleep(opts.idle_seconds)
            relay_sock.sendall(b'after-mobile-sleep')
            assert relay_sock.recv(100) == b'after-mobile-sleep'
        print('Telegram TLS relays: survived idle seconds', opts.idle_seconds, flush=True)
        # Validate the real mtg config and its connection admission independently.
        secret = 'ee'+'11'*16+'6d61782e7275'
        mtvalues = dict(common, mtproxy_secret_resolved=secret, mtproxy_max_connections=100,
                        mtproxy_effective_max_connections=concurrency, mtproxy_local_port=2084)
        (work/'mtg.toml').write_text(render('roles/mtproxy/templates/mtg.toml.j2', mtvalues))
        launch('mtg', [mtg, 'run', work/'mtg.toml'], limits['mtg'],
               dict(os.environ, GOMEMLIMIT=f"{int(limits['mtg']*.65)}MiB"))
        wait_port(2084)
        sockets = [socket.create_connection(('127.0.0.1',2084), timeout=2) for _ in range(160)]
        time.sleep(2)
        for sock in sockets:
            sock.close()
        time.sleep(11)
        wait_port(2084)
        print('mtg: accepts again after 160 incomplete handshakes, concurrency', concurrency, flush=True)
        bouncer_config = yaml.safe_load((cache/'crowdsec-test/bouncer.yaml').read_text())
        request = urllib.request.Request('http://127.0.0.1:18080/v1/decisions',
                                        headers={'X-Api-Key':bouncer_config['api_key']})
        with urllib.request.urlopen(request, timeout=5) as response:
            decisions = json.load(response)
        assert decisions, 'CrowdSec must detect the synthetic SSH brute-force burst'
        print('CrowdSec: live SSH detection and bouncer API validated, decisions',len(decisions),flush=True)
        for name, proc, group in processes:
            peaks[name] = int((group/'memory.peak').read_text())
            assert proc.poll() is None, (name, (work/f'{name}.log').read_text()[-3000:])
            events = dict(line.split() for line in (group/'memory.events').read_text().splitlines())
            assert events['oom_kill'] == '0', (name, events)
        peaks['aggregate'] = int((cgroup/'memory.peak').read_text())
        (work/'results.json').write_text(json.dumps(peaks, indent=2))
        print('Cgroup peak bytes:', json.dumps(peaks), flush=True)
        print('Artifacts:', work, flush=True)
    except Exception:
        for name, proc, group in processes:
            print(name, 'returncode', proc.poll(), 'memory.events', (group/'memory.events').read_text(), flush=True)
        print('Failure artifacts:', work, flush=True)
        raise
    finally:
        echo.shutdown()
        origin.shutdown()
        # Kill every test service before removing any cgroup. A delayed worker
        # reaping must not leave other services alive if one rmdir has to wait.
        for name, proc, group in reversed(processes):
            (group/'cgroup.kill').write_text('1')
        for name, proc, group in reversed(processes):
            proc.wait(timeout=10)
            for retry in range(100):
                try:
                    group.rmdir()
                    break
                except OSError:
                    if retry == 99:
                        raise
                    time.sleep(.05)
        cgroup.rmdir()


if __name__ == '__main__':
    main()
