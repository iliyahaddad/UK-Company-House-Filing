"""Requires no database, but does need copy.deepcopy semantics on nested dicts."""
import unittest
from datetime import date

from app.accounting.rules import DomainError
from app.uk_accounts.config_builder import (
    CompanyInfo, DetailsInfo, PeriodInfo, build_report_config, parse_directors,
)


def base_template():
    return {
        "accounts": {"file": "PLACEHOLDER", "kind": "csv"},
        "metadata": {
            "business": {
                "company-name": "", "company-number": "", "is-dormant": False, "sic-codes": [],
                "jurisdiction": "England and Wales", "directors": [],
                "company-formation": {"date": "PLACEHOLDER", "country": "england-and-wales"},
                "contact": {"name": "", "email": "", "phone": {"number": ""}},
            },
            "directors": {"report-date": "PLACEHOLDER"},
            "accounting": {
                "authorised-date": "PLACEHOLDER", "balance-sheet-date": "PLACEHOLDER", "date": "PLACEHOLDER",
                "periods": [{}, {}], "signing-officer": "director1", "directors-report-signing-officer": "director1",
            },
        },
    }


class ParseDirectorsTests(unittest.TestCase):
    def test_comma_separated(self):
        self.assertEqual(parse_directors("Jane Smith, Amir Khan"), ["Jane Smith", "Amir Khan"])

    def test_json_list(self):
        self.assertEqual(parse_directors('["Jane Smith", "Amir Khan"]'), ["Jane Smith", "Amir Khan"])

    def test_empty(self):
        self.assertEqual(parse_directors(None), [])
        self.assertEqual(parse_directors(""), [])

    def test_semicolon_separated(self):
        self.assertEqual(parse_directors("Jane Smith; Amir Khan"), ["Jane Smith", "Amir Khan"])


class BuildReportConfigTests(unittest.TestCase):
    def setUp(self):
        self.company = CompanyInfo("Acme Ltd", "12345678", "EW", "62020", date(2020, 1, 1), ["Jane Smith"])
        self.period = PeriodInfo("2024", date(2024, 1, 1), date(2024, 12, 31))
        self.details = DetailsInfo(date(2025, 3, 1), "Jane Smith", 2, "Consulting")
        self.contact = {"name": "Jane Smith", "email": "jane@example.com", "number": "01234 567890"}

    def test_fills_expected_fields(self):
        cfg = build_report_config(base_template(), company=self.company, period=self.period, previous=None,
                                  details=self.details, account_type="micro", contact=self.contact,
                                  csv_path="/tmp/x.csv")
        biz = cfg["metadata"]["business"]
        self.assertEqual(biz["company-name"], "Acme Ltd")
        self.assertEqual(biz["directors"], ["Jane Smith"])
        self.assertEqual(biz["is-dormant"], False)
        self.assertEqual(cfg["metadata"]["accounting"]["periods"][0]["end"], "2024-12-31")
        self.assertEqual(cfg["metadata"]["accounting"]["periods"][1]["end"], "2023-12-31")  # synthesised prior year

    def test_does_not_mutate_base_template(self):
        base = base_template()
        build_report_config(base, company=self.company, period=self.period, previous=None,
                            details=self.details, account_type="micro", contact=self.contact, csv_path="x")
        self.assertEqual(base["metadata"]["business"]["company-name"], "")

    def test_missing_incorporation_date_rejected(self):
        company = CompanyInfo("Acme Ltd", "12345678", "EW", None, None, ["Jane Smith"])
        with self.assertRaises(DomainError):
            build_report_config(base_template(), company=company, period=self.period, previous=None,
                                details=self.details, account_type="micro", contact=self.contact, csv_path="x")

    def test_signing_director_not_in_list_rejected(self):
        details = DetailsInfo(date(2025, 3, 1), "Someone Else", 2, "Consulting")
        with self.assertRaises(DomainError):
            build_report_config(base_template(), company=self.company, period=self.period, previous=None,
                                details=details, account_type="micro", contact=self.contact, csv_path="x")

    def test_incomplete_contact_rejected(self):
        with self.assertRaises(DomainError):
            build_report_config(base_template(), company=self.company, period=self.period, previous=None,
                                details=self.details, account_type="micro", contact={"name": "x"}, csv_path="x")


if __name__ == "__main__":
    unittest.main()
