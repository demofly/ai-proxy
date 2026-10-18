import base64
import importlib.util
from pathlib import Path
import unittest
import jinja2

ROOT = Path(__file__).resolve().parents[1]
SPEC = importlib.util.spec_from_file_location('mtproxy_policy', ROOT/'filter_plugins/mtproxy.py')
POLICY = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(POLICY)
ENV = jinja2.Environment()
ENV.filters.update(mtproxy_nodes=POLICY.mtproxy_nodes, bool=bool)
DOMAIN = 'example.com'
A = 'ee'+'11'*16+DOMAIN.encode().hex()
B = 'ee'+'22'*16+DOMAIN.encode().hex()


def reads(files):
    return [{'item': {'item': [node, filename]}, 'content':base64.b64encode(text.encode()).decode()}
            for node, filename, text in files]


class MTProxyClusterTests(unittest.TestCase):
    def test_default_domain_and_no_duplicate_sni_keys(self):
        plan = POLICY.mtproxy_cluster_plan(['n1'], {'n1':{}}, [])
        self.assertEqual(plan['domain'], 'max.ru')
        self.assertEqual(POLICY.mtproxy_domain_hex('max.ru'), '6d61782e7275')
        source = (ROOT/'roles/nginx/templates/sni-map.d/aiproxy.conf.j2').read_text()
        rendered = ENV.from_string(source).render(mtproxy_fake_tls_domain='max.ru',mtproxy_hostname='max.ru',
            mtproxy_enabled=True,groups={'upstreams':['n1']},hostvars={'n1':{'mtproxy_enabled':True}})
        self.assertEqual(sum(line.startswith('max.ru ') for line in rendered.splitlines()),1)

    def test_disabled_mtproxy_emits_no_empty_upstream_or_dangling_sni(self):
        values = dict(mtproxy_enabled=False,mtproxy_fake_tls_domain='max.ru',mtproxy_hostname='proxy.test',
                      groups={'upstreams':['n1']},hostvars={'n1':{'mtproxy_enabled':False}})
        for template in ('10-aiproxy-upstreams.conf.j2','sni-map.d/aiproxy.conf.j2'):
            source = (ROOT/'roles/nginx/templates'/template).read_text()
            self.assertNotIn('aiproxy_mtproxy',ENV.from_string(source).render(values))

    def setUp(self):
        self.nodes = ['n1','n2']
        self.hosts = {n: {'mtproxy_enabled':True, 'mtproxy_fake_tls_domain':DOMAIN} for n in self.nodes}

    def test_disabled_backends_are_excluded(self):
        self.hosts['n3'] = {'mtproxy_enabled':False}
        self.assertEqual(POLICY.mtproxy_nodes(['n1','n2','n3'],self.hosts),self.nodes)

    def test_fresh_cluster_requests_one_generation(self):
        self.assertEqual(POLICY.mtproxy_cluster_plan(self.nodes,self.hosts,[])['secret'],'')

    def test_one_existing_secret_is_adopted_by_missing_nodes(self):
        plan = POLICY.mtproxy_cluster_plan(self.nodes,self.hosts,reads([('n1','mtg.toml',f'secret = "{A}"')]))
        self.assertEqual(plan['secret'],A)
        self.assertFalse(plan['error'])

    def test_distinct_existing_secrets_never_rotate_implicitly(self):
        plan = POLICY.mtproxy_cluster_plan(self.nodes,self.hosts,reads([
            ('n1','mtg.toml',f'secret = "{A}"'),('n2','mtg.toml',f'secret = "{B}"')]))
        self.assertTrue(plan['error'])
        self.assertNotIn(A,plan['error'])
        self.assertNotIn(B,plan['error'])

    def test_toml_has_priority_over_stale_legacy_env(self):
        plan = POLICY.mtproxy_cluster_plan(self.nodes,self.hosts,reads([
            ('n1','mtg.toml',f'secret = "{A}"'),('n1','mtg.env',f'MTG_SECRET={B}')]))
        self.assertEqual(plan['secret'],A)

    def test_explicit_shared_secret_takes_priority_over_legacy(self):
        for host in self.hosts.values():
            host['mtproxy_secret'] = A
        plan = POLICY.mtproxy_cluster_plan(self.nodes,self.hosts,reads([('n1','mtg.env',f'MTG_SECRET={B}')]))
        self.assertEqual(plan['secret'],A)

    def test_partial_rotation_and_wrong_encoded_domain_are_rejected(self):
        self.hosts['n1']['mtproxy_secret'] = A
        self.assertTrue(POLICY.mtproxy_cluster_plan(self.nodes,self.hosts,[])['error'])
        self.hosts['n2']['mtproxy_secret'] = A
        for host in self.hosts.values():
            host['mtproxy_fake_tls_domain'] = 'other.example'
        self.assertTrue(POLICY.mtproxy_cluster_plan(self.nodes,self.hosts,[])['error'])


if __name__ == '__main__':
    unittest.main()
