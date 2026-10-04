# Testing

The application test suite validates the application-side accounting, HTTP,
security, XBRL generation plumbing, mapping and filing-state logic without
requiring live Companies House credentials or a live filing submission.

Run:

```bash
python -m venv .venv
source .venv/bin/activate
pip install -r requirements.txt
python -m pytest -q
python -m compileall -q app scripts tests
```

## Verified release result

The release tree used for this archive was executed with:

```text
python -m pytest -q
112 passed

python -m compileall -q app scripts tests
PASS
```

The archive was then cleaned of runtime database files, `__pycache__` directories
and `.pytest_cache` before packaging.

## Intentionally unverified live operations

These are not part of the automated release test because they require real
external runtime/data/credentials:

- Arelle validation against the installed UK disclosure system and real company
  data.
- Companies House Software Filing submission against the gateway using real
  credentials.

Those operational checks should be performed by the operator before an actual
filing.
