"""Budget invariants: host share, decimal GB cap, rounding and fixed overrides."""
import importlib.util
from pathlib import Path
import unittest

spec = importlib.util.spec_from_file_location('proxy_resources',
    Path(__file__).resolve().parents[1]/'filter_plugins/resources.py')
resources = importlib.util.module_from_spec(spec)
spec.loader.exec_module(resources)
SERVICES = ['squid','unbound','nginx','mtg','crowdsec','crowdsec_bouncer','haveged','health']


class BudgetTests(unittest.TestCase):
    def test_one_third_and_one_gigabyte_never_exceeded(self):
        for ram in range(1, 16385):
            budget = resources.proxy_memory_budget(ram)
            self.assertEqual(budget['bytes'], min(ram*1048576//3, 1_000_000_000))
            self.assertLessEqual(budget['mb']*1048576, budget['bytes'])

    def test_lower_inventory_ceiling_and_unraiseable_host_cap(self):
        self.assertEqual(resources.proxy_memory_budget(900, 296)['mb'], 296)
        self.assertEqual(resources.proxy_memory_budget(900, 400)['mb'], 300)
        self.assertEqual(resources.proxy_memory_budget(65536, 4096)['bytes'], 1_000_000_000)

    def test_distribution_rounding_and_service_floors(self):
        for budget in range(400, 954):
            plan = resources.proxy_memory_plan(budget, SERVICES)
            self.assertTrue(plan['fits'])
            self.assertEqual(plan['total_mb'], budget)
            self.assertEqual(sum(plan['limits'][n] for n in SERVICES), budget)
            for name in SERVICES:
                self.assertGreaterEqual(plan['limits'][name], resources.PROXY_MEMORY_FLOORS[name])

    def test_explicit_limits_preserved_while_others_adapt(self):
        plan = resources.proxy_memory_plan(440, SERVICES, {'crowdsec':192})
        self.assertTrue(plan['fits'])
        self.assertEqual(plan['limits']['crowdsec'],192)
        self.assertEqual(plan['total_mb'],440)
        self.assertFalse(resources.proxy_memory_plan(400, SERVICES, {'crowdsec':208})['fits'])

    def test_no_silent_underallocation_or_invalid_keys(self):
        plan = resources.proxy_memory_plan(399, SERVICES)
        self.assertFalse(plan['fits'])
        self.assertEqual(plan['minimum_mb'],400)
        with self.assertRaises(ValueError):
            resources.proxy_memory_plan(300, SERVICES, {'typo':64})
        with self.assertRaises(ValueError):
            resources.proxy_memory_plan(300, SERVICES, {'crowdsec':64})

    def test_every_service_rejects_overrides_below_its_floor(self):
        for name, minimum in resources.PROXY_MEMORY_FLOORS.items():
            with self.subTest(service=name):
                with self.assertRaises(ValueError):
                    resources.proxy_memory_plan(953, [name], {name:minimum-1})
                plan = resources.proxy_memory_plan(minimum-1, [name])
                self.assertFalse(plan['fits'])
                self.assertEqual(plan['limits'][name], minimum)


if __name__ == '__main__':
    unittest.main()
