"""Database models, encryption of stored secrets and light schema upgrades."""
from __future__ import annotations

import logging
import os
from datetime import datetime, timezone

from cryptography.fernet import Fernet, InvalidToken
from sqlalchemy import (
    Boolean,
    Column,
    Date,
    DateTime,
    ForeignKey,
    Integer,
    Numeric,
    String,
    Text,
    UniqueConstraint,
    create_engine,
    inspect,
    text,
)
from sqlalchemy.orm import declarative_base, relationship, sessionmaker
from sqlalchemy.types import TypeDecorator

from .. import config

log = logging.getLogger("ukaccounts.db")

_engine_kwargs = {}
if config.DATABASE_URL.startswith("sqlite"):
    _engine_kwargs["connect_args"] = {"check_same_thread": False}

engine = create_engine(config.DATABASE_URL, **_engine_kwargs)
SessionLocal = sessionmaker(autocommit=False, autoflush=False, bind=engine)
Base = declarative_base()


def get_db():
    """FastAPI dependency: one session per request."""
    db = SessionLocal()
    try:
        yield db
    finally:
        db.close()


def _utcnow() -> datetime:
    return datetime.now(timezone.utc).replace(tzinfo=None)


# --------------------------------------------------------------------------- #
# encryption of Companies House credentials
# --------------------------------------------------------------------------- #
class CredentialDecryptionError(RuntimeError):
    pass


def _load_or_create_encryption_key() -> bytes:
    """CH_CREDENTIALS_KEY is required in production; development may use a key file
    kept in DATA_DIR (never in the source tree)."""
    env_key = os.getenv("CH_CREDENTIALS_KEY")
    if env_key:
        key = env_key.strip().encode()
        Fernet(key)  # fail fast on a malformed key
        return key
    if config.IS_PRODUCTION:
        raise RuntimeError("CH_CREDENTIALS_KEY must be set when APP_ENV=production")

    key_path = config.DATA_DIR / "ch_credentials.key"
    if key_path.exists():
        key = key_path.read_bytes().strip()
        Fernet(key)
        return key
    key = Fernet.generate_key()
    key_path.write_bytes(key)
    try:
        os.chmod(key_path, 0o600)
    except OSError:
        pass
    log.warning("CH_CREDENTIALS_KEY is not set; created a development key at %s", key_path)
    return key


_fernet = Fernet(_load_or_create_encryption_key())


class EncryptedString(TypeDecorator):
    """Store sensitive text encrypted at rest using Fernet."""

    impl = Text
    cache_ok = True

    def process_bind_param(self, value, dialect):
        if value is None:
            return None
        return _fernet.encrypt(str(value).encode("utf-8")).decode("utf-8")

    def process_result_value(self, value, dialect):
        if value is None:
            return None
        try:
            return _fernet.decrypt(value.encode("utf-8")).decode("utf-8")
        except InvalidToken as exc:
            raise CredentialDecryptionError(
                "Stored filing credentials cannot be decrypted with the current CH_CREDENTIALS_KEY. "
                "Enter the credentials again."
            ) from exc


# --------------------------------------------------------------------------- #
# models
# --------------------------------------------------------------------------- #
class Company(Base):
    __tablename__ = "companies"

    id = Column(Integer, primary_key=True, index=True)
    name = Column(String(255), nullable=False)
    company_number = Column(String(50), unique=True, nullable=False)
    registered_address = Column(Text)
    incorporation_date = Column(Date, nullable=True)
    company_type = Column(String(50), default="EW", nullable=False)
    sic_code = Column(String(20))
    directors = Column(Text)
    fiscal_year_end = Column(String(20), default="12-31")
    created_at = Column(DateTime, default=_utcnow, nullable=False)
    updated_at = Column(DateTime, default=_utcnow, onupdate=_utcnow, nullable=False)

    accounts = relationship("Account", back_populates="company", cascade="all, delete-orphan")
    journal_entries = relationship("JournalEntry", back_populates="company", cascade="all, delete-orphan")
    fiscal_periods = relationship("FiscalPeriod", back_populates="company", cascade="all, delete-orphan",
                                  order_by="FiscalPeriod.start_date")
    filing_credentials = relationship("FilingCredential", back_populates="company", cascade="all, delete-orphan")
    submissions = relationship("Submission", back_populates="company", cascade="all, delete-orphan")


