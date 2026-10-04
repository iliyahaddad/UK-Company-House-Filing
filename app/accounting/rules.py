"""Pure accounting rules: no database, no web framework.

Everything the engine needs to *decide* lives here so it can be tested without
SQLAlchemy. The engine only fetches rows and hands them to these functions.
"""
from __future__ import annotations

import re
from dataclasses import dataclass
from datetime import date, datetime, time
from decimal import Decimal, InvalidOperation
from typing import Any, Dict, Iterable, List, Optional, Sequence

from dateutil.relativedelta import relativedelta

ZERO = Decimal("0.00")

ACCOUNT_TYPES = ("Asset", "Liability", "Equity", "Revenue", "Expense")
_TYPE_LOOKUP = {name.lower(): name for name in ACCOUNT_TYPES}

# category -> the account type it belongs to
CATEGORIES: Dict[str, str] = {
    "fixed_asset": "Asset",
    "current_asset": "Asset",
    "cash": "Asset",
    "debtor": "Asset",
    "creditor": "Liability",
    "current_liability": "Liability",
    "long_term_liability": "Liability",
    "share_capital": "Equity",
    "retained_earnings": "Equity",
    "revenue": "Revenue",
    "cost_of_sales": "Expense",
    "expense": "Expense",
    "tax": "Expense",
}

DEFAULT_CHART = [
    ("1000", "Bank", "Asset", "cash"),
    ("1100", "Debtors", "Asset", "debtor"),
    ("1200", "Fixed Assets", "Asset", "fixed_asset"),
    ("2000", "Creditors", "Liability", "creditor"),
    ("2100", "Accruals", "Liability", "current_liability"),
    ("2500", "Loans due after more than one year", "Liability", "long_term_liability"),
    ("3000", "Share Capital", "Equity", "share_capital"),
    ("3100", "Retained Earnings", "Equity", "retained_earnings"),
    ("4000", "Sales", "Revenue", "revenue"),
    ("5000", "Cost of Sales", "Expense", "cost_of_sales"),
    ("6000", "Office Expenses", "Expense", "expense"),
    ("6100", "Travel Expenses", "Expense", "expense"),
    ("6200", "Professional Fees", "Expense", "expense"),
    ("6300", "Bank Charges", "Expense", "expense"),
    ("7000", "Corporation Tax", "Expense", "tax"),
]

_COMPANY_NUMBER = re.compile(r"^[A-Z0-9]{8}$")


class DomainError(ValueError):
    """A request that is well-formed but breaks an accounting rule (HTTP 400)."""


class NotFoundError(LookupError):
    """The requested company/account/period/file does not exist (HTTP 404)."""


class ConflictError(DomainError):
    """The request clashes with existing data (HTTP 409)."""


class BalanceSheetError(DomainError):
    """The ledger does not produce a balancing statement of financial position."""


# --------------------------------------------------------------------------- #
# small value helpers
# --------------------------------------------------------------------------- #
def money(value: Any) -> Decimal:
    try:
        amount = Decimal(str(value if value is not None else 0))
    except (InvalidOperation, ValueError) as exc:
        raise DomainError(f"Invalid monetary value: {value!r}") from exc
    if not amount.is_finite():
        raise DomainError(f"Invalid monetary value: {value!r}")
    return amount.quantize(Decimal("0.01"))


def as_date(value: Any) -> date:
    if isinstance(value, datetime):
        return value.date()
    if isinstance(value, date):
        return value
    raise DomainError(f"Expected a date, got {value!r}")


def midnight(value: Any) -> datetime:
    return datetime.combine(as_date(value), time.min)


def normalise_company_number(value: Optional[str]) -> str:
    number = (value or "").strip().upper()
    if not _COMPANY_NUMBER.match(number):
        raise DomainError(
            "Company number must be 8 characters (digits, or a 2-letter prefix "
            "followed by 6 digits, e.g. 12345678 or SC123456)"
        )
    return number


