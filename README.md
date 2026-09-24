# US and UK annual and sustainability report harvester

For agent-run work, start with [AGENTS.md](AGENTS.md). It gives the exact workflow for English-language requests and the accuracy-gated speed experiment. A local benchmark can be started with `py benchmarks/optimize.py fixture`; real-source experiments require a reviewed `golden.csv` with `relative_path,sha256,pages` and `py benchmarks/optimize.py real --manifest sample.csv --golden golden.csv --repeats 2`. The script logs trials and promotes a faster setting only after all checks pass.

A local, resumable discovery and PDF ingestion system for US and UK annual reports, fiscal years 2017–2025. It follows the supplied **Phase-1 SOP: Folder & PDF File Naming Standard** and uses the two authoritative sources specified in `AR sources.txt`: SEC EDGAR and FCA NSM.

## Autonomous Agentic Two-Tier Pipeline & Permanent Google Drive Storage

This repository is built for **autonomous AI agent execution across the wide stock universe** (spanning ~9,548 US issuers, ~3,191 UK issuers, and global dual-listed issuers). Whenever a user requests a cohort, exchange, or country folder, the agent executes the full pipeline end-to-end without manual CLI intervention:

1. **Permanent Direct-to-Google-Drive Storage (`GLOBAL_SUSTAINABILITY_DATABASE`)**:
   - All final validated PDFs are permanently stored inside `GLOBAL_SUSTAINABILITY_DATABASE` (`C:\Users\CGS_Computer\Videos\annaual reportsssssss\GLOBAL_SUSTAINABILITY_DATABASE`), which is a Windows NTFS Directory Junction (`mklink /J`) pointing directly to **`G:\My Drive\GLOBAL_SUSTAINABILITY_DATABASE`** on Google Drive.
   - To create the junction on a new machine:
     ```cmd
     cmd /c mklink /J "GLOBAL_SUSTAINABILITY_DATABASE" "G:\My Drive\GLOBAL_SUSTAINABILITY_DATABASE"
     ```
   - Keep `--state local/harvest.sqlite3` and `cache/` on local SSD for lock safety and zero cloud lock contention while `--output-root GLOBAL_SUSTAINABILITY_DATABASE` streams all verified PDFs straight to Google Drive.
2. **Wide Universe Identifier Resolution**:
   - Dynamically exclude already-harvested companies in `local/harvest.sqlite3` (`SELECT cik, lei FROM companies`) and resolve exact 20-character ISO 17442 `LEI`, 12-character ISO 6166 `ISIN`, `CIK`, `ticker`, and 4-character `MIC` (`XNAS`, `XNYS`, `XLON`) using the SEC active issuer roster (`https://www.sec.gov/files/company_tickers_exchange.json`), Wikidata datasets (`local/wikidata_dump.json`, `local/wikidata_us_dump.json`, `local/wikidata_nasdaq_nyse_dump.json`), the **GLEIF Golden Copy API** (`https://api.gleif.org/api/v1/lei-records/{lei}/isins`), and the **OpenFIGI API** (`POST https://api.openfigi.com/v3/mapping`).
3. **Two-Tier High-Throughput Statutory Engine (`ar-harvest harvest-batch <universe.csv>`)**:
   - **Priority 1 (US Companies & Dual-Listed Global/UK Issuers with SEC CIKs)**:
     - **Method #1 (Direct Graphic PDF Passthrough)**: Concurrent download of official `Form ARS` PDFs (`16 workers`, `8 per_host`).
     - **Method #2 (Self-Healing Headless Chromium Layout)**: Automatic fallback rendering of remaining `Form 10-K` and `Form 20-F` HTML filings via `render-sec` (`6 render workers` across `3 browser processes`, `90.0s` `page.pdf()` timeout guard, automatic `docs_handled = 999` + `make_context()` self-healing tab recovery, and immediate `cache_path.unlink(missing_ok=True)` cache pruning).
   - **Priority 2 (UK Domestic Issuers beyond FTSE 100 without SEC CIKs)**:
     - Sourced via the **UK FCA National Storage Mechanism (NSM)** (`import-fca-csv`, `import-fca-map`, `render-fca`).
   - **Deprecated Last Resort (`AnnualReports.com`)**: Never use `AnnualReports.com` as a primary source; see the deprecated section at the bottom of this file for authorized fallback usage when explicitly requested.

