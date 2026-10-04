"""Double-entry bookkeeping on top of SQLAlchemy.

Decisions live in ``rules.py``; this module only reads and writes rows.
A period's figures are always selected by *date* (period start..end), so the
trial balance, profit and loss, balance sheet and the iXBRL export agree.
"""
from __future__ import annotations

import hashlib
from datetime import date, datetime
from decimal import Decimal
from typing import Any, Dict, List, Optional, Tuple

from sqlalchemy import func
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session

from ..db.database import Account, Company, FiscalPeriod, JournalEntry, JournalLine
from . import rules
from .rules import (
    DEFAULT_CHART,
    ZERO,
    AccountRow,
    ConflictError,
    DomainError,
    NotFoundError,
    as_date,
    midnight,
    money,
)

Sums = Dict[int, Tuple[Decimal, Decimal]]


class AccountingEngine:
    def __init__(self, db: Session):
        self.db = db

    # ------------------------------------------------------------------ lookups
    def _company(self, company_id: int) -> Company:
        company = self.db.query(Company).filter(Company.id == company_id).first()
        if not company:
            raise NotFoundError(f"Company {company_id} not found")
        return company

    def _account(self, company_id: int, account_id: int) -> Account:
        account = self.db.query(Account).filter(
            Account.id == account_id, Account.company_id == company_id
        ).first()
        if not account:
            raise NotFoundError(f"Account {account_id} does not belong to company {company_id}")
        return account

    def _period(self, company_id: int, period_id: int) -> FiscalPeriod:
        period = self.db.query(FiscalPeriod).filter(
            FiscalPeriod.id == period_id, FiscalPeriod.company_id == company_id
        ).first()
        if not period:
            raise NotFoundError(f"Fiscal period {period_id} does not belong to company {company_id}")
        return period

    def _commit(self, conflict_message: str) -> None:
        try:
            self.db.commit()
        except IntegrityError as exc:
            self.db.rollback()
            raise ConflictError(conflict_message) from exc
        except Exception:
            self.db.rollback()
            raise

    # ------------------------------------------------------------------ companies
    def create_company(
        self,
        name: str,
        company_number: str,
        registered_address: Optional[str] = None,
        company_type: str = "EW",
        sic_code: Optional[str] = None,
        directors: Optional[str] = None,
        incorporation_date: Optional[date] = None,
    ) -> Company:
        name = (name or "").strip()
        if not name:
            raise DomainError("Company name is required")
        number = rules.normalise_company_number(company_number)
        company_type = (company_type or "EW").strip().upper()
        if company_type not in ("EW", "SC", "NI"):
            raise DomainError("Company type must be EW, SC or NI")
        if self.db.query(Company).filter(Company.company_number == number).first():
            raise ConflictError(f"A company with number {number} already exists")

        company = Company(
            name=name,
            company_number=number,
            registered_address=registered_address,
            incorporation_date=incorporation_date,
            company_type=company_type,
            sic_code=(sic_code or None),
            directors=directors,
        )
        self.db.add(company)
        self._commit(f"A company with number {number} already exists")
        self.db.refresh(company)
        return company

    # ------------------------------------------------------------------ accounts
    def create_account(
        self,
        company_id: int,
        code: str,
        name: str,
        account_type: str,
        parent_id: Optional[int] = None,
        category: Optional[str] = None,
    ) -> Account:
        self._company(company_id)
        code = (code or "").strip()
        name = (name or "").strip()
        if not code or not name:
            raise DomainError("Account code and name are required")
        account_type = rules.normalise_account_type(account_type)
        category = rules.validate_category(category, account_type)

        if parent_id is not None:
            parent = self._account(company_id, parent_id)
            if parent.type != account_type:
                raise DomainError("A sub-account must have the same type as its parent account")
        if self.db.query(Account).filter(Account.company_id == company_id, Account.code == code).first():
            raise ConflictError(f"Account code {code} already exists for this company")

        account = Account(
            company_id=company_id, code=code, name=name, type=account_type,
            category=category, parent_id=parent_id,
        )
        self.db.add(account)
        self._commit(f"Account code {code} already exists for this company")
        self.db.refresh(account)
        return account

    def seed_default_chart(self, company_id: int) -> List[Account]:
        """Add the standard chart of accounts; codes that already exist are left alone."""
        self._company(company_id)
        existing = {
            code for (code,) in self.db.query(Account.code).filter(Account.company_id == company_id).all()
        }
        created = []
        for code, name, account_type, category in DEFAULT_CHART:
            if code in existing:
                continue
            account = Account(company_id=company_id, code=code, name=name, type=account_type, category=category)
            self.db.add(account)
            created.append(account)
        self._commit("The standard chart of accounts conflicts with existing accounts")
        return created

    # ------------------------------------------------------------------ periods
    def create_fiscal_period(
        self,
        company_id: int,
        name: str,
        start_date: Any,
        end_date: Any,
        is_current: bool = True,
    ) -> FiscalPeriod:
        company = self._company(company_id)
        name = (name or "").strip()
        if not name:
            raise DomainError("Fiscal period name is required")
        start, end = as_date(start_date), as_date(end_date)
        existing = [
            (p.id, p.start_date, p.end_date, p.name)
            for p in self.db.query(FiscalPeriod).filter(FiscalPeriod.company_id == company_id).all()
        ]
        rules.validate_period(start, end, existing, company.incorporation_date)

        if is_current:
            self.db.query(FiscalPeriod).filter(FiscalPeriod.company_id == company_id).update(
                {FiscalPeriod.is_current: False}
            )
        period = FiscalPeriod(
            company_id=company_id, name=name, start_date=midnight(start),
            end_date=midnight(end), is_current=bool(is_current),
        )
        self.db.add(period)
        self._commit("Fiscal period conflicts with an existing period")
        self.db.refresh(period)
        return period

    def period_for_date(self, company_id: int, when: date) -> Optional[FiscalPeriod]:
        moment = midnight(when)
        return self.db.query(FiscalPeriod).filter(
            FiscalPeriod.company_id == company_id,
            FiscalPeriod.start_date <= moment,
            FiscalPeriod.end_date >= moment,
        ).first()

    # ------------------------------------------------------------------ journal
    def create_journal_entry(
        self,
        company_id: int,
        date: Any,
        description: str,
        reference: str,
        lines: List[Dict[str, Any]],
        fiscal_period_id: Optional[int] = None,
    ) -> JournalEntry:
        self._company(company_id)
        if not lines or len(lines) < 2:
            raise DomainError("A journal entry must contain at least two lines")
        entry_date = midnight(date)

        if fiscal_period_id:
            period = self._period(company_id, fiscal_period_id)
            if not (period.start_date <= entry_date <= period.end_date):
                raise DomainError("Journal entry date is outside the fiscal period")
        else:
            period = self.period_for_date(company_id, entry_date)

        total_debit = total_credit = ZERO
        normalised = []
        for line in lines:
            try:
                account_id = int(line["account_id"])
            except (KeyError, TypeError, ValueError) as exc:
                raise DomainError("Every journal line needs an account") from exc
            self._account(company_id, account_id)
            debit = money(line.get("debit", 0))
            credit = money(line.get("credit", 0))
            if debit < 0 or credit < 0:
                raise DomainError("Debit and credit amounts cannot be negative")
            if debit > 0 and credit > 0:
                raise DomainError("A journal line cannot contain both debit and credit")
            if debit == 0 and credit == 0:
                raise DomainError("A journal line must contain a debit or credit amount")
            total_debit += debit
            total_credit += credit
            normalised.append((account_id, debit, credit, line.get("description")))

        if total_debit != total_credit:
            raise DomainError(f"Journal entry not balanced: debit={total_debit}, credit={total_credit}")

        entry = JournalEntry(
            company_id=company_id,
            date=entry_date,
            description=(description or "").strip(),
            reference=(reference or "").strip(),
            fiscal_period_id=period.id if period else None,
        )
        self.db.add(entry)
        try:
            self.db.flush()
            for account_id, debit, credit, line_description in normalised:
                self.db.add(JournalLine(
                    journal_entry_id=entry.id, account_id=account_id,
                    debit=debit, credit=credit, description=line_description,
                ))
            self.db.commit()
        except Exception:
            self.db.rollback()
            raise
        self.db.refresh(entry)
        return entry

    # ------------------------------------------------------------------ balances
    def _sums(self, company_id: int, start: Optional[datetime], end: Optional[datetime]) -> Sums:
        query = (
            self.db.query(
                JournalLine.account_id,
                func.sum(JournalLine.debit),
                func.sum(JournalLine.credit),
            )
            .join(JournalEntry, JournalEntry.id == JournalLine.journal_entry_id)
            .filter(JournalEntry.company_id == company_id)
        )
        if start is not None:
            query = query.filter(JournalEntry.date >= start)
        if end is not None:
            query = query.filter(JournalEntry.date <= end)
        query = query.group_by(JournalLine.account_id)
        return {account_id: (money(debit), money(credit)) for account_id, debit, credit in query.all()}

    def _rows(self, company_id: int, sums: Sums, types: Optional[Tuple[str, ...]] = None) -> List[AccountRow]:
        query = self.db.query(Account).filter(Account.company_id == company_id)
        if types:
            query = query.filter(Account.type.in_(types))
        rows = []
        for account in query.order_by(Account.code).all():
            debit, credit = sums.get(account.id, (ZERO, ZERO))
            rows.append(AccountRow(account.id, account.code, account.name, account.type,
                                   account.category, debit, credit))
        return rows

    def _bounds(self, company_id: int, period_id: Optional[int]):
        if not period_id:
            return None, None
        period = self._period(company_id, period_id)
        return period.start_date, period.end_date

    def get_trial_balance(self, company_id: int, period_id: Optional[int] = None) -> List[Dict[str, Any]]:
        self._company(company_id)
        start, end = self._bounds(company_id, period_id)
        if not period_id:
            return rules.build_trial_balance(self._rows(company_id, self._sums(company_id, None, None)), [])

        cumulative = self._sums(company_id, None, end)
        in_period = self._sums(company_id, start, end)
        bs_rows = self._rows(company_id, cumulative, ("Asset", "Liability", "Equity"))
        pl_rows = self._rows(company_id, in_period, ("Revenue", "Expense"))
        cumulative_pl = sum((r.balance for r in self._rows(company_id, cumulative, ("Revenue", "Expense"))), ZERO)
        prior = cumulative_pl - sum((r.balance for r in pl_rows), ZERO)
        return rules.build_trial_balance(bs_rows, pl_rows, prior)

    def get_profit_loss(self, company_id: int, period_id: Optional[int] = None) -> Dict[str, Decimal]:
        self._company(company_id)
        start, end = self._bounds(company_id, period_id)
        rows = self._rows(company_id, self._sums(company_id, start, end), ("Revenue", "Expense"))
        return rules.build_profit_loss(rows)

    def get_balance_sheet(self, company_id: int, period_id: Optional[int] = None) -> Dict[str, Decimal]:
        self._company(company_id)
        start, end = self._bounds(company_id, period_id)
        rows = self._rows(company_id, self._sums(company_id, None, end))
        sheet = rules.build_balance_sheet(rows)
        sheet["net_profit"] = self.get_profit_loss(company_id, period_id)["net_profit"]
        return sheet

    # ------------------------------------------------------------------ export helpers
    def ledger_fingerprint(self, company_id: int, end: datetime) -> str:
        """Return a deterministic fingerprint of all data that can affect an export.

        The fingerprint deliberately hashes the complete accounting inputs rather than
        aggregates such as line count/debit total.  Two different ledgers can have the
        same aggregates, so a checksum based only on totals is not sufficient to guard
        a generated filing from later edits.
        """
        self._company(company_id)

        accounts = (
            self.db.query(Account)
            .filter(Account.company_id == company_id)
            .order_by(Account.id)
            .all()
        )
        entries = (
            self.db.query(JournalEntry)
            .filter(JournalEntry.company_id == company_id, JournalEntry.date <= end)
            .order_by(JournalEntry.id)
            .all()
        )

        lines_by_entry = {}
        if entries:
            entry_ids = [entry.id for entry in entries]
            lines = (
                self.db.query(JournalLine)
                .filter(JournalLine.journal_entry_id.in_(entry_ids))
                .order_by(JournalLine.journal_entry_id, JournalLine.id)
                .all()
            )
            for line in lines:
                lines_by_entry.setdefault(line.journal_entry_id, []).append(line)

        parts = ["ledger-fingerprint-v2", f"company={company_id}", f"end={end.isoformat()}"]
        parts.extend(
            f"A|{a.id}|{a.code}|{a.name}|{a.type}|{a.category or ''}|{a.parent_id or ''}|{int(bool(a.is_active))}"
            for a in accounts
        )
        for entry in entries:
            parts.append(
                f"E|{entry.id}|{entry.date.isoformat()}|{entry.description or ''}|"
                f"{entry.reference or ''}|{entry.fiscal_period_id or ''}"
            )
            for line in lines_by_entry.get(entry.id, []):
                parts.append(
                    f"L|{line.id}|{line.account_id}|{money(line.debit)}|{money(line.credit)}|"
                    f"{line.description or ''}"
                )

        blob = "\n".join(parts)
        return hashlib.sha256(blob.encode("utf-8")).hexdigest()
