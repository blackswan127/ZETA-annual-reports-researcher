# Sri Lanka CSE annual-report harvesting runbook

## 1. Primary autonomous agentic directive

Operate this module as an autonomous, high-throughput annual report harvesting engine for companies listed on the Colombo Stock Exchange (CSE, MIC: `XCOL`, ISO3: `LKA`).

Whenever a user requests to *"download N Sri Lankan companies"* or *"harvest CSE reports"*, interpret N as **distinct listed operating equity issuers** (deduplicated by primary voting share class), not raw PDF counts or individual filing slots. **Do not pause, hesitate, or ask for manual confirmation.** Autonomously execute the entire pipeline from universe resolution through candidate discovery, parallel downloading, PyMuPDF validation, and atomic promotion into `GLOBAL_SUSTAINABILITY_DATABASE`.

---

## 2. Universe defaults and cohort selection

- **Target Exchange & MIC**:
  - Exchange: Colombo Stock Exchange (`XCOL`)
  - Country ISO3: `LKA`
- **Default Fiscal Years**: FY2017 through FY2025 inclusive.
- **Sri Lankan Corporate Fiscal Year Conventions**:
  - A significant majority of Sri Lankan listed corporations (including conglomerates, manufacturing, and diversified holdings such as John Keells Holdings, Hayleys, Carson Cumberbatch) operate on an **April 1 to March 31** fiscal year.
  - A filing titled `Annual Report as at 31st March 2024` or covering `2023/24` maps strictly to covered financial reporting period **FY2024**.
  - Commercial banks, insurance companies, and select multinationals operate on the calendar year (January 1 to December 31).
  - **Fiscal year is strictly the covered reporting period**, not the publication calendar date.
- **Authoritative Universe Roster & Share Class Deduplication**:
  - The live operating universe comprises **~290 listed companies** on the Colombo Stock Exchange (`cse.lk`).
  - **Deduplication Rule**: Many CSE companies issue multiple share classes (e.g. Non-Voting `.X0000` vs. Voting `.N0000`, or Rights `.R0000`). Automatically filter out rights (`.R`) and warrants (`.W`), and deduplicate to the primary voting equity counter (preferring `.N0000`).
  - Exclude debentures, corporate debt, and government Treasury instruments.
- **Identity Invariant**:
  - Every canonical filing requires a valid 20-character ISO 17442 `LEI` and 12-character ISO 6166 `ISIN` (prefix `LK`).
  - **Never invent or synthesize LEI/ISIN**. Issuers with missing or ambiguous identifiers are staged locally (`local/staging/unresolved_identity/LKA/`) until enriched via OpenFIGI or official overrides.
- **State Preservation**: Maintain SQLite state in `local/markets/SriLanka/harvest.sqlite3`. Never delete state to restart; select the next eligible unharvested companies in stable alphabetical ticker order.

---

## 3. Official sources and priority hierarchy

Harvest Sri Lanka corporate annual reports using the following strict priority:

```
[ CSE Listed Equity Universe (~290 Issuers) ]
                 │
                 ├──► Priority 1: Official CSE REST API (Directory & Financials)
                 │    ├── POST /api/alphabetical (A-Z Issuer Discovery)
                 │    └── POST /api/financials (Annual Report infoAnnualData)
                 │
                 └──► Priority 2: High-Speed CSE CloudFront Attachment CDN
                      └── https://cdn.cse.lk/cmt/... (Direct PDF Streaming)
```

1. **Priority 1 — Official CSE JSON API (`https://www.cse.lk/api/`)**:
   - `api/alphabetical`: Query A through Z to build the comprehensive current active issuer directory, with fallback to `api/todaySharePrice`.
   - `api/financials`: Issue a single efficient request per company (`symbol=TICKER.N0000`) with appropriate headers (`Origin: https://www.cse.lk`, `Referer: https://www.cse.lk/company-profile?symbol=...`).
   - Extract records from the official **`infoAnnualData`** array.
2. **Priority 2 — High-Speed CloudFront Attachment CDN (`https://cdn.cse.lk/`)**:
   - CSE stores all historical and current statutory filing PDFs on its Amazon CloudFront CDN (`dntlrejp0m7ff.cloudfront.net` / `cdn.cse.lk`).
   - Normalizes attachment paths (`cmt/upload_report_file/...`) to full CDN URLs.
   - Stream directly with HTTP/2 or HTTP/1.1 Range support; zero WAF interference.
