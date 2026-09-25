# Common Integration Contract: Seven Market Annual Reports

This document defines the architectural, data, and execution contract across all international market packages in `markets/`:
- **Australia (ASX)**: `markets/Australia/` (Exchange MIC: `XASX`, ISO3: `AUS`)
- **Bangladesh (Dhaka)**: `markets/Bangladesh/` (Exchange MIC: `XDHA`, ISO3: `BGD`)
- **Canada (TSX / TSXV)**: `markets/Canada/` (Exchange MICs: `XTSE`, `XTSX`, ISO3: `CAN`)
- **Hong Kong (HKEX)**: `markets/HongKong/` (Exchange MIC: `XHKG`, ISO3: `HKG`)
- **India (BSE / NSE)**: `markets/India/` (Exchange MICs: `XNSE`, `XBOM`, ISO3: `IND`)
- **New Zealand (NZX)**: `markets/NewZealand/` (Exchange MIC: `XNZE`, ISO3: `NZL`)
- **Singapore (SGX)**: `markets/Singapore/` (Exchange MIC: `XSES`, ISO3: `SGP`)

---

## 1. Absolute Isolation & Production Boundaries

1. **Untouchable US/UK Core**: The root package `src/annual_reports/`, tests in `tests/`, `ar-harvest` CLI, and `local/harvest.sqlite3` are strictly for the US and UK statutory pipelines (SEC EDGAR, Companies House, FCA NSM). No market package may import from or modify `src/annual_reports/`.
2. **Dedicated Market State**: All market SQLite state, cohort manifests, and staging downloads MUST live under `local/markets/<market>/` on local SSD.
3. **Common Drive Junction**: Final promoted PDFs are written exclusively into the permanent Google Drive junction:
   `GLOBAL_SUSTAINABILITY_DATABASE/` -> `G:\My Drive\GLOBAL_SUSTAINABILITY_DATABASE`
4. **Zero-Token High-Throughput Autonomy**: Follow the `corporate-harvester-speed-engine` and `zeta-autonomous-harvester` paradigms. Once initiated, execute end-to-end autonomously: resolve universe, freeze manifest, discover candidates, download with rate gates and bounded concurrency, validate with in-RAM zero-copy PyMuPDF, and promote to Google Drive.

---

## 2. Common Data Contract (Auditable Records)

Every market implementation must produce and conform to the four universal records defined in `markets/_integration/contract.py`:

### A. Current Issuer Record (`CurrentIssuerRecord`)
- `issuer_id`: Canonical unique market identifier (e.g., ASX ticker, HKEX stock code, ISIN for India, SEDAR profile for Canada).
- `legal_name`: Authoritative entity legal name.
- `country_iso3`: ISO 3166-1 alpha-3 code (`AUS`, `BGD`, `CAN`, `HKG`, `IND`, `NZL`, `SGP`).
- `mic`: ISO 10383 Market Identifier Code (`XASX`, `XDHA`, `XTSE`, `XTSX`, `XHKG`, `XNSE`, `XBOM`, `XNZE`, `XSES`).
- `ticker`: Primary trading ticker / exchange code.
- `isin`: ISO 6166 12-character ISIN (when available).
- `lei`: ISO 17442 20-character LEI (when available; never fabricate).
- `instrument_type`: Entity instrument class (`Equity`, `MainBoard`, `Catalist`, `SME`, etc.). Non-equity securities (ETFs, warrants, bonds) must be excluded.
- `active_status`: Active listing evidence and verification date (`YYYY-MM-DD`).
- `source_url`: URL or endpoint used for roster confirmation.

### B. Requested Slot (`RequestedSlot`)
- `run_id`: Unique deterministic run identifier (`YYYYMMDD_HHMMSS_<market>_<cohort>`).
- `issuer_id`: Target issuer identifier.
- `fiscal_year`: Covered reporting fiscal year (e.g. `2024`, distinct from publication year).
- `report_type`: Always `AR` (statutory annual report).
- `language`: Preferred language (`EN`).

