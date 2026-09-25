# Bangladesh DSE annual-report harvesting runbook

## 1. Primary autonomous agentic directive

Operate this module as an autonomous, high-throughput annual report harvesting engine for companies listed on the Dhaka Stock Exchange (DSE, MIC: `XDHA`, ISO3: `BGD`).

Whenever a user requests to *"download N Bangladesh companies"* or *"harvest DSE reports"*, interpret N as **distinct listed operating equity issuers**, not raw PDF counts or individual filing slots. **Do not pause, hesitate, or ask for manual confirmation.** Autonomously execute the entire pipeline from universe resolution through candidate discovery, parallel downloading, PyMuPDF validation, and atomic promotion into `GLOBAL_SUSTAINABILITY_DATABASE`.

---

## 2. Universe defaults and cohort selection

- **Target Exchange & MIC**:
  - Exchange: Dhaka Stock Exchange (`XDHA`)
  - Country ISO3: `BGD`
- **Default Fiscal Years**: FY2017 through FY2025 inclusive.
- **Bangladeshi Corporate Fiscal Year Convention**:
  - In Bangladesh, the standard corporate fiscal year for general industrial, commercial, and manufacturing companies runs from **July 1 to June 30**. A report covering the period `2024-25` maps strictly to **FY2025**.
  - Banking, non-bank financial institutions (NBFIs), and insurance companies follow the calendar year (January 1 to December 31).
  - **Fiscal year is strictly the covered reporting period**, not the publication calendar date.
- **Authoritative Universe Roster**:
  - The live operating universe comprises ~390+ listed equity companies on the Dhaka Stock Exchange (`dsebd.org`).
  - **Strict Instrument Filtering**: Operating equities only (`instrument_type == "Equity"`). Automatically exclude mutual funds, treasury bonds, corporate debentures, and Islamic Sukuk bonds.
- **Identity Invariant**:
  - Every canonical filing requires a valid 20-character ISO 17442 `LEI` and 12-character ISO 6166 `ISIN` (prefix `BD` linked via Central Depository Bangladesh Limited / CDBL).
  - **Never invent or synthesize LEI/ISIN**. Issuers with missing or ambiguous identifiers are staged locally (`local/staging/unresolved_identity/BGD/`) until enriched.
- **State Preservation**: Maintain SQLite state in `local/markets/Bangladesh/manifest.sqlite3`. Never delete state to restart; select the next eligible unharvested companies in stable alphabetical ticker order.

---

## 3. Official sources and priority hierarchy

Harvest Bangladesh corporate annual reports using the following strict priority:

```
[ DSE Equity Universe (~390 Issuers) ]
                 │
                 ├──► Priority 1: CDBL Security Master (ISIN Resolution)
                 │
                 ├──► Priority 2: Official DSE Public Profiles & Financial Archives
                 │
                 └──► Priority 3: Autonomous Corporate IR Discovery Engine (Issuer Archives)
```

1. **Priority 1 — CDBL Integration (`cdbl.py`)**:
   - Resolve official 12-character `BD` ISINs and security details via Central Depository Bangladesh Limited reference records.
2. **Priority 2 — DSE Official Financial Statements Archive (`dse_public.py`)**:
   - The harvester queries official DSE company profile pages and financial statements endpoints (`parse_company_page`, `parse_financial_page`) to extract statutory audited annual accounts.
3. **Priority 3 — Autonomous Corporate IR Engine (`discover_ir`)**:
   - For historical missing slots or unlinked DSE PDFs, the IR crawler inspects the company's verified corporate website investor subpaths (`/investor-relations`, `/annual-reports`, `/financial-statements`).
4. **Access Gates & Rate Rules**:
   - Respect the `DSE_ACKNOWLEDGE_TERMS=1` environment variable. 
   - Enforce polite rate limiting (minimum 0.35s request interval with jittered exponential backoff on 429/5xx). Do not attempt bot evasion or CAPTCHA bypass.

---

## 4. Document classification & false-positive prevention