## Current scope

- Countries: `USA` and `GBR`.
- Input: a company-level identity roster containing LEI, ISIN, exchange and ticker, plus CIK for US companies. `AR sources.txt` and `SR sources.txt` are execution guides. The supplied country workbook has aggregate counts, not the individual companies. `file naming.txt` is empty.
- US discovery: cached SEC bulk submissions ZIP, followed by only the historical submission JSON files needed for missing fiscal years. The SEC's `reportDate` determines the fiscal year; amendments stay separate.
- UK discovery: import the CSV exported by the FCA NSM search interface, join by LEI, and leave ambiguous fiscal years for review. PDF, XHTML and ZIP originals are handled separately.
- PDF acquisition: reviewed direct PDF links download concurrently. Official SEC HTML filings can be saved and locally rendered to PDF with a separate Chromium pool; the ledger records that conversion.
- Output: PDF only, complete English reports, using the SOP's exact path and filename:

  `GLOBAL_SUSTAINABILITY_DATABASE/GBR/XLON/2138007ZFQYRUSLU3J98_GB00BHJYC057_IHG/FY2024/2138007ZFQYRUSLU3J98_GBR_XLON_IHG_GB00BHJYC057_FY2024_AR_EN.pdf`

The source catalog must identify the **fiscal year**, not publication year. `verified=true` in an imported PDF manifest means a person or trusted upstream process confirmed the identifiers, period, report type and complete English content. The downloader checks PDF structure and location; arbitrary PDF content can still need human review.

The supplied self-improvement checklist mentions a `CATEGORY` subfolder, and `AR sources.txt` proposes `US_AAPL_2024_AR.html`. The updated V2 folder-and-file SOP explicitly requires the LEI/ISIN path and PDF name shown above. This repository follows the updated V2 SOP for every final PDF. Original SEC HTML is retained separately under `cache/`, not mislabeled as a source PDF.

## Setup

Python 3.11+:

```powershell
py -m venv .venv
.venv\Scripts\python -m pip install -e ".[test,render]"
```

The `render` extra is needed for SEC HTML conversion. On Windows, the CLI detects installed Chrome or Edge. On other systems, pass `--chrome` or install a Playwright Chromium browser.

## Company universe and discovery

Copy `examples/universe.csv` and add one listing per row. Its columns are `country,company_name,exchange,lei,isin,ticker,cik,aliases`. Use `USA` and `GBR`, the four-character exchange MIC, and the exact LEI/ISIN/ticker supplied by your data source. US rows require a numeric SEC CIK. `aliases` is optional text; leave it blank when unavailable.

```powershell
$env:SEC_USER_AGENT = "Your Organization research@example.org"
ar-harvest load-universe companies.csv --years 2017:2025 --state harvest.sqlite3
ar-harvest discover-us --state harvest.sqlite3
ar-harvest import-fca-csv fca-nsm-export.csv --state harvest.sqlite3
ar-harvest import-fca-map cache/fca/mapping.zip --state harvest.sqlite3
ar-harvest status --state harvest.sqlite3
ar-harvest export-manifest --state harvest.sqlite3
```

