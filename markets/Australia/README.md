# ASX Annual Reports Bulk Downloader

Production-oriented, resumable downloader for annual reports of **currently listed ASX companies**, targeting fiscal years **2017–2025** by default.

## Important ASX terms

ASX's public announcement access page states that company announcements are freely available for private/personal use and that commercial use requires ASX's express written authority. This project therefore refuses ASX network access until `ASX_ACKNOWLEDGE_TERMS=1` is explicitly set. The Windows launchers ask you to acknowledge this before each network run. The software does not bypass login, paywalls, authentication, CAPTCHAs, or other access controls.

Code in this repository can be used under the included MIT license. ASX data/documents remain subject to ASX's own rights and terms.

## Why this architecture

The modern ASX per-company JSON announcement feed is useful for recent notices but is hard-capped at the latest few announcements. It is therefore unsuitable for 2017–2025 history. This project uses ASX's official historical announcement search by company and publication year, then downloads only annual-report candidates.

Pipeline:

1. Load current ASX company universe from the current ASX front-end directory.
2. Fall back to the official `ASXListedCompanies.csv` if needed.
3. Scan each current ticker's official historical announcement pages for publication years 2017–2026. The extra year captures FY2025 annual reports published in early 2026.
4. Classify annual-report candidates while rejecting half-year, quarterly, ESG/sustainability, corporate-governance, AGM and dispatch-only notices.
5. Infer fiscal year from `FY25`, `2025`, etc.; use a conservative publication-date heuristic when the title contains no year and flag those rows for audit.
6. Pick the strongest candidate per company/fiscal-year slot.
7. Resolve the underlying official ASX PDF target only for selected reports.
8. Stream PDFs concurrently into `.part` files, resume with HTTP Range when supported, validate `%PDF-`, atomically rename on success, hash with SHA-256, and checkpoint in SQLite.
9. Export coverage and exception CSVs.

## Windows quick start

1. Extract the ZIP.
2. Double-click `install_windows.bat`.
3. Double-click `run_smoke_test.bat` and type `YES` only after reviewing/confirming your ASX usage rights.
4. If the smoke test passes, double-click `run_all_2017_2025.bat`.

For a more aggressive but still backoff-aware run, use `run_fast_2017_2025.bat` only after the normal mode is stable.

## CLI

```bat
set ASX_ACKNOWLEDGE_TERMS=1
asx-bulk smoke --ticker BHP --year 2025
asx-bulk --start-year 2017 --end-year 2025 universe
asx-bulk --start-year 2017 --end-year 2025 discover
asx-bulk --start-year 2017 --end-year 2025 download
asx-bulk --start-year 2017 --end-year 2025 audit
asx-bulk --start-year 2017 --end-year 2025 run
```

Target only selected tickers during discovery:

```bat
asx-bulk --start-year 2017 --end-year 2025 discover --ticker BHP --ticker CBA
```

Download only the first 10 pending reports (useful for testing):

```bat
asx-bulk --start-year 2017 --end-year 2025 download --limit 10
```

## Output

```text
output/
  manifest.sqlite3
  pdfs/
    BHP_BHP GROUP LIMITED/
      2017/BHP_2017_Annual_Report.pdf
      ...
      2025/BHP_2025_Annual_Report.pdf
  audit/
    issuers.csv
    filings.csv
    coverage.csv
    missing.csv
    multiple_candidates.csv
    heuristic_years.csv
    failed_downloads.csv
```

## Resume behaviour

Re-run the same command after a crash or network failure. Completed metadata scans are skipped, completed PDFs are skipped, and partial PDFs remain as `.part` files for Range-based resume where the origin supports it.

## Classification notes

Titles such as these score strongly:

- `2025 Annual Report`
- `FY25 Annual Report and Financial Statements`
- `Annual Report for Year Ended 2025`
- `Appendix 4E and Annual Report for Year Ended 30 June 2024`
- `Annual Report to Shareholders`

These are rejected as false positives:

- sustainability / ESG reports
- half-year / Appendix 4D reports
- quarterly reports
- Appendix 4G / corporate governance
- AGM notices
- `Release and dispatch of ... Annual Report`
- annual-report supplementary information

`audit/heuristic_years.csv` lists reports whose fiscal year was inferred from publication timing because no explicit year was present in the title. Review these before treating a corpus as final.

## Scale

The current company universe is obtained live at runtime, so the project does not hard-code a company count. A recent independent live check of ASX's current front-end directory returned about 1,840 companies; that count will change with listings/delistings. Nine fiscal years therefore represent roughly 16,500 possible company-year slots before accounting for companies listed after 2017 and missing years.

Historical discovery is the expensive phase because the public historical interface is company/year oriented. The SQLite `scan_state` table makes it fully resumable.

### Deterministic sharding

For multiple PCs or isolated jobs, split the ticker universe deterministically. Give each shard its own output directory:

```bat
asx-bulk --output output_shard0 --shard-count 4 --shard-index 0 --start-year 2017 --end-year 2025 run
asx-bulk --output output_shard1 --shard-count 4 --shard-index 1 --start-year 2017 --end-year 2025 run
```

Use shard indexes `0..N-1`. Do not point simultaneous machines at the same SQLite file.

## Tests

```bash
python -m pip install -e .[dev]
pytest -q
```

The offline suite covers classification, year inference, historical-page parsing, PDF target extraction, SQLite candidate selection/audits, filename safety, PDF streaming/resume, and rejection of HTML in place of a PDF.
