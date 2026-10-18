"""Build hostname-only FoxyProxy rules; merge exports without copying credentials.

Only the include arrays change when merging. This tool does not access Firefox's
profile or storage. Python 3.10+, standard library only.
"""
from __future__ import annotations

import argparse
import copy
import json
from pathlib import Path
import re

HERE = Path(__file__).resolve().parent
SCHEME = r"^(?:https?|wss?)://"
SUBDOMAINS = r"(?:[a-z0-9-]+\.)*"
END = r"\.?(?::[0-9]{1,5})?(?:[/?#]|$)"
TAG = "[AI Proxy:"
SHARED_ROOTS = {
    "google.com", "googleapis.com", "amazonaws.com", "cloudfront.net",
    "cloudflare.com", "azure.com", "windows.net", "vercel.app",
    "vercel-storage.com", "auth0.com", "supabase.co", "imgix.net",
}


def covered(host: str, domains: set[str]) -> bool:
    return any(host == domain or host.endswith("." + domain) for domain in domains)


def host_pattern(domains: list[str], hosts: list[str] = ()) -> str:
    branches = []
    if domains:
        branches.append(SUBDOMAINS + "(?:" + "|".join(map(re.escape, sorted(domains))) + ")")
    if hosts:
        branches.append("(?:" + "|".join(map(re.escape, sorted(hosts))) + ")")
    if not branches:
        raise ValueError("Empty hostname rule")
    return SCHEME + "(?:" + "|".join(branches) + ")" + END


def load_catalog(path: Path = HERE / "domains.json") -> dict:
    catalog = json.loads(path.read_text(encoding="utf-8"))
    if catalog.get("version") != 1:
        raise ValueError("Unsupported catalog version")
    categories = catalog["categories"]
    ids = [category["id"] for category in categories]
    if len(ids) != len(set(ids)) or not ids:
        raise ValueError("Category IDs must be unique")
    for category in categories:
        if not re.fullmatch(r"[a-z-]+", category["id"]):
            raise ValueError("Invalid category ID")
        for service in category["services"]:
            if not service.get("sources"):
                raise ValueError("Each service needs a primary source")
            for kind in ("domains", "hosts"):
                for host in service.get(kind, []):
                    if (not re.fullmatch(r"[a-z0-9-]+(?:\.[a-z0-9-]+)+", host)
                            or host in SHARED_ROOTS):
                        raise ValueError("Use specific hostnames for shared infrastructure: " + host)
    return catalog


def category_hosts(catalog: dict) -> list[tuple[dict, list[str], list[str]]]:
    """Deduplicate globally, including a child covered by another category."""
    all_roots = {domain for category in catalog["categories"]
                 for service in category["services"] for domain in service.get("domains", [])}
    roots = {domain for domain in all_roots if not covered(domain, all_roots - {domain})}
    seen: set[str] = set()
    result = []
    for category in catalog["categories"]:
        domains, hosts = [], []
        for service in category["services"]:
            for domain in service.get("domains", []):
                if domain in roots and domain not in seen:
                    domains.append(domain)
                    seen.add(domain)
            for host in service.get("hosts", []):
                if not covered(host, roots) and host not in seen:
                    hosts.append(host)
                    seen.add(host)
        result.append((category, domains, hosts))
    return result


def build_rules(catalog: dict) -> list[dict]:
    return [{"type": "regex", "title": TAG + category["id"] + "] " + category["title"],
             "pattern": host_pattern(domains, hosts), "active": True}
            for category, domains, hosts in category_hosts(catalog) if domains or hosts]


