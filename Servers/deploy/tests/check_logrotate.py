"""Real Ansible migration and logrotate parser against a private directory."""
import grp
import os
from pathlib import Path
import pwd
import subprocess
import tempfile

import yaml

DEPLOY = Path(__file__).resolve().parents[1]


def main():
    with tempfile.TemporaryDirectory(prefix='aiproxy-logrotate-') as temporary:
        root = Path(temporary)
        logs = root/'logs'
        logs.mkdir()
        (logs/'access.log').write_text('synthetic log\n')
        rules = root/'rules'
        rules.mkdir()
        original = str(logs)+'/*.log {\n daily\n rotate 2\n missingok\n}\n'
        (rules/'squid').write_text(original)
        (rules/'squid-aiproxy').write_text(original)
        main_config = root/'logrotate.conf'
        main_config.write_text('include '+str(rules)+'\n')
        def check():
            return subprocess.run(['logrotate','--debug','--state','/dev/null',str(main_config)],
                                  text=True,capture_output=True)
        before = check()
        assert before.returncode != 0 and 'duplicate log entry' in before.stderr
        play = yaml.safe_load((DEPLOY/'playbook.yml').read_text())[0]
        names = {'Удалить устаревшее дублирующее правило ротации журналов Squid','Разместить правило ротации журналов Squid'}
        tasks = [t for t in play['tasks'] if t.get('name') in names]
        assert len(tasks) == 2
        template = root/'squid.j2'
        template.write_text((DEPLOY/'templates/logrotate-squid.j2').read_text()
            .replace('/var/log/squid',str(logs))
            .replace('su proxy proxy','su '+pwd.getpwuid(os.getuid()).pw_name+' '+grp.getgrgid(os.getgid()).gr_name))
        tasks[0]['ansible.builtin.file']['path'] = str(rules/'squid-aiproxy')
        tasks[1]['ansible.builtin.template']['src'] = str(template)
        tasks[1]['ansible.builtin.template']['dest'] = str(rules/'squid')
        for key in ('owner','group'):
            tasks[1]['ansible.builtin.template'].pop(key)
        fixture = root/'fixture.yml'
        fixture.write_text(yaml.safe_dump([dict(hosts='localhost',gather_facts=False,
            vars={'enable_logging':True,'ansible_managed':'isolated fixture'},tasks=tasks)]))
        for _ in range(2):
            result = subprocess.run(['ansible-playbook','-i','localhost,','-c','local',str(fixture)],
                                    text=True,stdout=subprocess.PIPE,stderr=subprocess.STDOUT)
            assert result.returncode == 0, result.stdout
            assert not (rules/'squid-aiproxy').exists()
            result = check()
            assert result.returncode == 0, result.stderr
        print('Duplicate reproduced; actual migration and repeated apply parse without errors')


if __name__ == '__main__':
    main()
