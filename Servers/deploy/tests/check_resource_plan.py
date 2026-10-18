"""Exercise the real Ansible preflight in a local fixture (no host mutation)."""
import os
from pathlib import Path
import subprocess
import tempfile

import yaml

DEPLOY = Path(__file__).resolve().parents[1]
PLAY = yaml.safe_load((DEPLOY/'playbook.yml').read_text())[0]
NAMES = {
    'Определить параметры ресурсов с учётом inventory',
    'Рассчитать системные пределы ресурсов', 'Проверить доли памяти и резервы узла',
    'Рассчитать резерв памяти ОС и соседних приложений',
    'Определить включённые службы и фиксированные пределы памяти',
    'Рассчитать минимальную потребность служб в памяти',
    'Рассчитать потолок памяти проекта по RAM узла',
    'Рассчитать доступную память с учётом физических ограничений',
    'Рассчитать пределы памяти каждой службы', 'Ограничить число рабочих процессов бюджетом памяти',
    'Распределить бюджет памяти между включёнными службами',
    'Проверить число рабочих процессов и соединений по бюджету памяти',
    'Подсчитать сумму пределов памяти служб узла',
    'Проверить размещение плана памяти на узле',
    'Показать полный план памяти узла',
}
TASKS = [t for t in PLAY['pre_tasks'] if t.get('name') in NAMES]
assert len(TASKS) == len(NAMES)


def main():
    cases = [
        ('access900', True, dict(proxy_role='access', ansible_memtotal_mb=900)),
        ('upstream900', True, dict(ansible_memtotal_mb=900)),
        ('access961', True, dict(proxy_role='access', ansible_memtotal_mb=961, expected_budget_mb=368)),
        ('upstream961', True, dict(ansible_memtotal_mb=961, expected_budget_mb=400)),
        ('access1967', True, dict(proxy_role='access', ansible_memtotal_mb=1967, expected_budget_mb=655)),
        ('upstream512', False, dict(ansible_memtotal_mb=512)),
        ('upstream400', False, dict(ansible_memtotal_mb=400)),
        ('minimum-full-profile', True, dict(ansible_memtotal_mb=1200)),
        ('below-one-third-threshold', True, dict(ansible_memtotal_mb=1199)),
        ('physical-ram-boundary', True, dict(ansible_memtotal_mb=534)),
        ('below-physical-ram-boundary', False, dict(ansible_memtotal_mb=533)),
        ('two-gib-host', True, dict(ansible_memtotal_mb=2048)),
        ('large-node-still-capped', True, dict(ansible_memtotal_mb=4096)),
        ('very-large-node-still-capped', True, dict(ansible_memtotal_mb=16384)),
        ('fixed-nginx-respected-above-target', True, dict(proxy_memory_limits={'nginx':96}, expected_budget_mb=448)),
        ('minima-cannot-exceed-one-gb', False, dict(proxy_memory_limits={'nginx':1024})),
        ('mtg-request-bounded-by-ram-and-fds', True, dict(mtproxy_max_connections=4096)),
        ('invalid-mtg-limit', False, dict(mtproxy_max_connections=0)),
        ('shared-foreign-reserve', False, dict(shared_host=True,
                                             _proxy_foreign_memory={'reserved_mb':700})),
        ('shared-real-capacity', True, dict(shared_host=True,
                                           _proxy_foreign_memory={'reserved_mb':300})),
        ('long-connect-idle', True, dict(read_timeout='2 hours')),
        ('inventory-budget-is-only-a-ceiling', True, dict(proxy_memory_budget_mb=600)),
        ('explicit-lower-ceiling', True, dict(ansible_memtotal_mb=1536, proxy_memory_budget_mb=440)),
        ('explicit-ceiling-too-small-for-full-profile', False, dict(proxy_memory_budget_mb=200)),
        ('inventory-foreign-reserve-honored', False, dict(mem_foreign_reserved_mb=600)),
    ]
    with tempfile.TemporaryDirectory(prefix='aiproxy-plan-') as temporary:
        fixture = Path(temporary)/'fixture.yml'
        for name, expected, override in cases:
            values = dict(PLAY['vars'], ansible_memtotal_mb=1200, ansible_processor_vcpus=4,
                          proxy_role='upstream', shared_host=False, _proxy_nginx_needed=True,
                          mtproxy_enabled=True, crowdsec_enabled=True, enable_keepalived=False,
                          _proxy_foreign_memory={'reserved_mb':0}, read_timeout='1 hour', mtproxy_max_connections=100)
            values.update(override)
            tasks = TASKS+([{'ansible.builtin.assert': {'that': [
                'mem_planned_mb | int * 1048576 <= [ansible_memtotal_mb | int * 1048576 // 3, _proxy_minimum_plan.minimum_mb | int * 1048576] | max',
                'mem_planned_mb | int * 1048576 <= 1000000000',
                'mem_planned_mb | int == _proxy_memory_plan.total_mb | int',
                'expected_budget_mb is not defined or mem_planned_mb | int == expected_budget_mb | int',
                'mem_planned_mb | int + mem_system_reserved_mb | int + mem_foreign_effective_mb | int <= ansible_memtotal_mb | int',
                'mtproxy_effective_max_connections | int <= mtproxy_max_connections | int',
                'mtproxy_effective_max_connections | int * 4 + 256 <= 4096']}}] if expected else [])
            fixture.write_text(yaml.safe_dump([dict(name=name, hosts='localhost',
                connection='local', gather_facts=False, vars=values, tasks=tasks)], sort_keys=False))
            result = subprocess.run(['ansible-playbook', '-i', 'localhost,', str(fixture)],
                env=dict(os.environ, ANSIBLE_FILTER_PLUGINS=str(DEPLOY/'filter_plugins')),
                text=True, stdout=subprocess.PIPE, stderr=subprocess.STDOUT)
            if (result.returncode == 0) != expected:
                raise AssertionError(f'{name}: unexpected result\n{result.stdout}')
            if expected and name == 'access961':
                assert 'MTProxy 32' not in result.stdout, 'Disabled MTProxy must not be reported as allocated'
            print(name, 'PASS' if expected else 'REJECTED AS EXPECTED')


if __name__ == '__main__':
    main()
