"""Gathering the inputs for a set of accounts, fingerprints and generated-file lookups."""
from __future__ import annotations

import hashlib
import json
import os
from dataclasses import dataclass
from datetime import date
from pathlib import Path
from typing import Any, Dict, Mapping, Optional

from sqlalchemy.orm import Session

from .. import config
from ..accounting import rules
from ..accounting.engine import AccountingEngine
from ..accounting.rules import DomainError, NotFoundError, as_date
from ..db.database import AccountsDetails, AccountsFile, Company, FiscalPeriod
from ..uk_accounts import mapping, statutory
from ..uk_accounts.config_builder import (
    CompanyInfo,
    DetailsInfo,
    PeriodInfo,
    inputs_fingerprint,
    parse_directors,
)


@dataclass
class Inputs:
    company: CompanyInfo
    period: PeriodInfo
    previous: Optional[PeriodInfo]
    details: DetailsInfo
    contact: Dict[str, str]
    paths: Dict[str, str]


def load_contact() -> Dict[str, str]:
    return {
        "name": os.getenv("CH_CONTACT_NAME", "").strip(),
        "email": os.getenv("CH_CONTACT_EMAIL", "").strip(),
        "number": os.getenv("CH_CONTACT_NUMBER", "").strip(),
    }


def get_details(db: Session, company_id: int, period_id: int) -> Optional[AccountsDetails]:
    return db.query(AccountsDetails).filter(
        AccountsDetails.company_id == company_id, AccountsDetails.period_id == period_id
    ).first()


def build_inputs(
    db: Session,
    company: Company,
    period: FiscalPeriod,
    account_type: str,
    *,
    today: Optional[date] = None,
) -> Inputs:
    """Collect and validate everything the accounts need. Raises DomainError with all problems."""
    details = get_details(db, company.id, period.id)
    if details is None:
        raise DomainError("Save the accounts details (approval date, directors, employees, activities) first")
    directors = parse_directors(company.directors)
    statutory.validate_details(
        account_type=account_type,
        period_end=as_date(period.end_date),
        approval_date=details.approval_date,
        today=today or date.today(),
        directors=directors,
        signing_director=details.signing_director,
        average_employees=details.average_employees,
        principal_activities=details.principal_activities,
        confirm_eligibility=bool(details.confirm_eligibility),
        confirm_audit_exemption=bool(details.confirm_audit_exemption),
    )
    periods = db.query(FiscalPeriod).filter(FiscalPeriod.company_id == company.id).all()
    prev_row = rules.previous_period(
        [(p.id, p.start_date, p.end_date, p.name) for p in periods], as_date(period.start_date)
    )
    previous = PeriodInfo(prev_row[3], as_date(prev_row[1]), as_date(prev_row[2])) if prev_row else None
    return Inputs(
        company=CompanyInfo(
            name=company.name,
            number=company.company_number,
            company_type=company.company_type,
            sic_code=company.sic_code,
            incorporation_date=company.incorporation_date,
            directors=directors,
        ),
        period=PeriodInfo(period.name, as_date(period.start_date), as_date(period.end_date)),
        previous=previous,
        details=DetailsInfo(
            approval_date=details.approval_date,
            signing_director=details.signing_director,
            average_employees=int(details.average_employees),
            principal_activities=details.principal_activities.strip(),
        ),
        contact=load_contact(),
        paths=mapping.load_paths(config.ACCOUNT_PATHS_FILE),
    )


def source_fingerprint(engine: AccountingEngine, inputs: Inputs, company_id: int, period: FiscalPeriod,
                       account_type: str) -> str:
    ledger = engine.ledger_fingerprint(company_id, period.end_date)
    other = inputs_fingerprint(
        inputs.company, inputs.period, inputs.details, account_type, inputs.paths,
        previous=inputs.previous, contact=inputs.contact,
    )
    return hashlib.sha256(f"{ledger}:{other}".encode("utf-8")).hexdigest()


def sha256_of(path: Path) -> str:
    digest = hashlib.sha256()
    with open(path, "rb") as handle:
        for chunk in iter(lambda: handle.read(65536), b""):
            digest.update(chunk)
    return digest.hexdigest()


def file_path(record: AccountsFile) -> Path:
    """Path of a generated file, refusing anything outside the generated directory."""
    name = record.filename
    if not name or os.path.basename(name) != name or not name.startswith(f"accounts_{record.company_id}_"):
        raise DomainError("Invalid stored filename")
    path = (config.GENERATED_DIR / name).resolve()
    if config.GENERATED_DIR.resolve() not in path.parents:
        raise DomainError("Invalid stored filename")
    return path


def get_file(db: Session, company_id: int, file_id: int) -> AccountsFile:
    record = db.query(AccountsFile).filter(
        AccountsFile.id == file_id, AccountsFile.company_id == company_id
    ).first()
    if not record:
        raise NotFoundError("Generated accounts file not found for this company")
    return record


def _loads(value: Optional[str], default: Any) -> Any:
    if not value:
        return default
    try:
        return json.loads(value)
    except ValueError:
        return default


def file_to_dict(record: AccountsFile) -> Dict[str, Any]:
    return {
        "id": record.id,
        "period_id": record.period_id,
        "account_type": record.account_type,
        "filename": record.filename,
        "created_at": record.created_at.strftime("%Y-%m-%d %H:%M"),
        "reconciliation_ok": bool(record.reconciliation_ok),
        "reconciliation": _loads(record.reconciliation_report, {}),
        "warnings": _loads(record.warnings, []),
        "validation_valid": record.validation_valid,
        "validated_current": bool(record.validated_sha256 and record.validated_sha256 == record.sha256),
        "validated_at": record.validated_at.strftime("%Y-%m-%d %H:%M") if record.validated_at else None,
    }