def normalise_account_type(value: Optional[str]) -> str:
    key = (value or "").strip().lower()
    if key not in _TYPE_LOOKUP:
        raise DomainError(f"Account type must be one of: {', '.join(ACCOUNT_TYPES)}")
    return _TYPE_LOOKUP[key]


def validate_category(category: Optional[str], account_type: str) -> Optional[str]:
    if category in (None, ""):
        return None
    key = category.strip().lower()
    if key not in CATEGORIES:
        raise DomainError(f"Unknown category '{category}'. Allowed: {', '.join(sorted(CATEGORIES))}")
    if CATEGORIES[key] != account_type:
        raise DomainError(f"Category '{key}' cannot be used for a {account_type} account")
    return key


def default_category(account_type: str, code: str, name: str) -> str:
    """Fallback used only for accounts that have no explicit category."""
    lowered = (name or "").lower()
    code = code or ""
    if account_type == "Asset":
        if "fixed asset" in lowered or code.startswith("12"):
            return "fixed_asset"
        if "bank" in lowered or "cash" in lowered or code == "1000":
            return "cash"
        if "debtor" in lowered or "receivable" in lowered or code == "1100":
            return "debtor"
        return "current_asset"
    if account_type == "Liability":
        if code.startswith("2"):
            if "creditor" in lowered or "payable" in lowered or code == "2000":
                return "creditor"
            return "current_liability"
        return "long_term_liability"
    if account_type == "Equity":
        if "share" in lowered or code == "3000":
            return "share_capital"
        return "retained_earnings"
    if account_type == "Revenue":
        return "revenue"
    if "cost of sales" in lowered or code.startswith("5"):
        return "cost_of_sales"
    if "tax" in lowered and code.startswith("7"):
        return "tax"
    return "expense"


@dataclass(frozen=True)
class AccountRow:
    id: Optional[int]
    code: str
    name: str
    type: str
    category: Optional[str]
    debit: Decimal
    credit: Decimal

    @property
    def balance(self) -> Decimal:
        """Signed balance: debit positive, credit negative."""
        return self.debit - self.credit

    @property
    def effective_category(self) -> str:
        return self.category or default_category(self.type, self.code, self.name)


# --------------------------------------------------------------------------- #
# statements
# --------------------------------------------------------------------------- #
def build_profit_loss(rows: Iterable[AccountRow]) -> Dict[str, Decimal]:
    revenue = cost_of_sales = operating_expenses = tax = ZERO
    for row in rows:
        if row.type == "Revenue":
            revenue += -row.balance
        elif row.type == "Expense":
            category = row.effective_category
            if category == "cost_of_sales":
                cost_of_sales += row.balance
            elif category == "tax":
                tax += row.balance
            else:
                operating_expenses += row.balance
    gross_profit = revenue - cost_of_sales
    operating_profit = gross_profit - operating_expenses
    return {
        "revenue": revenue,
        "cost_of_sales": cost_of_sales,
        "gross_profit": gross_profit,
        "operating_expenses": operating_expenses,
        "operating_profit": operating_profit,
        "tax": tax,
        "net_profit": operating_profit - tax,
    }


