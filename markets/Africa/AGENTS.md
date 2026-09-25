# Agent Runbook: Pan-African Equity Markets Annual Reports Extractor

> **PRIMARY OPERATIONAL DIRECTIVE**: This package implements an autonomous, production-grade annual report harvesting engine across **16 English-reporting African equity markets**. When an autonomous agent is given a plain-English directive (*"harvest 50 companies in Nigeria for FY2023"*, *"download 20 Kenyan companies"*, *"extract all South African top issuers"*), **execute end-to-end autonomously** without hesitating, asking permission, or requesting manual CLI entry. Resolve universe identifiers, freeze cohort manifests, execute high-throughput candidate discovery, download with atomic `.part` guards and HTTP Range resume, validate via zero-copy in-RAM PyMuPDF, and promote canonical PDFs directly into Google Drive (`GLOBAL_SUSTAINABILITY_DATABASE`).

---

## 1. Core Invariants (Non-Negotiable Production Rules)

1. **Isolation from US/UK Core**: The core US/UK engine in `src/annual_reports/` and root tests in `tests/` must remain untouched. All African engine code lives strictly in `markets/Africa/src/africa_ar_bulk/`, local state in `work/` or `local/markets/Africa/`, and test suites in `markets/Africa/tests/`.
2. **LEI & ISIN Purity Rule**:
   - Never synthesize, invent, or truncate ISO 17442 LEIs (20 characters) or ISO 6166 ISINs (12 characters).
   - If an issuer lacks verified LEI or ISIN, **never write to canonical `GLOBAL_SUSTAINABILITY_DATABASE`**.
   - Instead, stage the verified PDF in local SSD under:
     `work/staging/unresolved_identity/<ISO3>/<MIC>/<Ticker>_FY<Year>/<Ticker>_FY<Year>_AR_EN.pdf`
     and log the issuer to `audit/identity_missing.csv`.
3. **Atomic Download Guard**:
   - Stream downloads directly into `<dest>.part`.
   - Support HTTP Range resume (`Range: bytes=<size>-`) on network drops.
   - Enforce minimum file size (`min_pdf_bytes = 25000` bytes).
   - Validate PDF magic header (`%PDF-`), page count (`>= 1`), and non-empty text extraction in-RAM before renaming `.part` to the final `.pdf`.
4. **Idempotent Persistence & WAL SQLite**:
   - All state, slot tracking, candidate scoring, download metrics, and events are committed to SQLite with `PRAGMA journal_mode=WAL;` and `PRAGMA foreign_keys=ON;`.
   - Never redownload or re-render verified slots unless explicitly invoked with `--repair`.
5. **Permanent Google Drive Corpus Junction**:
   - Final promoted documents must be saved directly into `GLOBAL_SUSTAINABILITY_DATABASE` (Windows NTFS junction pointing to `G:\My Drive\GLOBAL_SUSTAINABILITY_DATABASE`).

---

## 2. Supported African Markets & Source Matrix

The engine supports 16 primary equity exchanges across Sub-Saharan Africa:

| Country | ISO3 | Primary Exchange | MIC | Rate Limit (RPS) | Discovery Method |
| :--- | :--- | :--- | :--- | :--- | :--- |
| **South Africa** | `ZAF` | Johannesburg Stock Exchange | `XJSE` | 1.0 | Corporate IR Fallback / Authorized SENS |
| **Nigeria** | `NGA` | Nigerian Exchange Group | `XNSA` | 1.5 | Direct Exchange (`ngxgroup.com`) & IR |
| **Kenya** | `KEN` | Nairobi Securities Exchange | `XNAI` | 1.5 | Direct Exchange (`nse.co.ke`) & IR |
| **Ghana** | `GHA` | Ghana Stock Exchange | `XGHA` | 1.0 | Direct Exchange (`gse.com.gh`) & IR |
| **Botswana** | `BWA` | Botswana Stock Exchange | `XBOT` | 1.0 | Direct Exchange (`bse.co.bw`) & IR |
| **Zambia** | `ZMB` | Lusaka Securities Exchange | `XLUS` | 1.0 | Corporate IR Fallback / LuSE Portal |
| **Tanzania** | `TZA` | Dar es Salaam Stock Exchange | `XDAR` | 1.0 | Direct Exchange (`dse.co.tz`) & IR |
| **Zimbabwe** | `ZWE` | Zimbabwe Stock Exchange | `XZIM` | 1.0 | Direct Exchange (`zse.co.zw`) & IR |
| **Mauritius** | `MUS` | Stock Exchange of Mauritius | `XMAU` | 1.0 | Direct Exchange (`stockexchangeofmauritius.com`) |
| **Namibia** | `NAM` | Namibian Stock Exchange | `XNAM` | 1.0 | Direct Exchange (`nsx.com.na`) & IR |
| **Uganda** | `UGA` | Uganda Securities Exchange | `XUGA` | 1.0 | Direct Exchange (`use.or.ug`) & IR |
| **Malawi** | `MWI` | Malawi Stock Exchange | `XMSW` | 1.0 | Direct Exchange (`mse.co.mw`) & IR |
| **Rwanda** | `RWA` | Rwanda Stock Exchange | `XRWA` | 1.0 | Direct Exchange (`rse.rw`) & IR |
| **Eswatini** | `SWZ` | Eswatini Stock Exchange | `XSWA` | 1.0 | Direct Exchange (`ese.co.sz`) & IR |
| **Seychelles** | `SYC` | MERJ Exchange | `XMSX` | 1.0 | Direct Exchange (`merj.net`) & IR |
| **Sierra Leone**| `SLE` | Sierra Leone Stock Exchange | `XSLS` | 1.0 | Corporate IR / Bank Registrars |

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
`GLOBAL_SUSTAINABILITY_DATABASE/ZAF/XJSE/213800COVT3N6B3Q5O74_ZAE000015889_NPN/FY2023/213800COVT3N6B3Q5O74_ZAF_XJSE_NPN_ZAE000015889_FY2023_AR_EN.pdf`

