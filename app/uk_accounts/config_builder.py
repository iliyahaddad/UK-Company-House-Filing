"""Build the ixbrl-reporter configuration from plain data (pure functions)."""
from __future__ import annotations

import copy
import hashlib
import json
from dataclasses import asdict, dataclass, field
from datetime import date
from typing import Any, Dict, List, Mapping, Optional

from dateutil.relativedelta import relativedelta

from ..accounting.rules import DomainError

JURISDICTION = {
    "EW": "England and Wales",
    "SC": "Scotland",
    "NI": "Northern Ireland",
}
FORMATION_COUNTRY = {
    "EW": "england-and-wales",
    "SC": "scotland",
    "NI": "northern-ireland",
}


@dataclass(frozen=True)
class CompanyInfo:
    name: str
    number: str
    company_type: str
    sic_code: Optional[str]
    incorporation_date: Optional[date]
    directors: List[str] = field(default_factory=list)


@dataclass(frozen=True)
class PeriodInfo:
    name: str
    start: date
    end: date


@dataclass(frozen=True)
class DetailsInfo:
    approval_date: date
    signing_director: str
    average_employees: int
    principal_activities: str


def parse_directors(raw: Optional[str]) -> List[str]:
    """Directors are stored as free text: JSON list, or names separated by , or ;"""
    text = (raw or "").strip()
    if not text:
        return []
    try:
        parsed = json.loads(text)
        if isinstance(parsed, list):
            return [str(item).strip() for item in parsed if str(item).strip()]
        if isinstance(parsed, dict):
            values = parsed.get("names") or parsed.get("directors") or []
            if isinstance(values, list):
                return [str(item).strip() for item in values if str(item).strip()]
    except (json.JSONDecodeError, TypeError):
        pass
    return [part.strip() for part in text.replace(";", ",").split(",") if part.strip()]


def _iso(value: date) -> str:
    return value.strftime("%Y-%m-%d")


def build_report_config(
    base: Mapping[str, Any],
    *,
    company: CompanyInfo,
    period: PeriodInfo,
    previous: Optional[PeriodInfo],
    details: DetailsInfo,
    account_type: str,
    contact: Mapping[str, str],
    csv_path: str,
) -> Dict[str, Any]:
    """Return a copy of ``base`` (the evaluated jsonnet template) filled with real data."""
    if not all(contact.get(key) for key in ("name", "email", "number")):
        raise DomainError(
            "Contact details are incomplete. Set CH_CONTACT_NAME, CH_CONTACT_NUMBER and CH_CONTACT_EMAIL."
        )
    if not company.directors:
        raise DomainError("At least one director is required to generate UK accounts")
    if details.signing_director not in company.directors:
        raise DomainError("Signing director must be one of the company's directors")
    if company.incorporation_date is None:
        raise DomainError("Company incorporation date is required to generate UK accounts")

    cfg = copy.deepcopy(dict(base))
    cfg["accounts"]["file"] = csv_path
    cfg["accounts"]["kind"] = "csv"

    business = cfg["metadata"]["business"]
    business["company-name"] = company.name
    business["company-number"] = company.number
    business["contact"]["name"] = contact["name"]
    business["contact"]["email"] = contact["email"]
    business["contact"].setdefault("phone", {})["number"] = contact["number"]
    business["directors"] = list(company.directors)
    business["is-dormant"] = account_type == "dormant"
    business["sic-codes"] = [company.sic_code] if company.sic_code else []
    business["jurisdiction"] = JURISDICTION.get(company.company_type, "England and Wales")
    business["company-formation"]["date"] = _iso(company.incorporation_date)
    business["company-formation"]["country"] = FORMATION_COUNTRY.get(
        company.company_type, business["company-formation"].get("country", "england-and-wales")
    )

    officer = f"director{company.directors.index(details.signing_director) + 1}"
    approval = _iso(details.approval_date)
    cfg["metadata"]["directors"]["report-date"] = approval
    accounting = cfg["metadata"]["accounting"]
    accounting["authorised-date"] = approval
    accounting["balance-sheet-date"] = _iso(period.end)
    accounting["date"] = _iso(period.end)
    accounting["signing-officer"] = officer
    accounting["directors-report-signing-officer"] = officer

    if previous is not None:
        prev = {"name": previous.name, "start": _iso(previous.start), "end": _iso(previous.end)}
    else:
        prev = {
            "name": str(period.end.year - 1),
            "start": _iso(period.start - relativedelta(years=1)),
            "end": _iso(period.end - relativedelta(years=1)),
        }
    accounting["periods"][0] = {"name": period.name, "start": _iso(period.start), "end": _iso(period.end)}
    accounting["periods"][1] = prev
    return cfg


def inputs_fingerprint(
    company: CompanyInfo,
    period: PeriodInfo,
    details: DetailsInfo,
    account_type: str,
    account_paths: Mapping[str, str],
    previous: Optional[PeriodInfo] = None,
    contact: Optional[Mapping[str, str]] = None,
) -> str:
    """Hash of every non-ledger input that ends up in the accounts."""
    payload = {
        "company": asdict(company),
        "period": asdict(period),
        "previous": asdict(previous) if previous else None,
        "details": asdict(details),
        "account_type": account_type,
        "paths": dict(sorted(account_paths.items())),
        "contact": dict(sorted((contact or {}).items())),
    }
    blob = json.dumps(payload, sort_keys=True, default=str).encode("utf-8")
    return hashlib.sha256(blob).hexdigest()
