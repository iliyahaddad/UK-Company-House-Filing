from typing import Dict, Any, List, Optional
from pathlib import Path
from lxml import etree as ET

try:
    from ixbrl_parse.ixbrl import parse as ixbrl_parse
    IXBRL_PARSE_AVAILABLE = True
except ImportError:
    IXBRL_PARSE_AVAILABLE = False


class IxBRLInspector:
    """Inspect generated iXBRL files using ixbrl-parse."""

    def __init__(self):
        if not IXBRL_PARSE_AVAILABLE:
            raise RuntimeError("ixbrl-parse is not installed")

    def parse_file(self, ixbrl_path: str) -> Dict[str, Any]:
        tree = ET.parse(ixbrl_path)
        ixbrl = ixbrl_parse(tree)
        return ixbrl.to_dict()

    def get_fact_values(self, ixbrl_path: str, fact_names: List[str]) -> Dict[str, Any]:
        tree = ET.parse(ixbrl_path)
        ixbrl = ixbrl_parse(tree)

        results = {}
        for ctx in ixbrl.contexts.values():
            for name, value in ctx.values.items():
                local_name = name.localname if hasattr(name, "localname") else str(name)
                if local_name in fact_names:
                    results[local_name] = {
                        "value": value.to_value().get_value() if hasattr(value, "to_value") else str(value),
                        "context": ctx.id,
                    }
        return results

    def verify_facts_exist(self, ixbrl_path: str, expected_facts: List[str]) -> Dict[str, Any]:
        tree = ET.parse(ixbrl_path)
        ixbrl = ixbrl_parse(tree)

        found = set()
        for ctx in ixbrl.contexts.values():
            for name in ctx.values:
                local_name = name.localname if hasattr(name, "localname") else str(name)
                if local_name in expected_facts:
                    found.add(local_name)

        missing = set(expected_facts) - found
        return {
            "valid": len(missing) == 0,
            "found": list(found),
            "missing": list(missing),
        }

    def get_company_name(self, ixbrl_path: str) -> Optional[str]:
        tree = ET.parse(ixbrl_path)
        ixbrl = ixbrl_parse(tree)
        return ixbrl.get_entity_name()
