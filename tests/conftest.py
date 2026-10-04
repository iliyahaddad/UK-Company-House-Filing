"""Shared fixtures. Requires sqlalchemy/fastapi (see requirements.txt) -
not runnable in an environment without them (see docs/TESTING.md)."""
import os
import tempfile
from datetime import date

import pytest

os.environ.setdefault("APP_ENV", "test")
os.environ.setdefault("CH_CREDENTIALS_KEY", __import__("cryptography.fernet", fromlist=["Fernet"]).Fernet.generate_key().decode())
os.environ.setdefault("CH_CONTACT_NAME", "Test Contact")
os.environ.setdefault("CH_CONTACT_EMAIL", "test@example.com")
os.environ.setdefault("CH_CONTACT_NUMBER", "01234 567890")


@pytest.fixture()
def db_session(tmp_path, monkeypatch):
    from sqlalchemy import create_engine
    from sqlalchemy.orm import sessionmaker

    from app.db import database as db_module

    engine = create_engine(f"sqlite:///{tmp_path}/test.db", connect_args={"check_same_thread": False})
    db_module.init_db(bind=engine)
    TestingSession = sessionmaker(bind=engine)
    monkeypatch.setattr(db_module, "SessionLocal", TestingSession)
    session = TestingSession()
    try:
        yield session
    finally:
        session.close()


@pytest.fixture()
def company(db_session):
    from app.accounting.engine import AccountingEngine

    engine = AccountingEngine(db_session)
    c = engine.create_company("Acme Ltd", "12345678", company_type="EW",
                              directors="Jane Smith, Amir Khan", incorporation_date=date(2020, 1, 1))
    engine.seed_default_chart(c.id)
    return c


@pytest.fixture()
def client(tmp_path, monkeypatch):
    from sqlalchemy import create_engine
    from sqlalchemy.orm import sessionmaker
    from fastapi.testclient import TestClient
    from app.db import database as db_module
    monkeypatch.setenv("DATA_DIR", str(tmp_path))
    monkeypatch.setenv("APP_ENV", "test")
    test_engine = create_engine(f"sqlite:///{tmp_path}/api.db", connect_args={"check_same_thread": False})
    db_module.init_db(bind=test_engine)
    TestingSession = sessionmaker(bind=test_engine)
    monkeypatch.setattr(db_module, "SessionLocal", TestingSession)
    from app.main import app
    from app.api.routes import get_db
    def override_get_db():
        db = TestingSession()
        try:
            yield db
        finally:
            db.close()
    app.dependency_overrides[get_db] = override_get_db
    try:
        with TestClient(app) as c:
            yield c
    finally:
        app.dependency_overrides.pop(get_db, None)
        test_engine.dispose()
