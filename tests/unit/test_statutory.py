import unittest
from datetime import date
from decimal import Decimal as D

from app.accounting.rules import DomainError
from app.uk_accounts.statutory import eligibility_warnings, thresholds_for, validate_details


class ThresholdTests(unittest.TestCase):
    def test_old_micro_threshold_before_2025(self):
        limits = thresholds_for("micro", date(2024, 1, 1))
        self.assertEqual(limits.turnover, D("632000"))

    def test_new_micro_threshold_from_2025(self):
        limits = thresholds_for("micro", date(2025, 6, 1))
        self.assertEqual(limits.turnover, D("1000000"))

    def test_dormant_has_no_thresholds(self):
        self.assertIsNone(thresholds_for("dormant", date(2024, 1, 1)))


class EligibilityWarningTests(unittest.TestCase):
    def test_within_limits_no_size_warning(self):
        warnings = eligibility_warnings("micro", date(2025, 6, 1), turnover=D("50000"),
                                        balance_sheet_total=D("20000"), employees=2)
        self.assertFalse(any("does not qualify" in w for w in warnings))

    def test_exceeds_two_limits_flagged(self):
        warnings = eligibility_warnings("micro", date(2025, 6, 1), turnover=D("2000000"),
                                        balance_sheet_total=D("2000000"), employees=2)
        self.assertTrue(any("does not qualify" in w for w in warnings))

    def test_always_includes_advisory_disclaimer(self):
        warnings = eligibility_warnings("micro", date(2025, 6, 1), turnover=D("0"),
                                        balance_sheet_total=D("0"), employees=0)
        self.assertTrue(any("advisory" in w for w in warnings))


class ValidateDetailsTests(unittest.TestCase):
    def base_kwargs(self, **overrides):
        kwargs = dict(
            account_type="micro", period_end=date(2024, 12, 31), approval_date=date(2025, 3, 1),
            today=date(2025, 3, 15), directors=["Jane Smith"], signing_director="Jane Smith",
            average_employees=2, principal_activities="Consulting", confirm_eligibility=True,
            confirm_audit_exemption=True,
        )
        kwargs.update(overrides)
        return kwargs

    def test_valid_passes(self):
        validate_details(**self.base_kwargs())  # no raise

    def test_approval_before_period_end_rejected(self):
        with self.assertRaises(DomainError):
            validate_details(**self.base_kwargs(approval_date=date(2024, 6, 1)))

    def test_approval_in_future_rejected(self):
        with self.assertRaises(DomainError):
            validate_details(**self.base_kwargs(approval_date=date(2025, 4, 1)))

    def test_missing_approval_date(self):
        with self.assertRaises(DomainError):
            validate_details(**self.base_kwargs(approval_date=None))

    def test_no_directors(self):
        with self.assertRaises(DomainError):
            validate_details(**self.base_kwargs(directors=[]))

    def test_signing_director_not_in_list(self):
        with self.assertRaises(DomainError):
            validate_details(**self.base_kwargs(signing_director="Someone Else"))

    def test_missing_employees(self):
        with self.assertRaises(DomainError):
            validate_details(**self.base_kwargs(average_employees=None))

    def test_negative_employees(self):
        with self.assertRaises(DomainError):
            validate_details(**self.base_kwargs(average_employees=-1))

    def test_blank_principal_activities(self):
        with self.assertRaises(DomainError):
            validate_details(**self.base_kwargs(principal_activities="   "))

    def test_eligibility_not_confirmed(self):
        with self.assertRaises(DomainError):
            validate_details(**self.base_kwargs(confirm_eligibility=False))

    def test_audit_exemption_not_confirmed(self):
        with self.assertRaises(DomainError):
            validate_details(**self.base_kwargs(confirm_audit_exemption=False))

    def test_all_problems_reported_together(self):
        try:
            validate_details(**self.base_kwargs(approval_date=None, directors=[], average_employees=None,
                                                 principal_activities="", confirm_eligibility=False))
            self.fail("expected DomainError")
        except DomainError as exc:
            message = str(exc)
            self.assertIn("approve", message.lower())
            self.assertIn("director", message.lower())
            self.assertIn("employee", message.lower())


if __name__ == "__main__":
    unittest.main()
