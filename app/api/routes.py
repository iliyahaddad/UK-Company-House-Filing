"""HTTP routes: HTML pages (thin shells filled in by JavaScript) and the JSON API.

Routes are plain ``def`` so FastAPI runs them in its thread pool; database work,
iXBRL generation and Arelle never block the event loop.
"""
from __future__ import annotations

import json
import os
from datetime import date, datetime, timezone
from decimal import Decimal
from typing import Any

from fastapi import APIRouter, Depends, Request
from fastapi.responses import HTMLResponse, JSONResponse
from fastapi.templating import Jinja2Templates
from sqlalchemy.orm import Session

from .. import config
from ..accounting import rules
from ..accounting.engine import AccountingEngine
from ..accounting.rules import DomainError, NotFoundError
from ..db.database import (
    Account,
    AccountsDetails,
    AccountsFile,
    Company,
    FilingCredential,
    JournalEntry,
    Submission,
    get_db,
)
from ..filing.filer import CompaniesHouseFiler, validate_gateway_url
from ..services import files as file_service
from ..services.filing_guard import FileState, check_submission_allowed
from ..uk_accounts.config_builder import parse_directors
from ..validation.validator import ArelleValidator
from ..xbrl.generator import IxBRLGenerator
from . import schemas

router = APIRouter()
templates = Jinja2Templates(directory=os.path.join(os.path.dirname(__file__), "..", "web", "templates"))


# --------------------------------------------------------------------------- helpers
def jsonable(value: Any) -> Any:
    if isinstance(value, Decimal):
        return str(value)
    if isinstance(value, (datetime, date)):
        return value.isoformat()
    if isinstance(value, dict):
        return {key: jsonable(item) for key, item in value.items()}
    if isinstance(value, (list, tuple)):
        return [jsonable(item) for item in value]
    return value


def ok(**data: Any) -> JSONResponse:
    return JSONResponse(jsonable({"success": True, **data}))


def _company(db: Session, company_id: int) -> Company:
    return AccountingEngine(db)._company(company_id)


def _page(request: Request, name: str, **context: Any):
    return templates.TemplateResponse(request, name, context)


def _account_dict(account: Account) -> dict:
    return {
        "id": account.id,
        "code": account.code,
        "name": account.name,
        "type": account.type,
        "category": account.category,
        "effective_category": account.category or rules.default_category(account.type, account.code, account.name),
        "parent_id": account.parent_id,
    }


def _period_dict(period) -> dict:
    return {
        "id": period.id,
        "name": period.name,
        "start_date": period.start_date.strftime("%Y-%m-%d"),
        "end_date": period.end_date.strftime("%Y-%m-%d"),
        "is_current": period.is_current,
    }


# --------------------------------------------------------------------------- pages
@router.get("/", response_class=HTMLResponse)
def index(request: Request):
    return _page(request, "index.html")


@router.get("/companies", response_class=HTMLResponse)
def companies_page(request: Request, db: Session = Depends(get_db)):
    companies = db.query(Company).order_by(Company.name).all()
    return _page(request, "companies.html", companies=companies)


@router.get("/companies/{company_id}", response_class=HTMLResponse)
def company_detail(request: Request, company_id: int, db: Session = Depends(get_db)):
    return _page(request, "company_detail.html", company=_company(db, company_id))


@router.get("/companies/{company_id}/setup", response_class=HTMLResponse)
def setup_page(request: Request, company_id: int, db: Session = Depends(get_db)):
    return _page(request, "setup.html", company=_company(db, company_id),
                 categories=sorted(rules.CATEGORIES), types=rules.ACCOUNT_TYPES)


@router.get("/companies/{company_id}/journal", response_class=HTMLResponse)
def journal_page(request: Request, company_id: int, db: Session = Depends(get_db)):
    return _page(request, "journal.html", company=_company(db, company_id))


@router.get("/companies/{company_id}/reports", response_class=HTMLResponse)
def reports_page(request: Request, company_id: int, db: Session = Depends(get_db)):
    return _page(request, "reports.html", company=_company(db, company_id))


@router.get("/companies/{company_id}/uk-accounts", response_class=HTMLResponse)
def uk_accounts_page(request: Request, company_id: int, db: Session = Depends(get_db)):
    return _page(request, "uk_accounts.html", company=_company(db, company_id))


