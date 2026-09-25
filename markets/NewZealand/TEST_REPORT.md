# Test Report — v1.0.0

Release date: 2026-09-25

## Deterministic suite

**19 / 19 PASSED**

Coverage includes:

- current NZSX market-page parsing
- NZX company profile / ordinary-share ISIN parsing
- equity-vs-fund filtering
- direct Documents-page annual-report discovery
- `ANNREP` announcement parsing
- false-positive rejection for interim/AGM/presentation material
- `FY25` and `FY2025` fiscal-year inference
- exact `NZL/XNZE` ZETA naming
- identity completeness/quarantine
- SQLite expected slots and source priority
- authorized historical manifest ingestion
- local licensed-PDF ingestion
- PDF signature/parser/page validation
- SHA-256
- audit/repair queue generation
- explicit NZX public-site terms gate
- authorized current-universe CSV ingestion
- complete offline authorized-source → download → final ZETA placement flow
- deterministic/disjoint ticker sharding

## Release gates

- Python `compileall`: PASS
- CLI `--help`: PASS
- wheel build with local installed build tools: PASS
- no live NZX crawling required by deterministic tests

## Live validation status

The build environment does not guarantee direct outbound DNS/network access. The packaged `run_smoke_test.bat` performs a bounded live check on the user's PC against NZX Limited: it verifies the ordinary-share ISIN and discovers the FY2025 Annual Report from the company Documents page before a corpus run.
