"""Run real nginx worker tasks/handlers in isolated roles, with fake systemctl.

No packages, production configuration or real services are touched. In particular,
mtproxy must work without the access-only nginx role registering its handlers.
"""
from pathlib import Path
import shutil
import subprocess
import tempfile

import yaml

DEPLOY = Path(__file__).resolve().parents[1]
TASK_NAME = 'Ограничить число рабочих процессов общего nginx бюджетом памяти'


def main():
    with tempfile.TemporaryDirectory(prefix='aiproxy-handlers-') as temporary:
        root = Path(temporary)
        binaries = root/'bin'
        binaries.mkdir()
        systemctl = binaries/'systemctl'
        systemctl.write_text('#!/bin/sh\n'
            'printf "%s\\n" "$*" >> "$AIPROXY_TEST_CALLS"\n'
            'case "$*" in\n'
            '  "reset-failed nginx"|"is-active --quiet nginx"|"reload nginx") exit 0 ;;\n'
            '  *) exit 89 ;;\n'
            'esac\n')
        systemctl.chmod(0o755)
        for role in ('mtproxy', 'nginx'):
            role_path = root/'roles'/role
            (role_path/'tasks').mkdir(parents=True)
            (role_path/'handlers').mkdir()
            tasks = yaml.safe_load((DEPLOY/f'roles/{role}/tasks/main.yml').read_text())
            task = next(task for task in tasks if task.get('name') == TASK_NAME)
            configuration = root/f'{role}.conf'
            configuration.write_text('worker_processes auto;\n# preserve adjacent settings\n')
            task['ansible.builtin.lineinfile']['path'] = str(configuration)
            (role_path/'tasks/main.yml').write_text(yaml.safe_dump([task]))
            shutil.copyfile(DEPLOY/f'roles/{role}/handlers/main.yml', role_path/'handlers/main.yml')
            calls = root/f'{role}-calls'
            fixture = root/'fixture.yml'
            fixture.write_text(yaml.safe_dump([dict(hosts='localhost', gather_facts=False,
                environment={'PATH':str(binaries)+':/usr/bin:/bin', 'AIPROXY_TEST_CALLS':str(calls)},
                vars={'proxy_nginx_workers':1}, tasks=[
                    {'ansible.builtin.include_role': {'name':role}},
                    {'ansible.builtin.meta':'flush_handlers'}])]))
            for changed in (True, False):
                calls.unlink(missing_ok=True)
                result = subprocess.run(['ansible-playbook','-i','localhost,','-c','local',str(fixture)],
                    text=True, stdout=subprocess.PIPE, stderr=subprocess.STDOUT)
                if result.returncode:
                    raise AssertionError(f'{role}: {result.stdout}')
                observed = calls.read_text().splitlines() if calls.exists() else []
                expected = ['reset-failed nginx','is-active --quiet nginx','reload nginx'] if changed else []
                assert observed == expected, (role, changed, observed)
                assert configuration.read_text() == 'worker_processes 1;\n# preserve adjacent settings\n'
                print(role, 'reload after change' if changed else 'unchanged: no reload', 'PASS')


if __name__ == '__main__':
    main()
