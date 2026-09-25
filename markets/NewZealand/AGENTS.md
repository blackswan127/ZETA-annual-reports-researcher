# New Zealand NZX annual-report harvesting runbook

## 1. Primary autonomous agentic directive

Operate this module as an autonomous, high-throughput annual report harvesting engine for companies listed on the New Zealand Stock Exchange (NZX, MIC: `XNZE`, ISO3: `NZL`).

Whenever a user requests to *"download N New Zealand companies"* or *"harvest NZX reports"*, interpret N as **distinct listed operating equity issuers**, not raw PDF counts or individual filing slots. **Do not pause, hesitate, or ask for manual confirmation.** Autonomously execute the entire pipeline from universe resolution through candidate discovery, parallel downloading, PyMuPDF validation, and atomic promotion into `GLOBAL_SUSTAINABILITY_DATABASE`.

---

## 2. Universe defaults and cohort selection

- **Target Exchange & MIC**:
  - Exchange: New Zealand Stock Exchange (`XNZE`)
  - Country ISO3: `NZL`
- **Default Fiscal Years**: FY2017 through FY2025 inclusive.
- **New Zealand Balance Dates & Fiscal Year Logic**:
  - Many NZ companies operate on non-calendar fiscal years: June 30 (e.g., Meridian Energy, Contact Energy) or March 31 (e.g., Fisher & Paykel Healthcare).
  - **Fiscal year is strictly the covered reporting period**, not the publication calendar date. A filing released in September 2024 for the period ended 30 June 2024 is strictly **FY2024**.
- **Authoritative Universe Roster**:
  - The live equity universe comprises ~180+ listed operating companies.
  - Automatically exclude debt instruments, retail bonds, ETFs, and foreign exempt secondary listings where primary reporting is non-NZ.
- **Identity Invariant**:
  - Every canonical filing requires a valid 20-character ISO 17442 `LEI` and 12-character ISO 6166 `ISIN` (prefix `NZ`).
  - **Never invent or synthesize LEI/ISIN**. Issuers with missing or ambiguous identifiers are staged locally (`local/staging/unresolved_identity/NZL/`) until enriched via GLEIF or OpenFIGI.
- **State Preservation**: Maintain SQLite state in `local/markets/NewZealand/manifest.sqlite3`. Never delete state to restart; select the next eligible unharvested companies in stable alphabetical ticker order.

---

## 3. Official sources and priority hierarchy

Harvest New Zealand corporate annual reports using the following strict priority:

```
[ NZX Equity Universe (~180 Issuers) ]
                 │
                 ├──► Priority 1: Authorized NZX Bulk / Export Feed (when available)
                 │
                 ├──► Priority 2: NZX Public Announcements Portal (ANNREP Filings)
                 │
                 └──► Priority 3: Autonomous Corporate IR Discovery Engine (Issuer Archives)
```

1. **Priority 1 — Authorized Bulk Manifest (`ingest-authorized`)**:
   - Ingests verified bulk manifests or exchange data extracts when provided.
2. **Priority 2 — Official NZX Announcements Portal (`parse_documents_page`)**:
   - NZX requires listed companies to file their annual reports as formal market announcements under the announcement code **`ANNREP`** (Annual Report).
   - The harvester queries each company's document page (`https://www.nzx.com/companies/{TICKER}/documents`) and filters for official annual reports.
3. **Priority 3 — Autonomous Corporate IR Engine (`discover_ir_missing`)**:
   - For historical missing slots or unattached filings, the IR crawler inspects the company's verified corporate website investor subpaths (`/investor-centre`, `/reports-presentations`, `/financial-results`).
4. **Access Gates & Terms**:
   - Respect the `NZX_ACKNOWLEDGE_TERMS=1` environment variable. Do not bypass rate limits, terms gates, or access controls.

---

## 4. Document classification & climate disclosures

