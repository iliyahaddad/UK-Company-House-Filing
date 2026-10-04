"""Needs sqlalchemy - see docs/TESTING.md. Written to match app/accounting/engine.py."""
from datetime import date
from decimal import Decimal as D

import pytest

from app.accounting.engine import AccountingEngine
from app.accounting.rules import BalanceSheetError, ConflictError, DomainError, NotFoundError


def account_by_code(engine, company_id, code):
    return next(a for a in engine.db.query(__import__("app.db.database", fromlist=["Account"]).Account)
               .filter_by(company_id=company_id).all() if a.code == code)


def post(engine, company, ref, lines, when=date(2024, 6, 1), period_id=None):
    return engine.create_journal_entry(company.id, when, ref, ref, lines, fiscal_period_id=period_id)


class TestCompanyCreation:
    def test_duplicate_company_number_rejected(self, db_session, company):
        engine = AccountingEngine(db_session)
        with pytest.raises(ConflictError):
            engine.create_company("Other Ltd", "12345678")

    def test_invalid_company_number_rejected(self, db_session):
        with pytest.raises(DomainError):
            AccountingEngine(db_session).create_company("X Ltd", "abc")


class TestJournal:
    def test_unbalanced_entry_rejected(self, db_session, company):
        engine = AccountingEngine(db_session)
        bank = account_by_code(engine, company.id, "1000")
        sales = account_by_code(engine, company.id, "4000")
        with pytest.raises(DomainError):
            post(engine, company, "bad", [
                {"account_id": bank.id, "debit": "100", "credit": "0"},
                {"account_id": sales.id, "debit": "0", "credit": "90"},
            ])

    def test_line_with_both_debit_and_credit_rejected(self, db_session, company):
        engine = AccountingEngine(db_session)
        bank = account_by_code(engine, company.id, "1000")
        sales = account_by_code(engine, company.id, "4000")
        with pytest.raises(DomainError):
            post(engine, company, "bad", [
                {"account_id": bank.id, "debit": "100", "credit": "100"},
                {"account_id": sales.id, "debit": "0", "credit": "100"},
            ])

    def test_account_from_other_company_rejected(self, db_session, company):
        engine = AccountingEngine(db_session)
        other = engine.create_company("Other Ltd", "SC123456")
        engine.seed_default_chart(other.id)
        bank = account_by_code(engine, company.id, "1000")
        other_sales = account_by_code(engine, other.id, "4000")
        with pytest.raises(NotFoundError):
            post(engine, company, "bad", [
                {"account_id": bank.id, "debit": "100", "credit": "0"},
                {"account_id": other_sales.id, "debit": "0", "credit": "100"},
            ])


class TestBalanceSheet:
    def test_balances_after_simple_sale(self, db_session, company):
        engine = AccountingEngine(db_session)
        bank = account_by_code(engine, company.id, "1000")
        sales = account_by_code(engine, company.id, "4000")
        post(engine, company, "sale", [
            {"account_id": bank.id, "debit": "1000", "credit": "0"},
            {"account_id": sales.id, "debit": "0", "credit": "1000"},
        ])
        bs = engine.get_balance_sheet(company.id)
        assert bs["total_assets"] == D("1000")
        assert bs["net_assets"] == D("1000")

    def test_trial_balance_by_period_matches_balance_sheet_scope(self, db_session, company):
        engine = AccountingEngine(db_session)
        period = engine.create_fiscal_period(company.id, "2024", date(2024, 1, 1), date(2024, 12, 31))
        bank = account_by_code(engine, company.id, "1000")
        sales = account_by_code(engine, company.id, "4000")
        # one entry with an explicit period, one without (falls in the same date range)
        post(engine, company, "in-period", [
            {"account_id": bank.id, "debit": "500", "credit": "0"},
            {"account_id": sales.id, "debit": "0", "credit": "500"},
        ], when=date(2024, 3, 1), period_id=period.id)
        post(engine, company, "no-explicit-period", [
            {"account_id": bank.id, "debit": "200", "credit": "0"},
            {"account_id": sales.id, "debit": "0", "credit": "200"},
        ], when=date(2024, 4, 1))
        pl = engine.get_profit_loss(company.id, period.id)
        bs = engine.get_balance_sheet(company.id, period.id)
        # Regression check for the old bug: P&L (period-keyed) and balance sheet (date-keyed)
        # must agree on total revenue recognised, or the iXBRL and the P&L page will disagree.
        assert pl["revenue"] == D("700")
        assert bs["net_profit"] == D("700")


class TestFingerprint:
    def test_fingerprint_changes_when_ledger_changes(self, db_session, company):
        engine = AccountingEngine(db_session)
        end = __import__("app.accounting.rules", fromlist=["midnight"]).midnight(date(2024, 12, 31))
        before = engine.ledger_fingerprint(company.id, end)
        bank = account_by_code(engine, company.id, "1000")
        sales = account_by_code(engine, company.id, "4000")
        post(engine, company, "x", [
            {"account_id": bank.id, "debit": "10", "credit": "0"},
            {"account_id": sales.id, "debit": "0", "credit": "10"},
        ])
        after = engine.ledger_fingerprint(company.id, end)
        assert before != after

    def test_fingerprint_changes_for_non_aggregate_ledger_edit(self, db_session, company):
        engine = AccountingEngine(db_session)
        end = __import__("app.accounting.rules", fromlist=["midnight"]).midnight(date(2024, 12, 31))
        bank = account_by_code(engine, company.id, "1000")
        sales = account_by_code(engine, company.id, "4000")
        entry = post(engine, company, "x", [
            {"account_id": bank.id, "debit": "10", "credit": "0"},
            {"account_id": sales.id, "debit": "0", "credit": "10"},
        ])
        before = engine.ledger_fingerprint(company.id, end)
        entry.description = "edited description"
        db_session.commit()
        after = engine.ledger_fingerprint(company.id, end)
        assert before != after

class TestMultiYearBalanceSheet:
    def test_balance_sheet_carries_prior_year_profit_forward(self, db_session, company):
        engine = AccountingEngine(db_session)
        p2024 = engine.create_fiscal_period(company.id, "2024", date(2024, 1, 1), date(2024, 12, 31))
        p2025 = engine.create_fiscal_period(company.id, "2025", date(2025, 1, 1), date(2025, 12, 31))
        bank = account_by_code(engine, company.id, "1000")
        sales = account_by_code(engine, company.id, "4000")
        post(engine, company, "sale-2024", [
            {"account_id": bank.id, "debit": "1000", "credit": "0"},
            {"account_id": sales.id, "debit": "0", "credit": "1000"},
        ], when=date(2024, 6, 1), period_id=p2024.id)
        post(engine, company, "sale-2025", [
            {"account_id": bank.id, "debit": "200", "credit": "0"},
            {"account_id": sales.id, "debit": "0", "credit": "200"},
        ], when=date(2025, 6, 1), period_id=p2025.id)
        bs = engine.get_balance_sheet(company.id, p2025.id)
        pl = engine.get_profit_loss(company.id, p2025.id)
        assert bs["cash"] == D("1200")
        assert bs["retained_earnings"] == D("1200")
        assert pl["revenue"] == D("200")
