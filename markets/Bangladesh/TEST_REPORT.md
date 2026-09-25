# Test Report — Release 1.0.0

Target: current Dhaka Stock Exchange equity issuers, FY2017-FY2025, ZETA structure `BGD/XDHA`.

## Deterministic suite

**20 / 20 tests passed.**

Covered behaviors:

- DSE current-directory ticker extraction
- DSE issuer-profile parsing
- Equity vs bond/government-security prefiltering
- DSE-provided financial-report archive parsing
- Bangladesh fiscal-year ranges (`2024-25` -> FY2025)
- false-positive rejection (`Annual Return`, quarterly reports)
- CDBL ISIN parsing and conservative company-name matching
- BGD/XDHA ZETA folder/file naming
- source priority (`DSE_AUTHORIZED` > `DSE_FINANCIAL_LINK` > `ISSUER_IR`)
- authorized historical manifest ingestion
- PDF signature and page-count validation
- SHA-256 generation
- incomplete-identity staging
- final ZETA placement with complete LEI + ISIN + ticker
- audit/repair queue generation
- public DSE access acknowledgement gate
- authorized current-universe CSV
- offline authorized end-to-end pipeline
- deterministic multi-PC sharding
- interrupted `.part` HTTP Range resume

## Build gates

- `pytest`: PASS
- `compileall`: PASS
- CLI `--help`: PASS
- wheel build with local build tooling: PASS
- final ZIP cleanliness check: PASS
- final ZIP extraction/retest: PASS (20/20)

## Live source verification

The release environment does not use an unrestricted browser inside the test process. Separately verified live source behavior used to design the adapters:

- DSE `/companies` exposes the current directory.
- DSE `/company/UNITEDFIN` identifies United Finance PLC as `Instrument · Equity`, provides its year-end/website, and publishes the issuer's `Details of Financial Statement` URL.
- The linked United Finance financial-report page exposes Annual Reports 2017 through 2025.
- CDBL publishes a structured `List of ISIN` including security type.

The packaged `run_smoke_test.bat` performs a bounded live DSE + issuer-report check on the user's PC before a corpus run.
