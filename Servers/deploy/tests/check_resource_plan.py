"""Exercise the real Ansible preflight in a local fixture (no host mutation)."""
import os
from pathlib import Path
import subprocess
import tempfile

import yaml

DEPLOY = Path(__file__).resolve().parents[1]
PLAY = yaml.safe_load((DEPLOY/'playbook.yml').read_text())[0]
NAMES = {
    'Resolve inventory resource defaults without masking inventory values',
    'Calculate resource limits', 'Validate host resource shares',
    'Calculate the system and foreign memory reserve',
    'Calculate allocatable memory without exceeding physical RAM',
    'Calculate per-service memory limits', 'Bound workers by the service memory budget',
    'Validate worker counts and nginx connections against memory',
    'Sum planned memory limits for services deployed on this host',
    'Assert memory plan fits the node',
}
TASKS = [t for t in PLAY['pre_tasks'] if t.get('name') in NAMES]
assert len(TASKS) == len(NAMES)


def main():
    cases = [
        ('access900', True, dict(proxy_role='access')),
        ('upstream900', True, {}),
        ('upstream512', True, dict(ansible_memtotal_mb=512)),
        ('upstream400', False, dict(ansible_memtotal_mb=400)),
        ('large-node-still-capped', True, dict(ansible_memtotal_mb=4096)),
        ('oversized-shared-nginx', False, dict(proxy_memory_limits={'nginx':96})),
        ('unsafe-mtg-fds', False, dict(mtproxy_max_connections=4096)),
        ('shared-foreign-reserve', False, dict(shared_host=True,
                                             _proxy_foreign_memory={'reserved_mb':500})),
        ('shared-real-capacity', True, dict(shared_host=True,
                                           _proxy_foreign_memory={'reserved_mb':300})),
        ('long-connect-idle', True, dict(read_timeout='2 hours')),
        ('literal-400MB-cap', False, dict(proxy_memory_budget_mb=400)),
        ('inventory-foreign-reserve-honored', False, dict(mem_foreign_reserved_mb=600)),
    ]
    with tempfile.TemporaryDirectory(prefix='aiproxy-plan-') as temporary:
        fixture = Path(temporary)/'fixture.yml'
        for name, expected, override in cases:
            values = dict(PLAY['vars'], ansible_memtotal_mb=900, ansible_processor_vcpus=4,
                          proxy_role='upstream', shared_host=False, _proxy_nginx_needed=True,
                          mtproxy_enabled=True, crowdsec_enabled=True, enable_keepalived=False,
                          _proxy_foreign_memory={'reserved_mb':0}, read_timeout='1 hour')
            values.update(override)
            tasks = TASKS+([{'ansible.builtin.assert': {'that': [
                'mem_planned_mb | int <= 380',
                'squid_workers | int == 1',
                'proxy_nginx_workers | int == 1']}}] if expected else [])
            fixture.write_text(yaml.safe_dump([dict(name=name, hosts='localhost',
                connection='local', gather_facts=False, vars=values, tasks=tasks)], sort_keys=False))
            result = subprocess.run(['ansible-playbook', '-i', 'localhost,', str(fixture)],
                env=dict(os.environ, ANSIBLE_FILTER_PLUGINS=str(DEPLOY/'filter_plugins')),
                text=True, stdout=subprocess.PIPE, stderr=subprocess.STDOUT)
            if (result.returncode == 0) != expected:
                raise AssertionError(f'{name}: unexpected result\n{result.stdout}')
            print(name, 'PASS' if expected else 'REJECTED AS EXPECTED')


if __name__ == '__main__':
    main()
