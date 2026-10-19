#!/usr/bin/env python3
"""Synchronize Hub on expiry/drift; acknowledge only after CrowdSec was applied."""
import argparse
import fcntl
import hashlib
import json
import os
from pathlib import Path
import subprocess
import tempfile
import time

COLLECTIONS = ['crowdsecurity/linux', 'crowdsecurity/nginx', 'crowdsecurity/http-cve',
               'crowdsecurity/whitelist-good-actors']
ACTIVE_DIRS = ('collections', 'parsers', 'scenarios', 'postoverflows', 'contexts',
               'appsec-configs', 'appsec-rules', 'patterns')


def fingerprint(config, data, database=None):
    """Hash active content, including dependencies/data, but never the Hub index."""
    digest = hashlib.sha256()
    # Runtime SQLite storage is often inside data_dir. Its continuously changing
    # database/WAL/SHM are not Hub assets and must never invalidate the cache.
    databases = [data / 'crowdsec.db'] + ([Path(database)] if database else [])
    excluded = {str(Path(str(path) + suffix).resolve()) for path in databases
                for suffix in ('', '-wal', '-shm', '-journal')}
    for root in [config / name for name in ACTIVE_DIRS] + [data]:
        for path in sorted(root.rglob('*')):
            if not (path.is_file() or path.is_symlink()):
                continue
            if str(path.resolve()) in excluded:
                continue
            digest.update(str(path.relative_to(root.parent)).encode())
            digest.update(b'\0')
            try:
                with path.open('rb') as source:
                    for block in iter(lambda: source.read(65536), b''):
                        digest.update(block)
            except FileNotFoundError:
                digest.update(b'BROKEN_LINK')
            digest.update(b'\0')
    return digest.hexdigest()


def save(path, state):
    path.parent.mkdir(parents=True, exist_ok=True)
    with tempfile.NamedTemporaryFile(mode='w', dir=path.parent, delete=False) as output:
        json.dump(state, output, sort_keys=True)
        temporary = output.name
    os.chmod(temporary, 0o600)
    os.replace(temporary, path)


def installed_names(document):
    # cscli releases expose either an array or a hub category object.
    rows = document.get('collections') if isinstance(document, dict) else document
    if document is None or (isinstance(document, dict) and document.get('collections') is None and 'collections' in document):
        return set()
    if not isinstance(rows, list) or any(not isinstance(row, dict) or 'name' not in row for row in rows):
        raise ValueError('Неизвестный формат JSON cscli collections list')
    return {row['name'] for row in rows}


def synchronize(config, data, state_path, interval, force=False, cscli='cscli', ack=None, database=None):
    if interval < 0:
        raise ValueError('Интервал обновления Hub не может быть отрицательным')
    state_path.parent.mkdir(parents=True, exist_ok=True)
    with (state_path.parent / (state_path.name + '.lock')).open('a') as lock:
        fcntl.flock(lock, fcntl.LOCK_EX)
        try:
            state = json.loads(state_path.read_text())
        except (FileNotFoundError, json.JSONDecodeError):
            state = {}
        if not isinstance(state, dict):
            state = {}
        if database is None:
            database = state.get('database', '')
        current = fingerprint(config, data, database)
        if ack is not None:
            if current != ack or state.get('configured_digest') != ack:
                raise ValueError('Правила изменились во время применения CrowdSec; повторите деплоймент')
            state['applied_digest'] = ack
            save(state_path, state)
            return {'changed': False, 'synchronized': False, 'digest': current}
        now = time.time()
        age = now - state.get('checked_at', 0)
        due = (force or not 0 <= age < interval or state.get('collections') != COLLECTIONS
               or state.get('database', '') != database
               or state.get('configured_digest') != current
               or not any(path.is_file() for path in
                          (config / 'hub/.index.json', data.parent / 'hub/.index.json')))
        if due:
            # Preserve the last acknowledged digest before any operation can fail.
            # Partial upgrades and interruption before the handler remain observable.
            save(state_path, state)

            def run(*args):
                result = subprocess.run([cscli, *args], capture_output=True, text=True, timeout=180)
                if result.returncode:
                    raise RuntimeError(f'cscli {" ".join(args)}: {result.stderr.strip()}')
                return result.stdout

            run('hub', 'update')
            installed = installed_names(json.loads(run('collections', 'list', '-o', 'json')))
            missing = [name for name in COLLECTIONS if name not in installed]
            if missing:
                run('collections', 'install', *missing)
            run('collections', 'upgrade', '--all')
            # This includes parser/scenario/data changes even when the collection
            # version itself stays unchanged, and ignores JSON ordering/timestamps.
            current = fingerprint(config, data, database)
            state.update(checked_at=now, collections=COLLECTIONS, configured_digest=current, database=database)
            save(state_path, state)
        return {'changed': state.get('applied_digest') != current,
                'synchronized': due, 'digest': current}


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--config-dir', type=Path, default=Path('/etc/crowdsec'))
    parser.add_argument('--data-dir', type=Path, default=Path('/var/lib/crowdsec/data'))
    parser.add_argument('--state', type=Path, default=Path('/var/lib/aiproxy/crowdsec-hub.json'))
    parser.add_argument('--interval', type=int, default=21600)
    parser.add_argument('--force', action='store_true')
    parser.add_argument('--database', help='Runtime SQLite path from the effective CrowdSec config')
    parser.add_argument('--ack')
    args = parser.parse_args()
    print(json.dumps(synchronize(args.config_dir, args.data_dir, args.state,
                                 args.interval, args.force, ack=args.ack, database=args.database)))


if __name__ == '__main__':
    main()
