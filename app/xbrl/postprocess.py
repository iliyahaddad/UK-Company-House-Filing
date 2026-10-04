"""Repairs applied to the iXBRL that ixbrl-reporter produces (lxml only).

Each repair answers a validation failure seen on real output:

* ``<img src="">`` for the logo/signature placeholders  -> HMRC.SG.3.8
* ``ix:header`` hidden only through a CSS class          -> ix11.8.1.2 warning
* mandatory ``DescriptionPrincipalActivities`` and
  ``AverageNumberEmployeesDuringPeriod`` facts missing   -> JFCVC.3312

Repairs are idempotent: facts that already exist are never duplicated.
"""
from __future__ import annotations

import copy
import re
from dataclasses import dataclass, field
from datetime import date
from typing import List, Optional, Union

from lxml import etree

NS_XHTML = "http://www.w3.org/1999/xhtml"
NS_IX = "http://www.xbrl.org/2013/inlineXBRL"
NS_XBRLI = "http://www.xbrl.org/2003/instance"

_XML_DECLARATION = re.compile(r"^\s*<\?xml[^>]*\?>\s*")


class PostProcessError(ValueError):
    pass


@dataclass
class PostProcessResult:
    xml: bytes
    changes: List[str] = field(default_factory=list)


def parse_ixbrl(source: Union[str, bytes]) -> etree._Element:
    if isinstance(source, str):
        source = _XML_DECLARATION.sub("", source).encode("utf-8")
    parser = etree.XMLParser(resolve_entities=False, no_network=True, huge_tree=False)
    return etree.fromstring(source, parser)


def _remove_keep_tail(element: etree._Element) -> None:
    parent = element.getparent()
    if parent is None:
        return
    tail = element.tail
    previous = element.getprevious()
    if tail:
        if previous is not None:
            previous.tail = (previous.tail or "") + tail
        else:
            parent.text = (parent.text or "") + tail
    parent.remove(element)


def _prefix_for(root: etree._Element, suffix: str) -> str:
    for prefix, uri in root.nsmap.items():
        if prefix and uri and uri.startswith("http://xbrl.frc.org.uk/") and uri.rstrip("/").endswith(suffix):
            return prefix
    raise PostProcessError(f"The document does not declare an FRC '{suffix.strip('/')}' namespace")


def _has_fact(root: etree._Element, qualified_name: str) -> bool:
    for tag in ("nonNumeric", "nonFraction"):
        for element in root.iter(f"{{{NS_IX}}}{tag}"):
            if element.get("name") == qualified_name:
                return True
    return False


def _period_context(root: etree._Element, start: date, end: date) -> str:
    """Id of a dimension-free duration context for the reporting period (created if absent)."""
    ns = {"x": NS_XBRLI}
    contexts = root.xpath("//x:context", namespaces=ns)
    for context in contexts:
        if context.xpath(".//x:segment | .//x:scenario", namespaces=ns):
            continue
        s = context.xpath("x:period/x:startDate/text()", namespaces=ns)
        e = context.xpath("x:period/x:endDate/text()", namespaces=ns)
        if s and e and s[0].strip() == start.isoformat() and e[0].strip() == end.isoformat():
            return context.get("id")
    if not contexts:
        raise PostProcessError("The document has no XBRL contexts to copy an entity from")
    template = copy.deepcopy(contexts[0])
    for extra in template.xpath(".//x:segment | .//x:scenario", namespaces=ns):
        extra.getparent().remove(extra)
    period = template.find(f"{{{NS_XBRLI}}}period")
    for child in list(period):
        period.remove(child)
    etree.SubElement(period, f"{{{NS_XBRLI}}}startDate").text = start.isoformat()
    etree.SubElement(period, f"{{{NS_XBRLI}}}endDate").text = end.isoformat()
    template.set("id", "uka-period")
    contexts[-1].addnext(template)
    return "uka-period"


def _ensure_unit(root: etree._Element, unit_id: str, measure: str) -> None:
    ns = {"x": NS_XBRLI}
    if root.xpath(f"//x:unit[@id='{unit_id}']", namespaces=ns):
        return
    resources = root.find(f".//{{{NS_IX}}}resources")
    if resources is None:
        raise PostProcessError("The document has no ix:resources section")
    unit = etree.SubElement(resources, f"{{{NS_XBRLI}}}unit", id=unit_id)
    etree.SubElement(unit, f"{{{NS_XBRLI}}}measure").text = measure


def _hidden_section(root: etree._Element) -> etree._Element:
    header = root.find(f".//{{{NS_IX}}}header")
    if header is None:
        raise PostProcessError("The document has no ix:header")
    hidden = header.find(f"{{{NS_IX}}}hidden")
    if hidden is None:
        hidden = etree.Element(f"{{{NS_IX}}}hidden")
        header.insert(0, hidden)
    return hidden


def postprocess_ixbrl(
    source: Union[str, bytes],
    *,
    period_start: date,
    period_end: date,
    average_employees: int,
    principal_activities: str,
) -> PostProcessResult:
    if average_employees < 0:
        raise PostProcessError("Average number of employees cannot be negative")
    text = (principal_activities or "").strip()
    if not text:
        raise PostProcessError("Principal activities are required")

    root = parse_ixbrl(source)
    changes: List[str] = []

    # 1. drop empty image placeholders
    for image in list(root.iter(f"{{{NS_XHTML}}}img")):
        if not (image.get("src") or "").strip():
            _remove_keep_tail(image)
            changes.append("removed empty <img> placeholder")

    # 2. make the hidden header hidden inline as well as by class
    header = root.find(f".//{{{NS_IX}}}header")
    if header is not None:
        holder = header.getparent()
        if holder is not None and holder.tag == f"{{{NS_XHTML}}}div":
            style = holder.get("style") or ""
            if "display:none" not in style.replace(" ", ""):
                holder.set("style", (style.rstrip("; ") + "; " if style else "") + "display:none")
                changes.append("added display:none to the ix:header container")

    # 3. mandatory facts
    bus = _prefix_for(root, "/business")
    core = _prefix_for(root, "/core")
    hidden = _hidden_section(root)

    activities_name = f"{bus}:DescriptionPrincipalActivities"
    employees_name = f"{core}:AverageNumberEmployeesDuringPeriod"
    need_activities = not _has_fact(root, activities_name)
    need_employees = not _has_fact(root, employees_name)

    if need_activities or need_employees:
        context_id = _period_context(root, period_start, period_end)
        if need_activities:
            fact = etree.SubElement(hidden, f"{{{NS_IX}}}nonNumeric", name=activities_name, contextRef=context_id)
            fact.text = text
            changes.append("added DescriptionPrincipalActivities")
        if need_employees:
            _ensure_unit(root, "pure", "xbrli:pure")
            fact = etree.SubElement(
                hidden,
                f"{{{NS_IX}}}nonFraction",
                name=employees_name,
                contextRef=context_id,
                unitRef="pure",
                decimals="0",
            )
            fact.text = str(int(average_employees))
            changes.append("added AverageNumberEmployeesDuringPeriod")

    xml = etree.tostring(root, xml_declaration=True, encoding="UTF-8")
    return PostProcessResult(xml=xml, changes=changes)
