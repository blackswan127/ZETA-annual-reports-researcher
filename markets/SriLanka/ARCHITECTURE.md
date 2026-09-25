# Architecture

CURRENT CSE UNIVERSE
→ A-Z company discovery
→ deduplicate share classes (prefer `.N0000`)
→ expected FY2017-FY2025 slots
→ ONE `/api/financials` call per issuer
→ `infoAnnualData`
→ CDN URL normalization
→ fiscal-year resolution
→ SQLite candidate ledger
→ best candidate per issuer/FY
→ concurrent streaming downloads
→ `.part` + HTTP Range resume
→ PDF signature/parser/page validation
→ SHA-256
→ ZETA final path or identity staging
→ coverage / missing / repair queue

States: PENDING, FOUND, DOWNLOADING, DONE, MISSING, FAILED, IDENTITY_MISSING, FY_REVIEW.

Invariants:
- publication date != fiscal year unless independently supported;
- quarterly/other categories cannot satisfy AR;
- no fabricated LEI/ISIN;
- verified PDFs are not silently overwritten;
- reruns are idempotent;
- repeated 403 is a source-access problem, not a signal to brute-force.
