import unittest
from decimal import Decimal as D

from app.services.filing_guard import FileState, FilingBlocked, check_submission_allowed
from app.uk_accounts.mapping import AccountInfo, EntryData, build_csv_rows, full_account_name


def state(**overrides):
    base = dict(sha256="AAA", source_fingerprint="FP1", reconciliation_ok=True,
               validation_valid=True, validated_sha256="AAA")
    base.update(overrides)
    return FileState(**base)


class SubmissionGateTests(unittest.TestCase):
    def _call(self, **overrides):
        kwargs = dict(file=state(), sha256_on_disk="AAA", current_fingerprint="FP1", live=False,
                      live_filing_enabled=False, confirm_approval=True, earlier_statuses=[])
        kwargs.update(overrides)
        check_submission_allowed(**kwargs)

    def test_happy_path_test_mode(self):
        self._call()  # no raise

    def test_requires_confirmation(self):
        with self.assertRaises(FilingBlocked):
            self._call(confirm_approval=False)

    def test_blocks_if_file_changed_on_disk(self):
        with self.assertRaises(FilingBlocked):
            self._call(sha256_on_disk="BBB")

    def test_blocks_if_inputs_changed_since_generation(self):
        with self.assertRaises(FilingBlocked):
            self._call(current_fingerprint="FP2")

    def test_blocks_if_reconciliation_failed(self):
        with self.assertRaises(FilingBlocked):
            self._call(file=state(reconciliation_ok=False))

    def test_live_requires_flag(self):
        with self.assertRaises(FilingBlocked):
            self._call(live=True, live_filing_enabled=False)

    def test_live_requires_current_validation(self):
        with self.assertRaises(FilingBlocked):
            self._call(live=True, live_filing_enabled=True, file=state(validation_valid=None))

    def test_live_requires_validation_of_this_exact_file(self):
        with self.assertRaises(FilingBlocked):
            self._call(live=True, live_filing_enabled=True,
                       file=state(validation_valid=True, validated_sha256="OLD", sha256="AAA"))

    def test_live_allowed_when_all_conditions_met(self):
        self._call(live=True, live_filing_enabled=True)  # no raise

    def test_blocks_resubmit_while_pending(self):
        with self.assertRaises(FilingBlocked):
            self._call(earlier_statuses=["PENDING"])

    def test_blocks_resubmit_after_submitted(self):
        with self.assertRaises(FilingBlocked):
            self._call(earlier_statuses=["SUBMITTED"])

    def test_allows_resubmit_after_failed(self):
        self._call(earlier_statuses=["FAILED"])  # no raise

    def test_allows_resubmit_after_released(self):
        self._call(earlier_statuses=["RELEASED"])  # no raise


class MappingTests(unittest.TestCase):
    def test_full_account_name_uses_category_prefix(self):
        info = AccountInfo(name="Bank", type="Asset", category="cash")
        name = full_account_name(info, {"cash": "Assets:Current Assets:Cash at bank and in hand"})
        self.assertEqual(name, "Assets:Current Assets:Cash at bank and in hand:Bank")

    def test_falls_back_to_default_category_when_unset(self):
        info = AccountInfo(name="Bank", type="Asset", code="1000")
        name = full_account_name(info, {})
        self.assertTrue(name.endswith(":Bank"))
        self.assertIn("Cash", name)

    def test_csv_rows_sign_convention_asset_debit_positive(self):
        accounts = {1: AccountInfo(name="Bank", type="Asset", category="cash")}
        entries = [EntryData(id=1, date=__import__("datetime").datetime(2024, 1, 1), description="Opening",
                             lines=((1, D("100"), D("0")),))]
        rows = build_csv_rows(entries, accounts, {"cash": "Assets:Cash"})
        self.assertEqual(rows[0]["Amount Num."], "100.00")

    def test_csv_rows_sign_convention_liability_credit_positive(self):
        accounts = {1: AccountInfo(name="Loan", type="Liability", category="creditor")}
        entries = [EntryData(id=1, date=__import__("datetime").datetime(2024, 1, 1), description="Loan",
                             lines=((1, D("0"), D("500")),))]
        rows = build_csv_rows(entries, accounts, {"creditor": "Liabilities:Creditors"})
        self.assertEqual(rows[0]["Amount Num."], "500.00")

    def test_unknown_account_id_raises(self):
        entries = [EntryData(id=1, date=__import__("datetime").datetime(2024, 1, 1), description="x",
                             lines=((99, D("1"), D("0")),))]
        with self.assertRaises(KeyError):
            build_csv_rows(entries, {}, {})


if __name__ == "__main__":
    unittest.main()