All document filtering in [`classify.py`](file:///c:/Users/CGS_Computer/Videos/annaual%20reportsssssss/markets/Bangladesh/src/dse_zeta/classify.py) must strictly adhere to:

- **Positive Statutory Indicators**:
  - `Annual Report`, `Annual Financial Statements`, `Audited Financial Statements`, `Audited Balance Sheet`, `Audited Accounts`.
- **Negative Exclusions (Strict False-Positive Filter)**:
  - Discard: Annual Return (statutory registry summary), Quarterly financial statements (Q1, Q2, Q3 un-audited), Half-yearly reports, Price Sensitive Information (`PSI`) notices, AGM/EGM notices, Dividend declarations, and Board Meeting announcements.
- **Integrity Threshold**:
  - Statutory annual reports must contain the full Auditor's Report, Balance Sheet, Statement of Profit or Loss, Cash Flow Statement, and Notes.

---

## 5. Step-by-step CLI execution recipes

Always execute from the workspace root with `PYTHONPATH` pointed to `markets/Bangladesh/src`.

### Recipe A: Unified ZETA Master Coordinator (Recommended)
Harvest Bangladesh cohorts directly using the central multi-market orchestrator:
```powershell
# Plan and inspect cohort
py -m markets._integration.cli plan --market Bangladesh --count 10 --years 2017-2025

# Execute autonomous harvesting pipeline to completion
py -m markets._integration.cli execute --market Bangladesh --count 10 --years 2017-2025

# Promote validated files directly into Google Drive
py -m markets._integration.cli promote --market Bangladesh --source-dir markets/Bangladesh/work

# Review global database status
py -m markets._integration.cli status
```

### Recipe B: Direct Bangladesh Module CLI (`dse_zeta`)
For granular inspection, sharded runs, or manual repair:

```powershell
$env:PYTHONPATH = "markets/Bangladesh/src"
$env:DSE_ACKNOWLEDGE_TERMS = "1"

# 1. Run live pre-flight smoke test
py -m dse_zeta.cli smoke-test

# 2. Stage active DSE equity universe with GLEIF linkage
py -m dse_zeta.cli universe --gleif

# 3. Discover candidates via DSE financial reports archive
py -m dse_zeta.cli discover-dse-links

# 4. Fill missing historical slots via Corporate IR crawler
py -m dse_zeta.cli discover-ir

# 5. Parallel streaming download with PyMuPDF validation (8 concurrent workers)
py -m dse_zeta.cli download --download-workers 8 --limit 50

# 6. Audit completion and generate verification CSVs
py -m dse_zeta.cli audit

# 7. Repair missing or failed slots
py -m dse_zeta.cli repair-missing
```

### Recipe C: All-in-One Autonomous Production Run
```powershell
$env:PYTHONPATH = "markets/Bangladesh/src"
$env:DSE_ACKNOWLEDGE_TERMS = "1"
py -m dse_zeta.cli run --gleif
```

---

## 6. PyMuPDF validation, atomic drive promotion, and audit artifacts

1. **In-RAM Zero-Copy PyMuPDF Validation**:
   - Inspect `%PDF-` header signature, verify document trailer/xref integrity, test first-page text renderability, and enforce minimum page threshold ($\ge 5$ pages).
2. **Atomic Drive Promotion**:
   - Stream to temporary `.part` files on the target directory.
   - Verify SHA-256 before atomic rename to canonical ZETA path:
     ```
     GLOBAL_SUSTAINABILITY_DATABASE/BGD/XDHA/<LEI>_<ISIN>_<Ticker>/FYyyyy/<LEI>_BGD_XDHA_<Ticker>_<ISIN>_FYyyyy_AR_EN.pdf
     ```
3. **Auditable Verification Artifacts**:
   - `coverage.csv`: Matrix of completed issuer-year slots across FY2017–FY2025.
   - `missing.csv`: Audit of missing report slots with failure justifications.
   - `failed_downloads.csv`: Transient HTTP or network errors for retry.
   - `unresolved_identity/`: Safely isolated PDFs lacking complete LEI/ISIN mappings.
