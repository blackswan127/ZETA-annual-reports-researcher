# AGENTS.md — NZX ZETA Harvester

Read `START_HERE.txt`, `README.md`, `ARCHITECTURE.md`, `SELF_IMPROVEMENT_PROTOCOL.md`, and `SOURCES.md` before modifying collection logic.

## Mission

Maximize verified FY2017-FY2025 Annual Report coverage for the **current NZX equity issuer universe** while preserving ZETA naming/identity rules, provenance, resumability and source-access constraints.

## Non-negotiable rules

- Country = `NZL`; exchange MIC = `XNZE`.
- Final structure is `ROOT/NZL/XNZE/LEI_ISIN_Ticker/FYyyyy/PDF`.
- Final annual-report filename is `LEI_NZL_XNZE_Ticker_ISIN_FYyyyy_AR_EN.pdf`.
- Fiscal year means report period, not publication year.
- Missing identifiers go to staging; do not fabricate.
- Preserve source URL/path, source type and candidate metadata.
- A downloaded file is not `DONE` until PDF validation passes.
- Add a regression test before fixing a discovered recurring failure.
- Do not add browser/CAPTCHA/login bypasses.
- Do not turn a source-specific patch into a hard-coded company exception unless no general rule is possible.

## Priority order for repair

1. authorized NZX bulk/export source
2. NZX company Documents pages
3. authorized ANNREP records/attachments
4. issuer investor-relations archive
5. manual queue with recorded root cause

## Definition of production-ready change

Test added → fix generalized → all tests pass → bounded smoke test documented → source profile updated → audit remains reproducible.