def build_balance_sheet(rows: Iterable[AccountRow]) -> Dict[str, Decimal]:
    """Statement of financial position from *cumulative* balances to the period end.

    Profit and loss accounts are folded into equity, which is correct whether or
    not year-end closing entries have been posted (closed accounts are simply zero).
    """
    fixed_assets = current_assets = cash = debtors = ZERO
    creditors = current_liabilities = long_term_liabilities = ZERO
    share_capital = retained_earnings = cumulative_profit = ZERO

    for row in rows:
        category = row.effective_category
        if row.type == "Asset":
            if category == "fixed_asset":
                fixed_assets += row.balance
            else:
                current_assets += row.balance
                if category == "cash":
                    cash += row.balance
                elif category == "debtor":
                    debtors += row.balance
        elif row.type == "Liability":
            amount = -row.balance
            if category == "long_term_liability":
                long_term_liabilities += amount
            else:
                current_liabilities += amount
                if category == "creditor":
                    creditors += amount
        elif row.type == "Equity":
            amount = -row.balance
            if category == "share_capital":
                share_capital += amount
            else:
                retained_earnings += amount
        elif row.type in ("Revenue", "Expense"):
            cumulative_profit += -row.balance

    retained_earnings += cumulative_profit
    total_assets = fixed_assets + current_assets
    total_liabilities = current_liabilities + long_term_liabilities
    total_equity = share_capital + retained_earnings
    difference = total_assets - (total_liabilities + total_equity)
    if difference != 0:
        raise BalanceSheetError(
            "Balance sheet does not balance: "
            f"assets={total_assets}, liabilities+equity={total_liabilities + total_equity}, "
            f"difference={difference}"
        )
    return {
        "fixed_assets": fixed_assets,
        "current_assets": current_assets,
        "cash": cash,
        "debtors": debtors,
        "total_assets": total_assets,
        "creditors": creditors,
        "current_liabilities": current_liabilities,
        "long_term_liabilities": long_term_liabilities,
        "total_liabilities": total_liabilities,
        "share_capital": share_capital,
        "retained_earnings": retained_earnings,
        "total_equity": total_equity,
        "net_assets": total_assets - total_liabilities,
        "net_profit_to_date": cumulative_profit,
        "balance_check": ZERO,
    }


def build_trial_balance(
    balance_sheet_rows: Sequence[AccountRow],
    profit_loss_rows: Sequence[AccountRow],
    prior_result: Decimal = ZERO,
) -> List[Dict[str, Any]]:
    """Trial balance as at a period end.

    Balance-sheet accounts are cumulative, profit-and-loss accounts show only the
    period. Results of earlier periods that have not been closed to equity are
    shown as one brought-forward line so the trial balance still balances.
    ``prior_result`` is the signed (debit-positive) sum of earlier P&L balances.
    """
    result: List[Dict[str, Any]] = []
    for row in sorted(list(balance_sheet_rows) + list(profit_loss_rows), key=lambda r: r.code):
        if row.debit != 0 or row.credit != 0:
            result.append({
                "account_id": row.id,
                "code": row.code,
                "name": row.name,
                "type": row.type,
                "debit": row.debit,
                "credit": row.credit,
                "balance": row.balance,
            })
    if prior_result != 0:
        result.append({
            "account_id": None,
            "code": "B/F",
            "name": "Result of earlier periods brought forward (not yet closed to equity)",
            "type": "Equity",
            "debit": prior_result if prior_result > 0 else ZERO,
            "credit": -prior_result if prior_result < 0 else ZERO,
            "balance": prior_result,
        })
    return result


def trial_balance_totals(rows: Iterable[Dict[str, Any]]) -> Dict[str, Any]:
    debit = sum((r["debit"] for r in rows), ZERO)
    credit = sum((r["credit"] for r in rows), ZERO)
    return {"total_debit": debit, "total_credit": credit, "balanced": debit == credit}


# --------------------------------------------------------------------------- #
# fiscal periods
# --------------------------------------------------------------------------- #
def validate_period(
    start: date,
    end: date,
    existing: Iterable[tuple],
    incorporation_date: Optional[date] = None,
) -> None:
    """``existing`` is an iterable of ``(id, start_date, end_date, name)``."""
    if start > end:
        raise DomainError("Fiscal period start date must not be after its end date")
    if end >= start + relativedelta(months=18):
        raise DomainError("A financial period cannot be longer than 18 months")
    if incorporation_date and start < incorporation_date:
        raise DomainError("Fiscal period cannot start before the company's incorporation date")
    for _id, other_start, other_end, other_name in existing:
        if start <= as_date(other_end) and end >= as_date(other_start):
            raise ConflictError(f"Fiscal period overlaps existing period '{other_name}'")


def previous_period(periods: Iterable[tuple], start: date) -> Optional[tuple]:
    """The period ending the day before ``start`` (``(id, start, end, name)``), if any."""
    wanted = start - relativedelta(days=1)
    for period in periods:
        if as_date(period[2]) == wanted:
            return period
    return None
