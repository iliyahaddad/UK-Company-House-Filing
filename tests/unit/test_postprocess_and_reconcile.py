import unittest
from datetime import date
from decimal import Decimal as D
from pathlib import Path

from app.xbrl.postprocess import postprocess_ixbrl, parse_ixbrl, PostProcessError, NS_XHTML, NS_IX
from app.xbrl.reconcile import reconcile

FIXTURE = Path(__file__).resolve().parents[1] / "fixtures" / "real_micro_all_zero.xhtml"


class PostprocessTests(unittest.TestCase):
    def setUp(self):
        self.source = FIXTURE.read_bytes()

    def test_removes_empty_images_and_adds_facts(self):
        result = postprocess_ixbrl(self.source, period_start=date(2024, 1, 1), period_end=date(2024, 12, 31),
                                   average_employees=3, principal_activities="Consulting")
        self.assertIn("removed empty <img> placeholder", result.changes)
        self.assertIn("added DescriptionPrincipalActivities", result.changes)
        self.assertIn("added AverageNumberEmployeesDuringPeriod", result.changes)
        root = parse_ixbrl(result.xml)
        self.assertEqual(len(list(root.iter(f"{{{NS_XHTML}}}img"))), 0)

    def test_idempotent_second_run_no_changes(self):
        first = postprocess_ixbrl(self.source, period_start=date(2024, 1, 1), period_end=date(2024, 12, 31),
                                  average_employees=3, principal_activities="Consulting")
        second = postprocess_ixbrl(first.xml, period_start=date(2024, 1, 1), period_end=date(2024, 12, 31),
                                   average_employees=3, principal_activities="Consulting")
        self.assertEqual(second.changes, [])

    def test_rejects_blank_activities(self):
        with self.assertRaises(PostProcessError):
            postprocess_ixbrl(self.source, period_start=date(2024, 1, 1), period_end=date(2024, 12, 31),
                              average_employees=1, principal_activities="   ")

    def test_rejects_negative_employees(self):
        with self.assertRaises(PostProcessError):
            postprocess_ixbrl(self.source, period_start=date(2024, 1, 1), period_end=date(2024, 12, 31),
                              average_employees=-1, principal_activities="x")


class ReconcileTests(unittest.TestCase):
    def setUp(self):
        result = postprocess_ixbrl(FIXTURE.read_bytes(), period_start=date(2024, 1, 1), period_end=date(2024, 12, 31),
                                   average_employees=1, principal_activities="Consulting")
        self.xml = result.xml

    def test_zero_ledger_matches_zero_fixture(self):
        zero = {"total_equity": D(0), "net_assets": D(0), "fixed_assets": D(0), "current_assets": D(0)}
        outcome = reconcile(self.xml, period_start=date(2024, 1, 1), period_end=date(2024, 12, 31), balance_sheet=zero)
        self.assertTrue(outcome.ok)

    def test_nonzero_ledger_flagged_as_mismatch(self):
        nonzero = {"total_equity": D(11000), "net_assets": D(11000), "fixed_assets": D(0), "current_assets": D(11000)}
        outcome = reconcile(self.xml, period_start=date(2024, 1, 1), period_end=date(2024, 12, 31), balance_sheet=nonzero)
        self.assertFalse(outcome.ok)
        hard_failed = [c for c in outcome.checks if c.hard and c.status != "ok"]
        self.assertTrue(hard_failed)


if __name__ == "__main__":
    unittest.main()
