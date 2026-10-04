"""Rules that must hold before accounts may be sent to Companies House (pure)."""
from __future__ import annotations

from dataclasses import dataclass
from typing import Iterable, Optional

from ..accounting.rules import DomainError

# statuses of an earlier submission of the same file that forbid sending it again
BLOCKING_STATUSES = {"PENDING", "UNCERTAIN", "SUBMITTED", "ACCEPT", "ACCEPTED", "PARKED"}
FREE_STATUSES = {"FAILED", "REJECT", "REJECTED", "RELEASED", "INTERNAL_FAILURE"}


class FilingBlocked(DomainError):
    """Submission refused; the message says why."""


@dataclass(frozen=True)
class FileState:
    sha256: str
    source_fingerprint: str
    reconciliation_ok: bool
    validation_valid: Optional[bool]
    validated_sha256: Optional[str]


def check_submission_allowed(
    *,
    file: FileState,
    sha256_on_disk: str,
    current_fingerprint: str,
    live: bool,
    live_filing_enabled: bool,
    confirm_approval: bool,
    earlier_statuses: Iterable[str],
) -> None:
    if not confirm_approval:
        raise FilingBlocked("Confirm that the directors have approved these accounts before submitting")
    if sha256_on_disk != file.sha256:
        raise FilingBlocked("The file on disk no longer matches the generated file. Generate the accounts again.")
    if current_fingerprint != file.source_fingerprint:
        raise FilingBlocked(
            "The ledger or the accounts details changed after this file was generated. Generate the accounts again."
        )
    if not file.reconciliation_ok:
        raise FilingBlocked(
            "The iXBRL totals do not match the ledger. Fix the account mapping and generate the accounts again."
        )
    if live:
        if not live_filing_enabled:
            raise FilingBlocked("Live filing is switched off. Set ALLOW_LIVE_FILING=true to enable it.")
        if not (file.validation_valid and file.validated_sha256 == file.sha256):
            raise FilingBlocked("This exact file has not passed Arelle validation. Validate it before a live submission.")
    for status in earlier_statuses:
        normalised = (status or "").strip().upper()
        if normalised in BLOCKING_STATUSES or normalised not in FREE_STATUSES:
            raise FilingBlocked(
                f"This file already has a submission with status {normalised or 'unknown'}. "
                "Check it with Companies House; if it definitely was not received, release it first."
            )