class Account(Base):
    __tablename__ = "accounts"
    __table_args__ = (UniqueConstraint("company_id", "code", name="uq_account_company_code"),)

    id = Column(Integer, primary_key=True, index=True)
    company_id = Column(Integer, ForeignKey("companies.id"), nullable=False, index=True)
    code = Column(String(50), nullable=False)
    name = Column(String(255), nullable=False)
    type = Column(String(50), nullable=False)
    category = Column(String(40), nullable=True)
    parent_id = Column(Integer, ForeignKey("accounts.id"), nullable=True)
    is_active = Column(Boolean, default=True, nullable=False)
    created_at = Column(DateTime, default=_utcnow, nullable=False)
    updated_at = Column(DateTime, default=_utcnow, onupdate=_utcnow, nullable=False)

    company = relationship("Company", back_populates="accounts")
    parent = relationship("Account", remote_side=[id], back_populates="children", foreign_keys=[parent_id])
    children = relationship("Account", back_populates="parent", foreign_keys=[parent_id], cascade="all")
    journal_lines = relationship("JournalLine", back_populates="account")


class FiscalPeriod(Base):
    __tablename__ = "fiscal_periods"

    id = Column(Integer, primary_key=True, index=True)
    company_id = Column(Integer, ForeignKey("companies.id"), nullable=False, index=True)
    name = Column(String(100), nullable=False)
    start_date = Column(DateTime, nullable=False)
    end_date = Column(DateTime, nullable=False)
    is_current = Column(Boolean, default=False, nullable=False)
    created_at = Column(DateTime, default=_utcnow, nullable=False)

    company = relationship("Company", back_populates="fiscal_periods")
    journal_entries = relationship("JournalEntry", back_populates="fiscal_period")


class JournalEntry(Base):
    __tablename__ = "journal_entries"

    id = Column(Integer, primary_key=True, index=True)
    company_id = Column(Integer, ForeignKey("companies.id"), nullable=False, index=True)
    date = Column(DateTime, nullable=False, index=True)
    description = Column(String(500))
    reference = Column(String(100))
    fiscal_period_id = Column(Integer, ForeignKey("fiscal_periods.id"), nullable=True, index=True)
    created_at = Column(DateTime, default=_utcnow, nullable=False)

    company = relationship("Company", back_populates="journal_entries")
    fiscal_period = relationship("FiscalPeriod", back_populates="journal_entries")
    lines = relationship("JournalLine", back_populates="journal_entry", cascade="all, delete-orphan")


class JournalLine(Base):
    __tablename__ = "journal_lines"

    id = Column(Integer, primary_key=True, index=True)
    journal_entry_id = Column(Integer, ForeignKey("journal_entries.id"), nullable=False, index=True)
    account_id = Column(Integer, ForeignKey("accounts.id"), nullable=False, index=True)
    debit = Column(Numeric(precision=18, scale=2), default=0, nullable=False)
    credit = Column(Numeric(precision=18, scale=2), default=0, nullable=False)
    description = Column(String(500))
    created_at = Column(DateTime, default=_utcnow, nullable=False)

    journal_entry = relationship("JournalEntry", back_populates="lines")
    account = relationship("Account", back_populates="journal_lines")


