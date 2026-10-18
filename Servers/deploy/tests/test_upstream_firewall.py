"""Authorization matrix and fail-fast behavior of actual firewall templates/tasks."""
from pathlib import Path
import importlib.util
import json
import os
import shlex
import subprocess
import tempfile
import unittest

import jinja2
import yaml

DEPLOY = Path(__file__).resolve().parents[1]
ENV = jinja2.Environment()
ENV.filters['bool'] = bool
SPEC = importlib.util.spec_from_file_location('firewall_resources', DEPLOY/'filter_plugins/resources.py')
RESOURCES = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(RESOURCES)


def verdict(rules, source, port, protocol='tcp'):
    for line in rules.splitlines():
        if not line.startswith('-A '):
            continue
        fields = shlex.split(line)
        if '-i' in fields:  # Packet arrives on the public interface, not lo.
            continue
        if '-s' in fields and fields[fields.index('-s')+1] != source:
            continue
        if '-p' in fields and fields[fields.index('-p')+1] != protocol:
            continue
        if '--dport' in fields and int(fields[fields.index('--dport')+1]) != port:
            continue
        return fields[fields.index('-j')+1]
    return 'RETURN'


class FirewallTests(unittest.TestCase):
    def test_only_empty_default_tables_can_be_adopted_without_owner_marker(self):
        base = [{'table': {'family':'inet', 'name':'filter'}}]
        default = {'chain': {'name':'input', 'hook':'input', 'policy':'accept'}}
        self.assertTrue(RESOURCES.nft_empty_default_table(json.dumps({'nftables':base+[default]})))
        for item in ({'rule': {}}, {'set': {}},
                     {'chain': {'name':'foreign_service'}},
                     {'chain': {'name':'input', 'hook':'input', 'policy':'drop'}}):
            self.assertFalse(RESOURCES.nft_empty_default_table(json.dumps({'nftables':base+[item]})))

    def test_nft_preserves_the_shared_table_and_foreign_objects(self):
        text = (DEPLOY/'templates/nftables-upstream.conf.j2').read_text()
        self.assertNotIn('delete table', text)
        self.assertNotIn('flush ruleset', text)
        self.assertNotIn('flush table', text)
        self.assertIn('flush chain inet filter input', text)

    def test_ipv4_ipv6_and_separate_mtproxy_port(self):
        for squid_port in (443, 8080):
            values = dict(squid_chain='SQUID-PROXY', squid_port=squid_port, mtproxy_enabled=True,
                          groups={'access_proxies':['access']},
                          hostvars={'access':{'ansible_host':'198.51.100.10'}},
                          dns_allowed_clients=['198.51.100.10'])
            for version, source in (('iptables','192.0.2.99'), ('ip6tables','2001:db8::99')):
                rules = ENV.from_string((DEPLOY/f'templates/{version}-upstream.rules.j2').read_text()).render(values)
                for port in (squid_port, 443, 53):
                    self.assertEqual(verdict(rules, source, port), 'DROP', (version, port))
                self.assertEqual(verdict(rules, source, 53, 'udp'), 'DROP')
                self.assertEqual(verdict(rules, source, 22), 'RETURN')
                self.assertEqual(verdict(rules, source, 7881), 'RETURN')
                if version == 'iptables':
                    self.assertEqual(verdict(rules, '198.51.100.10', squid_port), 'ACCEPT')
                    self.assertEqual(verdict(rules, '198.51.100.10', 443), 'ACCEPT')

    @unittest.skipUnless(os.name == 'posix', 'requires bash')
    def test_failed_restore_cannot_be_hidden_by_a_successful_followup(self):
        play = yaml.safe_load((DEPLOY/'playbook.yml').read_text())[0]
        block = next(t['block'] for t in play['tasks'] if t.get('name') == 'Настроить отдельную цепочку iptables на upstream')
        task = next(t for t in block if t.get('name') == 'Атомарно применить отдельную цепочку с сохранением чужих правил')
        with tempfile.TemporaryDirectory(prefix='aiproxy-firewall-') as temp:
            root = Path(temp)
            for command in ('iptables','ip6tables'):
                (root/command).write_text('#!/bin/sh\nexit 0\n')
                (root/command).chmod(0o755)
                (root/(command+'-restore')).write_text('#!/bin/sh\nexit 42\n')
                (root/(command+'-restore')).chmod(0o755)
                text = ENV.from_string(task['ansible.builtin.shell']).render(
                    item={'command':command, 'path':'/unused.rules'}, squid_chain='SQUID-PROXY')
                result = subprocess.run(['bash','-c',text], env=dict(os.environ, PATH=str(root)+':'+os.environ['PATH']))
                self.assertEqual(result.returncode, 42)


if __name__ == '__main__':
    unittest.main()