@router.get("/companies/{company_id}/validation", response_class=HTMLResponse)
def validation_page(request: Request, company_id: int, db: Session = Depends(get_db)):
    return _page(request, "validation.html", company=_company(db, company_id))


@router.get("/companies/{company_id}/filing", response_class=HTMLResponse)
def filing_page(request: Request, company_id: int, db: Session = Depends(get_db)):
    company = _company(db, company_id)
    # Load plain columns only: the encrypted secrets are never read for this page.
    row = db.query(
        FilingCredential.presenter_id, FilingCredential.gateway_url, FilingCredential.test_mode
    ).filter(FilingCredential.company_id == company_id).first()
    credentials = None
    if row:
        credentials = {"presenter_id": row[0], "gateway_url": row[1], "test_mode": row[2]}
    return _page(request, "filing.html", company=company, credentials=credentials,
                 live_enabled=config.ALLOW_LIVE_FILING)


# --------------------------------------------------------------------------- companies, accounts, periods
@router.post("/api/companies")
def create_company(body: schemas.CompanyIn, db: Session = Depends(get_db)):
    company = AccountingEngine(db).create_company(
        name=body.name, company_number=body.company_number,
        registered_address=body.registered_address, company_type=body.company_type,
        sic_code=body.sic_code, directors=body.directors, incorporation_date=body.incorporation_date,
    )
    return ok(id=company.id, name=company.name)


@router.get("/api/companies/{company_id}/accounts")
def get_accounts(company_id: int, db: Session = Depends(get_db)):
    _company(db, company_id)
    accounts = db.query(Account).filter(Account.company_id == company_id).order_by(Account.code).all()
    return ok(accounts=[_account_dict(a) for a in accounts])


@router.post("/api/companies/{company_id}/accounts")
def create_account(company_id: int, body: schemas.AccountIn, db: Session = Depends(get_db)):
    account = AccountingEngine(db).create_account(
        company_id, body.code, body.name, body.type, body.parent_id, body.category
    )
    return ok(account=_account_dict(account))


@router.post("/api/companies/{company_id}/accounts/seed-chart")
def seed_chart(company_id: int, db: Session = Depends(get_db)):
    created = AccountingEngine(db).seed_default_chart(company_id)
    return ok(created=len(created))


@router.get("/api/companies/{company_id}/periods")
def get_periods(company_id: int, db: Session = Depends(get_db)):
    company = _company(db, company_id)
    return ok(periods=[_period_dict(p) for p in company.fiscal_periods])


@router.post("/api/companies/{company_id}/periods")
def create_period(company_id: int, body: schemas.PeriodIn, db: Session = Depends(get_db)):
    period = AccountingEngine(db).create_fiscal_period(
        company_id, body.name, body.start_date, body.end_date, body.is_current
    )
    return ok(period=_period_dict(period))


# --------------------------------------------------------------------------- journal
@router.get("/api/companies/{company_id}/journal")
def list_journal(company_id: int, db: Session = Depends(get_db)):
    _company(db, company_id)
    accounts = {a.id: a for a in db.query(Account).filter(Account.company_id == company_id).all()}
    entries = (
        db.query(JournalEntry).filter(JournalEntry.company_id == company_id)
        .order_by(JournalEntry.date.desc(), JournalEntry.id.desc()).limit(200).all()
    )
    result = []
    for entry in entries:
        result.append({
            "id": entry.id,
            "date": entry.date.strftime("%Y-%m-%d"),
            "description": entry.description,
            "reference": entry.reference,
            "lines": [
                {
                    "account": f"{accounts[l.account_id].code} {accounts[l.account_id].name}"
                    if l.account_id in accounts else str(l.account_id),
                    "debit": l.debit, "credit": l.credit, "description": l.description,
                }
                for l in entry.lines
            ],
        })
    return ok(entries=result)


@router.post("/api/companies/{company_id}/journal")
def create_journal_entry(company_id: int, body: schemas.JournalIn, db: Session = Depends(get_db)):
    entry = AccountingEngine(db).create_journal_entry(
        company_id=company_id,
        date=body.date,
        description=body.description,
        reference=body.reference,
        lines=[line.model_dump() for line in body.lines],
        fiscal_period_id=body.fiscal_period_id,
    )
    return ok(id=entry.id, description=entry.description, fiscal_period_id=entry.fiscal_period_id)


