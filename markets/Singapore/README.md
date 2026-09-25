# SGX Current-Listed Annual Reports Bulk Downloader

Production-oriented downloader for **current SGX Mainboard and Catalist stock issuers**, targeting annual-report fiscal years **2017–2025** by default.

## What it does

1. Loads Mainboard/Catalist issuer profiles from SGX's public Corporate Information API, including REITs, business trusts, and listed funds that are not represented in the ordinary stock-counter feed.
2. Joins that roster to SGX's live `securities/v1.1/stocks` feed and `marketmetadata/v2`, preferring a live counter and using SGX metadata as the identifier fallback. Profiles outside Mainboard/Catalist are excluded.
3. Scans the keyless SGX `financialreports/v1.0` feed in pages and keeps only `title == Annual Report` with period years in your requested range.
4. Maps those filings to the current Mainboard/Catalist universe.
5. Runs targeted per-company recovery for issuers that still have uncovered years.
6. Opens each SGX report-detail page and selects annual-report PDF attachments while rejecting sustainability reports, AGM notices, proxy forms, appendices, etc.
7. Streams PDFs concurrently to `.part`, resumes when the server honors `Range`, validates `%PDF-`, hashes SHA-256, and atomically renames completed files.
8. Stores every state in SQLite so reruns skip completed work.
9. Writes coverage, failures, unmapped reports, and multi-file candidates to CSV.

## Windows quick start

Extract the ZIP, then run in this order:

```text
install_windows.bat
run_smoke_test.bat
run_all_2017_2025.bat
```

Use `run_fast_2017_2025.bat` only after the normal run is stable on your connection. The downloader respects `429 Retry-After`; it does not attempt to bypass SGX controls.

## Command line

```bash
python -m sgx_bulk smoke
python -m sgx_bulk run --start-year 2017 --end-year 2025 --output output
python -m sgx_bulk discover --start-year 2017 --end-year 2025
python -m sgx_bulk download --output output
python -m sgx_bulk audit --start-year 2017 --end-year 2025 --output output
```

Tuning:

```bash
python -m sgx_bulk run --start-year 2017 --end-year 2025 \
  --discovery-workers 6 --detail-workers 8 --download-workers 6
```

## Output

```text
output/
├── manifest.sqlite3
├── pdfs/
│   └── S68_SINGAPORE EXCHANGE LIMITED/
│       └── 2025/
│           └── 859054_2025_SGX_Annual_Report.pdf
└── audit/
    ├── issuers.csv
    ├── filings.csv
    ├── downloads.csv
    ├── coverage.csv
    ├── failed_downloads.csv
    ├── unmapped_annual_reports.csv
    └── multiple_annual_candidates.csv
```

## Important coverage semantics

`coverage.csv` creates a row for every **current issuer × requested year**. `NO_FILING_FOUND` is not automatically an error: a company may have listed after that fiscal year, changed name, merged, or not have a qualifying SGX annual-report record for that period. Use the CSV as an audit queue, not as a claim that every current issuer existed in every historical year.

The project targets issuer profiles whose SGX Corporate Information entry identifies them as Mainboard or Catalist. This includes stock companies, REITs, business trusts, and listed funds, and may include an issuer with no live stock counter. It does not attempt to build the historical universe of delisted issuers. Because SGX exposes separate issuer and security counts, the roster count should not be compared directly with a listed-securities total. Review the generated `audit/issuers.csv` as the auditable roster for each discovery run.

## Recovery and resume

Re-run the same command after any interruption. SQLite retains discovered filings and attachment states. Finished PDFs are validated and skipped. Partial files use `.part` and are resumed when the SGX document host supports HTTP Range.

## Why this is faster than naive company-year loops

The first pass scans the shared SGX financial-report feed by page. It then asks per-company only for issuers where the global pass did not give complete requested-year coverage. This avoids thousands of unnecessary search requests while retaining a targeted fallback.

## Tests

```bash
python -m pip install -e .[dev]
pytest
```

See `TEST_REPORT.md` for the packaged test result and live-contract checks.
