"""Request bodies. Validation errors come back as HTTP 422 with a readable message."""
from __future__ import annotations

import datetime as dt
from decimal import Decimal
from typing import List, Literal, Optional

from pydantic import BaseModel, ConfigDict, Field


class _Body(BaseModel):
    model_config = ConfigDict(str_strip_whitespace=True, extra="forbid")


class CompanyIn(_Body):
    name: str = Field(min_length=1, max_length=255)
    company_number: str
    registered_address: Optional[str] = None
    company_type: Literal["EW", "SC", "NI"] = "EW"
    sic_code: Optional[str] = Field(default=None, max_length=20)
    directors: Optional[str] = None
    incorporation_date: Optional[dt.date] = None


class AccountIn(_Body):
    code: str = Field(min_length=1, max_length=50)
    name: str = Field(min_length=1, max_length=255)
    type: str
    parent_id: Optional[int] = None
    category: Optional[str] = None


class PeriodIn(_Body):
    name: str = Field(min_length=1, max_length=100)
    start_date: dt.date
    end_date: dt.date
    is_current: bool = True


class JournalLineIn(_Body):
    account_id: int
    debit: Decimal = Decimal("0")
    credit: Decimal = Decimal("0")
    description: Optional[str] = None


class JournalIn(_Body):
    date: dt.date
    description: str = Field(min_length=1, max_length=500)
    reference: str = ""
    fiscal_period_id: Optional[int] = None
    lines: List[JournalLineIn] = Field(min_length=2)


class DetailsIn(_Body):
    period_id: int
    approval_date: Optional[dt.date] = None
    signing_director: Optional[str] = None
    average_employees: Optional[int] = Field(default=None, ge=0, le=1_000_000)
    principal_activities: Optional[str] = Field(default=None, max_length=2000)
    confirm_eligibility: bool = False
    confirm_audit_exemption: bool = False


class GenerateIn(_Body):
    account_type: Literal["dormant", "micro", "small"]
    period_id: int


class FileRef(_Body):
    file_id: int


class SubmitIn(_Body):
    file_id: int
    confirm_approval: bool = False


class ReleaseIn(_Body):
    confirm: bool = False


class CredentialsIn(_Body):
    presenter_id: str = Field(min_length=1, max_length=255)
    authentication: str = Field(min_length=1)
    company_auth_code: str = Field(min_length=1)
    gateway_url: Optional[str] = None
    test_mode: bool = True
