# Canada ZETA Annual Reports Bulk Downloader

Production-oriented annual-report harvesting pipeline for **currently listed Toronto Stock Exchange (TSX) and TSX Venture Exchange (TSXV) companies**, targeting **FY2017-FY2025**, with final storage that follows the ZETA-AI folder and filename SOP.

## What this project is — and is not

This is a resumable corpus pipeline, not a one-off web scraper. It creates a current issuer universe, expected company-year slots, source/candidate ledgers, validated downloads, a repair queue, and a final ZETA-compliant corpus.

**SEDAR+ public-site scraping is intentionally not implemented.** The SEDAR+ Public Website Terms prohibit automated scraping and using public-site content to construct a database. For regulatory-filings-scale collection, use an **authorized SEDAR+ Data Distribution Service (DDS) delivery / licensed manifest**. The project can also crawl official issuer investor-relations sites as a secondary source while respecting `robots.txt` by default.

## Target universe

- Country ISO3: `CAN`
- Toronto Stock Exchange MIC: `XTSE`
- TSX Venture Exchange MIC: `XTSX`
- NEX MIC: `XTNX` (excluded by default; opt in with `--include-nex`)
- Fiscal years: `FY2017` through `FY2025`
- Report type: statutory/full Annual Report (`AR`)
- Default language: English (`EN`); French can be considered with `--include-fr`

The universe count is **not hard-coded**. Each run ingests the current official TMX issuer list and writes `work/audit/universe_summary.csv` with raw, eligible-company, and excluded-product counts by exchange. By default, ETFs/ETPs, CDRs, closed-end/investment funds, SPACs and capital pool companies are excluded from the operating-company corpus.

## Exact ZETA SOP output

Final folder chain:

```text
GLOBAL_SUSTAINABILITY_DATABASE/
└── CAN/
    ├── XTSE/
    │   └── LEI_ISIN_Ticker/
    │       ├── FY2017/
    │       ├── ...
    │       └── FY2025/
    └── XTSX/
        └── LEI_ISIN_Ticker/
            └── FYyyyy/
```

Exact Annual Report filename:

```text
LEI_CAN_ExchangeMIC_Ticker_ISIN_FYyyyy_AR_EN.pdf
```

Example using verified Royal Bank of Canada identifiers:

```text
GLOBAL_SUSTAINABILITY_DATABASE/CAN/XTSE/
ES7IP3U3RHIGC71XBU11_CA7800871021_RY/FY2025/
ES7IP3U3RHIGC71XBU11_CAN_XTSE_RY_CA7800871021_FY2025_AR_EN.pdf
```

The pipeline uses the **financial reporting period**, not the publication year. If a report published in 2025 covers FY2024, it goes in `FY2024`.

A file is not placed in the final ZETA tree unless ticker, exchange MIC, ISIN and LEI are resolved. Valid PDFs with unresolved identity are retained in `work/staging/unresolved_identity/` and surfaced in `identity_missing.csv`; identifiers are never fabricated.

## Source strategy

### Tier 1 — authorized SEDAR+ bulk distribution

Use a licensed/authorized SEDAR+ DDS delivery or a manifest derived from it. The importer supports CSV, JSON, JSONL and ZIP-wrapped CSV/JSONL. It accepts licensed HTTP(S) URLs **or local delivered PDF paths**.

The importer uses field aliases, so a normalized row can be as simple as:

```csv
issuer_name,ticker,exchange_mic,isin,lei,document_title,document_url,period_end,filing_date,language,document_id
Royal Bank of Canada,RY,XTSE,CA7800871021,ES7IP3U3RHIGC71XBU11,2025 Annual Report,https://licensed.example/rbc-2025.pdf,2025-10-31,2025-12-04,EN,abc123
```

For locally delivered files, use `document_path` instead of `document_url`:

```csv
issuer_name,ticker,exchange_mic,document_title,document_path,period_end
Example Corp,ABC,XTSE,2024 Annual Report,delivery/ABC_2024.pdf,2024-12-31
```

### Tier 2 — official issuer investor-relations sites

The crawler is bounded, rate-limited, same-site, and obeys `robots.txt` by default. It searches common investor/financial/report paths and only accepts annual-report-like PDF links. It rejects common false positives such as Annual Information Forms, proxies/management information circulars, AGM notices, MD&A, interim/quarterly, sustainability/ESG/climate documents, presentations and news releases.

For best free-mode coverage, add official issuer websites to the universe file or `input/identity_overrides.csv`. The current TMX download may not contain every website/identifier field.

## Production controls

- SQLite WAL manifest (`work/harvest.sqlite3`)
- current/eligible issuer universe with stale issuers deactivated on refresh
- expected FY2017-FY2025 slots
- source profiles and discovery health
- candidate provenance and source priority
- SEDAR DDS > issuer-site candidate priority
- conservative fiscal-year classification
- English-first selection, optional French fallback
- concurrent, connection-pooled streaming downloads
- `.part` files + HTTP Range resume
- `429` / `5xx` retry and exponential backoff
- local licensed-file ingestion
- PDF magic, minimum size, parse/page and lightweight semantic checks
- SHA-256 content hash
- atomic final writes
- final ZETA-path gate on LEI + ISIN + ticker + MIC
- deterministic sharding for multiple PCs/processes
- reruns skip completed work
- repair only missing/failed slots
- CSV coverage, gap, identity, source-health and failure audits

