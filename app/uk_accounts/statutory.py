"""Statutory inputs and advisory eligibility checks (pure functions).

The thresholds below are the size limits for financial years beginning on or
after 6 April 2025 and the limits they replaced. They are *advisory*: qualifying
also depends on the previous year, group membership, company type and other
exclusions, so the directors' own confirmation is always required.
"""
from __future__ import annotations

from dataclasses import dataclass
from datetime import date
from decimal import Decimal
from typing import List, Optional, Sequence

from ..accounting.rules import DomainError

NEW_REGIME_START = date(2025, 4, 6)
ACCOUNT_TYPES = ("dormant", "micro", "small")


@dataclass(frozen=True)
class Thresholds:
    turnover: Decimal
    balance_sheet_total: Decimal
    employees: int


MICRO_BEFORE = Thresholds(Decimal("632000"), Decimal("316000"), 10)
MICRO_FROM_2025 = Thresholds(Decimal("1000000"), Decimal("500000"), 10)
SMALL_BEFORE = Thresholds(Decimal("10200000"), Decimal("5100000"), 50)
SMALL_FROM_2025 = Thresholds(Decimal("15000000"), Decimal("7500000"), 50)


def thresholds_for(account_type: str, period_start: date) -> Optional[Thresholds]:
    new = period_start >= NEW_REGIME_START
    if account_type == "micro":
        return MICRO_FROM_2025 if new else MICRO_BEFORE
    if account_type == "small":
        return SMALL_FROM_2025 if new else SMALL_BEFORE
    return None


def eligibility_warnings(
    account_type: str,
    period_start: date,
    *,
    turnover: Decimal,
    balance_sheet_total: Decimal,
    employees: int,
) -> List[str]:
    """Warnings when a company appears too large for the chosen account type."""
    limits = thresholds_for(account_type, period_start)
    if limits is None:
        return []
    exceeded = []
    if turnover > limits.turnover:
        exceeded.append(f"turnover £{turnover:,.2f} is above £{limits.turnover:,.0f}")
    if balance_sheet_total > limits.balance_sheet_total:
        exceeded.append(
            f"balance sheet total £{balance_sheet_total:,.2f} is above £{limits.balance_sheet_total:,.0f}"
        )
    if employees > limits.employees:
        exceeded.append(f"average employees {employees} is above {limits.employees}")
    warnings: List[str] = []
    if len(exceeded) >= 2:
        warnings.append(
            f"This company exceeds two or more {account_type}-company limits ("
            + "; ".join(exceeded)
            + "). It probably does not qualify for this type of accounts."
        )
    warnings.append(
        f"Size limits used for {account_type} accounts are advisory. Qualification also depends on "
        "the previous year and on exclusions such as public companies and some group members."
    )
    return warnings


def validate_details(
    *,
    account_type: str,
    period_end: date,
    approval_date: Optional[date],
    today: date,
    directors: Sequence[str],
    signing_director: Optional[str],
    average_employees: Optional[int],
    principal_activities: Optional[str],
    confirm_eligibility: bool,
    confirm_audit_exemption: bool,
) -> None:
    """Raise :class:`DomainError` listing everything missing before accounts are generated."""
    problems: List[str] = []
    if account_type not in ACCOUNT_TYPES:
        problems.append("Account type must be dormant, micro or small")
    if approval_date is None:
        problems.append("Date the directors approved the accounts is required")
    else:
        if approval_date < period_end:
            problems.append("Approval date cannot be before the end of the accounting period")
        if approval_date > today:
            problems.append("Approval date cannot be in the future")
    if not directors:
        problems.append("The company needs at least one director")
    elif not signing_director or signing_director not in directors:
        problems.append("Signing director must be one of the company's directors")
    if average_employees is None or average_employees < 0:
        problems.append("Average number of employees is required (0 or more)")
    if not (principal_activities or "").strip():
        problems.append("Principal activities are required")
    elif len(principal_activities) > 2000:
        problems.append("Principal activities must be 2000 characters or fewer")
    if not confirm_eligibility:
        problems.append("Confirm that the company is eligible for this type of accounts")
    if account_type in ("micro", "small", "dormant") and not confirm_audit_exemption:
        problems.append("Confirm that the company is entitled to audit exemption")
    if problems:
        raise DomainError("; ".join(problems))
