import unittest
from datetime import date
from decimal import Decimal as D

from app.accounting.rules import (
    AccountRow, BalanceSheetError, ConflictError, DomainError,
    build_balance_sheet, build_profit_loss, build_trial_balance, trial_balance_totals,
    default_category, normalise_company_number, validate_category, validate_period,
)


def row(id_, code, name, type_, debit, credit, category=None):
    return AccountRow(id_, code, name, type_, category, D(debit), D(credit))


class CompanyNumberTests(unittest.TestCase):
    def test_valid_digits(self):
        self.assertEqual(normalise_company_number("12345678"), "12345678")

    def test_valid_scotland_prefix(self):
        self.assertEqual(normalise_company_number("sc123456"), "SC123456")

    def test_rejects_short(self):
        with self.assertRaises(DomainError):
            normalise_company_number("1234")

    def test_rejects_empty(self):
        with self.assertRaises(DomainError):
            normalise_company_number("")


class CategoryTests(unittest.TestCase):
    def test_default_bank_is_cash(self):
        self.assertEqual(default_category("Asset", "1000", "Bank"), "cash")

    def test_default_fixed_asset_by_code(self):
        self.assertEqual(default_category("Asset", "1200", "Equipment"), "fixed_asset")

    def test_default_liability_2xxx_is_current(self):
        self.assertEqual(default_category("Liability", "2500", "Bank Loan"), "current_liability")

    def test_default_liability_other_is_long_term(self):
        self.assertEqual(default_category("Liability", "9000", "Director Loan"), "long_term_liability")

    def test_validate_category_mismatch(self):
        with self.assertRaises(DomainError):
            validate_category("cash", "Liability")

    def test_validate_category_unknown(self):
        with self.assertRaises(DomainError):
            validate_category("not-a-category", "Asset")

    def test_validate_category_none_is_ok(self):
        self.assertIsNone(validate_category(None, "Asset"))


class ProfitLossTests(unittest.TestCase):
    def test_basic_pl(self):
        rows = [
            row(1, "4000", "Sales", "Revenue", "0", "10000"),
            row(2, "5000", "Cost of Sales", "Expense", "4000", "0"),
            row(3, "6000", "Office", "Expense", "1000", "0"),
            row(4, "7000", "Tax", "Expense", "500", "0"),
        ]
        pl = build_profit_loss(rows)
        self.assertEqual(pl["revenue"], D("10000"))
        self.assertEqual(pl["cost_of_sales"], D("4000"))
        self.assertEqual(pl["gross_profit"], D("6000"))
        self.assertEqual(pl["operating_expenses"], D("1000"))
        self.assertEqual(pl["operating_profit"], D("5000"))
        self.assertEqual(pl["net_profit"], D("4500"))


class BalanceSheetTests(unittest.TestCase):
    def test_balances(self):
        rows = [
            row(1, "1000", "Bank", "Asset", "11000", "0"),
            row(2, "3000", "Share Capital", "Equity", "0", "1000"),
            row(3, "3100", "Retained Earnings", "Equity", "0", "0"),
            row(4, "4000", "Sales", "Revenue", "0", "10000"),
        ]
        bs = build_balance_sheet(rows)
        self.assertEqual(bs["total_assets"], D("11000"))
        self.assertEqual(bs["total_equity"], D("11000"))
        self.assertEqual(bs["net_assets"], D("11000"))
        self.assertEqual(bs["retained_earnings"], D("10000"))

    def test_out_of_balance_raises(self):
        rows = [row(1, "1000", "Bank", "Asset", "100", "0"), row(2, "3000", "Equity", "Equity", "0", "50")]
        with self.assertRaises(BalanceSheetError):
            build_balance_sheet(rows)

    def test_cumulative_does_not_double_count_closed_profit(self):
        # Prior-year profit already closed into retained earnings, this year's activity separate.
        rows = [
            row(1, "1000", "Bank", "Asset", "15000", "0"),
            row(2, "3000", "Share Capital", "Equity", "0", "1000"),
            row(3, "3100", "Retained Earnings", "Equity", "0", "9000"),  # closed from last year
            row(4, "4000", "Sales", "Revenue", "0", "6000"),  # this year, not yet closed
            row(5, "6000", "Expenses", "Expense", "1000", "0"),
        ]
        bs = build_balance_sheet(rows)
        self.assertEqual(bs["retained_earnings"], D("14000"))  # 9000 + (6000-1000)
        self.assertEqual(bs["total_equity"], D("15000"))
        self.assertEqual(bs["total_assets"], D("15000"))


class TrialBalanceTests(unittest.TestCase):
    def test_totals_balance(self):
        rows = build_trial_balance(
            [row(1, "1000", "Bank", "Asset", "100", "0")],
            [row(2, "4000", "Sales", "Revenue", "0", "100")],
        )
        totals = trial_balance_totals(rows)
        self.assertTrue(totals["balanced"])
        self.assertEqual(totals["total_debit"], D("100"))

    def test_prior_result_brought_forward_line(self):
        rows = build_trial_balance([], [], prior_result=D("500"))
        self.assertEqual(len(rows), 1)
        self.assertEqual(rows[0]["code"], "B/F")
        self.assertEqual(rows[0]["debit"], D("500"))


class PeriodValidationTests(unittest.TestCase):
    def test_start_after_end(self):
        with self.assertRaises(DomainError):
            validate_period(date(2024, 12, 31), date(2024, 1, 1), [])

    def test_over_18_months(self):
        with self.assertRaises(DomainError):
            validate_period(date(2023, 1, 1), date(2024, 12, 1), [])

    def test_before_incorporation(self):
        with self.assertRaises(DomainError):
            validate_period(date(2023, 1, 1), date(2023, 12, 31), [], incorporation_date=date(2023, 6, 1))

    def test_overlap_rejected(self):
        existing = [(1, date(2023, 1, 1), date(2023, 12, 31), "Y1")]
        with self.assertRaises(ConflictError):
            validate_period(date(2023, 6, 1), date(2024, 6, 1), existing)

    def test_back_to_back_ok(self):
        existing = [(1, date(2023, 1, 1), date(2023, 12, 31), "Y1")]
        validate_period(date(2024, 1, 1), date(2024, 12, 31), existing)  # no raise


if __name__ == "__main__":
    unittest.main()
