"""Compare the numbers inside a generated iXBRL document with the ledger.

ixbrl-reporter maps ledger accounts onto statutory lines by *account name*. If
that mapping does not line up, it silently produces a balance sheet full of
zeros that still validates. This check makes that failure loud.
"""
from __future__ import annotations

import re
from dataclasses import dataclass, field
from datetime import date
from decimal import Decimal, InvalidOperation
from typing import Any, Dict, List, Mapping, Optional, Union

from lxml import etree

from .postprocess import NS_IX, NS_XBRLI, parse_ixbrl

TOLERANCE = Decimal("1.00")  # the templates round to whole pounds


@dataclass
class Check:
    concept: str
    expected: Decimal
    actual: Optional[Decimal]
    status: str  # ok | mismatch | missing
    hard: bool

    def as_dict(self) -> Dict[str, Any]:
        return {
            "concept": self.concept,
            "expected": str(self.expected),
            "actual": None if self.actual is None else str(self.actual),
            "status": self.status,
            "hard": self.hard,
        }


@dataclass
class Reconciliation:
    ok: bool
    checks: List[Check] = field(default_factory=list)
    message: str = ""

    def as_dict(self) -> Dict[str, Any]:
        return {"ok": self.ok, "message": self.message, "checks": [c.as_dict() for c in self.checks]}


def _number(element: etree._Element) -> Decimal:
    text = "".join(element.itertext()).strip().replace("\u00a0", "").replace(",", "")
    text = re.sub(r"^[£$€]", "", text)
    if text in ("", "-", "\u2013", "\u2014"):
        value = Decimal(0)
    else:
        try:
            value = Decimal(text)
        except InvalidOperation:
            raise ValueError(f"Cannot read numeric fact value {text!r}")
    scale = element.get("scale")
    if scale:
        value = value.scaleb(int(scale))
    if element.get("sign") == "-":
        value = -value
    return value


def _contexts(root: etree._Element) -> Dict[str, Dict[str, Any]]:
    ns = {"x": NS_XBRLI}
    result: Dict[str, Dict[str, Any]] = {}
    for context in root.xpath("//x:context", namespaces=ns):
        instant = context.xpath("x:period/x:instant/text()", namespaces=ns)
        start = context.xpath("x:period/x:startDate/text()", namespaces=ns)
        end = context.xpath("x:period/x:endDate/text()", namespaces=ns)
        result[context.get("id")] = {
            "instant": instant[0].strip() if instant else None,
            "start": start[0].strip() if start else None,
            "end": end[0].strip() if end else None,
            "dimensional": bool(context.xpath(".//x:segment | .//x:scenario", namespaces=ns)),
        }
    return result


def _find(root, contexts, concept: str, *, instant: Optional[date] = None, start: Optional[date] = None,
          end: Optional[date] = None) -> Optional[Decimal]:
    values = []
    for fact in root.iter(f"{{{NS_IX}}}nonFraction"):
        name = fact.get("name") or ""
        if name.split(":")[-1] != concept:
            continue
        ctx = contexts.get(fact.get("contextRef"))
        if ctx is None or ctx["dimensional"]:
            continue
        if instant is not None and ctx["instant"] != instant.isoformat():
            continue
        if start is not None and (ctx["start"] != start.isoformat() or ctx["end"] != end.isoformat()):
            continue
        values.append(_number(fact))
    if not values:
        return None
    return values[0]


def reconcile(
    source: Union[str, bytes],
    *,
    period_start: date,
    period_end: date,
    balance_sheet: Mapping[str, Decimal],
    profit_loss: Optional[Mapping[str, Decimal]] = None,
) -> Reconciliation:
    root = parse_ixbrl(source)
    contexts = _contexts(root)

    plan = [
        # (concept, expected, hard, kwargs)
        ("Equity", balance_sheet["total_equity"], True, {"instant": period_end}),
        ("NetAssetsLiabilities", balance_sheet["net_assets"], True, {"instant": period_end}),
        ("FixedAssets", balance_sheet["fixed_assets"], False, {"instant": period_end}),
        ("CurrentAssets", balance_sheet["current_assets"], False, {"instant": period_end}),
    ]
    if profit_loss is not None:
        plan.append(("ProfitLoss", profit_loss["net_profit"], False,
                     {"start": period_start, "end": period_end}))

    checks: List[Check] = []
    for concept, expected, hard, kwargs in plan:
        actual = _find(root, contexts, concept, **kwargs)
        if actual is None:
            if concept == "ProfitLoss":
                continue  # optional line, not present in every accounts type
            status = "ok" if abs(expected) <= TOLERANCE else "missing"
        elif abs(actual - expected) <= TOLERANCE:
            status = "ok"
        else:
            status = "mismatch"
        checks.append(Check(concept, expected, actual, status, hard))

    failed = [c for c in checks if c.hard and c.status != "ok"]
    if failed:
        message = (
            "The numbers in the generated iXBRL do not match the ledger ("
            + ", ".join(c.concept for c in failed)
            + "). Account names/categories probably do not map onto the statutory lines - "
            "check config/account_paths.json against the ixbrl-reporter-jsonnet templates."
        )
    else:
        soft = [c.concept for c in checks if c.status != "ok"]
        message = "iXBRL totals agree with the ledger" + (
            f" (not checked or different: {', '.join(soft)})" if soft else ""
        )
    return Reconciliation(ok=not failed, checks=checks, message=message)
