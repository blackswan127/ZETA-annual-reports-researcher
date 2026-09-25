# Agent Runbook: Middle East Equity Markets Annual Reports Extractor

> **PRIMARY OPERATIONAL DIRECTIVE**: This package implements an autonomous, production-grade annual report harvesting engine across **eight core Middle Eastern equity markets** (Oman, Jordan, UAE Dubai, UAE Abu Dhabi, Saudi Arabia, Qatar, Bahrain, Kuwait). By strict directive, **Palestine and Israel are completely excluded and ignored**. When an autonomous agent is given a plain-English directive (*"harvest 25 companies from Oman for FY2023"*, *"download 10 issuers in Saudi Arabia for FY2024"*, *"extract UAE top companies"*), **execute end-to-end autonomously** without hesitating or asking permission. Resolve universe identifiers, freeze cohort manifests, execute high-throughput candidate discovery, download with atomic `.part` guards and HTTP Range resume, validate via zero-copy in-RAM PyMuPDF, and promote canonical PDFs directly into Google Drive (`GLOBAL_SUSTAINABILITY_DATABASE`).

---

## 1. Core Invariants (Non-Negotiable Production Rules)

1. **Isolation from US/UK Core**: The core US/UK engine in `src/annual_reports/` and root tests in `tests/` must remain completely untouched. All Middle Eastern engine code lives strictly in `markets/MiddleEast/src/me_ar_bulk/`, local state in `work/` or `local/markets/MiddleEast/`, and test suites in `markets/MiddleEast/tests/`.
2. **Strict Exclusion of Palestine & Israel**:
   - Palestine (PEX / `XPSX`) and Israel (TASE / `XTAE`) must never be loaded into universes, staged, or downloaded.
   - Any query or directive referencing Palestine or Israel is rejected immediately.
3. **Hard Distinction: Annual Financial Statements != Full Annual Report**:
   - `ANNUAL_FS_COMPONENT` (audited annual financial statements only) can prove annual filing coverage, but **CANNOT** satisfy a final ZETA `_AR_EN.pdf` slot.
   - Only `AR_FULL` (full narrative Annual Report / Integrated Annual Report containing corporate governance, management discussion, and audited financial statements) satisfies a final slot.
   - Missing `AR_FULL` slots remain explicitly visible as `MISSING_AR_FULL` or `ANNUAL_COMPONENT_FOUND` in audit logs; never falsely claim 100% AR coverage with statements alone.
4. **LEI & ISIN Purity Rule**:
   - Never synthesize, invent, or truncate ISO 17442 LEIs (20 characters) or ISO 6166 ISINs (12 characters).
   - If an issuer lacks verified LEI or ISIN, **never write to canonical `GLOBAL_SUSTAINABILITY_DATABASE`**.
   - Instead, stage the verified PDF in local SSD under:
     `work/staging/unresolved_identity/<ISO3>/<MIC>/<Ticker>_FY<Year>/<Ticker>_FY<Year>_AR_EN.pdf`
     and log the issuer to `audit/identity_missing.csv`.
5. **Atomic Download Guard**:
   - Stream downloads directly into `<dest>.part`.
   - Support HTTP Range resume (`Range: bytes=<size>-`) on network drops.
   - Enforce minimum file size (`min_pdf_bytes = 35000` bytes).
   - Validate PDF magic header (`%PDF-`), page count (`>= 1`), and non-empty text extraction in-RAM before renaming `.part` to the final `.pdf`.
6. **Idempotent Persistence & WAL SQLite**:
   - All state, slot tracking, candidate scoring, download metrics, and events are committed to SQLite with `PRAGMA journal_mode=WAL;` and `PRAGMA foreign_keys=ON;`.
   - Never redownload or re-render verified slots unless explicitly invoked with `--repair`.
7. **Permanent Google Drive Corpus Junction**:
   - Final promoted documents must be saved directly into `GLOBAL_SUSTAINABILITY_DATABASE` (Windows NTFS junction pointing to `G:\My Drive\GLOBAL_SUSTAINABILITY_DATABASE`).

