#!/usr/bin/env python3
"""List the account names the ixbrl-reporter-jsonnet templates refer to.

The iXBRL only contains real numbers when the account names in the CSV match
what the templates look for. This prints every quoted string that looks like a
hierarchical account name (e.g. "Assets:Current Assets") in the templates so
you can compare them with config/account_paths.json.

    python scripts/inspect_mapping.py [path-to-ixbrl-reporter-jsonnet]
"""
from __future__ import annotations

import json
import re
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
DEFAULT = ROOT / "sample_data" / "ixbrl-reporter-jsonnet"
PATTERN = re.compile(r'"([^"\n]*[A-Za-z][^"\n]*:[^"\n]*[A-Za-z][^"\n]*)"')


def find_names(text: str):
    for number, line in enumerate(text.splitlines(), 1):
        for match in PATTERN.finditer(line):
            value = match.group(1)
            if " " in value or value.split(":")[0][:1].isupper():
                yield number, value


def main(argv) -> int:
    base = Path(argv[1]) if len(argv) > 1 else DEFAULT
    if not base.is_dir():
        print(f"Not found: {base}\nRun scripts/bootstrap_upstreams.py first.")
        return 2
    seen = 0
    for path in sorted(list(base.rglob("*.libsonnet")) + list(base.rglob("*.jsonnet"))):
        hits = list(find_names(path.read_text(encoding="utf-8", errors="replace")))
        if hits:
            print(f"\n{path.relative_to(base)}")
            for number, value in hits:
                print(f"  {number:>4}: {value}")
                seen += 1
    if not seen:
        print("No hierarchical account names found in the templates.")
    print("\nCurrent config/account_paths.json:")
    print(json.dumps(json.loads((ROOT / "config" / "account_paths.json").read_text()), indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main(sys.argv))
