"""Runtime configuration, read once from environment variables.

Nothing in here talks to the network or the database, so it is safe to import
from anywhere (including tests, which set the environment before importing).
"""
from __future__ import annotations

import os
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]


def _flag(name: str, default: bool = False) -> bool:
    value = os.getenv(name)
    if value is None:
        return default
    return value.strip().lower() in {"1", "true", "yes", "on"}


APP_ENV = os.getenv("APP_ENV", "development").strip().lower()
IS_PRODUCTION = APP_ENV == "production"

# Everything the app writes (database, generated iXBRL, filing counters, the
# development key) lives here, outside the source tree.
DATA_DIR = Path(os.getenv("DATA_DIR") or ROOT / "data").resolve()
GENERATED_DIR = DATA_DIR / "generated"
FILING_STATE_DIR = Path(os.getenv("CH_FILING_STATE_DIR") or DATA_DIR / "ch_filing_state").resolve()
for _directory in (DATA_DIR, GENERATED_DIR):
    _directory.mkdir(parents=True, exist_ok=True)

DATABASE_URL = os.getenv("DATABASE_URL") or f"sqlite:///{(DATA_DIR / 'ukaccounts.db').as_posix()}"

# Single-user HTTP Basic authentication.
AUTH_USER = os.getenv("AUTH_USER", "")
AUTH_PASSWORD = os.getenv("AUTH_PASSWORD", "")
ALLOWED_ORIGINS = {
    origin.strip().rstrip("/")
    for origin in os.getenv("ALLOWED_ORIGINS", "").split(",")
    if origin.strip()
}

# Companies House
CH_PACKAGE_REFERENCE = os.getenv("CH_PACKAGE_REFERENCE", "0000")
ALLOW_LIVE_FILING = _flag("ALLOW_LIVE_FILING")

# Arelle
ARELLE_INTERNET = os.getenv("ARELLE_INTERNET", "online")
ARELLE_PACKAGES = [p for p in os.getenv("ARELLE_TAXONOMY_PACKAGES", "").split(os.pathsep) if p]

# ledger -> ixbrl-reporter account naming (see config/account_paths.json)
ACCOUNT_PATHS_FILE = Path(os.getenv("ACCOUNT_PATHS_FILE") or ROOT / "config" / "account_paths.json")


def auth_enabled() -> bool:
    return bool(AUTH_USER and AUTH_PASSWORD)


def production_problems() -> list[str]:
    """Return everything that makes this process unsafe to run in production."""
    problems: list[str] = []
    if not os.getenv("CH_CREDENTIALS_KEY"):
        problems.append("CH_CREDENTIALS_KEY is not set")
    if not auth_enabled():
        problems.append("AUTH_USER and AUTH_PASSWORD are not set")
    elif len(AUTH_PASSWORD) < 12:
        problems.append("AUTH_PASSWORD must be at least 12 characters")
    return problems