# --------------------------------------------------------------------------- reports
@router.get("/api/companies/{company_id}/reports/trial-balance")
def trial_balance(company_id: int, period_id: int | None = None, db: Session = Depends(get_db)):
    rows = AccountingEngine(db).get_trial_balance(company_id, period_id)
    return ok(rows=rows, **rules.trial_balance_totals(rows))


@router.get("/api/companies/{company_id}/reports/profit-loss")
def profit_loss(company_id: int, period_id: int | None = None, db: Session = Depends(get_db)):
    return ok(report=AccountingEngine(db).get_profit_loss(company_id, period_id))


@router.get("/api/companies/{company_id}/reports/balance-sheet")
def balance_sheet(company_id: int, period_id: int | None = None, db: Session = Depends(get_db)):
    return ok(report=AccountingEngine(db).get_balance_sheet(company_id, period_id))


# --------------------------------------------------------------------------- accounts details + generation
@router.get("/api/companies/{company_id}/details")
def get_details(company_id: int, period_id: int, db: Session = Depends(get_db)):
    company = _company(db, company_id)
    AccountingEngine(db)._period(company_id, period_id)
    row = file_service.get_details(db, company_id, period_id)
    details = None
    if row:
        details = {
            "approval_date": row.approval_date.isoformat() if row.approval_date else None,
            "signing_director": row.signing_director,
            "average_employees": row.average_employees,
            "principal_activities": row.principal_activities,
            "confirm_eligibility": row.confirm_eligibility,
            "confirm_audit_exemption": row.confirm_audit_exemption,
        }
    return ok(details=details, directors=parse_directors(company.directors))


@router.put("/api/companies/{company_id}/details")
def save_details(company_id: int, body: schemas.DetailsIn, db: Session = Depends(get_db)):
    company = _company(db, company_id)
    period = AccountingEngine(db)._period(company_id, body.period_id)
    directors = parse_directors(company.directors)
    if body.approval_date and body.approval_date < rules.as_date(period.end_date):
        raise DomainError("Approval date cannot be before the end of the accounting period")
    if body.signing_director and body.signing_director not in directors:
        raise DomainError("Signing director must be one of the company's directors")

    row = file_service.get_details(db, company_id, body.period_id)
    if row is None:
        row = AccountsDetails(company_id=company_id, period_id=body.period_id)
        db.add(row)
    row.approval_date = body.approval_date
    row.signing_director = body.signing_director
    row.average_employees = body.average_employees
    row.principal_activities = body.principal_activities
    row.confirm_eligibility = body.confirm_eligibility
    row.confirm_audit_exemption = body.confirm_audit_exemption
    db.commit()
    return ok()


@router.get("/api/companies/{company_id}/files")
def list_files(company_id: int, db: Session = Depends(get_db)):
    _company(db, company_id)
    records = (
        db.query(AccountsFile).filter(AccountsFile.company_id == company_id)
        .order_by(AccountsFile.id.desc()).all()
    )
    return ok(files=[file_service.file_to_dict(r) for r in records])


@router.post("/api/companies/{company_id}/uk-accounts/generate")
def generate_uk_accounts(company_id: int, body: schemas.GenerateIn, db: Session = Depends(get_db)):
    record = IxBRLGenerator(db).generate(company_id, body.period_id, body.account_type)
    return ok(file=file_service.file_to_dict(record))


@router.post("/api/companies/{company_id}/validate")
def validate_ixbrl(company_id: int, body: schemas.FileRef, db: Session = Depends(get_db)):
    _company(db, company_id)
    record = file_service.get_file(db, company_id, body.file_id)
    path = file_service.file_path(record)
    if not path.is_file():
        raise NotFoundError("The generated file is missing from disk")
    result = ArelleValidator().validate(str(path))
    record.validation_valid = bool(result["valid"])
    record.validated_sha256 = file_service.sha256_of(path)
    record.validated_at = datetime.now(timezone.utc).replace(tzinfo=None)
    record.validation_summary = json.dumps({"errors": len(result["errors"]), "warnings": len(result["warnings"])})
    db.commit()
    return ok(result=result, file=file_service.file_to_dict(record))