---

## 2. Supported Middle Eastern Markets & Source Matrix

The engine supports 8 core equity exchanges:

| Country | ISO3 | Primary Exchange | MIC | Rate Limit (RPS) | Discovery Method | True AR Role |
| :--- | :--- | :--- | :--- | :--- | :--- | :--- |
| **Oman** | `OMN` | Muscat Stock Exchange | `XMUS` | 1.5 | MSX Financial Reports (`AR EN` links) | Wave-1 Primary (Cleanest) |
| **Jordan** | `JOR` | Amman Stock Exchange | `XAMM` | 1.5 | ASE Annual Financial Report Disclosures | Wave-1 Primary |
| **UAE Dubai** | `ARE` | Dubai Financial Market | `XDFM` | 1.5 | DFM document feed (`feeds.dfm.ae`) | Wave-1/2 Primary |
| **UAE Abu Dhabi**| `ARE` | Abu Dhabi Securities Exchange | `XADS` | 1.5 | ADX Disclosures CDN (`apigateway.adx.ae`) | Wave-2 Primary |
| **Saudi Arabia**| `SAU` | Saudi Exchange (Tadawul) | `XSAU` | 1.0 | Company Profile Financials / Annual Report | Wave-2 Primary |
| **Qatar** | `QAT` | Qatar Stock Exchange | `DSMD` | 1.0 | QSE Financial Statements & Q-Disclosure | Wave-2 Component-Aware |
| **Bahrain** | `BHR` | Bahrain Bourse | `XBAH` | 1.0 | Company Profiles & Exchange Disclosures | Wave-3 Component-Aware |
| **Kuwait** | `KWT` | Boursa Kuwait | `XKUW` | 1.0 | IFSah English Disclosures & Financials | Wave-3 Component-Aware |

*Excluded*: Palestine (`XPSX`), Israel (`XTAE`).

---

## 3. ZETA Canonical Storage Contract

All promoted documents conforming to verified identity must strictly follow the ZETA naming contract:

```
GLOBAL_SUSTAINABILITY_DATABASE/
  └── <ISO3>/
      └── <MIC>/
          └── <LEI>_<ISIN>_<Ticker>/
              └── FY<Year>/
                  └── <LEI>_<ISO3>_<MIC>_<Ticker>_<ISIN>_FY<Year>_<REPORT_TYPE>_<LANG>.pdf
```

### Example Canonical Path:
`GLOBAL_SUSTAINABILITY_DATABASE/OMN/XMUS/549300H4Y0C0R46L4A57_OM0000001004_BKMB/FY2023/549300H4Y0C0R46L4A57_OMN_XMUS_BKMB_OM0000001004_FY2023_AR_EN.pdf`

### Unresolved Identity Staging:
For issuers whose LEI or ISIN has not yet been resolved through GLEIF, Wikidata, or OpenFIGI:
`work/staging/unresolved_identity/JOR/XAMM/ARBK_FY2022/ARBK_FY2022_AR_EN.pdf`

---

## 4. Strict Document Classification & Language Protocol

### Document Classification (`classify.py`)
- **`AR_FULL`**: Full narrative Annual Report or Integrated Report.
  - Matches: `Annual Report`, `Integrated Annual Report`, `Annual Report and Financial Statements`, `AR EN` (Oman MSX tag), `Annual Financial Report` (Jordan ASE category).
- **`ANNUAL_FS_COMPONENT`**: Standalone financial statements.
  - Matches: `Audited Financial Statements`, `Annual Financial Statements`, `Independent Auditor's Report and Financial Statements`.
  - Action: Recorded as component evidence; does not satisfy `AR_FULL` slot.
- **`GOVERNANCE_COMPONENT`**: Standalone governance reports (`Corporate Governance Report`).
- **`ESG_COMPONENT`**: Standalone sustainability reports (`Sustainability Report`, `ESG Report`).
- **`REJECT`**: Interim results, AGM notices, proxies, press releases, dividends, circulars.

