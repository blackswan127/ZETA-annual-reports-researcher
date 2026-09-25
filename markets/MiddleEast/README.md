# Middle East AR v2

Production-grade architecture for mass FY2017-FY2025 English Annual Report harvesting across the core Middle Eastern equity markets.

## Core markets after live source testing

1. Oman — Muscat Stock Exchange — XMUS
2. Jordan — Amman Stock Exchange — XAMM
3. UAE — Dubai Financial Market — XDFM
4. UAE — Abu Dhabi Securities Exchange — XADS
5. Saudi Arabia — Saudi Exchange — XSAU
6. Qatar — Qatar Stock Exchange — DSMD
7. Bahrain — Bahrain Bourse — XBAH
8. Kuwait — Boursa Kuwait — XKUW

The order above is the recommended engineering rollout, not an investment ranking.

## Critical v2 distinction

A filing called annual financial statements is NOT automatically a full Annual Report.

The pipeline keeps two separate document classes:

- `AR_FULL` — full annual/integrated report containing corporate narrative/governance plus audited financial statements, or explicitly labelled Annual Report.
- `ANNUAL_FS_COMPONENT` — audited annual financial statements / yearly audited financial report only.

Only `AR_FULL` can satisfy a final ZETA `_AR_EN.pdf` slot.

## Shared flow

Current equity universe
→ FY2017-FY2025 expected slots
→ exchange adapter
→ English-language candidate
→ document class (`AR_FULL` vs component)
→ fiscal-year resolver
→ direct-PDF manifest
→ resumable downloader
→ PDF validation + SHA-256
→ ZETA placement
→ coverage audit
→ missing-only repair

## ZETA tree

GLOBAL_SUSTAINABILITY_DATABASE/
└── ISO3/
    └── MIC/
        └── LEI_ISIN_Ticker/
            └── FY2024/
                └── LEI_ISO3_MIC_Ticker_ISIN_FY2024_AR_EN.pdf

Never fabricate LEI/ISIN. Unresolved identity stays in staging.

See `HEAVY_TEST_REPORT.md`, `SOURCE_SCORECARD.csv`, `ARCHITECTURE.md`, and `RUNBOOK.md`.
