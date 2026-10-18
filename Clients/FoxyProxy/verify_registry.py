"""Verify additions against the pinned public registry, without loading private settings."""
import argparse
import csv
import gzip
import hashlib
from pathlib import Path

from rules import load_catalog


def verify(path: Path, catalog: dict) -> int:
    registry = catalog["registry"]
    digest = hashlib.sha256()
    with path.open("rb") as source:
        for block in iter(lambda: source.read(1024 * 1024), b""):
            digest.update(block)
    if digest.hexdigest() != registry["sha256"]:
        raise ValueError("Registry SHA256 differs from the pinned catalog snapshot")
    required = {entry for category in catalog["categories"] for service in category["services"]
                if service["basis"] == "rkn" for entry in service["registry_entries"]}
    missing = required.copy()
    csv.field_size_limit(40_000_000)
    # The historical CSV includes non-UTF-8 URL bytes. Evidence uses only ASCII
    # hostname fields; the digest above still verifies every original byte.
    with gzip.open(path, "rt", encoding="utf-8", errors="replace", newline="") as source:
        if next(source).strip() != "Updated: " + registry["updated"]:
            raise ValueError("Registry update date differs from the pinned snapshot")
        for row in csv.reader(source, delimiter=";"):
            if len(row) >= 2:
                missing.difference_update(entry.strip().lower().rstrip(".") for entry in row[1].split("|"))
    if missing:
        raise ValueError("Registry entries not found: " + ", ".join(sorted(missing)))
    return len(required)


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("dump", type=Path, help="Pinned dump.csv.gz downloaded from zapret-info/z-i")
    args = parser.parse_args()
    try:
        count = verify(args.dump, load_catalog())
    except (OSError, ValueError) as error:
        parser.exit(1, str(error) + "\n")
    print(f"Verified {count} additions against the pinned registry snapshot")
