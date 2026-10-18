"""Routing regressions: media dependencies, false positives and safe merging."""
import copy
import re
import unittest

import rules


class RulesTest(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.catalog = rules.load_catalog()
        cls.generated = rules.build_rules(cls.catalog)
        cls.patterns = [re.compile(rule["pattern"], re.I) for rule in cls.generated]

    def matches(self, url):
        return any(pattern.search(url) for pattern in self.patterns)

    def test_every_service_and_dependency(self):
        for category in self.catalog["categories"]:
            for service in category["services"]:
                for domain in service.get("domains", []):
                    for scheme in ("http", "https", "ws", "wss"):
                        for host in (domain, "a.b." + domain):
                            with self.subTest(host=host, scheme=scheme):
                                self.assertTrue(self.matches(scheme + "://" + host + ":443/file?range=0-1"))
                for host in service.get("hosts", []):
                    with self.subTest(host=host):
                        self.assertTrue(self.matches("https://" + host + "/"))

    def test_video_images_uploads_and_websockets(self):
        for url in (
            "https://rr1---sn-example.googlevideo.com/videoplayback?sig=" + "a.b." * 4000,
            "https://www.youtube-nocookie.com/embed/example",
            "wss://bridge.claudeusercontent.com/bridge",
            "https://scontent-example.cdninstagram.com/media/example.mp4",
            "https://www.canva.com/",
            "https://as1.ftcdn.net/image.jpg",
            "HTTPS://CHATGPT.COM?new=true",
            "https://chatgpt.com.:443/",
        ):
            with self.subTest(url=url[:100]):
                self.assertTrue(self.matches(url))

    def test_unrelated_domains_and_shared_clouds_stay_direct(self):
        for host in ("example.org", "example.ai", "perplexity.ai", "www.perplexity.ai", "google.com", "mail.google.com",
                     "maps.googleapis.com", "storage.googleapis.com", "example.amazonaws.com",
                     "unrelated.cloudfront.net", "unrelated.vercel.app", "unrelated.supabase.co",
                     "evil.workos.imgix.net", "figma.com", "tiktok.com", "pinterest.com",
                     "oaiusercontent.com", "spacex.ai", "hf.co", "notion.so", "mistral.ai"):
            with self.subTest(host=host):
                self.assertFalse(self.matches("https://" + host + "/"))

    def test_hostnames_in_paths_queries_credentials_and_suffixes(self):
        for host in ("chatgpt.com", "youtube.com", "pinimg.com", "tiktokcdn.com", "figma.com"):
            for url in (
                "https://example.org/a." + host + "/",
                "https://example.org/?redirect=https://" + host + "/",
                "https://" + host + ".example.org/",
                "https://fake" + host + "/",
                "https://" + host + "@example.org/",
                "https://" + host + ":443.example.org/",
            ):
                with self.subTest(url=url):
                    self.assertFalse(self.matches(url))

    def test_exact_shared_hosts_do_not_include_arbitrary_subdomains(self):
        self.assertTrue(self.matches("https://as1.ftcdn.net/image"))
        self.assertFalse(self.matches("https://other.ftcdn.net/image"))
        self.assertFalse(self.matches("https://extra.as1.ftcdn.net/image"))
        self.assertFalse(self.matches("https://canva.com/"))
        self.assertFalse(self.matches("https://other.canva.com/"))

    def test_common_suffixes_are_factored_with_exact_host_semantics(self):
        pattern = rules.host_pattern(["chatgpt.com", "openai.com"], ["accounts.google.com"])
        self.assertEqual(pattern.count(r"\.com"), 1)
        for url in ("https://chatgpt.com/", "https://sub.openai.com/", "https://accounts.google.com/"):
            self.assertTrue(re.search(pattern, url))
        for url in ("https://google.com/", "https://sub.accounts.google.com/", "https://fakeopenai.com/"):
            self.assertFalse(re.search(pattern, url))
        self.assertTrue(all(r["pattern"].count(r"\.com") <= 1 for r in self.generated))

    def test_exact_parent_and_descendant_domains(self):
        pattern = rules.host_pattern(["app.example.com"], ["example.com"])
        for host in ("example.com", "app.example.com", "sub.app.example.com"):
            self.assertTrue(re.search(pattern, "https://" + host + "/"))
        self.assertFalse(re.search(pattern, "https://other.example.com/"))
        self.assertEqual(rules.host_pattern(["example.com"], ["app.example.com"]),
                         rules.host_pattern(["example.com"]))

    def test_compact_existing_rule_keeps_exact_hosts_separate(self):
        old = (rules.SCHEME + "(?:" + rules.SUBDOMAINS
               + r"(?:chatgpt\.com|openai\.com)|(?:accounts\.google\.com))" + rules.END)
        new = rules.compact_pattern(old)
        self.assertEqual(new, rules.host_pattern(["chatgpt.com", "openai.com"], ["accounts.google.com"]))
        self.assertEqual(rules.compact_pattern(new), new)
        self.assertFalse(re.search(new, "https://sub.accounts.google.com/"))
        custom = r"^https://example\.org/(?:com|net)/"
        self.assertEqual(rules.compact_pattern(custom), custom)

    def test_finite_legacy_expression(self):
        self.assertEqual(rules.finite_expression(r"cursor(api)?\.(sh|com|so)"),
                         ["cursor.com", "cursor.sh", "cursor.so", "cursorapi.com", "cursorapi.sh", "cursorapi.so"])
        for expression in (r".*\.ai", r"example.com", r"[a-z]+\.com", r"a\.(com|net", ""):
            with self.subTest(expression=expression):
                with self.assertRaises(ValueError):
                    rules.finite_expression(expression)

    def test_merge_preserves_private_settings_and_custom_rules(self):
        arbitrary = {"type": "regex", "title": "Custom path", "active": True,
                     "pattern": r"^https://example\.org/only-this-path/"}
        disabled = {"type": "regex", "title": "Disabled", "active": False,
                    "pattern": r"^https?://(.*\.)*disabled\.example($|/)"}
        legacy = {"type": "regex", "title": "Old AI + personal", "active": True,
                  "pattern": r"^https?://(.*\.)*(chatgpt\.com|personal\.example)($|/)"}
        proxy = {"type": "http", "active": False, "hostname": "proxy.example.invalid", "port": "443",
                 "username": "sample-user", "password": "sample-secret", "color": "#aabbcc",
                 "include": [legacy, arbitrary, disabled], "exclude": [copy.deepcopy(arbitrary)],
                 "tabProxy": [], "pacString": "", "proxyDNS": True}
        before = {"mode": "pattern", "sync": False, "container": {}, "data": [proxy]}
        result = rules.merge_settings(before, self.catalog)
        self.assertEqual(before["data"][0], proxy)
        self.assertEqual({**result, "data": before["data"]}, before)
        self.assertEqual({**result["data"][0], "include": proxy["include"]}, proxy)
        custom = result["data"][0]["include"][len(self.generated):]
        self.assertEqual(custom[1:], [arbitrary, disabled])
        self.assertTrue(re.search(custom[0]["pattern"], "https://sub.personal.example/"))
        self.assertFalse(re.search(custom[0]["pattern"], "https://chatgpt.com/"))
        self.assertEqual(rules.merge_settings(result, self.catalog), result)

    def test_disabled_category_stays_disabled(self):
        item = {"type": "http", "include": copy.deepcopy(self.generated)}
        item["include"][0]["active"] = False
        updated = rules.merge_settings({"data": [item]}, self.catalog)
        self.assertFalse(updated["data"][0]["include"][0]["active"])

    def test_old_titles_migrate_without_changing_patterns_or_states(self):
        previous = copy.deepcopy(self.generated)
        categories = [c for c, domains, hosts in rules.category_hosts(self.catalog) if domains or hosts]
        for rule, category in zip(previous, categories):
            rule["title"] = "[AI Proxy:" + category["id"] + "] Old description"
        previous[0]["active"] = False
        migrated = rules.merge_settings({"data": [{"type": "http", "include": previous}]}, self.catalog)
        actual = migrated["data"][0]["include"]
        self.assertEqual([r["title"] for r in actual], [c["title"] for c in categories])
        self.assertEqual([{**r, "title": old["title"]} for r, old in zip(actual, previous)], previous)
        self.assertEqual(rules.merge_settings(migrated, self.catalog), migrated)

    def test_custom_rule_with_same_short_title_is_preserved(self):
        custom = {"type": "regex", "title": "AI", "active": True,
                  "pattern": r"^https://personal\.example/ai/"}
        actual = rules.merge_settings({"data": [{"type": "http", "include": [custom]}]}, self.catalog)
        self.assertEqual(actual["data"][0]["include"], self.generated + [custom])

    def test_empty_category_does_not_misalign_legacy_coverage(self):
        catalog = copy.deepcopy(self.catalog)
        catalog["categories"].insert(0, {"id": "empty", "title": "Empty", "services": []})
        merged = rules.merge_settings({"data": [{"type": "http", "include": []}]}, catalog)
        self.assertEqual(merged["data"][0]["include"], self.generated)

    def test_small_deduplicated_ruleset(self):
        self.assertEqual(len(self.generated), 5)
        flattened = [name for _, domains, hosts in rules.category_hosts(self.catalog) for name in domains + hosts]
        self.assertEqual(len(flattened), len(set(flattened)))

    def test_original_user_exceptions_are_preserved(self):
        for host in ("chatgpt.com", "gemini.google.com", "cursorapi.so", "sentry.io",
                     "cloudflare.com", "azure.com", "intel.com", "phrack.org", "oracleimg.com",
                     "githubcopilot.com", "play.google.com", "doubleclick.net", "developer.amd.com"):
            with self.subTest(host=host):
                self.assertTrue(self.matches("https://sub." + host + "/"))

    def test_registry_scope_does_not_expand_exact_hosts(self):
        entries = {entry for c in self.catalog["categories"] for s in c["services"]
                   if s["basis"] == "rkn" for entry in s["registry_entries"]}
        self.assertEqual(len(entries), 12)
        for c in self.catalog["categories"]:
            for s in c["services"]:
                if s["basis"] == "rkn":
                    self.assertEqual(set(s["registry_entries"]),
                                     {"*." + d for d in s.get("domains", [])} | set(s.get("hosts", [])))


if __name__ == "__main__":
    unittest.main()