### Unresolved Identity Staging:
For issuers whose LEI or ISIN has not yet been resolved through GLEIF, Wikidata, or OpenFIGI:
`work/staging/unresolved_identity/GHA/XGHA/GCB_FY2022/GCB_FY2022_AR_EN.pdf`

---

## 4. Strict Classification & Fiscal Year Contract

### Report Classification Contract (`classify.py`)
- **Positive AR Indicators**: `Annual Report`, `Integrated Report`, `Integrated Annual Report`, `Audited Financial Statements`, `Annual Financial Statements`, `Group Annual Report`, `Annual Accounts`.
- **Exclusion Filters (Negative Tokens)**:
  - Interim reports: `Half Year`, `Half-Year`, `Interim Report`, `HY`, `H1`, `H2`, `Q1`, `Q2`, `Q3`, `Q4`, `Quarterly`.
  - Corporate governance & notices: `AGM Notice`, `Notice of Meeting`, `Proxy Form`, `Voting Card`, `Circular to Shareholders`, `Dividend Announcement`.
  - ESG standalone: `Sustainability Report`, `ESG Report`, `CSR Report`, `Climate Report` (classified as `ESG`, never `AR`).
  - Summaries: `Factsheet`, `Investor Presentation`, `Press Release`, `Earnings Release`.

### Fiscal Year Resolution (`fy.py`)
1. **Explicit FY Tokens**: Matches `FY2024`, `FY24`, `FY 2024`.
2. **Year Ranges**: Matches `2023/2024`, `2023/24` -> maps to ending year `2024`.
3. **Period End Dates**: Extracts explicit reporting dates (`31 December 2023`, `30 June 2024`).
4. **Headline Heuristics**: Extracts trailing 4-digit years (`2017-2025`) from document headlines.

---

## 5. CLI Command Reference (`africa-ar`)

The package includes a comprehensive CLI tool `africa-ar` installed via `markets/Africa/pyproject.toml`:

```bash
# 1. Stage universe and generate slots for all 16 African markets (or specific country)
africa-ar universe --country NGA --limit 20
africa-ar universe --country ZAF
africa-ar universe --csv path/to/custom_universe.csv

# 2. Discover candidate filings across official exchange feeds & corporate IR archives
africa-ar discover --country NGA --limit 20
africa-ar discover

# 3. Download and promote candidates with PyMuPDF validation
africa-ar download --limit 50
africa-ar download --repair

# 4. End-to-end autonomous harvest run
africa-ar run --country KEN --limit 10 --years 2017-2025
africa-ar run --country NGA

# 5. Export comprehensive audit CSVs (coverage, missing, failed, identity_missing)
africa-ar audit

# 6. Run smoke test on exchange and corporate endpoints
africa-ar smoke-test --country NGA
```

---

## 6. Multi-Market Coordinator Integration

The Pan-African harvester is fully integrated into the unified market coordinator in `markets/_integration/`:
- **Market Name**: `Africa`
- **Aliases**: `AFRICA`, `PANAFRICA`, `SOUTHAFRICA`, `NIGERIA`, `KENYA`, `GHANA`, `BOTSWANA`, `ZAMBIA`, `TANZANIA`, `ZIMBABWE`, `MAURITIUS`, `NAMIBIA`, `UGANDA`, `MALAWI`, `RWANDA`, `ESWATINI`, `SEYCHELLES`, `SIERRALEONE`.
- **Adapter**: `AfricaAdapter` in `markets/_integration/adapters.py`.

### Example Plain-English Directives Executed Autonomously:
```python
from markets._integration.coordinator import Coordinator

coord = Coordinator()
# Executes end-to-end harvesting for Nigeria
await coord.execute_directive("harvest the next 20 companies in Nigeria for FY2023")

# Executes end-to-end harvesting across Pan-African cohort
await coord.execute_directive("download 50 companies in Africa for FY2024")
```

---

## 7. Self-Improvement & Operational Recovery

1. **JSE / Anti-Bot Throttling**:
   - If JSE direct requests return HTTP 403, the adapter automatically activates `IssuerIRCrawler` to discover annual reports directly from the company's official corporate IR domain.
2. **Rate Limit Gates**:
   - Nigerian Exchange (`XNSA`) and Nairobi Exchange (`XNAI`) are rate-gated at 1.5 RPS.
   - All other African exchange endpoints are strictly rate-gated at 1.0 RPS.
   - Downloader concurrency defaults to 16 workers across disjoint host domains.
3. **Auditable Artifacts**:
   - Every run exports full audit metrics into `work/audit/`:
     - `universe_summary.csv`
     - `issuers.csv`
     - `coverage.csv`
     - `missing.csv`
     - `failed_downloads.csv`
     - `identity_missing.csv`
