# UK Accounts - Companies House Filing

Double-entry ledger, UK statutory micro/small/dormant accounts as iXBRL, Arelle
validation, and Companies House Software Filing submission, in one FastAPI app.

Built on: `cybermaggedon/ixbrl-reporter`, `cybermaggedon/ixbrl-reporter-jsonnet`,
`cybermaggedon/ixbrl-parse`, `cybermaggedon/companies-house-filing`, `Arelle/Arelle`.

## This is not "done" in the sense of "safe to file real accounts with today"

No accounting or filing software should be trusted blind. What this version
fixes relative to the six zips that came before it, and what it still cannot
prove without your data and a network connection, are both listed below -
read that before using it for a real company. See `docs/ARELLE_INTEGRATION.md`
for the Arelle-specific details and `docs/TESTING.md` for exactly which tests
ran and passed while this was built, and which need `pytest` on your machine.

## Quickstart

```bash
python -m venv .venv && source .venv/bin/activate
pip install -r requirements.txt
python scripts/bootstrap_upstreams.py   # fetches ixbrl-reporter-jsonnet templates
python scripts/preflight.py             # checks the environment is wired up
pytest -q                               # application test suite; see docs/TESTING.md

export CH_CREDENTIALS_KEY=$(python -c "from cryptography.fernet import Fernet; print(Fernet.generate_key().decode())")
export CH_CONTACT_NAME="Your Name" CH_CONTACT_EMAIL="you@example.com" CH_CONTACT_NUMBER="01234 567890"
python run.py    # http://127.0.0.1:8000, no auth in dev mode
```

To require a login (recommended even locally once you enter real data):

```bash
export AUTH_USER=you AUTH_PASSWORD="something-long-and-random"
```

Production (`APP_ENV=production`) refuses to start without `CH_CREDENTIALS_KEY`
and `AUTH_USER`/`AUTH_PASSWORD` (12+ characters) set. Put a real reverse proxy
with TLS in front of it; `run.py` only binds to `127.0.0.1` and is for local use.

## Workflow

1. **Companies** - add a company (number, incorporation date, directors).
2. **Setup** - chart of accounts, fiscal periods, and per-period accounts
   details (approval date, signing director, average employees, principal
   activities - all required by the taxonomy, see `docs/ARELLE_INTEGRATION.md`).
3. **Journal** - double-entry postings.
4. **Reports** - trial balance, P&L, balance sheet, all computed from the same
   date-scoped ledger query so they always agree with each other and with what
   gets exported.
5. **UK Accounts** - generate the iXBRL. It is immediately reconciled against
   the ledger (`app/xbrl/reconcile.py`); a mismatch is shown and blocks filing.
6. **Validation** - run Arelle (`validate/UK`, disclosure system `hmrc`) against
   the exact generated file.
7. **Filing** - enter Companies House Software Filing credentials (test mode
   by default), then submit. A `Submission` row is created with status
   `PENDING` *before* anything is sent, so a crash mid-request can never leave
   an untracked filing (`app/services/filing_guard.py`, `app/filing/filer.py`).

## Final verification status

The application-side test suite has been run from this release tree:

- `python -m pytest -q` — **112 passed**
- `python -m compileall -q app scripts tests` — **passed**
- The release archive was rebuilt after removing runtime databases, `__pycache__`
  and `.pytest_cache`.

The following live operational checks remain intentionally outside the automated
suite because they require the operator's real environment and credentials:

- Arelle validation against the installed UK disclosure system and the real
  generated company accounts.
- Companies House Software Filing submission using real credentials.

### Important application-side fixes retained in this release

- API tests use an isolated per-test SQLAlchemy database.
- Journal input requires at least two lines at the API boundary, while the
  accounting engine independently enforces double-entry rules.
- Balance-sheet reporting is cumulative through the period end while P&L remains
  period-scoped; a multi-year regression test covers the distinction.
- The generate/validate/submit workflow is guarded by the generated file hash,
  reconciliation result and ledger fingerprint.
- The ledger fingerprint hashes the complete relevant chart of accounts and every
  journal entry/line through the export date, rather than relying on aggregate
  totals that could collide for different ledgers.
- The project continues to use the upstream Arelle, ixbrl-reporter,
  ixbrl-reporter-jsonnet, ixbrl-parse and companies-house-filing components rather
  than reimplementing their protocols or taxonomy logic.

## License

This project is licensed under the Creative Commons Attribution-NonCommercial-NoDerivatives 4.0 International (CC BY-NC-ND 4.0) license.
Commercial use is not permitted.
Redistribution is permitted with attribution.
Modified or derivative versions may not be distributed.
You may not sell, sublicense, or use this project for commercial purposes.
See the full license text in the LICENSE file.