`discover-us` downloads the SEC bulk ZIP once to `cache/sec/submissions.zip`, reuses a fresh cached copy, and fetches only referenced history files for missing years. For offline testing, use `--bulk-zip path/to/submissions.zip --no-history`. Every SEC network request needs `SEC_USER_AGENT` with a real contact address. [SEC bulk API documentation](https://www.sec.gov/search-filings/edgar-application-programming-interfaces).

Export UK NSM search results as CSV from the [FCA search interface](https://www.fca.org.uk/markets/primary-markets/regulatory-disclosures/national-storage-mechanism); the current [investor guide](https://www.fca.org.uk/publication/primary-market/nsm-investor-user-guide.pdf) says the export includes a document download link and permits up to 4,000 rows per export. Import multiple date/LEI shards by repeating `import-fca-csv`. The older NSM search API named in `AR sources.txt` returned `Invalid index` in a live check, and the FCA's [current FAQ](https://data.fca.org.uk/artefacts/PUBLISHING_HUB_FAQs_v0.1.pdf) says direct programmatic NSM access is not permitted. This repository uses the CSV export route.

For historic Morningstar NSM links, download the [FCA migration mapping ZIP](https://data.fca.org.uk/artefacts/NSM/data-migration/MS_to_FCA_NSM_Document_URL_Mapping.zip) to `cache/fca/mapping.zip` and run `import-fca-map`. The default streams the 2017–2020 CSVs and stores only mappings needed by your candidate catalog; `--all` stores every mapping and needs much more disk space.

### UK statutory accounts discovery via Companies House (2020–2025)

To fill missing UK company-years (especially 2020–2025 where FCA NSM migration archives cut off), discover official statutory accounts from Companies House:

```powershell
$env:COMPANIES_HOUSE_API_KEY = "your_ch_api_key"
# 1. Multi-factor company matching (validates legal name, CRN, PLC vs Ltd, active status)
ar-harvest ch-match --state local/harvest.sqlite3

# 2. Statutory accounts discovery (extracts period-end FY, filters dormant/micro/abbreviated/filleted)
ar-harvest ch-discover --years 2017:2025 --state local/harvest.sqlite3 --output-root "GLOBAL_SUSTAINABILITY_DATABASE"

# 3. Export review audit log for unconfirmed subtypes, name collisions, or amended filings
ar-harvest ch-review --state local/harvest.sqlite3 --output ch-review.csv

# 4. Export direct PDF manifest for missing slots only (never overwriting existing canonical PDFs)
ar-harvest ch-export-manifest --years 2017:2025 --state local/harvest.sqlite3 --output-root "GLOBAL_SUSTAINABILITY_DATABASE" --output ch-direct.csv

# 5. Execute rate-gated concurrent transfer into Google Drive
ar-harvest run ch-direct.csv --state local/harvest.sqlite3 --output-root "GLOBAL_SUSTAINABILITY_DATABASE" --workers 8 --per-host 2
```

All Companies House API and document requests share a persisted rolling rate gate (maximum 600 requests per 5 minutes) tracked in SQLite `ch_rate_budget`. Basic auth credentials are sent strictly to official Companies House API hosts and automatically stripped when following redirects to external S3 storage.


SEC HTML filings are discovered but omitted from the direct-PDF manifest. Render those separately:

```powershell
ar-harvest render-sec --state harvest.sqlite3 --output-root "GLOBAL_SUSTAINABILITY_DATABASE"
ar-harvest render-fca --state harvest.sqlite3 --output-root "GLOBAL_SUSTAINABILITY_DATABASE"
```

`render-sec` downloads official SEC HTML with the SEC request limit, keeps the original source in `cache/sec/html/` during rendering (and automatically unlinks cached HTML upon commit), and produces a local PDF in the SOP path. `render-fca` preserves each FCA original in `cache/fca/originals/`; it passes through genuine PDFs and renders HTML/XHTML or a ZIP package's largest report page. Its FCA network concurrency starts at 4 and decreases on 429/503 responses. Both renderers block external page resources, so inspect a sample of converted reports for layout and missing images. Conversion provenance is kept in SQLite. Records with unresolved fiscal years remain in `status` for review.

## Direct PDF downloads

`export-manifest` writes only verified direct PDF candidates. You can also create a reviewed CSV from `examples/reports.csv`. Its columns are:

| Column | Example | Meaning |
| --- | --- | --- |
| `country` | `GBR` | `GBR` or `USA` |
| `exchange` | `XLON` | Four-character exchange MIC, supplied with the listing |
| `lei` | `2138007ZFQYRUSLU3J98` | 20-character LEI |
| `isin` | `GB00BHJYC057` | 12-character ISIN |
| `ticker` | `IHG` | Supplied ticker |
| `fiscal_year` | `FY2024` | Reporting year |
| `report_type` | `AR` | SOP code, including `AR`, `10K`, `20F`, `IR` |
| `language` | `EN` | Complete English report |
| `pdf_url` | `https://.../report.pdf` | Direct PDF endpoint |
| `source_page` | `https://.../reports` | Public page or filing where the link was found; may be blank |
| `verified` | `true` | Confirmation of report identity and scope |

Keep credentials in environment variables. For SEC-hosted URLs, set `SEC_USER_AGENT` to an organization name and contact email. Never put credentials into a CSV.

```powershell
ar-harvest plan resolved-reports.csv
ar-harvest run resolved-reports.csv --output-root "GLOBAL_SUSTAINABILITY_DATABASE" --state harvest.sqlite3
ar-harvest verify --output-root "GLOBAL_SUSTAINABILITY_DATABASE" --state harvest.sqlite3
ar-harvest benchmark --limit 200 --output-root "GLOBAL_SUSTAINABILITY_DATABASE" --state harvest.sqlite3
```

The SOP recommends storing the database on a non-system drive and keeping a backup (`GLOBAL_SUSTAINABILITY_DATABASE` points directly to `G:\My Drive\GLOBAL_SUSTAINABILITY_DATABASE`). `run` writes `run-summary.json` and `failures.csv` in the current directory. Re-running skips successful files whose recorded URL and file size match. If a process stopped after an atomic write but before its database update, the next run validates and recovers that file. `verify` performs full hash and page-tree checks. Use `--replace` only when intentionally replacing existing files.

`benchmark` downloads up to 200 pending discovered direct PDFs, displays live counts, records the run in SQLite, and appends `benchmark.csv`. It performs real downloads into the chosen final output path.

## Performance model

The default has 32 concurrent transfers and at most 2 per host. It interleaves hosts, caps each request at 15 seconds, sends retryable failures to a second pass, validates PDFs in memory, and writes each completed PDF once through a `.part` file and atomic rename. The default PDF size cap is 64 MiB per transfer. Adjust `--workers` to the available RAM and bandwidth; maximum possible in-flight PDF memory is roughly `workers × max-mib`, plus overhead. At 32 × 64 MiB that upper bound is high, so use a lower cap or worker count for memory-limited machines.

Throughput is constrained by source bandwidth, file size and source access policies. The downloader does not promise a fixed number of PDFs per second. It respects the SEC's [10 requests/second fair access limit](https://www.sec.gov/about/webmaster-frequently-asked-questions) with a margin (8.8/second). An individual corporate host gets at most two concurrent transfers.

## Source strategy

The [SEC submissions API](https://www.sec.gov/search-filings/edgar-application-programming-interfaces) provides filing metadata, but many 10-K filings are HTML. The [FCA NSM](https://www.fca.org.uk/markets/primary-markets/regulatory-disclosures/national-storage-mechanism) holds UK annual financial reports, but many recent filings are structured XHTML or ZIP packages. [FCA guidance](https://www.fca.org.uk/markets/filing-structured-annual-financial-reports) distinguishes structured reports from PDF filings. These source formats determine the number of annual reports that can be ingested as original PDFs without local conversion.

The supplied workbook lists approximately 9,548 US and 3,191 UK companies, but contains no individual records. Supply the company roster before a full 2017–2025 run. Discovery status reports expected, found, missing, PDF-ready, non-PDF and manual-review counts; it never invents absent documents.

## Sustainability pilot: first two companies

`examples/sustainability-first-two.csv` contains Microsoft and Coca-Cola official PDF examples. They illustrate report-family changes; they are not the company limit. The general workflow below accepts any supplied US/UK universe and 2017–2025 metadata export. The full source strategy is in `docs/sustainability-pipeline.md`.

Create a company identity CSV using `examples/universe.csv`. Obtain an **authorized** bulk portal export, or create the same metadata format from official company archive links. Required columns are `company_name,ticker,isin,country,report_year,report_title,report_type,language,source_url,filename,page_count`. `source_url` is an HTTPS direct PDF URL when available; `filename` is an exact member path in a supplied bulk ZIP. Rows may have either or both. Country uses `USA` or `GBR`, and `report_year` uses `2017` through `2025`.

```powershell
ar-harvest sr-import companies.csv authorized-metadata.csv --years 2017:2025
ar-harvest plan sr-direct.csv
ar-harvest run sr-direct.csv --output-root "GLOBAL_SUSTAINABILITY_DATABASE"
ar-harvest sr-ingest-zip authorized-bulk.zip --index sr-bulk-index.csv --output-root "GLOBAL_SUSTAINABILITY_DATABASE"
```

`sr-import` joins by exact country and ISIN, classifies standalone sustainability/ESG/CSR, integrated reports, and topic updates, and writes ambiguous or unmatched rows to `sr-review.csv`. Conflicting reports for the same SOP path go to review. It creates the full URL manifest before `run` starts. `sr-ingest-zip` reads only listed members, caps member size, verifies PDF structure, hashes the bytes, writes atomically to the SOP path, and records results in SQLite. The portal itself does not expose an authorized automation API in this repository; obtain its metadata and ZIP through your licensed workflow. Official archive URLs can use the same metadata import format. Report availability and access depend on the supplied universe and source exports.

## Development

```powershell
.venv\Scripts\python -m pytest -q
.venv\Scripts\python benchmarks\local_batch.py --count 100
.venv\Scripts\python benchmarks\local_batch.py --count 100 --image-side 1024
```

`--allow-http` exists only to run local HTTP integration tests. Production manifests should use HTTPS.
The benchmark serves synthetic PDFs from localhost. The image option creates roughly 3 MiB files. Its throughput is a regression check for the local pipeline, not a prediction for remote hosts.

## AnnualReports.com source option (Deprecated / Absolute Last Resort)

> **⚠️ DEPRECATION & PRIORITY NOTICE**: `AnnualReports.com` is **deprecated as a primary extraction method** and must **only be used as the absolute last option** when explicitly requested by the user or after SEC EDGAR, FCA NSM, and official corporate IR archives have been completely exhausted.

When the task explicitly requests AnnualReports.com, `annualreports-discover` searches the site's company pages, verifies ticker and exchange against the supplied universe, and resolves the listed years and PDF links into one SOP-compliant manifest. It caches page HTML for seven days and writes missing or ambiguous company-years to `annualreports-unresolved.csv`. Discovery finishes before downloading starts. The existing concurrent engine then transfers PDFs, follows the site's recent-report redirects, validates page trees, hashes files, and writes atomic SOP names.

```powershell
ar-harvest annualreports-discover companies.csv --years 2017:2025
ar-harvest plan annualreports-direct.csv
ar-harvest run annualreports-direct.csv --authorized-hosted --workers 32 --per-host 2 --output-root "GLOBAL_SUSTAINABILITY_DATABASE"
ar-harvest verify --output-root "GLOBAL_SUSTAINABILITY_DATABASE"
ar-harvest annualreports-audit companies.csv annualreports-direct.csv --output-root "GLOBAL_SUSTAINABILITY_DATABASE"
```

The `--authorized-hosted` flag explicitly enables automated AnnualReports.com PDF transfers when your access permits them. Start at two connections per host and tune with the accuracy-gated benchmark. Inspect `annualreports-unresolved.csv` and use SEC/FCA or official company archives for gaps. `annualreports-audit` checks readable opening and ending pages for company and fiscal-year clues and writes `annualreports-content-review.csv`; flagged files need review, especially scanned PDFs. Discovery never guesses PDF URLs or downloads files while resolving company pages.

For an authorized metadata export or vendor-provided ZIP, use `annualreports-import` and `annualreports-ingest-zip` instead. The normalized metadata CSV columns are `country,isin,report_year,report_title,pdf_url,zip_member,source_page`. Match the supplied universe by exact country and ISIN. `pdf_url` is a direct HTTPS PDF URL; `zip_member` is the exact path inside an authorized ZIP. At least one is required. The importer writes an SOP-compliant direct manifest, a bulk ZIP index, and a review CSV before transfer.

```powershell
ar-harvest annualreports-import companies.csv annualreports-metadata.csv
ar-harvest annualreports-ingest-zip authorized-annualreports.zip --output-root "GLOBAL_SUSTAINABILITY_DATABASE"
ar-harvest run annualreports-direct.csv --output-root "GLOBAL_SUSTAINABILITY_DATABASE"
```

AnnualReports.com [lists annual PDFs by company and year](https://www.annualreports.com/Company/microsoft-corporation), but no public bulk ZIP/API is documented on its [site information](https://www.annualreports.com/About). Its [robots.txt](https://www.annualreports.com/robots.txt) disallows automated HostedData PDF access. Use the hosted transfer flag only with access that permits automation. The implementation does not evade blocks or use proxies. A ZIP supplied through authorized access is ingested locally. Individual remote PDFs still require individual transfers; no fixed seconds-per-hundred rate can be promised.
