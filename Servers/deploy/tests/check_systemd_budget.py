"""Apply the real resource tasks to a private disposable systemd sleep service.

Linux root only. Does not touch production service names or aiproxy.slice.
Verifies live cgroup caps without a restart, then placement after a normal restart.
"""
import os
from pathlib import Path
import subprocess
import tempfile
import threading
import uuid
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer

import yaml

DEPLOY = Path(__file__).resolve().parents[1]


def run(*args):
    return subprocess.check_output(args, text=True).strip()


def main():
    name = 'aiproxytest'+uuid.uuid4().hex[:12]
    unit = name+'.service'
    slice_name = name+'.slice'
    directory = Path('/etc/systemd/system')/(unit+'.d')
    slice_path = Path('/etc/systemd/system')/slice_name
    unit_path = Path('/run/systemd/system')/unit
    try:
        unit_path.write_text('[Unit]\nDescription=Disposable ai-proxy regression service\n'
                            '[Service]\nExecStart=/usr/bin/sleep 300\nExecReload=/usr/bin/true\n'
                            '[Install]\nWantedBy=multi-user.target\n')
        subprocess.run(['systemctl', 'daemon-reload'], check=True)
        subprocess.run(['systemctl', 'start', unit], check=True)
        before = run('systemctl', 'show', unit, '-p', 'MainPID', '--value')
        tasks = yaml.safe_load((DEPLOY/'tasks/resource-limits.yml').read_text())
        # Replace only project-specific test targets, retaining the actual module
        # arguments, verification expressions and live cgroup read from deployment.
        tasks = yaml.safe_load(yaml.safe_dump(tasks[1:]).replace('aiproxy.slice', slice_name))
        for task in tasks:
            if 'ansible.builtin.template' in task:
                task['ansible.builtin.template']['src'] = str(DEPLOY/'templates/aiproxy.slice.j2')
        with tempfile.TemporaryDirectory(prefix=name) as temp:
            fixture = Path(temp)/'play.yml'
            fixture.write_text(yaml.safe_dump([dict(hosts='localhost', gather_facts=False,
                vars=dict(_proxy_resource_units=[{'name':unit, 'memory_mb':64}],
                          mem_planned_mb=64, proxy_memory_budget_mb=380), tasks=tasks)], sort_keys=False))
            result = subprocess.run(['ansible-playbook', '-i', 'localhost,', '-c', 'local', str(fixture)],
                                    stdout=subprocess.PIPE, stderr=subprocess.STDOUT, text=True)
            if result.returncode:
                raise AssertionError(result.stdout)
        after = run('systemctl', 'show', unit, '-p', 'MainPID', '--value')
        assert before == after and int(after) > 0, (before, after)
        group = run('systemctl', 'show', unit, '-p', 'ControlGroup', '--value')
        assert int((Path('/sys/fs/cgroup')/group.lstrip('/')/'memory.max').read_text()) == 64*1048576
        print('Live MemoryMax applied; original PID and connections preserved')
        subprocess.run(['systemctl', 'restart', unit], check=True)
        group = run('systemctl', 'show', unit, '-p', 'ControlGroup', '--value')
        assert group.startswith('/'+slice_name+'/'), group
        assert int((Path('/sys/fs/cgroup')/slice_name/'memory.max').read_text()) == 380*1048576
        print('Next normal restart enters the capped project slice')
        # Exercise the deployment's actual stop/init/start versus reload logic.
        class Manager(BaseHTTPRequestHandler):
            def do_GET(self):
                self.send_response(200)
                self.end_headers()
                self.wfile.write(b'Squid Object Cache: local test manager')
            def log_message(self, *args):
                pass
        manager = ThreadingHTTPServer(('127.0.0.1', 0), Manager)
        threading.Thread(target=manager.serve_forever, daemon=True).start()
        try:
            with tempfile.TemporaryDirectory(prefix=name) as temp:
                temp = Path(temp)
                configuration = temp/'squid.conf'
                configuration.write_text('http_port 127.0.0.1:12345\nworkers 1\n')
                sequence = (DEPLOY/'tasks/squid-apply.yml').read_text().replace('/var/lib/aiproxy', str(temp/'state'))
                sequence = sequence.replace('systemctl reset-failed squid', 'systemctl reset-failed '+unit)
                sequence = sequence.replace('systemctl is-active squid', 'systemctl is-active '+unit)
                sequence = yaml.safe_load(sequence)
                for task in sequence:
                    if 'ansible.builtin.systemd' in task:
                        task['ansible.builtin.systemd']['name'] = unit
                fixture = temp/'apply.yml'
                for case, restart, change in [('initial',True,False), ('unchanged',False,False),
                                               ('new-workers',True,False), ('acl-only',False,True)]:
                    if case == 'new-workers':
                        configuration.write_text('http_port 127.0.0.1:12345\nworkers 2\n')
                    pid = run('systemctl', 'show', unit, '-p', 'MainPID', '--value')
                    fixture.write_text(yaml.safe_dump([dict(hosts='localhost', gather_facts=False,
                        vars=dict(squid_config_path=str(configuration), squid_workers=1, enable_caching=False,
                                  squid_mgmt_port=manager.server_port, squid_config_access={'changed':change}),
                        tasks=sequence)], sort_keys=False))
                    result = subprocess.run(['ansible-playbook','-i','localhost,','-c','local',str(fixture)],
                        text=True, stdout=subprocess.PIPE, stderr=subprocess.STDOUT)
                    if result.returncode:
                        raise AssertionError(result.stdout)
                    after = run('systemctl', 'show', unit, '-p', 'MainPID', '--value')
                    assert (pid != after) == restart, (case, pid, after)
                    print('Squid application sequence:', case, 'PASS')
        finally:
            manager.shutdown()
    finally:
        subprocess.run(['systemctl', 'stop', unit], check=False, capture_output=True)
        subprocess.run(['systemctl', 'disable', unit], check=False, capture_output=True)
        if unit_path.exists():
            unit_path.unlink()
        dropin = directory/'zz-aiproxy-resources.conf'
        if dropin.exists():
            dropin.unlink()
        if directory.exists():
            directory.rmdir()
        if slice_path.exists():
            slice_path.unlink()
        subprocess.run(['systemctl', 'stop', slice_name], check=False, capture_output=True)
        subprocess.run(['systemctl', 'daemon-reload'], check=True)


if __name__ == '__main__':
    main()
