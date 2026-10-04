"""Arelle-based iXBRL validation through Arelle's supported Python API.

The validator fails *closed*: if Arelle cannot run, or produces no log at all,
the result is "not valid" rather than a silent pass.
"""
from __future__ import annotations

import os
import threading
from pathlib import Path
from typing import Any, Dict, Iterable, List, Optional, Sequence
from xml.etree import ElementTree as ET

from .. import config


class ArelleValidator:
    UK_PLUGIN = "validate/UK"
    UK_DISCLOSURE_SYSTEM = "hmrc"
    LOG_MODE = os.getenv("ARELLE_LOG_MODE", "logToBuffer")
    _session_lock = threading.Lock()  # Arelle allows one Session per process at a time

    def __init__(
        self,
        *,
        plugin: str = UK_PLUGIN,
        disclosure_system: str = UK_DISCLOSURE_SYSTEM,
        internet_connectivity: Optional[str] = None,
        packages: Optional[Sequence[str]] = None,
    ) -> None:
        self.plugin = plugin
        self.disclosure_system = disclosure_system
        self.internet_connectivity = internet_connectivity or config.ARELLE_INTERNET
        self.packages = list(packages if packages is not None else config.ARELLE_PACKAGES)

    @staticmethod
    def _require_arelle():
        try:
            from arelle import Version
            from arelle.api.Session import Session
            from arelle.RuntimeOptions import RuntimeOptions
        except ImportError as exc:
            raise RuntimeError(
                "Arelle is not installed. Install requirements.txt (arelle-release, tinycss2) first."
            ) from exc
        return Session, RuntimeOptions, Version

    @staticmethod
    def _text(value: Any) -> str:
        if value is None:
            return ""
        if isinstance(value, bytes):
            return value.decode("utf-8", errors="replace")
        return str(value)

    @classmethod
    def _parse_xml_logs(cls, xml_logs: Any):
        text = cls._text(xml_logs)
        if not text.strip():
            return [], [], []
        errors: List[str] = []
        warnings: List[str] = []
        info: List[str] = []
        try:
            root = ET.fromstring(text)
        except ET.ParseError:
            lines = [line.strip() for line in text.splitlines() if line.strip()]
            return cls._classify_text(lines)

        for entry in root.iter():
            if entry is root:
                continue
            severity = (entry.attrib.get("level") or entry.attrib.get("severity")
                        or entry.attrib.get("logLevel") or "").upper()
            code = entry.attrib.get("messageCode") or entry.attrib.get("code") or ""
            message = "".join(entry.itertext()).strip()
            if not message:
                continue
            line = f"[{code}] {message}" if code else message
            if severity in {"ERROR", "FATAL", "CRITICAL"}:
                errors.append(line)
            elif severity in {"WARNING", "WARN"}:
                warnings.append(line)
            else:
                info.append(line)
        return errors, warnings, info

    @staticmethod
    def _classify_text(lines: Iterable[str]):
        """Fallback for plain-text logs: Arelle prefixes lines with the level or message code."""
        errors: List[str] = []
        warnings: List[str] = []
        info: List[str] = []
        for line in lines:
            lowered = line.lower()
            if any(marker in lowered for marker in ("[error]", "[fatal]", "[critical]", "error:", "exception")):
                errors.append(line)
            elif "warning" in lowered or lowered.startswith("[warn"):
                warnings.append(line)
            elif lowered.startswith("[arelle:") and "not recognized" in lowered:
                errors.append(line)  # e.g. an unknown disclosure system means nothing was validated
            elif "pluginloadingerror" in lowered or "unable to load module" in lowered:
                errors.append(line)
            else:
                info.append(line)
        return errors, warnings, info

    def _result(self, valid: bool, errors, warnings, info, raw_log: str, version: str,
                selected_ds: str, connectivity: str, packages) -> Dict[str, Any]:
        return {
            "valid": valid,
            "exit_code": 0 if valid else 3,
            "errors": errors,
            "warnings": warnings,
            "info": info,
            "log": raw_log,
            "arelle_version": version,
            "plugin": self.plugin,
            "disclosure_system": selected_ds,
            "internet_connectivity": connectivity,
            "packages": list(packages),
        }

    def validate(
        self,
        ixbrl_path: str,
        *,
        disclosure_system: Optional[str] = None,
        internet_connectivity: Optional[str] = None,
        packages: Optional[Sequence[str]] = None,
    ) -> Dict[str, Any]:
        path = Path(ixbrl_path).resolve()
        if not path.is_file():
            raise FileNotFoundError(f"iXBRL file not found: {path}")

        Session, RuntimeOptions, Version = self._require_arelle()
        selected_ds = disclosure_system or self.disclosure_system
        connectivity = internet_connectivity or self.internet_connectivity
        selected_packages = list(packages if packages is not None else self.packages)
        version = getattr(Version, "__version__", "unknown")

        options = RuntimeOptions(
            entrypointFile=str(path),
            disclosureSystemName=selected_ds,
            internetConnectivity=connectivity,
            packages=selected_packages,
            plugins=self.plugin,
            validate=True,
            keepOpen=False,
            logFile=self.LOG_MODE,
            logFormat="[%(levelname)s] [%(messageCode)s] %(message)s - %(file)s",
            logPropagate=False,
        )

        with self._session_lock:
            try:
                with Session() as session:
                    run_ok = session.run(options)
                    raw_log = ""
                    for fmt in ("xml", "text"):
                        try:
                            raw_log = self._text(session.get_logs(fmt))
                        except Exception:
                            continue
                        if raw_log.strip():
                            break
            except Exception as exc:
                return self._result(False, [f"Arelle execution failed: {exc}"], [], [], "", version,
                                    selected_ds, connectivity, selected_packages)

        errors, warnings, info = self._parse_xml_logs(raw_log)
        if not raw_log.strip():
            errors.append(
                "Arelle produced no log, so the result cannot be trusted. Check the Arelle "
                "installation and the log mode (ARELLE_LOG_MODE)."
            )
        if not run_ok and not errors:
            errors.append("Arelle validation run reported failure without a structured error message")
        valid = bool(run_ok) and not errors
        return self._result(valid, errors, warnings, info, raw_log, version, selected_ds, connectivity,
                            selected_packages)
