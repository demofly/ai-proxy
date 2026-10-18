"""Actual delegated Ansible tasks: fresh generation, legacy adoption and refusal."""
import os
from pathlib import Path
import subprocess
import tempfile

import yaml

DEPLOY = Path(__file__).resolve().parents[1]
DOMAIN = 'example.com'
A = 'ee'+'11'*16+DOMAIN.encode().hex()
B = 'ee'+'22'*16+DOMAIN.encode().hex()


def main():
    with tempfile.TemporaryDirectory(prefix='aiproxy-mtproxy-') as temporary:
        root = Path(temporary)
        for name in ('n1','n2'):
            (root/name).mkdir()
        tasks = (DEPLOY/'tasks/mtproxy-cluster.yml').read_text().replace(
            '/etc/mtproxy/{{ item.1 }}', str(root)+'/{{ item.0 }}/{{ item.1 }}')
        (root/'tasks.yml').write_text(tasks)
        fixture = root/'fixture.yml'
        inventory = root/'inventory.yml'
        for case in ('fresh','fresh-repeat','adopt-existing','reject-different','explicit-rotation','disabled'):
            for name in ('n1','n2'):
                (root/name/'mtg.toml').unlink(missing_ok=True)
            if case in ('adopt-existing','reject-different','explicit-rotation'):
                (root/'n1/mtg.toml').write_text(f'secret = "{A}"\n')
            if case in ('reject-different','explicit-rotation'):
                (root/'n2/mtg.toml').write_text(f'secret = "{B}"\n')
            hosts = {n: {'ansible_connection':'local', 'mtproxy_enabled':True,
                         'mtproxy_fake_tls_domain':DOMAIN} for n in ('n1','n2')}
            if case == 'explicit-rotation':
                for host in hosts.values():
                    host['mtproxy_secret'] = A
            if case == 'disabled':
                for host in hosts.values():
                    host['mtproxy_enabled'] = False
            inventory.write_text(yaml.safe_dump({'all': {'children': {'upstreams': {'hosts':hosts}}}}))
            expected = A
            if case.startswith('fresh'):
                expected = '' if case == 'fresh' else generated
            if case == 'disabled':
                expected = ''
            checks = [{'ansible.builtin.assert': {'that':
                ["hostvars['localhost']._mtproxy_cluster_secret == expected_secret"]}}] if expected else []
            fixture.write_text(yaml.safe_dump([dict(hosts='upstreams', gather_facts=False,
                vars={'expected_secret':expected}, tasks=[
                    {'ansible.builtin.include_tasks':str(root/'tasks.yml'), 'run_once':True}]+checks)]))
            before = {str(f):f.read_bytes() for f in root.glob('n*/mtg.toml')}
            result = subprocess.run(['ansible-playbook','-i',str(inventory),str(fixture)],
                env=dict(os.environ, ANSIBLE_FILTER_PLUGINS=str(DEPLOY/'filter_plugins')),
                text=True, stdout=subprocess.PIPE, stderr=subprocess.STDOUT)
            if (result.returncode != 0) != (case == 'reject-different'):
                raise AssertionError(case+'\n'+result.stdout)
            assert all(Path(f).read_bytes() == text for f,text in before.items())
            if case == 'fresh':
                entropy = (root/'secrets/mtproxy-entropy').read_text().splitlines()[0].lower()
                generated = 'ee'+entropy+DOMAIN.encode().hex()
                assert (root/'secrets/mtproxy-entropy').stat().st_mode & 0o077 == 0
            print(case,'PASS')


if __name__ == '__main__':
    main()
