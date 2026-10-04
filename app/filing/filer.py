"""Companies House Software Filing.

The upstream ``companies-house-filing`` package is the wire-format client. This
module owns what surrounds it: which credentials and dates go in, the
per-presenter counter files (locked across processes), and a submission record
that exists *before* anything is sent, so a crash can never leave an untracked
filing behind.
"""
from __future__ import annotations

import hashlib
import json
import os
import shutil
import tempfile
import uuid
from datetime import date, datetime, timezone
from pathlib import Path
from typing import Any, Dict, Optional
from urllib.parse import urlparse

from sqlalchemy.orm import Session

from .. import config
from ..accounting.rules import DomainError
from ..db.database import AccountsFile, Company, FilingCredential, Submission

DEFAULT_GATEWAY_URL = "https://xmlgw.companieshouse.gov.uk/v1-0/xmlgw/Gateway"
ALLOWED_GATEWAY_HOST = "xmlgw.companieshouse.gov.uk"


def validate_gateway_url(url: Optional[str]) -> str:
    """Only the official Companies House gateway may be used (prevents credential leaks)."""
    value = (url or DEFAULT_GATEWAY_URL).strip()
    parsed = urlparse(value)
    if parsed.scheme != "https" or parsed.hostname != ALLOWED_GATEWAY_HOST:
        raise DomainError(
            f"Companies House gateway URL must use HTTPS and the official host {ALLOWED_GATEWAY_HOST}"
        )
    return value


