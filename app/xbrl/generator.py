"""Generate, repair and reconcile one set of accounts."""
from __future__ import annotations

import json
import os
import tempfile
import uuid
from datetime import date, datetime, timezone
from pathlib import Path
from typing import Any, Dict, List, Optional

from sqlalchemy.orm import Session

from .. import config
from ..accounting.engine import AccountingEngine
from ..accounting.rules import DomainError, ZERO, NotFoundError
from ..db.database import Account, AccountsFile, Company, FiscalPeriod, JournalEntry
from ..services import files as file_service
from ..uk_accounts import mapping, statutory
from ..uk_accounts.config_builder import build_report_config
from ..uk_accounts.generator import UKAccountsRenderer
from .postprocess import postprocess_ixbrl
from .reconcile import reconcile


def _parent_names(account: Account, by_id: Dict[int, Account]) -> tuple:
    names: List[str] = []
    seen = {account.id}
    parent_id = account.parent_id
    while parent_id and parent_id not in seen and parent_id in by_id:
        seen.add(parent_id)
        parent = by_id[parent_id]
        names.insert(0, parent.name)
        parent_id = parent.parent_id
    return tuple(names)


class IxBRLGenerator:
    def __init__(
        self,
        db: Session,
        renderer: Optional[UKAccountsRenderer] = None,
        output_dir=None,
        today: Optional[date] = None,
    ):
        self.db = db
        self.engine = AccountingEngine(db)
        self.renderer = renderer or UKAccountsRenderer()
        self.output_dir = output_dir or config.GENERATED_DIR
        self.today = today

    # ------------------------------------------------------------------ csv
    def _csv_rows(self, company_id: int, period: FiscalPeriod, paths: Dict[str, str]):
        accounts = self.db.query(Account).filter(Account.company_id == company_id).all()
        by_id = {a.id: a for a in accounts}
        info = {
            a.id: mapping.AccountInfo(
                name=a.name, type=a.type, code=a.code, category=a.category,
                parent_names=_parent_names(a, by_id),
            )
            for a in accounts
        }
        entries = (
            self.db.query(JournalEntry)
            .filter(JournalEntry.company_id == company_id, JournalEntry.date <= period.end_date)
            .order_by(JournalEntry.date, JournalEntry.id)
            .all()
        )
        data = [
            mapping.EntryData(
                id=e.id, date=e.date, description=e.description or "",
                lines=tuple((l.account_id, l.debit, l.credit) for l in e.lines),
            )
            for e in entries
        ]
        return mapping.build_csv_rows(data, info, paths)

    # ------------------------------------------------------------------ main entry
    def generate(self, company_id: int, period_id: int, account_type: str) -> AccountsFile:
        if account_type not in statutory.ACCOUNT_TYPES:
            raise DomainError("Account type must be dormant, micro or small")
        company = self.db.query(Company).filter(Company.id == company_id).first()
        if not company:
            raise NotFoundError(f"Company {company_id} not found")
        period = self.engine._period(company_id, period_id)
        inputs = file_service.build_inputs(self.db, company, period, account_type, today=self.today)

        balance_sheet = self.engine.get_balance_sheet(company_id, period_id)
        profit_loss = self.engine.get_profit_loss(company_id, period_id)

        warnings: List[str] = []
        if account_type == "dormant":
            movement = any(profit_loss[k] != ZERO for k in
                           ("revenue", "cost_of_sales", "operating_expenses", "tax"))
            if movement:
                raise DomainError(
                    "This period has income or expenses, so the company is not dormant. "
                    "Choose micro or small accounts."
                )
        else:
            warnings += statutory.eligibility_warnings(
                account_type, inputs.period.start,
                turnover=profit_loss["revenue"],
                balance_sheet_total=balance_sheet["total_assets"],
                employees=inputs.details.average_employees,
            )

        base = self.renderer.load_template(account_type)
        with tempfile.TemporaryDirectory(prefix="ukaccounts_csv_") as tmp:
            csv_path = os.path.join(tmp, "accounts.csv")
            mapping.write_csv(csv_path, self._csv_rows(company_id, period, inputs.paths))
            report_config = build_report_config(
                base,
                company=inputs.company, period=inputs.period, previous=inputs.previous,
                details=inputs.details, account_type=account_type,
                contact=inputs.contact, csv_path=csv_path,
            )
            raw = self.renderer.render(report_config)

        repaired = postprocess_ixbrl(
            raw,
            period_start=inputs.period.start,
            period_end=inputs.period.end,
            average_employees=inputs.details.average_employees,
            principal_activities=inputs.details.principal_activities,
        )
        outcome = reconcile(
            repaired.xml,
            period_start=inputs.period.start,
            period_end=inputs.period.end,
            balance_sheet=balance_sheet,
            profit_loss=profit_loss if account_type == "small" else None,
        )
        if not outcome.ok:
            warnings.append(outcome.message)

        stamp = datetime.now(timezone.utc).strftime("%Y%m%d%H%M%S")
        filename = f"accounts_{company_id}_{period_id}_{account_type}_{stamp}_{uuid.uuid4().hex[:6]}.xhtml"
        path = os.path.join(str(self.output_dir), filename)
        with open(path, "wb") as handle:
            handle.write(repaired.xml)

        report = outcome.as_dict()
        report["repairs"] = sorted(set(repaired.changes))
        record = AccountsFile(
            company_id=company_id,
            period_id=period_id,
            account_type=account_type,
            filename=filename,
            sha256=file_service.sha256_of(Path(path)),
            source_fingerprint=file_service.source_fingerprint(self.engine, inputs, company_id, period, account_type),
            reconciliation_ok=outcome.ok,
            reconciliation_report=json.dumps(report),
            warnings=json.dumps(warnings),
        )
        self.db.add(record)
        self.db.commit()
        self.db.refresh(record)
        return record
