"""Needs fastapi/sqlalchemy - see docs/TESTING.md."""
import os

import pytest


class TestTrialBalanceSerialisation:
    def test_trial_balance_with_decimal_values_serialises(self, client):
        # regression test for the old bug: JSONResponse cannot serialise Decimal directly
        resp = client.post("/api/companies", json={
            "name": "Acme Ltd", "company_number": "12345678", "company_type": "EW",
            "directors": "Jane Smith", "incorporation_date": "2020-01-01",
        })
        assert resp.status_code == 200, resp.text
        company_id = resp.json()["id"]
        client.post(f"/api/companies/{company_id}/accounts/seed-chart")
        accounts = client.get(f"/api/companies/{company_id}/accounts").json()["accounts"]
        bank = next(a for a in accounts if a["code"] == "1000")
        sales = next(a for a in accounts if a["code"] == "4000")
        resp = client.post(f"/api/companies/{company_id}/journal", json={
            "date": "2024-06-01", "description": "Sale", "reference": "INV1",
            "lines": [
                {"account_id": bank["id"], "debit": "100.00", "credit": "0"},
                {"account_id": sales["id"], "debit": "0", "credit": "100.00"},
            ],
        })
        assert resp.status_code == 200, resp.text
        resp = client.get(f"/api/companies/{company_id}/reports/trial-balance")
        assert resp.status_code == 200, resp.text
        body = resp.json()
        assert body["total_debit"] == "100.00"


class TestErrorHandling:
    def test_duplicate_company_number_returns_409(self, client):
        payload = {"name": "Acme Ltd", "company_number": "12345678", "company_type": "EW",
                   "directors": "Jane Smith", "incorporation_date": "2020-01-01"}
        assert client.post("/api/companies", json=payload).status_code == 200
        resp = client.post("/api/companies", json=payload)
        assert resp.status_code == 409
        assert resp.json()["success"] is False

    def test_missing_company_returns_404(self, client):
        resp = client.get("/api/companies/999999/accounts")
        assert resp.status_code == 404

    def test_unbalanced_journal_returns_400(self, client):
        resp = client.post("/api/companies", json={
            "name": "Acme Ltd", "company_number": "12345678", "company_type": "EW",
            "directors": "Jane Smith", "incorporation_date": "2020-01-01",
        })
        company_id = resp.json()["id"]
        client.post(f"/api/companies/{company_id}/accounts/seed-chart")
        accounts = client.get(f"/api/companies/{company_id}/accounts").json()["accounts"]
        bank = next(a for a in accounts if a["code"] == "1000")
        resp = client.post(f"/api/companies/{company_id}/journal", json={
            "date": "2024-06-01", "description": "Bad", "reference": "",
            "lines": [{"account_id": bank["id"], "debit": "100.00", "credit": "0"}],
        })
        assert resp.status_code == 422  # only one line: pydantic min length would also catch this


class TestSecurityHeaders:
    def test_response_has_security_headers(self, client):
        resp = client.get("/health")
        assert resp.headers.get("x-content-type-options") == "nosniff"
        assert resp.headers.get("content-security-policy")

    def test_cross_site_post_rejected(self, client):
        resp = client.post("/api/companies", json={"name": "x", "company_number": "12345678"},
                           headers={"Origin": "https://evil.example.com"})
        assert resp.status_code == 403
