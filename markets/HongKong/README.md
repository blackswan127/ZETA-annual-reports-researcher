# HKEX Annual Reports — Mass Bulk Downloader

Production-oriented downloader for **annual-report PDFs of currently active HKEX-listed issuers**, designed for large 2017–2025 collection runs.

It uses **HKEXnews directly**. No browser, Selenium, API key, or per-company/year search loop is required.

## Why this architecture is fast

Instead of doing ~2,000 companies × 9 years = ~18,000 metadata searches, it queries HKEXnews's **Annual Report headline category globally**, adaptively splits date ranges only when a response is too large, stores every candidate in SQLite, intersects filing stock codes with HKEX's current active-securities list, then downloads selected PDFs concurrently.

Pipeline:

```text
HKEX current active-securities JSON
                    +
HKEX Annual Report category search (global date shards)
                    ↓
           Current-listed intersection
                    ↓
         Fiscal-year classification
                    ↓
       Best report per issuer / FY
                    ↓
             SQLite manifest
                    ↓
       Concurrent streamed downloads
                    ↓
       .part → %PDF validation → rename
                    ↓
              SHA-256 + audit CSVs
```

## Windows — easiest way

1. Extract the ZIP.
2. Double-click **`install_windows.bat`** once.
3. Double-click **`run_smoke_test.bat`**. It checks Tencent metadata and downloads **no PDF**.
4. Double-click **`run_all_2017_2025.bat`**.

Re-running `run_all_2017_2025.bat` resumes. Validated PDFs are skipped.

## Command line

```bash
python -m venv .venv
# Windows
.venv\Scripts\activate
# macOS/Linux: source .venv/bin/activate
pip install -r requirements.txt

python run.py smoke --stock-code 00700 --smoke-year 2025
python run.py companies
python run.py all --start-year 2017 --end-year 2025 --workers 16 --download-rps 8
```

### Test with only 20 PDFs first

```bash
python run.py all --start-year 2017 --end-year 2025 --limit-reports 20
```

Then run the same command without `--limit-reports` for the full collection.

## Important year behavior

`--start-year 2017 --end-year 2025` means **fiscal/report years**, not merely publication dates.

The downloader intentionally searches into the following year, so FY2025 annual reports published during 2026 can be captured. The default publication-end is today's date.

Fiscal year is primarily extracted from the report title. If a title contains no year, a publication-date heuristic is used and the row is marked `year_confidence=low` in the audit.

## Output

```text
output/
  manifest.sqlite3
  active_securities.csv
  reports.csv
  coverage.csv
  ambiguous_years.csv
  multi_file_candidates.csv
  failed_downloads.csv
  pdf/
    00700_TENCENT/
      2017/
      ...
      2025/
```

`manifest.sqlite3` is the source of truth. Do not delete it when resuming.

## What “currently listed” means here

HKEX's free `activestock_sehk_e.json` is a list of **active securities**, not a clean company master. It includes more than ordinary equity issuers. This project avoids pretending all rows are companies: it first retrieves genuine **Annual Report** filing rows and then keeps only filings whose stock codes are still in the active list. That gives a practical current-listed annual-report issuer universe.

The active-securities row count is not a company count. Use `python run.py companies` for HKEX's latest official month-end Main Board + GEM listed-company total. `all` and `discover` print the same official total and its as-of date alongside the securities count. The company total comes from HKEX's monthly "Report on Initial Public Offering Applications, Delisting and Suspensions"; the downloader's report issuer universe remains the distinct active stock codes that have matching annual-report filings in the requested fiscal years.

It does **not** include delisted issuers. That is intentional for this build.

## Duplicate annual reports

All discovered candidates are retained in SQLite. One primary report is selected per stock code / fiscal year using category/title/year/PDF/file-size evidence. This prevents supplements and unrelated documents from becoming the primary annual report. You can audit the raw candidates directly in SQLite.

## Multi-file filings

Rare HKEX `Multi-Files` wrappers are not silently treated as PDFs. They are logged to `multi_file_candidates.csv` and marked failed for special handling. This protects dataset integrity.

## Rate / concurrency controls

Defaults are deliberately moderate:

- Metadata: `2.5 requests/sec`
- PDF traffic: `8 requests/sec`
- Download workers: `16`

You may tune them:

```bash
python run.py all --workers 24 --download-rps 10 --metadata-rps 2.5
```

Do not use this project to circumvent access controls or overload HKEXnews.

## Recovery

If the PC, Python process, or internet connection stops:

```bash
python run.py all --start-year 2017 --end-year 2025
```

The database resets stale `DOWNLOADING` rows to pending. Existing valid PDFs are SHA-256 checked/registered and skipped.

## Audit / status

```bash
python run.py status
python run.py audit --start-year 2017 --end-year 2025
```

`coverage.csv` flags missing years **after each issuer's first observed report**. It does not automatically call years before the first observed report “missing,” because those can simply be pre-listing years.

## Local tests

```bash
python -m unittest discover -s tests -v
```

The unit suite is network-free. `python run.py smoke ...` is the live HKEX metadata test.

## Source stability note

HKEXnews's title-search servlet is a public website interface but not a formally documented public API. If HKEX changes request parameters or response fields, run the smoke test first and update the adapter rather than weakening validation.
