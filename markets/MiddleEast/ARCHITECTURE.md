# Middle East AR v2 — Production Architecture

## 1. Goal

Mass harvest English full Annual Reports for current-listed equity issuers across the eight core Middle Eastern markets for FY2017-FY2025.

## 2. Common pipeline

CURRENT EXCHANGE EQUITY UNIVERSE
    ↓
IDENTITY NORMALIZATION
    ticker / legal name / ISIN / LEI / fiscal-year-end / language policy
    ↓
EXPECTED SLOTS
    issuer × FY2017..FY2025 × AR_FULL
    ↓
CENTRALIZED EXCHANGE ADAPTER
    ↓
CANDIDATE LEDGER
    ↓
LANGUAGE CLASSIFIER
    ↓
DOCUMENT CLASSIFIER
    ├─ AR_FULL
    ├─ ANNUAL_FS_COMPONENT
    ├─ GOVERNANCE_COMPONENT
    ├─ ESG_COMPONENT
    └─ REJECT
    ↓
FISCAL-YEAR RESOLVER
    ↓
BEST CANDIDATE
    ↓
DIRECT PDF/ATTACHMENT URL
    ↓
DOWNLOAD POOL
    ↓
PDF VALIDATION + SHA256
    ↓
ZETA FINAL PATH
    ↓
COVERAGE AUDIT
    ↓
MISSING_AR_FULL
    ↓
SECONDARY EXCHANGE SOURCE / ISSUER IR REPAIR

## 3. Hard invariant: component != Annual Report

`ANNUAL_FS_COMPONENT` can prove annual filing coverage but cannot mark the ZETA Annual Report slot DONE.

Only `AR_FULL` can create `_AR_EN.pdf`.

Examples accepted as AR_FULL:
- Annual Report
- Integrated Annual Report
- Annual Report and Financial Statements
- full report package with board/management/governance + audited financial statements

Examples not accepted:
- Audited Financial Statements only
- Annual Financial Statements only
- preliminary annual results
- press release
- AGM invitation
- governance report only
- ESG/Sustainability report only
- quarterly/interim/semiannual report

## 4. Fiscal-year resolver

1. explicit period end in exchange metadata
2. explicit FY/title year
3. PDF first-page/report-period evidence
4. known issuer FY-end + filing-date heuristic (review threshold required)
5. unresolved -> FY_REVIEW

Never map publication date directly to FY.

## 5. Language resolver

A report satisfies `_EN` only if:
- exchange attachment explicitly says EN/English; or
- extracted first-page text is confidently English; or
- bilingual PDF contains a complete English section judged suitable by policy.

Arabic-only object is kept as source evidence but cannot satisfy English slot.

## 6. Transport

Discovery and download are separate queues.

Recommended baseline:
- global discovery concurrency: 12
- per-host discovery concurrency: 2
- PDF workers: 16
- increase to 32 only after source benchmark
- `.part` file + Range resume
- respect Retry-After
- 403 repeat -> SOURCE_BLOCKED
- 429/5xx -> exponential backoff
- stream PDFs to local SSD
- validate/hash off critical download path where possible
- atomic rename after validation

## 7. Source-specific adapters

### XMUS — Oman
Primary selector: Financial Reports -> `AR EN`.
This is the canonical easiest adapter.

### XAMM — Jordan
Primary selector: disclosure category `Annual Financial Report` plus date/company filters.
Classify actual attachment as AR_FULL or component.

### XDFM — Dubai
Primary selector: DFM documents/disclosures. Direct `feeds.dfm.ae` transport.
Strong title filter for Annual Report.

### XADS — Abu Dhabi
Primary selector: Listed Companies Disclosures / financial reports. Direct ADX CDN transport.

### XSAU — Saudi Arabia
Primary selector: issuer company profile -> Financials -> Annual Report. Require English attachment.

### DSMD — Qatar
Primary selector: QSE Financial Statements annual column + Q-Disclosure. Treat annual statements as components unless full Annual Report evidence exists.

### XBAH — Bahrain
Primary selector: issuer company profile historical annual statements/disclosures. Full-AR repair when profile only supplies FS.

### XKUW — Kuwait
Primary selector: IFSah financial statements with frequency Annual and English version. Full-AR repair if package is statements-only.

## 8. SQLite control plane

Tables:
- issuers
- issuer_aliases
- expected_slots
- candidates
- candidate_evidence
- downloads
- files
- source_profiles
- source_health
- discovery_state
- events
- manual_review

Slot states:
PENDING
DISCOVERING
AR_FULL_FOUND
ANNUAL_COMPONENT_FOUND
READY
DOWNLOADING
DONE
MISSING_AR_FULL
FAILED
SOURCE_BLOCKED
IDENTITY_MISSING
LANGUAGE_REVIEW
FY_REVIEW

## 9. ZETA storage

GLOBAL_SUSTAINABILITY_DATABASE/ISO3/MIC/LEI_ISIN_Ticker/FYyyyy/
LEI_ISO3_MIC_Ticker_ISIN_FYyyyy_AR_EN.pdf

No invented identifiers.

## 10. Multi-machine mode

shard = stable_hash(ISO3 + MIC + ticker) % shard_count

Each machine uses a separate SQLite shard and local staging directory. Merge manifests after acquisition by deterministic issuer keys and SHA-256.
