# Dhaka Stock Exchange — ZETA Annual Reports Bulk Downloader

Production-oriented harvester for **current DSE-listed equity issuers** and **FY2017–FY2025 annual reports**, aligned to the ZETA-AI folder/file SOP.

## What it does

1. Loads the current DSE security directory.
2. Opens each DSE profile and keeps only `Instrument · Equity` issuers.
3. Captures the issuer website, DSE-provided `Details of Financial Statement` URL, fiscal-year end, board/status metadata.
4. Enriches ISIN from the official CDBL ISIN list using conservative normalized-name matching.
5. Optionally enriches LEI through exact-name GLEIF matching (`--gleif`). No LEI is invented.
6. Creates expected slots for FY2017..FY2025.
7. Ingests an optional authorized historical manifest first.
8. Crawls the DSE-provided issuer financial-report URL for Annual Reports.
9. Uses the issuer website as a repair source for still-missing years.
10. Selects the best source per company/year, downloads concurrently and resumes `.part` files with HTTP Range.
11. Validates PDFs, hashes them with SHA-256, and writes final files only when LEI+ISIN+ticker are complete.
12. Exports coverage, missing, repair and identity queues.

## ZETA final structure

```text
GLOBAL_SUSTAINABILITY_DATABASE/
└── BGD/
    └── XDHA/
        └── LEI_ISIN_Ticker/
            └── FY2025/
                └── LEI_BGD_XDHA_Ticker_ISIN_FY2025_AR_EN.pdf
```

Reports found before identity is complete are preserved under:

```text
work/staging/unresolved_identity/TICKER/FYyyyy/
```

They are not silently placed into the final ZETA tree with fake identifiers.

## Windows quick start

1. Extract the ZIP to D: or E: (not your Desktop/C: for a large corpus).
2. Run `install_windows.bat`.
3. Run `run_smoke_test.bat`.
4. Run `run_all_2017_2025.bat`.
5. Review `work/audit/coverage.csv` and `work/audit/repair_queue.csv`.
6. Run `run_repair_missing.bat` after adding missing identity overrides or new source URLs.

Use `run_fast_2017_2025.bat` only after the normal mode is stable on your network and your access is authorized.

## CLI examples

```bat
set DSE_ACKNOWLEDGE_TERMS=1
dse-zeta --work work --zeta-root "E:\GLOBAL_SUSTAINABILITY_DATABASE" universe --gleif
dse-zeta --work work --zeta-root "E:\GLOBAL_SUSTAINABILITY_DATABASE" discover-dse-links
dse-zeta --work work --zeta-root "E:\GLOBAL_SUSTAINABILITY_DATABASE" discover-ir
dse-zeta --work work --zeta-root "E:\GLOBAL_SUSTAINABILITY_DATABASE" download
dse-zeta --work work --zeta-root "E:\GLOBAL_SUSTAINABILITY_DATABASE" audit
```

For an authorized/offline universe:

```bat
dse-zeta --work work --zeta-root "E:\GLOBAL_SUSTAINABILITY_DATABASE" universe --universe-csv templates\current_universe.csv
```

For a licensed or manually verified historical manifest:

```bat
dse-zeta --work work --zeta-root "E:\GLOBAL_SUSTAINABILITY_DATABASE" ingest-authorized templates\authorized_dse_manifest.csv
```

## Source priority

| Priority | Source | Purpose |
|---:|---|---|
| 100 | `DSE_AUTHORIZED` | Licensed/manual verified historical manifest or local PDFs |
| 92 | `DSE_FINANCIAL_LINK` | Annual reports on the official financial-statement URL published on the DSE issuer profile |
| 75 | `ISSUER_IR` | Official company investor/financial-report pages used for repair |

## Current-universe logic

DSE's current directory can contain securities other than ordinary equities. The project therefore does **not** accept the raw directory count as the company count. It opens each `/company/<ticker>` profile and keeps profiles whose instrument is Equity. Funds, bonds, debt and government securities are rejected.

The exact filtered current-equity count for your run is written to:

```text
work/audit/universe_summary.csv
work/audit/issuers.csv
```

## Fiscal-year rule

ZETA uses the reporting fiscal year, not publication year. Bangladesh reports commonly use ranges:

- `Annual Report 2024-25` -> FY2025
- `Annual Report 2023-2024` -> FY2024
- `Annual Report 2022` -> FY2022

## Identity policy

- ISIN: official CDBL list first, then `identity_overrides.csv`.
- LEI: exact GLEIF match when explicitly enabled, then overrides.
- No guessed LEI/ISIN.
- Incomplete identities remain in staging.

## Audit files

`work/audit/` contains:

- `universe_summary.csv`
- `issuers.csv`
- `coverage.csv`
- `candidates.csv`
- `missing.csv`
- `repair_queue.csv`
- `identity_missing.csv`
- `source_profiles.csv`

## Multi-PC sharding

The universe command/run supports deterministic `--shard-count N --shard-index I`. A ticker belongs to exactly one shard.

## Access / responsible use

The project does not bypass authentication, CAPTCHA, paywalls or access controls. Public-site network access is disabled until `DSE_ACKNOWLEDGE_TERMS=1` is explicitly set. For large commercial use, verify DSE/CDBL permissions and use authorized data/export sources where required.
