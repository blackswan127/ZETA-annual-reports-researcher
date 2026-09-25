# Source contracts

This project uses public SGX endpoints and document pages:

- Mainboard/Catalist issuer profiles: `https://api.sgx.com/corporateinformation/v1.0`
- Current stock counters: `https://api.sgx.com/securities/v1.1/stocks`
- Issuer metadata: `https://api.sgx.com/marketmetadata/v2`
- Financial reports: `https://api.sgx.com/financialreports/v1.0`
- Announcement/report detail: `https://links.sgx.com/1.0.0/corporate-announcements/...`
- PDF attachments: `https://links.sgx.com/1.0.0/corporate-announcements/<announcement>/<file>.pdf`

The general SGX corporate-announcements API is intentionally not required for annual reports. The financial-reports feed is the narrower source designed for annual/interim/quarterly/sustainability report documents.

Corporate Information is the roster source because the securities endpoint represents counters and omits some Mainboard/Catalist issuer profiles. The downloader takes the union of those profiles with active Mainboard/Catalist stock-counter issuers, keyed by SGX IBM code; a roster-only profile uses its IBM code as its identifier and does not get a fabricated ticker. This is an issuer-profile universe (including trusts/funds), distinct from SGX's listed-securities count.

Implementation notes were cross-checked against the MIT-licensed OpenFilings SGX adapter and the archived PySGX project, then implemented independently for the mass-downloader workflow.
