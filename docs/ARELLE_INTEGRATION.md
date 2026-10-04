# Arelle / HMRC disclosure system

`tests/fixtures/real_micro_all_zero.xhtml` is a genuine output of this
codebase's ancestor, run through Arelle (`validate/UK` plugin, disclosure
system `hmrc`) on 2026-09-13, kept from the previous iteration's
`tests/validation/` folder. Its validation log showed three real problems,
all addressed here:

| Arelle message | Fix | Where |
|---|---|---|
| `JFCVC.3312` - `AverageNumberEmployeesDuringPeriod` / `DescriptionPrincipalActivities` missing | Facts added into `ix:hidden`, sourced from directors' input | `app/xbrl/postprocess.py` |
| `JFCVC.3315` - director member has no name | Directors are now required, mapped to `director1..N` in the same order used to name the member | `app/uk_accounts/config_builder.py` |
| `HMRC.SG.3.8` - `<img src="">` for logo/signature | Empty `<img>` elements stripped | `app/xbrl/postprocess.py` |
| `ix11.8.1.2` warning - `ix:header` not visually hidden | `display:none` added to its container | `app/xbrl/postprocess.py` |
| `tinycss2` missing, so `validate/UK` never loaded at all | Added to `requirements.txt` | - |

`tests/unit/test_postprocess_and_reconcile.py` runs the repair against this
exact fixture and was executed with `python -m unittest` while building this
(6/6 passed) - so the repair logic is confirmed against real Arelle-tested
output, not just invented XML.

**What this does not prove:** that a *freshly generated* file (real company
data, through `ixbrl-reporter` end to end) still validates. Arelle itself was
not run in this environment (no network, no Java/taxonomy packages). Before
filing anything real:

```bash
python scripts/bootstrap_upstreams.py
python scripts/preflight.py
# generate a set of accounts through the UI or API, then:
curl -X POST localhost:8000/api/companies/1/validate -d '{"file_id": 1}' -H 'Content-Type: application/json'
```

If Arelle reports something not in the table above, it is new territory:
extend `app/xbrl/postprocess.py` and add a test against the file that
actually failed, the same way this fixture was used.

## Account mapping to the taxonomy

`ixbrl-reporter` finds numbers by matching the "Full Account Name" column in
the CSV against names its jsonnet templates look for. `config/account_paths.json`
holds the prefixes this app generates; `scripts/inspect_mapping.py` lists the
names the actual templates in `sample_data/ixbrl-reporter-jsonnet` reference,
once that checkout exists, so the two can be compared and corrected.

`app/xbrl/reconcile.py` is the safety net for this specific failure mode: it
re-reads the generated iXBRL's `Equity`/`NetAssetsLiabilities`/`FixedAssets`/
`CurrentAssets` facts and compares them to the ledger's own balance sheet. If
the mapping is wrong, generation still succeeds but is flagged
`reconciliation_ok: false` and the filing guard (`app/services/filing_guard.py`)
refuses to submit it. `tests/unit/test_postprocess_and_reconcile.py` confirms
this against the real fixture (a ledger with a nonzero balance is correctly
flagged as a mismatch against the fixture's all-zero accounts).