All document filtering in [`classify.py`](file:///c:/Users/CGS_Computer/Videos/annaual%20reportsssssss/markets/NewZealand/src/nzx_zeta/classify.py) must strictly adhere to:

- **Positive Statutory Indicators**:
  - Announcement type `ANNREP`, `Annual Report`, `Annual Financial Report`, `Audited Financial Statements`, `Annual Report and Financial Statements`.
- **Negative Exclusions (Strict False-Positive Filter)**:
  - Discard: Interim/half-year statements, quarterly reports, annual meeting/AGM notices, investor presentations, corporate governance statements, distribution notices, and market updates.
- **Mandatory Climate Statements (NZ CS 1, 2, 3)**:
  - Under the *Financial Sector (Climate-related Disclosures and Other Matters) Amendment Act 2021*, New Zealand mandates standalone **Climate Statements**.
  - These must be excluded from the statutory `AR` slot to prevent financial ledger corruption. Route standalone climate filings to `CLIMATE` or `SR` slots.

---

## 5. Step-by-step CLI execution recipes

Always execute from the workspace root with `PYTHONPATH` pointed to `markets/NewZealand/src`.

### Recipe A: Unified ZETA Master Coordinator (Recommended)
Harvest New Zealand cohorts directly using the central multi-market orchestrator:
```powershell
# Plan and inspect cohort
py -m markets._integration.cli plan --market NewZealand --count 10 --years 2017-2025

# Execute autonomous harvesting pipeline to completion
py -m markets._integration.cli execute --market NewZealand --count 10 --years 2017-2025

# Promote validated files directly into Google Drive
py -m markets._integration.cli promote --market NewZealand --source-dir markets/NewZealand/work

# Review global database status
py -m markets._integration.cli status
```

### Recipe B: Direct New Zealand Module CLI (`nzx_zeta`)
For granular inspection, sharded runs, or manual repair:

```powershell
$env:PYTHONPATH = "markets/NewZealand/src"
$env:NZX_ACKNOWLEDGE_TERMS = "1"

# 1. Run live pre-flight smoke test
py -m nzx_zeta.cli smoke-test

# 2. Stage active NZX equity universe with GLEIF linkage
py -m nzx_zeta.cli universe --gleif

# 3. Discover candidates via NZX documents portal
py -m nzx_zeta.cli discover-documents

# 4. Fill missing historical slots via Corporate IR crawler
py -m nzx_zeta.cli discover-ir

# 5. Parallel streaming download with PyMuPDF validation (6 concurrent workers)
py -m nzx_zeta.cli download --download-workers 6 --limit 50

# 6. Audit completion and generate verification CSVs
py -m nzx_zeta.cli audit

# 7. Repair missing or failed slots
py -m nzx_zeta.cli repair-missing
```

### Recipe C: All-in-One Autonomous Production Run
```powershell
$env:PYTHONPATH = "markets/NewZealand/src"
$env:NZX_ACKNOWLEDGE_TERMS = "1"
py -m nzx_zeta.cli run --gleif
```

---

## 6. PyMuPDF validation, atomic drive promotion, and audit artifacts

1. **In-RAM Zero-Copy PyMuPDF Validation**:
   - Inspect `%PDF-` header signature, verify document trailer/xref integrity, test first-page text renderability, and enforce minimum page threshold ($\ge 5$ pages).
2. **Atomic Drive Promotion**:
   - Stream to temporary `.part` files on the target directory.
   - Verify SHA-256 before atomic rename to canonical ZETA path:
     ```
     GLOBAL_SUSTAINABILITY_DATABASE/NZL/XNZE/<LEI>_<ISIN>_<Ticker>/FYyyyy/<LEI>_NZL_XNZE_<Ticker>_<ISIN>_FYyyyy_AR_EN.pdf
     ```
3. **Auditable Verification Artifacts**:
   - `coverage.csv`: Matrix of completed issuer-year slots across FY2017–FY2025.
   - `missing.csv`: Audit of missing report slots with failure justifications.
   - `failed_downloads.csv`: Transient HTTP or network errors for retry.
   - `unresolved_identity/`: Safely isolated PDFs lacking complete LEI/ISIN mappings.
