# Canada TSX/TSXV annual-report harvesting runbook

## 1. Primary autonomous agentic directive

Operate this module as an autonomous, high-throughput annual report harvesting engine for companies listed on the Toronto Stock Exchange (TSX, MIC: `XTSE`) and TSX Venture Exchange (TSXV, MIC: `XTSX`). 

Whenever a user requests to *"download N Canadian companies"* or *"harvest Canada reports"*, interpret N as **distinct listed operating issuers**, not raw PDF counts or individual filing slots. **Do not pause, hesitate, or ask for manual confirmation.** Autonomously execute the entire pipeline from universe resolution through candidate discovery, parallel downloading, PyMuPDF validation, and atomic promotion into `GLOBAL_SUSTAINABILITY_DATABASE`.

---

## 2. Universe defaults and cohort selection

- **Target Exchanges & MICs**:
  - Primary: Toronto Stock Exchange (`XTSE`)
  - Venture: TSX Venture Exchange (`XTSX`)
  - Country ISO3: `CAN`
- **Default Fiscal Years**: FY2017 through FY2025 inclusive. Canadian statutory reporting periods commonly end on December 31, October 31 (banks), or March 31. Reporting fiscal year must reflect the covered financial year, not the calendar publication date.
- **Authoritative Universe Roster**:
  - The live operating universe comprises **3,768 operating issuers** sourced directly from the official TMX Listed Companies Directory (`https://www.tsx.com/en/resource/571`).
  - **Strict Instrument Filtering**: Operating equities only. Automatically exclude NEX board listings, exchange-traded funds (ETFs), closed-end investment funds, structured notes, and debt instruments.
- **Identity Invariant**:
  - Every canonical filing requires a valid 20-character ISO 17442 `LEI` and 12-character ISO 6166 `ISIN` (prefix `CA`).
  - **Never invent or synthesize LEI/ISIN**. Issuers with missing or ambiguous identifiers are downloaded into local staging (`local/staging/unresolved_identity/CAN/`) until enriched via GLEIF or OpenFIGI.
- **Cohort Execution**: Maintain a persistent state ledger in SQLite (`local/markets/Canada/manifest.sqlite3`). When asked for "next N companies", select the next N eligible issuers in stable alphabetical ticker order that lack completed FY2017–2025 coverage.

---

## 3. Three-vector source hierarchy & priority

To achieve maximum throughput and legal reliability without triggering bot blocks, harvest Canadian filings using the following strict source priority:

```
[ TSX/TSXV Universe (3,768 Issuers) ]
                 │
                 ├──► Vector 1: SEC EDGAR MJDS (Form 40-F / ARS) ──► Top ~230 Mega-Caps (>80% Market Cap)
                 │
                 ├──► Vector 2: Corporate IR Discovery Engine   ──► Mid/Small Caps (Issuer IR Archives)
                 │
                 └──► Vector 3: Authorized SEDAR+ Export Feeds  ──► Offline / Licensed Manifest Ingestion
```

1. **Vector 1 — SEC EDGAR MJDS (Form 40-F / ARS Passthrough)**:
   - Under the US-Canada Multijurisdictional Disclosure System (MJDS), all major Canadian cross-listed companies (e.g. Royal Bank of Canada, TD Bank, Enbridge, Shopify, Canadian Pacific Kansas City) file their annual reports with the US SEC as Form `40-F` exhibits or Form `ARS`.
   - Source these directly via SEC EDGAR at high speed (10 req/s rate-gated) using the core Two-Tier Engine.
2. **Vector 2 — Autonomous Corporate IR Discovery Engine (`issuer_sites.py`)**:
   - Canadian securities regulations require issuers to maintain public shareholder archives.
   - The crawler starts at the verified corporate website URL from TMX and traverses standard investor subpaths:
     `["/investors", "/investor-relations", "/financials", "/reports", "/annual-reports", "/regulatory-filings"]`.
   - **Polite Crawling**: Respects `robots.txt`, enforces jittered per-host rate limiting, and uses connection pooling.
3. **Vector 3 — Authorized SEDAR+ Export Ingestion (`sedar_manifest.py`)**:
   - Ingests structured search CSV exports from SEDAR+ or licensed DDS bulk packages.
   - Regex-extracts official Document IDs (`extract_document_id`) and maps them to canonical issuer slots.
   - **SEDAR+ Scraping Prohibition**: Never attempt automated browser scraping, CAPTCHA bypass, or session hijacking against the public `sedarplus.ca` Cloudflare-shielded web interface. Use only authorized manifests or issuer-owned archives.

---

## 4. Document classification & multilingual rules

