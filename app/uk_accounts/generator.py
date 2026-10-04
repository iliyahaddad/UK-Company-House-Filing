"""Thin wrapper around the upstream ixbrl-reporter / jsonnet libraries.

Everything that needs the upstream packages is in this file and imported lazily,
so the rest of the application (and its tests) work without them.
"""
from __future__ import annotations

import json
import os
import tempfile
from pathlib import Path
from typing import Any, Dict, Optional

from ..accounting.rules import DomainError

TEMPLATE_DIR = Path(__file__).resolve().parents[1] / "xbrl" / "templates"
DEFAULT_JSONNET_PATH = Path(__file__).resolve().parents[2] / "sample_data" / "ixbrl-reporter-jsonnet"
TEMPLATES = {"dormant": "dormant.jsonnet", "micro": "micro.jsonnet", "small": "small.jsonnet"}


class UKAccountsRenderer:
    def __init__(self, jsonnet_path: Optional[str] = None, software_name: str = "ukaccounts"):
        self.jsonnet_path = Path(
            jsonnet_path or os.getenv("IXBRL_REPORTER_JSONNET_PATH") or DEFAULT_JSONNET_PATH
        ).resolve()
        self.software_name = software_name

    def load_template(self, account_type: str) -> Dict[str, Any]:
        """Evaluate the jsonnet template into the base ixbrl-reporter configuration."""
        if account_type not in TEMPLATES:
            raise DomainError("Account type must be dormant, micro or small")
        if not self.jsonnet_path.is_dir():
            raise DomainError(
                "ixbrl-reporter-jsonnet is not available. Run scripts/bootstrap_upstreams.py "
                "or set IXBRL_REPORTER_JSONNET_PATH to a checkout of the upstream repository."
            )
        try:
            import _jsonnet
        except ImportError as exc:
            raise RuntimeError("The 'jsonnet' package is not installed (see requirements.txt)") from exc
        result = _jsonnet.evaluate_file(
            str(TEMPLATE_DIR / TEMPLATES[account_type]), jpathdir=str(self.jsonnet_path)
        )
        return json.loads(result)

    def render(self, config: Dict[str, Any]) -> str:
        """Run ixbrl-reporter on a fully populated configuration and return the iXBRL text."""
        try:
            import io

            import ixbrl_reporter.accounts as accounts
            from ixbrl_reporter.config import Config
            from ixbrl_reporter.data_source import DataSource
            from ixbrl_reporter.taxonomy import Taxonomy
        except ImportError as exc:
            raise RuntimeError(
                f"ixbrl-reporter is not installed ({exc}). Install requirements.txt."
            ) from exc

        with tempfile.TemporaryDirectory(prefix="ukaccounts_") as tmp:
            config_path = os.path.join(tmp, "config.json")
            with open(config_path, "w", encoding="utf-8") as handle:
                json.dump(config, handle, indent=2)

            cfg = Config.load(config_path)
            cfg.set("internal.software-name", self.software_name)
            session = accounts.get_class(cfg.get("accounts.kind"))(
                cfg.get("accounts.file"), cfg.get("metadata.accounting.currency")
            )
            data = DataSource(cfg, session)
            element = data.get_element("report")
            taxonomy = Taxonomy(cfg.get("report.taxonomy"), data)
            out = io.StringIO()
            element.to_ixbrl(taxonomy, out)
            return out.getvalue()
