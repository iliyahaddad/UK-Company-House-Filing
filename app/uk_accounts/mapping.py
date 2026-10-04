"""Ledger -> CSV handed to ixbrl-reporter (pure functions)."""
from __future__ import annotations

import csv
import json
from dataclasses import dataclass, field
from datetime import datetime
from decimal import Decimal
from pathlib import Path
from typing import Any, Dict, Iterable, List, Mapping, Optional, Sequence, Tuple

from ..accounting.rules import CATEGORIES, default_category

CSV_FIELDS = ["Date", "Transaction ID", "Description", "Full Account Name", "Amount Num."]

DEFAULT_PATHS: Dict[str, str] = {
    "fixed_asset": "Assets:Fixed Assets",
    "current_asset": "Assets:Current Assets",
    "cash": "Assets:Current Assets:Cash at bank and in hand",
    "debtor": "Assets:Current Assets:Debtors",
    "creditor": "Liabilities:Current Liabilities:Creditors",
    "current_liability": "Liabilities:Current Liabilities",
    "long_term_liability": "Liabilities:Long Term Liabilities",
    "share_capital": "Equity:Share Capital",
    "retained_earnings": "Equity:Retained Earnings",
    "revenue": "Income",
    "cost_of_sales": "Expenses:Cost of Sales",
    "expense": "Expenses:Overheads",
    "tax": "Expenses:Tax",
}


@dataclass(frozen=True)
class AccountInfo:
    name: str
    type: str
    code: str = ""
    category: Optional[str] = None
    parent_names: Tuple[str, ...] = ()


@dataclass(frozen=True)
class EntryData:
    id: int
    date: datetime
    description: str
    lines: Sequence[Tuple[int, Decimal, Decimal]] = field(default_factory=tuple)  # (account_id, debit, credit)


def load_paths(path: Optional[Path] = None) -> Dict[str, str]:
    paths = dict(DEFAULT_PATHS)
    if path and Path(path).is_file():
        loaded = json.loads(Path(path).read_text(encoding="utf-8"))
        for key, value in loaded.items():
            if key in CATEGORIES and isinstance(value, str) and value.strip():
                paths[key] = value.strip().strip(":")
    return paths


def full_account_name(info: AccountInfo, paths: Mapping[str, str]) -> str:
    category = info.category or default_category(info.type, info.code, info.name)
    prefix = paths.get(category) or DEFAULT_PATHS[category]
    return ":".join([prefix, *info.parent_names, info.name])


def build_csv_rows(
    entries: Iterable[EntryData],
    accounts: Mapping[int, AccountInfo],
    paths: Mapping[str, str],
) -> List[Dict[str, str]]:
    """One row per journal line. Amounts use each account's natural sign
    (debit-positive for assets/expenses, credit-positive for the rest)."""
    rows: List[Dict[str, str]] = []
    for entry in entries:
        for account_id, debit, credit in entry.lines:
            info = accounts.get(account_id)
            if info is None:
                raise KeyError(f"Journal entry {entry.id} references unknown account {account_id}")
            amount = (debit - credit) if info.type in ("Asset", "Expense") else (credit - debit)
            rows.append({
                "Date": entry.date.strftime("%d/%m/%y"),
                "Transaction ID": f"TX{entry.id:06d}",
                "Description": entry.description or "",
                "Full Account Name": full_account_name(info, paths),
                "Amount Num.": f"{amount:.2f}",
            })
    return rows


def write_csv(path: str, rows: Iterable[Mapping[str, Any]]) -> None:
    with open(path, "w", newline="", encoding="utf-8") as handle:
        writer = csv.DictWriter(handle, fieldnames=CSV_FIELDS)
        writer.writeheader()
        writer.writerows(rows)