class AccountsDetails(Base):
    """Facts the directors must supply for one set of accounts (one per period)."""

    __tablename__ = "accounts_details"
    __table_args__ = (UniqueConstraint("period_id", name="uq_details_period"),)

    id = Column(Integer, primary_key=True)
    company_id = Column(Integer, ForeignKey("companies.id"), nullable=False, index=True)
    period_id = Column(Integer, ForeignKey("fiscal_periods.id"), nullable=False)
    approval_date = Column(Date, nullable=True)
    signing_director = Column(String(255))
    average_employees = Column(Integer)
    principal_activities = Column(Text)
    confirm_eligibility = Column(Boolean, default=False, nullable=False)
    confirm_audit_exemption = Column(Boolean, default=False, nullable=False)
    updated_at = Column(DateTime, default=_utcnow, onupdate=_utcnow, nullable=False)


class AccountsFile(Base):
    """A generated iXBRL document plus what is known about it."""

    __tablename__ = "accounts_files"

    id = Column(Integer, primary_key=True)
    company_id = Column(Integer, ForeignKey("companies.id"), nullable=False, index=True)
    period_id = Column(Integer, ForeignKey("fiscal_periods.id"), nullable=False)
    account_type = Column(String(20), nullable=False)
    filename = Column(String(255), unique=True, nullable=False)
    sha256 = Column(String(64), nullable=False)
    source_fingerprint = Column(String(64), nullable=False)
    reconciliation_ok = Column(Boolean, default=False, nullable=False)
    reconciliation_report = Column(Text)
    warnings = Column(Text)
    validation_valid = Column(Boolean, nullable=True)
    validated_sha256 = Column(String(64), nullable=True)
    validated_at = Column(DateTime, nullable=True)
    validation_summary = Column(Text)
    created_at = Column(DateTime, default=_utcnow, nullable=False)


class FilingCredential(Base):
    __tablename__ = "filing_credentials"

    id = Column(Integer, primary_key=True, index=True)
    company_id = Column(Integer, ForeignKey("companies.id"), nullable=False, unique=True)
    presenter_id = Column(String(255), nullable=False)
    authentication = Column(EncryptedString, nullable=False)
    company_auth_code = Column(EncryptedString, nullable=False)
    gateway_url = Column(String(500), default="https://xmlgw.companieshouse.gov.uk/v1-0/xmlgw/Gateway", nullable=False)
    test_mode = Column(Boolean, default=True, nullable=False)
    created_at = Column(DateTime, default=_utcnow, nullable=False)
    updated_at = Column(DateTime, default=_utcnow, onupdate=_utcnow, nullable=False)

    company = relationship("Company", back_populates="filing_credentials")


class Submission(Base):
    __tablename__ = "submissions"

    id = Column(Integer, primary_key=True, index=True)
    company_id = Column(Integer, ForeignKey("companies.id"), nullable=False, index=True)
    accounts_file_id = Column(Integer, ForeignKey("accounts_files.id"), nullable=True)
    submission_id = Column(String(100), unique=True, nullable=False)
    status = Column(String(50), default="PENDING", nullable=False)
    accounts_type = Column(String(50))
    filing_date = Column(DateTime, default=_utcnow, nullable=False)
    response_data = Column(Text)
    created_at = Column(DateTime, default=_utcnow, nullable=False)
    updated_at = Column(DateTime, default=_utcnow, onupdate=_utcnow, nullable=False)

    company = relationship("Company", back_populates="submissions")


# --------------------------------------------------------------------------- #
# schema creation and upgrades
# --------------------------------------------------------------------------- #
_ADDED_COLUMNS = {
    "companies": {"incorporation_date": "DATE"},
    "accounts": {"category": "VARCHAR(40)"},
    "submissions": {"accounts_file_id": "INTEGER"},
}


def init_db(bind=None) -> None:
    """Create missing tables and add columns introduced after the first release.

    Existing installations keep their data. (Alembic is not used: the only
    upgrades so far are optional columns.)
    """
    target = bind or engine
    Base.metadata.create_all(bind=target)
    inspector = inspect(target)
    for table, columns in _ADDED_COLUMNS.items():
        existing = {column["name"] for column in inspector.get_columns(table)}
        for name, ddl in columns.items():
            if name not in existing:
                with target.begin() as connection:
                    connection.execute(text(f"ALTER TABLE {table} ADD COLUMN {name} {ddl}"))
