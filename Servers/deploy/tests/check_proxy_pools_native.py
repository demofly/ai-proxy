# [AITS] 2026-11-06T15:09:32Z
# AI-GENERATED — NOT REVIEWED: SECTION START
"""Нативная проверка пулов на настоящем Squid: userhash выбирает пира только среди
разрешённых cache_peer_access, а пользователь вне пулов получает 403.

Запуск (WSL, без root): python3 tests/check_proxy_pools_native.py [--cache ~/.cache/ai-proxy-validation]
Кеш готовит tests/prepare_native_validation.py. Внешние адреса не затрагиваются:
родители — локальные HTTP-серверы на 127.0.0.1, пароли синтетические.

Сценарии:
- контроль: без cache_peer_access пользователи каждого пула расходятся по обоим пирам
  (иначе наблюдения ниже ничего не доказывали бы);
- GET и CONNECT: пользователи пула pa только на up-a, пула pb только на up-b,
  члены обеих групп — на объединении (видны оба пира);
- пул без upstream и пользователь вне пулов — 403, без учётных данных — 407;
- allow_direct_fallback=true: CONNECT по-прежнему идёт через пиров своего пула.
"""
import argparse
import base64
from collections import Counter
import contextlib
from datetime import datetime, timezone
import http.client
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
import importlib.util
import os
from pathlib import Path
import shutil
import socket
import subprocess
import sys
import tempfile
import threading
import time

import jinja2

DEPLOY = Path(__file__).resolve().parents[1]
REPEATS = 20  # число повторов GET на пользователя: выбор пира должен быть устойчив
CONNECTS = 3  # число повторов CONNECT на пользователя
GROUP_SIZE = 12  # пользователей в группе: шанс, что контроль не различит пиров, ниже 1/2000
UPSTREAMS = ['up-a', 'up-b']
BOTH = {(200, 'up-a'), (200, 'up-b')}


def load(name):
    spec = importlib.util.spec_from_file_location(name, DEPLOY / 'filter_plugins' / (name + '.py'))
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def user_names():
    """Группы пользователей проверки: ga -> up-a, gb -> up-b, gu -> оба, gd -> пул без upstream."""
    names = {prefix: [f'{prefix}{n}' for n in range(GROUP_SIZE)] for prefix in ('alice', 'bob', 'carol')}
    return names, ['dave'], ['erin']


def free_port():
    # Порт, выданный ядром для привязки к 127.0.0.1; до запуска служб он свободен.
    with socket.socket() as sock:
        sock.bind(('127.0.0.1', 0))
        return sock.getsockname()[1]


def parent_server(label):
    """Родитель-заглушка: на GET отвечает своим именем, на CONNECT пишет имя в туннель."""
    class Handler(BaseHTTPRequestHandler):
        def do_GET(self):
            body = label.encode()
            self.send_response(200)
            self.send_header('Content-Length', str(len(body)))
            self.send_header('Cache-Control', 'no-store')
            self.end_headers()
            self.wfile.write(body)

        def do_CONNECT(self):
            self.send_response(200, 'Connection established')
            self.end_headers()
            self.wfile.write(label.encode())

        def log_message(self, *args):
            pass

    server = ThreadingHTTPServer(('127.0.0.1', 0), Handler)
    threading.Thread(target=server.serve_forever, daemon=True).start()
    return server


def apr1(password):
    # Формат $apr1$ понимает basic_ncsa_auth; хэш считает openssl.
    return subprocess.run(['openssl', 'passwd', '-apr1', password], check=True,
                          capture_output=True, text=True).stdout.strip()


def render_config(work, ports, root, fallback=False, strip_peer_access=False):
    """Рендерит боевой шаблон access и подменяет пути на рабочий каталог проверки."""
    helper = root / 'usr/lib/squid/basic_ncsa_auth'
    resources = load('resources')
    pools = load('pools')
    members, idle, _ = user_names()
    # Члены gu состоят в двух пулах: их набор upstream — объединение.
    groups = {'ga': members['alice'], 'gb': members['bob'], 'gu': members['carol'], 'gd': idle}
    pool_defs = [{'name': 'pa', 'groups': ['ga', 'gu'], 'upstreams': ['up-a']},
                 {'name': 'pb', 'groups': ['gb', 'gu'], 'upstreams': ['up-b']},
                 {'name': 'empty', 'groups': ['gd'], 'upstreams': []}]
    env = jinja2.Environment(trim_blocks=True, keep_trailing_newline=True)
    env.filters['bool'] = resources.as_bool
    values = dict(
        ansible_managed='native pool check', inventory_hostname='access-native', ansible_host='127.0.0.1',
        enable_caching=False, enable_logging=False, enable_auth=True, nginx_on_443=False,
        squid_transit_tls=False, proxy_port=ports['squid'], squid_mgmt_port=ports['mgmt'],
        squid_workers=1, squid_fd_limit=1024, mem_squid_mb=64, allow_direct_fallback=fallback,
        allowed_domains=[], allowed_domain_patterns=[],
        groups={'upstreams': UPSTREAMS},
        hostvars={name: {'ansible_host': '127.0.0.1', 'proxy_port': ports[name]} for name in UPSTREAMS},
        _squid_pools=pools.aiproxy_pools(pool_defs, groups, UPSTREAMS))
    template = (DEPLOY / 'templates/squid-access.conf.j2').read_text(encoding='utf-8')
    text = env.from_string(template).render(values)
    if strip_peer_access:
        # Контроль: без ограничений пиров userhash обязан расходиться по обоим пирам.
        text = ''.join(line + '\n' for line in text.splitlines() if not line.startswith('cache_peer_access '))
    # Подмена боевых путей и привязки на рабочий каталог проверки.
    text = text.replace('/usr/lib/squid/basic_ncsa_auth /etc/squid/passwd', f'{helper} {work}/passwd')
    text = text.replace(f'http_port {ports["squid"]} ', f'http_port 127.0.0.1:{ports["squid"]} ')
    text = text.replace('cache_log /dev/null', f'cache_log {work}/cache.log')
    text += f'\npid_filename {work}/squid.pid\ncoredump_dir {work}\n'
    share = root / 'usr/share/squid'
    text += f'error_directory {share}/errors/templates\nicon_directory {share}/icons\n'
    text += f'mime_table {share}/mime.conf\nunlinkd_program {root}/usr/lib/squid/unlinkd\n'
    text += 'pinger_enable off\n'
    return text


