# India Annual Reports Bulk Downloader (NSE + BSE)

Production-oriented, resumable downloader for **annual reports of companies that are currently listed on NSE and/or BSE**, targeting fiscal years ending **2017 through 2025**.

## What it does

1. Downloads the current NSE main-board equity list and (by default) NSE SME list.
2. Queries BSE's active equity-security directory across BSE security groups.
3. Deduplicates NSE/BSE listings primarily by **ISIN**, preserving NSE symbol and BSE scrip code on one issuer record.
4. Creates one expected annual-report slot per current issuer per FY-end year (2017..2025 by default).
5. Uses NSE's dedicated annual-report API as the primary source for NSE-listed issuers.
6. Uses BSE's annual-report page as the primary source for BSE-only issuers and as a fallback for missing NSE slots.
7. Optionally enables a slower BSE announcement fallback for unresolved BSE slots.
8. Selects one best candidate per issuer/FY while preserving all candidates in SQLite for audit.
9. Streams PDFs/ZIPs with retry/backoff and `.part` resume support.
10. Extracts historical NSE ZIP filings safely; when an archive contains multiple PDFs, it keeps all parts and selects the largest valid PDF as the primary artifact while flagging the archive in audit output.
11. Validates `%PDF-`, hashes completed PDFs with SHA-256, checkpoints in SQLite, and produces CSV coverage/audit files.

## Important: what “2017–2025” means

This project uses the **fiscal-year end**, matching NSE's `toYr` field. Thus:

- FY 2016-17 -> `2017`
- FY 2024-25 -> `2025`

This is more reliable for India than using publication year alone.

## Current listed-company counts

Do **not** add NSE and BSE headline counts together because many companies are dual-listed.

- NSE's May 2026 corporate presentation reports **2,979 total companies listed as of 31 March 2026**.
- The latest official BSE market-statistics snapshot indexed during project construction (4 Nov 2025, 16:00) showed **5,032 companies with listed equity capital**, of which 4,514 were available for trade and 518 suspended. This is a dated snapshot, not claimed as the Sep 2026 live count.

The downloader therefore queries both exchange universes at run time and writes the current values to:

`output/audit/universe_summary.csv`

It reports:

- `nse_raw`
- `bse_raw`
- `dual_listed`
- `nse_only`
- `bse_only`
- `deduped`

The deduplicated number is the useful “current Indian issuer universe” for this project.

## Access / terms requirement

NSE's Terms of Use restrict automated/systematic collection, scraping, extraction and aggregation without appropriate permission. BSE also places restrictions on reproduction/redistribution of exchange information. **Use this software only where your intended use is authorized.**

The project intentionally refuses live network access unless:

```text
INDIA_AR_ACKNOWLEDGE_TERMS=1
```

is set. Windows launchers ask for explicit acknowledgement. The code does **not** bypass CAPTCHA, login, paywalls, bot challenges, authentication or other access controls.

## Windows — easiest route

Extract the ZIP. Then:

1. Run `install_windows.bat`
2. Run `run_smoke_test.bat`
3. If smoke passes, run `run_all_2017_2025.bat`

For higher authorized throughput after the normal run is stable, use `run_fast_2017_2025.bat`.

## Manual install

```powershell
py -m venv .venv
.venv\Scripts\python -m pip install --upgrade pip
.venv\Scripts\python -m pip install -e ".[dev]"
```

Then:

```powershell
$env:INDIA_AR_ACKNOWLEDGE_TERMS="1"
.venv\Scripts\india-ar smoke --nse-symbol RELIANCE --year 2025
.venv\Scripts\india-ar --output output --start-year 2017 --end-year 2025 run
```

## Recommended production run

```powershell
india-ar --output output --start-year 2017 --end-year 2025 \
  --metadata-workers 6 --nse-rps 1.5 --bse-rps 2.5 \
  --download-workers 8 --download-rps 4 run
```

### Deep BSE fallback

BSE's secondary announcement search is deliberately **off by default** because it is slower and creates substantially more metadata traffic. Run it only if the normal audit still contains BSE-only missing slots:

```powershell
india-ar --output output --start-year 2017 --end-year 2025 --deep-bse-fallback discover
india-ar --output output --start-year 2017 --end-year 2025 download
india-ar --output output --start-year 2017 --end-year 2025 audit
```

## Multiple machines / shards

Issuer assignment is deterministic. Four independent machines can use:

```text
PC 1: --shard-count 4 --shard-index 0
PC 2: --shard-count 4 --shard-index 1
PC 3: --shard-count 4 --shard-index 2
PC 4: --shard-count 4 --shard-index 3
```

Give each shard a separate output directory. Merge the resulting corpora/CSVs later; do not point multiple machines at the same SQLite file over a network share.

## Output

```text
output/
├── manifest.sqlite3
├── pdfs/
│   └── <ISIN-or-code>_<company>/
│       ├── 2017/<...>_2017_Annual_Report.pdf
│       ├── ...
│       └── 2025/<...>_2025_Annual_Report.pdf
└── audit/
    ├── issuers.csv
    ├── universe_summary.csv
    ├── candidates.csv
    ├── coverage.csv
    ├── missing.csv
    ├── multiple_candidates.csv
    ├── failed_downloads.csv
    ├── multi_file_archives.csv
    └── source_counts.csv
```

## Source priority

For each company/FY:

1. NSE dedicated annual-report API
2. BSE annual-report page
3. BSE announcement fallback (when explicitly enabled)

All candidates remain in SQLite. Selection can therefore be audited/re-run without re-downloading metadata.

## Resume semantics

- Completed PDFs are skipped on rerun.
- Interrupted transfers remain as `.part` files.
- Servers supporting HTTP Range resume from the partial byte offset.
- Servers ignoring Range are restarted safely from byte zero.
- `429` and transient `5xx` responses use exponential backoff.
- A slot is `DONE` only after a valid PDF is on disk.

## Why ZIP support is necessary

The current NSE annual-report API returns direct PDFs for many recent filings, but some older annual reports are exposed as ZIP archives. The downloader handles both formats and keeps multi-PDF archive contents for audit rather than silently discarding pieces.

## Commands

```text
india-ar universe
india-ar discover [--force]
india-ar download [--limit N]
india-ar audit
india-ar smoke --nse-symbol RELIANCE --year 2025
india-ar run
```

## Testing

Run:

```powershell
.venv\Scripts\python -m pytest -q
```

See `TEST_REPORT.md` for the deterministic test matrix and live-verification limitations.