3. **Pacing and Politeness**:
   - Enforce polite rate limiting: 2.0 requests/sec for discovery metadata; 8.0 requests/sec for PDF downloads with up to 16 concurrent workers.

---

## 4. Document classification & fiscal year resolution

All document filtering in [`fy.py`](file:///c:/Users/CGS_Computer/Videos/annaual%20reportsssssss/markets/SriLanka/src/lka_cse_bulk/fy.py) must strictly adhere to:

- **Positive Statutory Indicators**:
  - `Annual Report`, `Integrated Annual Report`, `Annual Report as at 31st March`, `Annual Financial Statements`.
- **Fiscal Year Extraction Rules**:
  - Explicit pattern: `\bFY\s*20(\d{2})\b` $\to$ confidence 1.0.
  - Split range: `\b(20\d{2})\s*[-/]\s*(20\d{2}|\d{2})\b` (e.g. `2023/24` $\to$ FY2024) $\to$ confidence 0.98.
  - Title year: `(?:annual\s+report|integrated\s+annual\s+report)[^\d]{0,15}(20\d{2})` $\to$ confidence 0.96.
- **Negative Exclusions (Strict False-Positive Filter)**:
  - Discard: Interim financial statements (Quarterly reports Q1, Q2, Q3, Q4), circulars to shareholders, notices of AGM/EGM, rights issues, and corporate disclosure announcements.

---

## 5. Step-by-step CLI execution recipes

Always execute from the workspace root with `PYTHONPATH` pointed to `markets/SriLanka/src`.

### Recipe A: Unified ZETA Master Coordinator (Recommended)
Harvest Sri Lanka cohorts directly using the central multi-market orchestrator:
```powershell
# Plan and inspect cohort
py -m markets._integration.cli plan --market SriLanka --count 10 --years 2017-2025

# Execute autonomous harvesting pipeline to completion
py -m markets._integration.cli execute --market SriLanka --count 10 --years 2017-2025

# Promote validated files directly into Google Drive
py -m markets._integration.cli promote --market SriLanka --source-dir markets/SriLanka/work

# Review global database status
py -m markets._integration.cli status
```

### Recipe B: Direct Sri Lanka Module CLI (`cse-ar`)
For granular inspection, sharded runs, or manual repair:

```powershell
$env:PYTHONPATH = "markets/SriLanka/src"

# 1. Discover active universe and extract annual report candidates
py -m lka_cse_bulk.cli discover --start-year 2017 --end-year 2025 --discovery-workers 8 --discovery-rps 2.0

# 2. Parallel streaming download with PyMuPDF validation (16 workers, 8 RPS)
py -m lka_cse_bulk.cli download --start-year 2017 --end-year 2025 --pdf-workers 16 --pdf-rps 8.0 --zeta-root GLOBAL_SUSTAINABILITY_DATABASE

# 3. Repair missing or failed slots
py -m lka_cse_bulk.cli repair-missing --zeta-root GLOBAL_SUSTAINABILITY_DATABASE

# 4. Export audit metrics and coverage report
py -m lka_cse_bulk.cli audit
```

### Recipe C: All-in-One Autonomous Production Run
```powershell
$env:PYTHONPATH = "markets/SriLanka/src"
py -m lka_cse_bulk.cli run --start-year 2017 --end-year 2025 --zeta-root GLOBAL_SUSTAINABILITY_DATABASE
```

---

## 6. PyMuPDF validation, atomic drive promotion, and audit artifacts

1. **In-RAM Zero-Copy PyMuPDF Validation**:
   - Inspect `%PDF-` header signature, verify document trailer/xref integrity, test first-page renderability, and enforce minimum size/page threshold ($\ge 1$ page, $\ge 20$ KB).
2. **Atomic Drive Promotion**:
   - Stream to temporary `.part` files on the target directory.
   - Verify SHA-256 before atomic rename to canonical ZETA path:
     ```
     GLOBAL_SUSTAINABILITY_DATABASE/LKA/XCOL/<LEI>_<ISIN>_<Ticker>/FYyyyy/<LEI>_LKA_XCOL_<Ticker>_<ISIN>_FYyyyy_AR_EN.pdf
     ```
3. **Auditable Verification Artifacts**:
   - `coverage.csv`: Matrix of completed issuer-year slots across FY2017–FY2025.
   - `missing.csv`: Audit of missing report slots with failure justifications.
   - `failed_downloads.csv`: Transient HTTP or network errors for retry.
   - `unresolved_identity/`: Safely isolated PDFs lacking complete LEI/ISIN mappings awaiting enrichment.