def auth_header(user, password):
    return 'Basic ' + base64.b64encode(f'{user}:{password}'.encode()).decode()


def request(port, user=None, password='', attempt=0):
    """Один GET через Squid; возвращает (код, тело)."""
    headers = {} if user is None else {'Proxy-Authorization': auth_header(user, password)}
    conn = http.client.HTTPConnection('127.0.0.1', port, timeout=10)
    try:
        conn.request('GET', f'http://127.0.0.1:9/probe-{attempt}', headers=headers)
        response = conn.getresponse()
        return response.status, response.read().decode(errors='replace')
    finally:
        conn.close()


def connect(port, user, password):
    """Один CONNECT через Squid; возвращает (код, первые байты туннеля — имя родителя)."""
    sock = socket.create_connection(('127.0.0.1', port), timeout=10)
    try:
        sock.sendall((f'CONNECT example.test:443 HTTP/1.1\r\nHost: example.test:443\r\n'
                      f'Proxy-Authorization: {auth_header(user, password)}\r\n\r\n').encode())
        sock.settimeout(3)
        data = b''
        try:
            while True:
                chunk = sock.recv(4096)
                if not chunk:
                    break
                data += chunk
                head, sep, body = data.partition(b'\r\n\r\n')
                # 200 — ждём имя родителя в теле туннеля; иной код — тело ответа ошибки не нужно.
                if sep and (b' 200 ' not in head.split(b'\r\n')[0] or len(body) >= 4):
                    break
        except socket.timeout:
            pass
    finally:
        sock.close()
    head, _, body = data.partition(b'\r\n\r\n')
    status = int(head.split(b' ')[1]) if head.startswith(b'HTTP/') else 0
    return status, body.decode(errors='replace')[:4]


def wait_port(port):
    for _ in range(100):
        try:
            with socket.create_connection(('127.0.0.1', port), timeout=.2):
                return True
        except OSError:
            time.sleep(.1)
    return False


class Stats:
    """Счётчик запросов и перечень нарушений для итоговых метрик (§1.4.8)."""
    def __init__(self):
        self.total = 0
        self.failures = []

    def expect(self, ok, text):
        if not ok:
            self.failures.append(text)


@contextlib.contextmanager
def running_squid(squid, root, work, config):
    """Запускает Squid с заданной конфигурацией и гарантированно гасит его."""
    (work / 'squid.conf').write_text(config, encoding='utf-8', newline='\n')
    env = dict(os.environ, LD_LIBRARY_PATH=str(root / 'usr/lib/x86_64-linux-gnu'))
    process = subprocess.Popen([str(squid), '-N', '-f', str(work / 'squid.conf')], env=env,
                               stdout=subprocess.PIPE, stderr=subprocess.STDOUT, text=True)
    try:
        yield process
    finally:
        if process.poll() is None:
            process.terminate()
            try:
                process.wait(timeout=10)
            except subprocess.TimeoutExpired:
                process.kill()


def answers(port, user, password, how, repeats):
    """Счётчик (код, тело) по повторам GET либо CONNECT одного пользователя."""
    seen = Counter()
    for attempt in range(repeats):
        seen[request(port, user, password, attempt) if how == 'GET' else connect(port, user, password)] += 1
    return seen


def check_control(port, passwords, stats):
    """Контроль: без cache_peer_access группы расходятся по обоим пирам, иначе проверки пусты."""
    members, _, _ = user_names()
    for group, other in (('alice', 'up-b'), ('bob', 'up-a')):
        reached = set()
        for user in members[group]:
            reached |= set(answers(port, user, passwords[user], 'GET', 1))
            stats.total += 1
        print(f'контроль {group}*: без cache_peer_access получены {sorted(reached)}')
        stats.expect((200, other) in reached, f'контроль: {group}* ни разу не попал на {other}')


