# [AITS] 2026-11-06T15:09:32Z
# AI-GENERATED — NOT REVIEWED: SECTION START
"""Модульные тесты фильтров пулов пользователей (filter_plugins/pools.py)."""
import importlib.util
from pathlib import Path
import unittest

ROOT = Path(__file__).resolve().parents[1]
spec = importlib.util.spec_from_file_location('pools', ROOT / 'filter_plugins/pools.py')
pools = importlib.util.module_from_spec(spec)
spec.loader.exec_module(pools)

try:
    from ansible.errors import AnsibleFilterError
except ImportError:  # без ansible фильтры бросают то же исключение лишь при его наличии
    AnsibleFilterError = None

UPSTREAMS = ['up-1', 'up-2', 'up-3']
DEFAULTS = [{'name': 'default', 'groups': ['all'], 'upstreams': 'all'},
            {'name': 'reserve', 'groups': [], 'upstreams': []}]


@unittest.skipIf(AnsibleFilterError is None, 'requires ansible')
class PoolFilterTests(unittest.TestCase):
    def resolve(self, pool_list, groups=None, upstreams=UPSTREAMS):
        return pools.aiproxy_pools(pool_list, {} if groups is None else groups, upstreams)

    def assert_rejected(self, text, *args):
        with self.assertRaises(AnsibleFilterError) as caught:
            self.resolve(*args)
        self.assertIn(text, str(caught.exception))

    def test_defaults_resolve_to_everyone_and_empty_reserve(self):
        self.assertEqual(self.resolve(DEFAULTS), [
            {'name': 'default', 'all_users': True, 'users': [], 'upstreams': UPSTREAMS},
            {'name': 'reserve', 'all_users': False, 'users': [], 'upstreams': []}])

    def test_groups_are_united_and_sorted(self):
        groups = {'a': ['carol', 'alice'], 'b': ['bob', 'alice']}
        result = self.resolve([{'name': 'p', 'groups': ['a', 'b'], 'upstreams': ['up-1']}], groups)
        self.assertEqual(result[0]['users'], ['alice', 'bob', 'carol'])
        self.assertFalse(result[0]['all_users'])

    def test_all_group_combined_with_named_group(self):
        result = self.resolve([{'name': 'p', 'groups': ['all', 'a'], 'upstreams': 'all'}], {'a': ['x']})
        self.assertTrue(result[0]['all_users'])
        self.assertEqual(result[0]['users'], ['x'])

    def test_upstream_order_follows_inventory_not_the_pool(self):
        result = self.resolve([{'name': 'p', 'groups': [], 'upstreams': ['up-3', 'up-1']}])
        self.assertEqual(result[0]['upstreams'], ['up-1', 'up-3'])

    def test_pool_order_is_preserved(self):
        result = self.resolve([{'name': 'zz', 'groups': [], 'upstreams': []},
                               {'name': 'aa', 'groups': [], 'upstreams': []}])
        self.assertEqual([pool['name'] for pool in result], ['zz', 'aa'])

    def test_unknown_group_and_upstream(self):
        self.assert_rejected('неизвестная группа', [{'name': 'p', 'groups': ['x'], 'upstreams': []}])
        self.assert_rejected('неизвестные upstream', [{'name': 'p', 'groups': [], 'upstreams': ['nope']}])

    def test_duplicates(self):
        groups = {'a': []}
        self.assert_rejected('groups есть повторы', [{'name': 'p', 'groups': ['a', 'a'], 'upstreams': []}], groups)
        self.assert_rejected('upstreams есть повторы', [{'name': 'p', 'groups': [], 'upstreams': ['up-1', 'up-1']}])
        self.assert_rejected('повторяется', [{'name': 'p', 'groups': [], 'upstreams': []},
                                             {'name': 'p', 'groups': [], 'upstreams': []}])
        self.assert_rejected('имена пользователей повторяются', [], {'a': ['x', 'x']})

    def test_invalid_names(self):
        for name in ('Upper', '1abc', '', 'a' * 33, 'sp ace', 5):
            with self.subTest(name=name):
                self.assert_rejected('Недопустимое имя пула', [{'name': name, 'groups': [], 'upstreams': []}])
        for user in ('', '-x', 'a b', 'a"b', 'x' * 129, 'REQUIRED', 7):
            with self.subTest(user=user):
                self.assert_rejected('Недопустимое имя пользователя', [], {'g': [user]})
        self.assert_rejected('Недопустимое имя группы', [], {'-bad': []})

    def test_non_string_names_are_explained_as_yaml_coercion(self):
        # 1001 и no YAML читает как число и булево: сообщение должно назвать тип и совет про кавычки.
        self.assert_rejected('нужна строка', [], {'g': [1001]})
        self.assert_rejected('заключите имя в кавычки', [{'name': False, 'groups': [], 'upstreams': []}])
        self.assert_rejected('нужна строка', [{'name': 'p', 'groups': [7], 'upstreams': []}], {'g': []})
        self.assert_rejected('Недопустимое имя группы', [], {5: []})

    def test_reserved_all_cannot_be_a_group_key(self):
        self.assert_rejected('зарезервировано', [], {'all': ['x']})

    def test_extra_and_missing_keys(self):
        self.assert_rejected('лишние', [{'name': 'p', 'groups': [], 'upstreams': [], 'extra': 1}])
        self.assert_rejected('недостающие', [{'name': 'p', 'groups': []}])

    def test_wrong_types(self):
        self.assert_rejected('proxy_pools должен', 'default')
        self.assert_rejected('должен быть отображением', ['default'])
        self.assert_rejected('groups должен быть списком', [{'name': 'p', 'groups': 'all', 'upstreams': []}])
        self.assert_rejected('upstreams должен быть', [{'name': 'p', 'groups': [], 'upstreams': 'up-1'}])
        self.assert_rejected('proxy_user_groups должен', [], [])
        self.assert_rejected('должна быть списком', [], {'g': 'alice'})

    def test_passwd_users_skip_blank_and_comment_lines(self):
        text = '# comment\n\nalice:$apr1$x$y\n  bob:hash:with:colons\n#carol:no\n'
        self.assertEqual(pools.aiproxy_passwd_users(text), ['alice', 'bob'])

    def test_group_users_are_sorted_union(self):
        self.assertEqual(pools.aiproxy_group_users({'a': ['b', 'a'], 'c': ['a', 'z']}), ['a', 'b', 'z'])
        self.assertEqual(pools.aiproxy_group_users({}), [])
# AI-GENERATED — NOT REVIEWED: SECTION END


if __name__ == '__main__':
    unittest.main()