## Windows — recommended workflow

### 1. Install

Double-click:

```text
install_windows.bat
```

### 2. Obtain the current official TSX/TSXV issuer list

From TMX's **Listed Company Directory**, use **“Click here to download a full list of TSX/TSXV issuers”** and save the CSV/XLSX locally. The project accepts common CSV/XLSX/JSON field names.

Alternatively, if your intended use is authorized under the applicable TMX terms, `universe --fetch-tmx` can attempt the single official current-list download after you set `CANADA_AR_ACKNOWLEDGE_TMX_TERMS=1`.

### 3. Optional but recommended — prepare identifiers/websites

Copy `input/identity_overrides.example.csv` to `input/identity_overrides.csv` and fill verified missing LEIs/ISINs/websites. You can also run conservative GLEIF/OpenFIGI enrichment; unresolved items stay quarantined.

### 4. Optional production source — SEDAR+ DDS

If you have an authorized DDS delivery, normalize its document metadata to one of the supported manifest formats or point the manifest at delivered local PDFs.

### 5. Run the corpus

Double-click:

```text
run_all_2017_2025.bat
```

It asks for:

- current TMX issuer-list file
- optional identity-overrides CSV
- optional authorized SEDAR DDS manifest
- final ZETA root (for example a mounted Google Drive path on `E:`)

### 6. Repair gaps

After the first pass:

```text
run_repair_missing.bat
```

This works only on unresolved slots. It does not waste time redownloading complete reports.

### 7. Audit

```text
run_audit.bat
```

Read especially:

```text
work/audit/universe_summary.csv
work/audit/coverage.csv
work/audit/missing.csv
work/audit/repair_queue.csv
work/audit/identity_missing.csv
work/audit/source_profiles.csv
work/audit/failed_downloads.csv
```

## CLI examples

Load current universe:

```bash
canada-zeta-ar universe --universe-file "C:\data\tsx_tsxv_issuers.xlsx"
```

Apply verified identities and websites:

```bash
canada-zeta-ar identity-override input/identity_overrides.csv
```

Conservative identity enrichment:

```bash
canada-zeta-ar identity-enrich
```

With optional OpenFIGI ISIN lookup:

```bash
canada-zeta-ar identity-enrich --openfigi --openfigi-key YOUR_KEY
```

Import authorized SEDAR bulk manifest:

```bash
canada-zeta-ar import-sedar "C:\licensed_sedar\manifest.csv"
```

Discover issuer-site candidates only for missing slots:

```bash
canada-zeta-ar discover-sites --missing-only
```

Resolve candidates, download and audit:

```bash
canada-zeta-ar resolve
canada-zeta-ar download
canada-zeta-ar finalize
canada-zeta-ar audit
```

One-command run:

```bash
canada-zeta-ar --zeta-root "E:\GLOBAL_SUSTAINABILITY_DATABASE" run ^
  --universe-file "C:\data\tsx_tsxv_issuers.xlsx" ^
  --identity-overrides input\identity_overrides.csv ^
  --sedar-manifest "C:\licensed_sedar\manifest.csv"
```

## Multi-machine sharding

For four independent machines/processes:

```text
Machine 1: --shard-count 4 --shard-index 0
Machine 2: --shard-count 4 --shard-index 1
Machine 3: --shard-count 4 --shard-index 2
Machine 4: --shard-count 4 --shard-index 3
```

Use a separate `--work` directory for each shard. If they share a final cloud root, make sure your cloud client safely handles concurrent writes; each issuer deterministically belongs to one shard.

## Google Drive / ZETA storage

Keep `work/` (SQLite, temporary `.part` files, cache) on a fast local disk. Point only `--zeta-root` to your mounted Google Drive final destination, e.g.:

```text
E:\My Drive\GLOBAL_SUSTAINABILITY_DATABASE
```

This follows the ZETA operational principle of using local working storage and synchronized cloud storage for final validated documents.

## Coverage semantics

Each eligible current issuer receives expected Annual Report slots from FY2017 to FY2025, except years before a known listing date. Slot states are:

- `MISSING` — no acceptable candidate found yet
- `FOUND` — selected candidate exists but not successfully completed
- `DONE` — PDF validated and recorded
- `FAILED` — selected candidate download/validation failed

`coverage.csv` is the corpus truth table. A folder count alone is not considered coverage evidence.

## Important limitations

1. **Full free public-SEDAR scraping is intentionally excluded.** Do not modify the project to evade SEDAR+ terms, CAPTCHAs, access controls or rate protections.
2. The issuer-site fallback cannot honestly guarantee 100% historical coverage for thousands of Canadian issuers because corporate websites change and archives disappear.
3. Near-complete regulatory coverage requires an authorized bulk filing source (e.g. SEDAR+ DDS) or another licensed source whose terms permit your corpus use.
4. Identifier automation is deliberately conservative. Ambiguity is surfaced for review instead of guessed.
5. A structurally valid PDF can still be the wrong document; this pipeline records provenance and performs lightweight semantic checks, but high-assurance corpora should sample/golden-test content as well.

## Tests

Run:

```bash
python -m pytest -q
```

See `TEST_REPORT.md` for the packaged validation status.
