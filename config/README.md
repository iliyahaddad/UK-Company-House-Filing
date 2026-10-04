# config/account_paths.json

Maps each internal ledger *category* (fixed_asset, cash, creditor, ...) to the
"Full Account Name" prefix that `ixbrl-reporter` expects in its CSV input, per
the account names its jsonnet templates (in `sample_data/ixbrl-reporter-jsonnet`)
are written against.

If the generated accounts reconcile to zero, or `/validate` reports
`FixedAssets`/`Equity` mismatches, this file is the first thing to check -
run `python scripts/inspect_mapping.py` and compare its output with the values
here.