### C. Candidate Filing (`CandidateFiling`)
- `candidate_id`: Stable unique candidate hash or filing ID.
- `issuer_id`: Associated issuer.
- `fiscal_year`: Inferred reporting fiscal year.
- `publication_date`: ISO date (`YYYY-MM-DD`) when released.
- `filing_title`: Exact official announcement or filing headline.
- `source_type`: Official exchange feed, company IR archive, or authorized bulk repository.
- `source_url`: Direct download URL or archive member reference.
- `classification_confidence`: Score / justification confirming this is a genuine annual report (excluding half-year, quarterly, notices, proxy, ESG-only).

### D. Slot Result (`SlotResult`)
- `slot_id`: `f"{run_id}:{issuer_id}:{fiscal_year}"`.
- `status`: One of `PROMOTED`, `VERIFIED`, `STAGED_UNRESOLVED_IDENTITY`, `FAILED`, `UNRESOLVED`.
- `reason`: Explanation if failed, unresolved, or staged.
- `sha256`: Hexadecimal SHA-256 digest of the validated PDF.
- `page_count`: Extracted page count (> 0).
- `file_size_bytes`: Final byte size.
- `destination_path`: Relative or absolute path in `GLOBAL_SUSTAINABILITY_DATABASE` (or local staging).
- `elapsed_seconds`: Time taken for download and processing.
- `timestamp`: UTC ISO 8601 completion timestamp.

---

## 3. Strict Deterministic Exact-N Cohort Selection

1. **Company vs Report Invariant**: User requests specifying "N companies" (e.g., "download the next 100 current listed companies in India for FY2024") must select exactly N distinct active issuers. CLI options that limit report count (`--limit N`) must NOT be used to satisfy cohort requests.
2. **Deduplication Policy**:
   - **India**: Deduplicate BSE and NSE listings primarily by valid ISIN, retaining both exchange identifiers and giving NSE priority for annual report downloads.
   - **Hong Kong**: Derive issuers from active stock codes with qualifying annual report candidates; distinguish from raw active security rows.
   - **Singapore**: Deduplicate by SGX IBM entity code; separate issuer profiles from listed security counters.
   - **Canada**: Target operating companies on TSX/TSXV; exclude funds/split-share instruments.
   - **Australia & New Zealand**: Distinguish listed operating equities from debt, indices, and warrants.
   - **Bangladesh**: Target DSE public equity issuers, excluding treasury bonds and debentures.
3. **Resumable Progression**: Exclude all issuer-years that already exist and pass verification in `GLOBAL_SUSTAINABILITY_DATABASE` or the market's completed ledger.
4. **Frozen Manifest**: Before transferring any files, the exact cohort must be frozen in a run manifest (`local/markets/<market>/manifests/<run_id>.csv`).

---

## 4. SOP Naming & Controlled Google Drive Promotion

### Target SOP Canonical Layout
```
GLOBAL_SUSTAINABILITY_DATABASE/<ISO3>/<MIC>/<LEI>_<ISIN>_<Ticker>/FYyyyy/<LEI>_<ISO3>_<MIC>_<Ticker>_<ISIN>_FYyyyy_AR_EN.pdf
```
- **Fiscal Year Rule**: Always use the reporting period fiscal year (`FY2024`), never the publication year.
- **Controlled Promotion Pipeline**:
  1. **Validation**: Stream to `.part` file in local SSD staging. Validate `%PDF-` signature, PyMuPDF extraction (readable text or renderable pages), and page count.
  2. **Identity Verification**: If `LEI` or `ISIN` is missing or unverified, **never fabricate**. The report is placed in local staging (`local/markets/<market>/staging/unresolved_identity/`) with an explicit reason in `identity_missing.csv`.
  3. **Drive Junction Safety**: Verify `GLOBAL_SUSTAINABILITY_DATABASE` is an active junction pointing to `G:\My Drive\GLOBAL_SUSTAINABILITY_DATABASE`.
  4. **Atomic Promotion**: Write temporary file `.part` on the Google Drive target directory, then atomically rename (`os.replace`) to the final SOP PDF name.
  5. **Conflict Resolution**: If the final file exists:
     - If SHA-256 is identical: idempotent success.
     - If SHA-256 differs: place candidate in `local/markets/<market>/conflicts/` and log to conflict review queue; NEVER overwrite silently.
  6. **Commit Ledger**: Commit record to SQLite `manifest.sqlite3` only after successful atomic promotion.