class CompaniesHouseFiler:
    def __init__(self, state_dir: Optional[str] = None):
        try:
            from ch_filing.client import Client
            from ch_filing.envelope import Envelope
            from ch_filing.form_submission import Accounts
            from ch_filing.state import State
            from ch_filing.submission_status import SubmissionStatus

            self.Client, self.State, self.Envelope = Client, State, Envelope
            self.Accounts, self.SubmissionStatus = Accounts, SubmissionStatus
            self.available = True
        except ImportError as exc:
            self.available = False
            self._import_error = str(exc)

        self.state_dir = Path(state_dir or config.FILING_STATE_DIR)
        self.state_dir.mkdir(parents=True, exist_ok=True)
        try:
            os.chmod(self.state_dir, 0o700)
        except OSError:
            pass

    # ------------------------------------------------------------------ helpers
    def _require_available(self) -> None:
        if not self.available:
            raise RuntimeError(
                "companies-house-filing is not installed: "
                f"{getattr(self, '_import_error', 'unknown import error')}"
            )

    @staticmethod
    def _gateway_url(credential: FilingCredential) -> str:
        return validate_gateway_url(credential.gateway_url)

    def _state_path(self, presenter_id: str) -> Path:
        digest = hashlib.sha256(presenter_id.encode("utf-8")).hexdigest()[:32]
        return self.state_dir / f"presenter_{digest}.json"

    def _lock(self, state_path: Path):
        from filelock import FileLock  # cross-process and cross-platform

        return FileLock(str(state_path) + ".lock", timeout=60)

    @staticmethod
    def _initialise_state(path: Path) -> None:
        if path.exists():
            return
        tmp = path.with_suffix(path.suffix + ".tmp")
        tmp.write_text(json.dumps({"transaction-id": 0, "submission-id": 0}), encoding="utf-8")
        os.replace(tmp, path)
        try:
            os.chmod(path, 0o600)
        except OSError:
            pass

    @staticmethod
    def _contact_config() -> Dict[str, str]:
        values = {
            "contact-name": os.getenv("CH_CONTACT_NAME", "").strip(),
            "contact-number": os.getenv("CH_CONTACT_NUMBER", "").strip(),
            "email": os.getenv("CH_CONTACT_EMAIL", "").strip(),
        }
        if not all(values.values()):
            raise DomainError(
                "Companies House contact details are incomplete. "
                "Set CH_CONTACT_NAME, CH_CONTACT_NUMBER and CH_CONTACT_EMAIL."
            )
        return values

    def _build_config(self, company: Company, credential: FilingCredential,
                      approval_date: Optional[date] = None) -> Dict[str, Any]:
        contact = self._contact_config()
        today = datetime.now(timezone.utc).date().isoformat()
        return {
            "presenter-id": credential.presenter_id,
            "authentication": credential.authentication,
            "company-number": company.company_number,
            "company-name": company.name,
            "company-type": company.company_type or "EW",
            **contact,
            "date-signed": (approval_date or datetime.now(timezone.utc).date()).isoformat(),
            "date": today,
            "test-flag": "1" if credential.test_mode else "0",
            "package-reference": config.CH_PACKAGE_REFERENCE,
            "company-authentication-code": credential.company_auth_code,
            "url": self._gateway_url(credential),
        }

    def _client_state(self, tmpdir: Path, cfg: Dict[str, Any], state_path: Path):
        config_path = tmpdir / "config.json"
        config_path.write_text(json.dumps(cfg, indent=2), encoding="utf-8")
        try:
            os.chmod(config_path, 0o600)
        except OSError:
            pass
        self._initialise_state(state_path)
        return self.State(str(config_path), str(state_path))

    # ------------------------------------------------------------------ submit
    def submit_accounts(
        self,
        db: Session,
        company: Company,
        credential: FilingCredential,
        record: AccountsFile,
        ixbrl_path: Path,
        approval_date: date,
    ) -> Submission:
        self._require_available()
        submission = Submission(
            company_id=company.id,
            accounts_file_id=record.id,
            submission_id=f"PENDING-{uuid.uuid4().hex[:16]}",
            status="PENDING",
            accounts_type=record.account_type,
        )
        db.add(submission)
        db.commit()

        sent = False
        try:
            cfg = self._build_config(company, credential, approval_date)
            state_path = self._state_path(credential.presenter_id)
            ixbrl_data = Path(ixbrl_path).read_text(encoding="utf-8")
            tmpdir = Path(tempfile.mkdtemp(prefix="ch_filing_"))
            try:
                with self._lock(state_path):
                    state = self._client_state(tmpdir, cfg, state_path)
                    client = self.Client(state)
                    form = self.Accounts.create_submission(state, Path(ixbrl_path).name, ixbrl_data)
                    envelope = self.Envelope.create(state, form, "request", "request")
                    sent = True  # from here on Companies House may have received it
                    response = client.call(state, envelope)
            finally:
                shutil.rmtree(tmpdir, ignore_errors=True)

            body = getattr(response, "Body", None)
            form_response = getattr(body, "FormSubmissionResponse", None)
            number = str(getattr(form_response, "SubmissionNumber", "") or "") if form_response is not None else ""
            if not number:
                raise RuntimeError("No submission number in the Companies House response")
            submission.submission_id = number
            submission.status = "SUBMITTED"
            submission.response_data = str(response)
            db.commit()
            db.refresh(submission)
            return submission
        except Exception as exc:
            db.rollback()
            submission = db.query(Submission).filter(Submission.id == submission.id).first()
            if submission is not None:
                submission.status = "UNCERTAIN" if sent else "FAILED"
                submission.response_data = f"{type(exc).__name__}: {exc}"
                db.commit()
            raise

    def get_submission_status(self, db: Session, company: Company, credential: FilingCredential,
                              submission: Submission) -> Dict[str, Any]:
        self._require_available()
        number = (submission.submission_id or "").strip().upper()
        if not number.startswith("S") or not number[1:].isdigit():
            raise DomainError("This submission has no Companies House submission number yet")

        cfg = self._build_config(company, credential)
        state_path = self._state_path(credential.presenter_id)
        tmpdir = Path(tempfile.mkdtemp(prefix="ch_status_"))
        try:
            with self._lock(state_path):
                state = self._client_state(tmpdir, cfg, state_path)
                client = self.Client(state)
                request = self.SubmissionStatus.create_request(state, sub_id=number)
                envelope = self.Envelope.create(state, request, "request", "request")
                response = client.call(state, envelope)
        finally:
            shutil.rmtree(tmpdir, ignore_errors=True)

        body = getattr(response, "Body", None)
        result = getattr(body, "GetSubmissionStatusResult", None)
        status = str(getattr(result, "Status", "UNKNOWN")) if result is not None else "UNKNOWN"
        submission.status = status
        db.commit()
        return {"submission_id": number, "status": status, "response": str(response)}