### Language Detection
- **`EN`**: Explicit English attachment marker (`AR EN`, `en_`, `_en`, `English`), or English text ratio >= 90%.
- **`AR`**: Arabic text ratio > 40%. Kept as source evidence but cannot satisfy `_EN.pdf` slot.
- **`BILINGUAL`**: Dual English/Arabic reports containing full English narrative.

---

## 5. Deterministic Fiscal Year Resolution (`fy.py`)

1. **Explicit Period End Date** (Highest Priority):
   - ISO date (`2023-12-31`), DMY (`31/12/2023`), Text (`31 December 2023`).
2. **Explicit FY Tokens**: Matches `FY2024`, `FY24`, `FY 2024`.
3. **Year Ranges**: Matches `2023/2024`, `2023/24` -> maps to ending year `2024`.
4. **Headline Heuristics**: Standalone years (`2017-2025`) in official report titles.
5. **Never map publication date directly to FY without review threshold.**

---

## 6. CLI Command Reference (`me-ar`)

The package provides the production CLI `me-ar` installed via `markets/MiddleEast/pyproject.toml`:

```bash
# 1. Stage universe and generate expected slots (Oman, Jordan, UAE, Saudi, Qatar, Bahrain, Kuwait)
me-ar universe --country OMN --limit 10
me-ar universe --country SAU
me-ar universe --csv path/to/custom_universe.csv

# 2. Discover candidates across centralized exchange feeds and IR archives
me-ar discover --country OMN --limit 10
me-ar discover

# 3. Download and promote verified AR_FULL PDFs to ZETA tree
me-ar download --limit 50
me-ar download --repair

# 4. End-to-end autonomous harvest run
me-ar run --country OMN --limit 10 --years 2017-2025
me-ar run --country SAU

# 5. Export comprehensive audit CSVs
me-ar audit

# 6. Run connectivity smoke test to all 8 Middle Eastern exchanges
me-ar smoke-test
```

---

## 7. Multi-Market Coordinator Integration

The Middle East harvester is fully integrated into the unified market coordinator in `markets/_integration/`:
- **Market Name**: `MiddleEast`
- **Aliases**: `MIDDLEEAST`, `MIDDLE EAST`, `ME`, `OMAN`, `JORDAN`, `UAE`, `DUBAI`, `DFM`, `ABUDHABI`, `ABU DHABI`, `ADX`, `SAUDI`, `SAUDIARABIA`, `SAUDI ARABIA`, `TADAWUL`, `QATAR`, `QSE`, `BAHRAIN`, `KUWAIT`, `BOURSAKUWAIT`.
- **Adapter**: `MiddleEastAdapter` in `markets/_integration/adapters.py`.

### Example Plain-English Directives:
```python
from markets._integration.coordinator import Coordinator

coord = Coordinator()
# Executes end-to-end harvesting for Oman
await coord.execute_directive("harvest the next 10 companies in Oman for FY2023")

# Executes end-to-end harvesting for Saudi Arabia
await coord.execute_directive("download 20 companies in Saudi Arabia for FY2024")
```

---

## 8. Auditable Artifacts

Every run exports full audit metrics into `work/audit/`:
- `universe_summary.csv`: Active issuer counts, ISIN/LEI counts per market.
- `issuers.csv`: Complete roster with status and identifiers.
- `coverage.csv`: Issuer-year matrix with slot statuses (`DONE`, `IDENTITY_MISSING`, `ANNUAL_COMPONENT_FOUND`, `MISSING_AR_FULL`, `FAILED`).
- `missing.csv`: Unfilled or failed slots requiring review.
- `failed_downloads.csv`: Download failure logs and error details.
- `identity_missing.csv`: Staged reports pending LEI/ISIN verification.
- `components.csv`: Slots where only annual financial statements (components) were located.