# --------------------------------------------------------------------------- filing
@router.post("/api/companies/{company_id}/filing/credentials")
def save_credentials(company_id: int, body: schemas.CredentialsIn, db: Session = Depends(get_db)):
    _company(db, company_id)
    gateway = validate_gateway_url(body.gateway_url)
    # Replace without reading: an old row that can no longer be decrypted must not block this.
    db.query(FilingCredential).filter(FilingCredential.company_id == company_id).delete()
    db.add(FilingCredential(
        company_id=company_id, presenter_id=body.presenter_id,
        authentication=body.authentication, company_auth_code=body.company_auth_code,
        gateway_url=gateway, test_mode=body.test_mode,
    ))
    db.commit()
    return ok(configured=True, test_mode=body.test_mode)


@router.get("/api/companies/{company_id}/filing/submissions")
def list_submissions(company_id: int, db: Session = Depends(get_db)):
    _company(db, company_id)
    rows = db.query(Submission).filter(Submission.company_id == company_id).order_by(Submission.id.desc()).all()
    return ok(submissions=[
        {"id": s.id, "submission_id": s.submission_id, "status": s.status, "accounts_type": s.accounts_type,
         "file_id": s.accounts_file_id, "date": s.filing_date.strftime("%Y-%m-%d %H:%M"),
         "detail": (s.response_data or "")[:300] if s.status in ("FAILED", "UNCERTAIN") else ""}
        for s in rows
    ])


@router.post("/api/companies/{company_id}/filing/submit")
def submit_to_companies_house(company_id: int, body: schemas.SubmitIn, db: Session = Depends(get_db)):
    company = _company(db, company_id)
    record = file_service.get_file(db, company_id, body.file_id)
    credential = db.query(FilingCredential).filter(FilingCredential.company_id == company_id).first()
    if credential is None:
        raise DomainError("Companies House filing credentials are not configured")

    engine = AccountingEngine(db)
    period = engine._period(company_id, record.period_id)
    inputs = file_service.build_inputs(db, company, period, record.account_type)
    path = file_service.file_path(record)
    if not path.is_file():
        raise NotFoundError("The generated file is missing from disk")

    earlier = [s.status for s in db.query(Submission).filter(Submission.accounts_file_id == record.id).all()]
    check_submission_allowed(
        file=FileState(record.sha256, record.source_fingerprint, bool(record.reconciliation_ok),
                       record.validation_valid, record.validated_sha256),
        sha256_on_disk=file_service.sha256_of(path),
        current_fingerprint=file_service.source_fingerprint(engine, inputs, company_id, period, record.account_type),
        live=not credential.test_mode,
        live_filing_enabled=config.ALLOW_LIVE_FILING,
        confirm_approval=body.confirm_approval,
        earlier_statuses=earlier,
    )
    submission = CompaniesHouseFiler().submit_accounts(
        db, company, credential, record, path, inputs.details.approval_date
    )
    return ok(submission_id=submission.submission_id, status=submission.status, test_mode=credential.test_mode)


@router.post("/api/companies/{company_id}/filing/submissions/{submission_pk}/status")
def check_submission_status(company_id: int, submission_pk: int, db: Session = Depends(get_db)):
    company = _company(db, company_id)
    submission = db.query(Submission).filter(
        Submission.id == submission_pk, Submission.company_id == company_id
    ).first()
    if submission is None:
        raise NotFoundError("Submission not found for this company")
    credential = db.query(FilingCredential).filter(FilingCredential.company_id == company_id).first()
    if credential is None:
        raise DomainError("Companies House filing credentials are not configured")
    result = CompaniesHouseFiler().get_submission_status(db, company, credential, submission)
    return ok(status=result["status"], submission_id=result["submission_id"])


@router.post("/api/companies/{company_id}/filing/submissions/{submission_pk}/release")
def release_submission(company_id: int, submission_pk: int, body: schemas.ReleaseIn,
                       db: Session = Depends(get_db)):
    _company(db, company_id)
    submission = db.query(Submission).filter(
        Submission.id == submission_pk, Submission.company_id == company_id
    ).first()
    if submission is None:
        raise NotFoundError("Submission not found for this company")
    if not body.confirm:
        raise DomainError("Confirm that you have checked with Companies House that this was not received")
    if submission.status not in ("PENDING", "UNCERTAIN"):
        raise DomainError("Only pending or uncertain submissions can be released")
    submission.status = "RELEASED"
    db.commit()
    return ok(status="RELEASED")