Canadian corporate reporting is officially bilingual (English and French). All document classification in [`classify.py`](file:///c:/Users/CGS_Computer/Videos/annaual%20reportsssssss/markets/Canada/src/canada_zeta_bulk/classify.py) must strictly adhere to:

- **Positive Statutory Indicators**:
  - English: `Annual Report`, `Annual Report to Shareholders`, `Annual Financial Report`, `Integrated Annual Report`, `Year in Review`.
  - French: `Rapport Annuel`, `Rapport Financier Annuel`, `Rapport aux Actionnaires`.
- **Negative Exclusions (Strict False-Positive Filter)**:
  - Discard all non-statutory documents: Management Information Circular (`MIC`), Proxy Circular, Notice of Meeting, Annual Information Form (`AIF`), MD&A only (`Management's Discussion & Analysis`), Quarterly/Interim statements, Presentation slide decks, and Press releases.
- **Sustainability / ESG Routing**:
  - Exclude standalone ESG reports (`r"sustainab"`, `r"esg"`, `r"climate"`) from the statutory `AR` slot.
  - Route standalone sustainability documents to `SR` or `CLIMATE` slots under canonical naming.
- **Language Detection**:
  - Classify document language as `EN` or `FR` based on title, URL tokens, and document headers. Default to `EN` when ambiguous.

---

## 5. Step-by-step CLI execution recipes

Always execute from the workspace root with `PYTHONPATH` pointed to `markets/Canada/src`.

### Recipe A: Unified ZETA Master Coordinator (Recommended)
Harvest Canadian cohorts directly using the central multi-market orchestrator:
```powershell
# Plan and inspect cohort
py -m markets._integration.cli plan --market Canada --count 10 --years 2017-2025

# Execute autonomous harvesting pipeline to completion
py -m markets._integration.cli execute --market Canada --count 10 --years 2017-2025

# Promote validated files directly into Google Drive
py -m markets._integration.cli promote --market Canada --source-dir markets/Canada/work

# Review global database status
py -m markets._integration.cli status
```

### Recipe B: Direct Canada Module CLI (`canada_zeta_bulk`)
For granular inspection, sharded runs, or manual repair:

```powershell
# 1. Staging the active universe (3,768 operating issuers)
$env:PYTHONPATH = "markets/Canada/src"
py -m canada_zeta_bulk.cli universe --universe-file markets/Canada/templates/current_universe.csv

# 2. Enrich identifiers with OpenFIGI (optional)
py -m canada_zeta_bulk.cli identity-enrich --openfigi

# 3. Discover candidates via Corporate IR sites (8 concurrent workers)
py -m canada_zeta_bulk.cli discover-sites --metadata-workers 8 --download-rps 4.0

# 4. Resolve discovered links to expected FY slots
py -m canada_zeta_bulk.cli resolve

# 5. Parallel streaming download with PyMuPDF validation
py -m canada_zeta_bulk.cli download --download-workers 8 --limit 50

# 6. Finalize validated staging PDFs into Google Drive
py -m canada_zeta_bulk.cli finalize --zeta-root GLOBAL_SUSTAINABILITY_DATABASE

# 7. Generate comprehensive audit metrics
py -m canada_zeta_bulk.cli audit
```

### Recipe C: All-in-One Autonomous Production Run
```powershell
$env:PYTHONPATH = "markets/Canada/src"
py -m canada_zeta_bulk.cli run --universe-file markets/Canada/templates/current_universe.csv
```

---

## 6. PyMuPDF validation, atomic drive promotion, and audit artifacts

1. **In-RAM Zero-Copy PyMuPDF Validation**:
   - Every downloaded stream is inspected in memory before committing to disk.
   - Validates `%PDF-` signature, uncorrupted xref tables, renderability of page 0, and minimum page count ($\ge 5$ pages).
2. **Atomic Drive Promotion**:
   - Write files using temporary `.part` paths on the destination volume.
   - Verify file SHA-256 before atomic `os.replace` to prevent corrupted files in Google Drive:
     ```
     GLOBAL_SUSTAINABILITY_DATABASE/CAN/<MIC>/<LEI>_<ISIN>_<Ticker>/FYyyyy/<LEI>_CAN_<MIC>_<Ticker>_<ISIN>_FYyyyy_AR_<LANG>.pdf
     ```
3. **Auditable Verification Artifacts**:
   - `coverage.csv`: Issuer-year completion matrix across FY2017–FY2025.
   - `missing.csv`: Expected slots where no compliant statutory report was found.
   - `failed_downloads.csv`: Network timeouts or HTTP errors requiring retry.
   - `unresolved_identity/`: Local SSD directory containing validated PDFs awaiting LEI/ISIN enrichment.
