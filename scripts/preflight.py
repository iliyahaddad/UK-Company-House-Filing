#!/usr/bin/env python3
"""Run before trusting this app with real data. Exits non-zero on any failure.

    python scripts/preflight.py
"""
from __future__ import annotations

import importlib
import os
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

REQUIRED_MODULES = [
    ("fastapi", None), ("uvicorn", None), ("pydantic", None), ("jinja2", None),
    ("sqlalchemy", None), ("cryptography", None), ("dateutil", None),
    ("filelock", None), ("lxml", None),
    ("_jsonnet", "pip install jsonnet"),
    ("ixbrl_reporter", "pip install ixbrl-reporter"),
    ("ixbrl_parse", "pip install git+https://github.com/cybermaggedon/ixbrl-parse.git"),
    ("tinycss2", "pip install tinycss2 (required by Arelle's validate/UK plugin)"),
    ("arelle", "pip install arelle-release"),
    ("ch_filing", "pip install git+https://github.com/cybermaggedon/companies-house-filing (not on PyPI, see README)"),
]


def check(label: str, ok: bool, detail: str = "") -> bool:
    print(f"[{'OK' if ok else 'FAIL'}] {label}" + (f" - {detail}" if detail and not ok else ""))
    return ok


def main() -> int:
    failures = 0

    for module_name, hint in REQUIRED_MODULES:
        try:
            importlib.import_module(module_name)
            check(f"import {module_name}", True)
        except ImportError as exc:
            failures += 1
            check(f"import {module_name}", False, hint or str(exc))

    try:
        from app import config
        details = config.production_problems()
        if os.getenv("APP_ENV", "development").lower() == "production":
            failures += 0 if check("production config", not details, "; ".join(details)) else 1
        else:
            check("APP_ENV", True, f"{config.APP_ENV} (not production - fine for local testing)")
    except Exception as exc:
        failures += 1
        check("app.config import", False, str(exc))

    jsonnet_dir = os.getenv("IXBRL_REPORTER_JSONNET_PATH") or str(ROOT / "sample_data" / "ixbrl-reporter-jsonnet")
    failures += 0 if check("ixbrl-reporter-jsonnet checkout", Path(jsonnet_dir).is_dir(),
                           f"not found at {jsonnet_dir} - run scripts/bootstrap_upstreams.py") else 1

    try:
        from app.xbrl.postprocess import postprocess_ixbrl
        from app.xbrl.reconcile import reconcile
        from datetime import date
        fixture = ROOT / "tests" / "fixtures" / "real_micro_all_zero.xhtml"
        if fixture.is_file():
            result = postprocess_ixbrl(
                fixture.read_bytes(), period_start=date(2024, 1, 1), period_end=date(2024, 12, 31),
                average_employees=1, principal_activities="Test",
            )
            check("postprocess a real Arelle-tested fixture", True, f"{len(result.changes)} repairs applied")
        else:
            check("postprocess fixture", False, "tests/fixtures/real_micro_all_zero.xhtml missing")
            failures += 1
    except Exception as exc:
        failures += 1
        check("postprocess a real Arelle-tested fixture", False, str(exc))

    print()
    if failures:
        print(f"{failures} check(s) failed. Fix these before generating or filing real accounts.")
        return 1
    print("All checks passed. This only confirms the environment is wired up correctly - "
          "it does not confirm your accounts data is correct. Still run `pytest` and validate "
          "a real set of accounts with Arelle before filing anything.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