def finite_expression(expression: str) -> list[str]:
    """Expand only literal domains, groups, alternatives and optional groups.

    Arbitrary user regular expressions are never interpreted or simplified.
    Bounded expansion and strict validation prevent a wildcard becoming a domain.
    """
    pos = 0

    def sequence() -> list[str]:
        nonlocal pos
        values = [""]
        while pos < len(expression) and expression[pos] not in ")|":
            char = expression[pos]
            pos += 1
            if char == "(":
                if expression[pos:pos + 2] == "?:":
                    pos += 2
                choices = alternatives()
                if pos >= len(expression) or expression[pos] != ")":
                    raise ValueError("Unclosed group")
                pos += 1
            elif char == "\\" and expression[pos:pos + 1] == ".":
                pos += 1
                choices = ["."]
            elif re.fullmatch(r"[a-z0-9-]", char):
                choices = [char]
            else:
                raise ValueError("Nonliteral domain expression")
            if expression[pos:pos + 1] == "?":
                choices = choices + [""]
                pos += 1
            if len(values) * len(choices) > 1024:
                raise ValueError("Too many alternatives")
            values = [left + right for left in values for right in choices]
        return values

    def alternatives() -> list[str]:
        nonlocal pos
        values = sequence()
        while expression[pos:pos + 1] == "|":
            pos += 1
            values += sequence()
            if len(values) > 1024:
                raise ValueError("Too many alternatives")
        return values

    domains = alternatives()
    if pos != len(expression) or not all(re.fullmatch(r"[a-z0-9-]+(?:\.[a-z0-9-]+)+", d) for d in domains):
        raise ValueError("Not a finite list of domains")
    return sorted(set(domains))


def legacy_domains(rule: dict) -> list[str] | None:
    if rule.get("type") != "regex" or not rule.get("active"):
        return None
    pattern = rule.get("pattern", "")
    for scheme in (SCHEME, "^https?://"):
        for subdomains in (SUBDOMAINS, r"(.*\.)*"):
            prefix = scheme + subdomains
            if pattern.startswith(prefix) and pattern.endswith("($|/)"):
                try:
                    return finite_expression(pattern[len(prefix):-len("($|/)")])
                except ValueError:
                    return None
    return None


def merge_settings(preferences: dict, catalog: dict) -> dict:
    result = copy.deepcopy(preferences)
    generated = build_rules(catalog)
    roots_by_title = {TAG + category["id"] + "] " + category["title"]: set(domains)
                      for category, domains, _ in category_hosts(catalog)}
    for proxy in result["data"]:
        if proxy.get("type") in ("direct", "pac"):
            continue
        previous = proxy.get("include", [])
        # Keep a user's disabled category disabled on subsequent updates.
        states = {rule.get("title", "").split("]", 1)[0]: rule.get("active", True)
                  for rule in previous if rule.get("title", "").startswith(TAG)}
        rules = copy.deepcopy(generated)
        for rule in rules:
            rule["active"] = states.get(rule["title"].split("]", 1)[0], True)
        roots = {d for rule in rules if rule["active"] for d in roots_by_title[rule["title"]]}
        retained = []
        for rule in previous:
            if rule.get("title", "").startswith(TAG):
                continue
            domains = legacy_domains(rule)
            if domains is None:
                retained.append(rule)
                continue
            remaining = [d for d in domains if not covered(d, roots)]
            remaining = [d for d in remaining if not covered(d, set(remaining) - {d})]
            if remaining:
                retained.append({**rule, "pattern": host_pattern(remaining)})
        proxy["include"] = rules + retained
    return result


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    group = parser.add_mutually_exclusive_group()
    group.add_argument("--check", action="store_true", help="Check that the public sample is up to date")
    group.add_argument("--merge", type=Path, help="Merge a private FoxyProxy JSON export")
    parser.add_argument("--output", type=Path, help="Private merged export; input is never overwritten")
    args = parser.parse_args()
    catalog = load_catalog()
    if args.merge:
        if args.output is None or args.output.resolve() == args.merge.resolve():
            parser.error("--merge requires a different --output file")
        # Avoid accidentally replacing the public sample with private credentials.
        if args.output.resolve().is_relative_to(HERE.parent.parent):
            parser.error("Private output must be outside the repository")
        config = merge_settings(json.loads(args.merge.read_text(encoding="utf-8-sig")), catalog)
        with args.output.open("x", encoding="utf-8") as output:
            output.write(json.dumps(config, ensure_ascii=False, indent=2) + "\n")
        print("Updated include rules; proxy credentials and other settings preserved.")
    else:
        if args.output:
            parser.error("--output requires --merge")
        path = HERE / "FoxyProxy.json"
        config = json.loads(path.read_text(encoding="utf-8"))
        expected = copy.deepcopy(config)
        expected["mode"] = "pattern"
        expected["data"][0]["include"] = build_rules(catalog)
        if args.check:
            if expected != config:
                parser.exit(1, "FoxyProxy.json is stale; run rules.py\n")
            print("Public sample matches domains.json.")
        else:
            path.write_text(json.dumps(expected, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
            print("Public sample regenerated.")


if __name__ == "__main__":
    main()
