local l = import "lib/frs102.libsonnet";

local elts = {
    "element": "frs102",
    "accounting_standards": "micro-entities",
    "accounts_status": "audit-exempt-no-accountants-report",
    "accounts_type": "abridged-accounts",
    "title": "Dormant Company Accounts",
    "accounts_file": "PLACEHOLDER",
    "accounts_kind": "csv",
    "elements": [
        {
            "element": "composite",
            "id": "report",
            "elements": [
                {
                    "element": "title-page"
                },
                {
                    "element": "company-info"
                },
                {
                    "element": "balance-sheet-unaudited-micro",
                    "signature": "signature"
                },
                {
                    "element": "notes"
                }
            ]
        }
    ]
};

local accts = {
    metadata: {
        "business": {
            "company-name": "PLACEHOLDER",
            "company-number": "PLACEHOLDER",
            "entity-scheme": "http://www.companieshouse.gov.uk/",
            "is-dormant": true,
            "sic-codes": [],
            "jurisdiction": "England and Wales",
            "industry-sector": "m",
            "company-formation": {
                "country": "england-and-wales",
                "date": "2024-01-01",
                "form": "private-limited-company"
            },
            "contact": {
                "name": "Corporate Enquiries",
                "email": "",
                "country": "UK",
                "phone": {
                    "type": "landline"
                }
            }
        },
        "directors": {
            "report-date": "PLACEHOLDER"
        },
        "accounting": {
            "authorised-date": "PLACEHOLDER",
            "balance-sheet-date": "PLACEHOLDER",
            "currency": "GBP",
            "decimals": 0,
            "scale": 0,
            "currency-label": "£",
            "date": "PLACEHOLDER",
            "periods": [
                {
                    "name": "PLACEHOLDER",
                    "start": "PLACEHOLDER",
                    "end": "PLACEHOLDER"
                },
                {
                    "name": "PLACEHOLDER",
                    "start": "PLACEHOLDER",
                    "end": "PLACEHOLDER"
                }
            ],
            "signed-by": "Director",
            "signing-officer": "director1",
            "directors-report-signed-by": "Director",
            "directors-report-signing-officer": "director1"
        }
    },
    accounts:: l.from_element_def(elts, self).with_metadata(self.metadata),
    resource(x):: ""
};

accts.accounts
