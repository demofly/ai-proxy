"""Exercise actual role tasks against private files, preserving neighbor settings."""
import os
from pathlib import Path
import subprocess
import tempfile

import yaml

DEPLOY = Path(__file__).resolve().parents[1]
ROLE = yaml.safe_load((DEPLOY/'roles/crowdsec/tasks/main.yml').read_text())
START = next(i for i, task in enumerate(ROLE) if task.get('name') == 'Read CrowdSec base configuration')
TASKS = ROLE[START:START+5]
assert TASKS[-1]['name'] == 'Bound the CrowdSec SQLite pool without replacing other local settings'


def main():
    with tempfile.TemporaryDirectory(prefix='aiproxy-crowdsec-') as temporary:
        directory = Path(temporary)
        base = directory/'config.yaml'
        local = directory/'config.yaml.local'
        fixture = directory/'fixture.yml'
        for case in ('sqlite-new', 'sqlite-existing', 'postgres-existing'):
            base.write_text(yaml.safe_dump({'db_config': {'type':'sqlite', 'db_path':'/unchanged.db'},
                                           'api': {'server': {'listen_uri':'127.0.0.1:8080'}}}))
            original = {} if case == 'sqlite-new' else {
                'api': {'server': {'listen_uri':'127.0.0.1:18080'}},
                'db_config': {'type':'postgres' if case == 'postgres-existing' else 'sqlite',
                              'max_open_conns':17, 'custom_field':'preserve'},
                'prometheus': {'enabled':True}}
            if local.exists():
                local.unlink()
            if original:
                local.write_text(yaml.safe_dump(original))
            tasks = yaml.safe_load(yaml.safe_dump(TASKS).replace('/etc/crowdsec/config.yaml', str(base)))
            fixture.write_text(yaml.safe_dump([dict(hosts='localhost', gather_facts=False,
                tasks=tasks, handlers=[{'name':'Restart crowdsec', 'ansible.builtin.debug':
                                      {'msg':'Fixture: restart notification received'}}])]))
            outputs = []
            for _ in range(2):
                result = subprocess.run(['ansible-playbook','-i','localhost,','-c','local',str(fixture)],
                    text=True, stdout=subprocess.PIPE, stderr=subprocess.STDOUT)
                if result.returncode:
                    raise AssertionError(result.stdout)
                outputs.append(local.read_bytes())
            expected = dict(original)
            if case != 'postgres-existing':
                expected['db_config'] = dict(original.get('db_config', {}), max_open_conns=1)
            assert yaml.safe_load(outputs[0]) == expected, case
            assert outputs[0] == outputs[1], (case, 'second apply must be idempotent')
            print(case, 'preserved settings and idempotence PASS')


if __name__ == '__main__':
    main()