def check_routing(port, passwords, stats, how, repeats):
    """Пользователи pa -> только up-a, pb -> только up-b, члены обеих -> объединение."""
    members, _, _ = user_names()
    for group, only in (('alice', 'up-a'), ('bob', 'up-b')):
        for user in members[group]:
            seen = answers(port, user, passwords[user], how, repeats)
            stats.total += repeats
            stats.expect(set(seen) == {(200, only)}, f'{how} {user} всегда {only}: получено {dict(seen)}')
    union = Counter()
    for user in members['carol']:
        seen = answers(port, user, passwords[user], how, repeats)
        stats.total += repeats
        union.update(seen)
        stats.expect(set(seen) <= BOTH, f'{how} {user} только из up-a, up-b: получено {dict(seen)}')
    print(f'{how} объединение carol*: {dict(union)}')
    stats.expect(set(union) == BOTH, f'{how} carol* должны быть видны на обоих пирах: {dict(union)}')


def check_denials(port, passwords, stats):
    """Пул без upstream, пользователь вне пулов, без учётных данных, неверный пароль."""
    for label, user, password, want in (
            ('dave (пул без upstream) -> 403', 'dave', passwords['dave'], 403),
            ('erin (вне пулов) -> 403', 'erin', passwords['erin'], 403),
            ('без учётных данных -> 407', None, '', 407),
            ('неверный пароль -> 407', 'alice0', 'wrong-password', 407)):
        status, _ = request(port, user, password)
        stats.total += 1
        print(f'{label}: {status}')
        stats.expect(status == want, f'{label}: получено {status}')
    status, _ = connect(port, 'erin', passwords['erin'])
    stats.total += 1
    print(f'CONNECT erin (вне пулов) -> 403: {status}')
    stats.expect(status == 403, f'CONNECT erin: получено {status}')


def run_scenarios(squid, root, work, ports, passwords, stats):
    """Три запуска Squid: контроль, основная конфигурация, режим allow_direct_fallback."""
    runs = (('контроль без cache_peer_access', dict(strip_peer_access=True)),
            ('основная конфигурация', {}),
            ('allow_direct_fallback=true', dict(fallback=True)))
    for title, options in runs:
        print(f'--- {title}')
        with running_squid(squid, root, work, render_config(work, ports, root, **options)) as process:
            if not wait_port(ports['squid']):
                process.terminate()
                stats.failures.append(f'{title}: Squid не запустился: ' + process.communicate(timeout=10)[0][-2000:])
                return
            if 'strip_peer_access' in options:
                check_control(ports['squid'], passwords, stats)
                continue
            if not options:
                check_routing(ports['squid'], passwords, stats, 'GET', REPEATS)
                check_denials(ports['squid'], passwords, stats)
            check_routing(ports['squid'], passwords, stats, 'CONNECT', CONNECTS)


def setup_fixtures(work, servers):
    """Поднимает родителей, выбирает порты, пишет passwd; возвращает (порты, пароли)."""
    ports = {'squid': free_port(), 'mgmt': free_port()}
    for name in UPSTREAMS:
        server = parent_server(name)
        servers.append(server)
        ports[name] = server.server_address[1]
    members, idle, outside = user_names()
    everyone = [u for group in members.values() for u in group] + idle + outside
    passwords = {user: f'synthetic-{user}-pw' for user in everyone}
    (work / 'passwd').write_text(''.join(f'{u}:{apr1(p)}\n' for u, p in passwords.items()),
                                 encoding='utf-8', newline='\n')
    return ports, passwords


def report(stats, started):
    """Печатает метрики прогона (§1.4.8) и нарушения; возвращает код выхода."""
    elapsed = time.monotonic() - started
    print(f'Запросов: {stats.total}; длительность: {elapsed:.2f} с; скорость: {stats.total / elapsed:.1f} запр/с')
    for line in stats.failures:
        print('НАРУШЕНИЕ:', line)
    print('Итог: нарушений', len(stats.failures))
    return 1 if stats.failures else 0


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument('--cache', type=Path, default=Path.home() / '.cache/ai-proxy-validation')
    opts = parser.parse_args()
    root = opts.cache / 'root'
    squid = root / 'usr/sbin/squid'
    if not squid.exists() or not (root / 'usr/lib/squid/basic_ncsa_auth').exists():
        print(f'Нет нативного Squid в {root}: выполните tests/prepare_native_validation.py', file=sys.stderr)
        return 2
    started = time.monotonic()
    print('Начало:', datetime.now(timezone.utc).strftime('%Y-%m-%dT%H:%M:%SZ'))
    work = Path(tempfile.mkdtemp(prefix='pools-native-'))
    servers, stats = [], Stats()
    try:
        ports, passwords = setup_fixtures(work, servers)
        run_scenarios(squid, root, work, ports, passwords, stats)
    finally:
        for server in servers:
            server.shutdown()
        shutil.rmtree(work, ignore_errors=True)
    return report(stats, started)


if __name__ == '__main__':
    sys.exit(main())
# AI-GENERATED — NOT REVIEWED: SECTION END
