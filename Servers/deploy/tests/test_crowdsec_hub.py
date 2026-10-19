"""Hub updates, drift and interrupted application using real files/CLI calls."""
import importlib.util
import copy
import json
import os
from pathlib import Path
import shutil
import tempfile
import subprocess
import unittest

import yaml

DEPLOY = Path(__file__).resolve().parents[1]


@unittest.skipUnless(os.name == 'posix', 'Linux Hub synchronization')
class CrowdSecHubTests(unittest.TestCase):
    def setUp(self):
        spec = importlib.util.spec_from_file_location('crowdsec_sync', DEPLOY / 'scripts/sync-crowdsec-hub.py')
        self.hub = importlib.util.module_from_spec(spec)
        spec.loader.exec_module(self.hub)
        self.temporary = tempfile.TemporaryDirectory(prefix='aiproxy-hub-')
        self.addCleanup(self.temporary.cleanup)
        self.root = Path(self.temporary.name)
        self.config, self.data = self.root / 'etc', self.root / 'data'
        self.config.mkdir()
        self.data.mkdir()
        (self.config / 'hub').mkdir()
        (self.config / 'hub/.index.json').write_text('{}')
        (self.config / 'parsers').mkdir()
        self.parser = self.config / 'parsers/http.yaml'
        self.parser.write_text('version: 1\n')
        self.state = self.root / 'state/hub.json'
        self.calls = self.root / 'calls'
        self.cli = self.root / 'cscli'
        self.cli.write_text('''#!/usr/bin/env python3
import json, pathlib, sys
root = pathlib.Path(__file__).parent
args = sys.argv[1:]
with (root / 'calls').open('a') as calls: calls.write(json.dumps(args) + '\\n')
if (root / 'fail').exists() and args[:2] == ['collections', 'upgrade']:
    (root / 'etc/parsers/http.yaml').write_text('partially changed\\n')
    sys.exit(2)
if args[:2] == ['collections', 'list']:
    path = root / 'installed'
    names = json.loads(path.read_text()) if path.exists() else []
    names = [name for name in names if (root / 'etc/collections' / (name.split('/')[-1] + '.yaml')).exists()]
    print(json.dumps({'collections': [{'name': name, 'local_version': '1', 'status': 'enabled'} for name in names]}))
elif args[:2] == ['collections', 'install']:
    old = json.loads((root / 'installed').read_text()) if (root / 'installed').exists() else []
    (root / 'installed').write_text(json.dumps(sorted(set(old + args[2:]))))
    folder = root / 'etc/collections'
    folder.mkdir(exist_ok=True)
    for name in args[2:]: (folder / (name.split('/')[-1] + '.yaml')).write_text('version: 1\\n')
elif args[:2] == ['collections', 'upgrade'] and (root / 'upgrade-parser').exists():
    (root / 'etc/parsers/http.yaml').write_text('version: 2\\n')
''')
        self.cli.chmod(0o755)

    def sync(self, **kwargs):
        return self.hub.synchronize(self.config, self.data, self.state, kwargs.pop('interval', 21600),
                                    cscli=str(self.cli), **kwargs)

    def commands(self):
        return [json.loads(line) for line in self.calls.read_text().splitlines()]

    def applied(self):
        result = self.sync()
        self.sync(ack=result['digest'])
        return result

    def test_second_deployment_has_zero_cscli_calls_or_restart(self):
        first = self.applied()
        self.assertTrue(first['changed'])
        self.assertEqual(len(self.commands()), 4)  # update, list, one install, upgrade
        self.assertEqual(sum(row[:2] == ['collections', 'install'] for row in self.commands()), 1)
        before = self.state.read_bytes()
        self.assertEqual(self.sync(), {'changed': False, 'synchronized': False, 'digest': first['digest']})
        self.assertEqual(len(self.commands()), 4)
        self.assertEqual(self.state.read_bytes(), before)

    def test_expired_or_forced_check_without_content_change_does_not_restart(self):
        self.applied()
        for kwargs in ({'force': True}, {'interval': 0}):
            result = self.sync(**kwargs)
            self.assertTrue(result['synchronized'])
            self.assertFalse(result['changed'])
        self.assertEqual(len(self.commands()), 10)  # no reinstallation

    def test_parser_dependency_update_triggers_apply_with_same_collection_version(self):
        self.applied()
        (self.root / 'upgrade-parser').touch()
        result = self.sync(force=True)
        self.assertTrue(result['changed'])
        self.assertIn('version: 2', self.parser.read_text())

    def test_missing_active_file_and_data_drift_bypass_fresh_cache(self):
        self.applied()
        (self.config / 'collections/nginx.yaml').unlink()
        self.assertTrue(self.sync()['synchronized'])
        self.assertTrue((self.config / 'collections/nginx.yaml').exists())
        self.applied()
        (self.data / 'allowlist.txt').write_text('updated data')
        self.assertTrue(self.sync()['synchronized'])

    def test_interrupted_apply_is_remembered_without_repeating_network_work(self):
        first = self.sync()
        second = self.sync()
        self.assertTrue(second['changed'])
        self.assertFalse(second['synchronized'])
        self.assertEqual(first['digest'], second['digest'])
        self.assertEqual(len(self.commands()), 4)
        self.sync(ack=second['digest'])
        self.assertFalse(self.sync()['changed'])

    def test_partial_failure_does_not_advance_cache_and_remains_pending(self):
        self.applied()
        before = json.loads(self.state.read_text())['checked_at']
        (self.root / 'fail').touch()
        with self.assertRaises(RuntimeError):
            self.sync(force=True)
        self.assertEqual(json.loads(self.state.read_text())['checked_at'], before)
        (self.root / 'fail').unlink()
        self.assertTrue(self.sync()['changed'])

    def test_acknowledgement_rejects_files_changed_during_apply(self):
        result = self.sync()
        self.parser.write_text('concurrent change')
        with self.assertRaises(ValueError):
            self.sync(ack=result['digest'])

    def test_runtime_database_and_journals_never_invalidate_hub_cache(self):
        database = self.data / 'custom-runtime.sqlite'
        result = self.sync(database=str(database))
        self.sync(ack=result['digest'])
        for base in (database, self.data / 'crowdsec.db'):
            for suffix in ('', '-wal', '-shm', '-journal'):
                Path(str(base) + suffix).write_text('active runtime storage')
        self.assertEqual(self.sync(), {'changed': False, 'synchronized': False, 'digest': result['digest']})
        self.assertEqual(len(self.commands()), 4)

    def test_json_variants_and_empty_installation(self):
        self.assertEqual(self.hub.installed_names([{'name': 'test'}]), {'test'})
        self.assertEqual(self.hub.installed_names({'collections': None}), set())
        with self.assertRaises(ValueError):
            self.hub.installed_names({'unknown': []})

    def test_real_role_tasks_apply_once_then_noop_and_forced_check_without_restart(self):
        source = yaml.safe_load((DEPLOY / 'roles/crowdsec/tasks/main.yml').read_text())
        names = {'Проверить интервал обновления Hub CrowdSec', 'Разместить синхронизацию Hub CrowdSec',
                 'Синхронизировать Hub CrowdSec при истечении срока или дрейфе правил',
                 'Применить ожидающие изменения CrowdSec до завершения роли'}
        tasks = copy.deepcopy([task for task in source if task['name'] in names])
        helper, wrapper = self.root / 'helper', self.root / 'wrapper'
        wrapper.write_text(f'#!/bin/sh\nexec "{helper}" --config-dir "{self.config}" --data-dir "{self.data}" --state "{self.state}" "$@"\n')
        wrapper.chmod(0o755)
        for task in tasks:
            if 'ansible.builtin.copy' in task:
                task['ansible.builtin.copy'].update(src=str(DEPLOY / 'scripts/sync-crowdsec-hub.py'), dest=str(helper))
            if 'ansible.builtin.command' in task:
                task['ansible.builtin.command']['argv'] = task['ansible.builtin.command']['argv'].replace('/usr/local/sbin/aiproxy-crowdsec-hub', str(wrapper))
        apply = yaml.safe_load((DEPLOY / 'roles/crowdsec/tasks/apply.yml').read_text())
        # Only the actual engine restart is replaced; the real handler ordering,
        # validation command and acknowledgement are exercised by Ansible.
        apply[1] = {'ansible.builtin.command': str(self.root / 'restart')}
        apply[2]['ansible.builtin.command']['argv'][0] = str(wrapper)
        role = self.root / 'roles/crowdsec'
        (role / 'tasks').mkdir(parents=True)
        (role / 'handlers').mkdir()
        (role / 'tasks/apply.yml').write_text(yaml.safe_dump(apply, allow_unicode=True))
        (role / 'tasks/main.yml').write_text(yaml.safe_dump(tasks, allow_unicode=True))
        shutil.copyfile(DEPLOY / 'roles/crowdsec/handlers/main.yml', role / 'handlers/main.yml')
        (self.root / 'crowdsec').write_text('#!/bin/sh\nexit 0\n')
        (self.root / 'crowdsec').chmod(0o755)
        (self.root / 'restart').write_text(f'#!/bin/sh\necho restart >> "{self.root / "restarts"}"\n')
        (self.root / 'restart').chmod(0o755)
        for force in (False, False, True):
            play = [{'hosts': 'localhost', 'connection': 'local', 'gather_facts': False,
                     'environment': {'PATH': str(self.root) + ':' + os.environ['PATH']},
                     'vars': {'crowdsec_hub_update_interval': 21600, 'crowdsec_hub_force_update': force,
                              '_crowdsec_packages': {'changed': False},
                              '_crowdsec_base_config': {'content': 'ZGJfY29uZmlnOiB7dHlwZTogc3FsaXRlfQ=='},
                              '_crowdsec_local_config': {}},
                     'tasks': [{'ansible.builtin.include_role': {'name': 'crowdsec'}}]}]
            (self.root / 'play.yml').write_text(yaml.safe_dump(play, allow_unicode=True))
            result = subprocess.run(['ansible-playbook', '-i', 'localhost,', str(self.root / 'play.yml')],
                                    capture_output=True, text=True, timeout=30)
            self.assertEqual(result.returncode, 0, result.stdout + result.stderr)
            self.assertEqual((self.root / 'restarts').read_text().splitlines(), ['restart'])
            if not force:
                self.assertEqual(len(self.commands()), 4)
        self.assertEqual(len(self.commands()), 7)


if __name__ == '__main__':
    unittest.main()
