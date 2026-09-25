# Africa AR - Production Architecture

## Goal
One annual-report harvesting platform for current-listed equity issuers across 16 African markets, FY2017-FY2025. Country differences live behind adapters; the core pipeline is shared.

## High-level flow
CURRENT EQUITY UNIVERSE
-> IDENTITY NORMALIZATION (ticker, legal name, ISIN, verified LEI, ISO3, MIC, fiscal year-end)
-> EXPECTED SLOTS (issuer x FY2017-FY2025)
-> SOURCE ORCHESTRATOR
-> CANDIDATE LEDGER
-> AR CLASSIFIER
-> FISCAL-YEAR RESOLVER
-> BEST-CANDIDATE SELECTOR
-> PDF DOWNLOAD POOL
-> VALIDATION
-> ZETA PLACEMENT
-> COVERAGE AUDIT
-> REPAIR-MISSING

## Production invariants
- Never equate publication year with fiscal year.
- Never label interim results, audited statements-only, AGM notices, proxy material or sustainability-only reports as AR.
- Never fabricate LEI or ISIN.
- Never overwrite a verified PDF with a lower-confidence candidate.
- Every company-year slot has an explicit state.
- Every source URL and source decision is persisted.
- Every completed PDF has SHA-256.
- Download to .part and atomically rename only after validation.
- Repeated 403/429 is quarantined; never brute-force access controls.
- Site terms, robots directives and licensed-feed constraints are respected.

## Data plane
### A. Universe
Fetch/import each exchange current equity universe. Filter ETFs, funds, bonds, notes, warrants, rights, preference-only instruments and delisted issuers.

### B. Discovery
Metadata/URL discovery only; no PDF transfer. Persist all candidates before download.

### C. AR classification
Positive: Annual Report, Integrated Annual Report, Annual Report and Financial Statements, Annual Report to Shareholders.
Negative: Interim/Half-year/Quarterly, Annual Return, AGM/Proxy, audited statements-only, abridged results, ESG/Sustainability-only, presentation, press release.

### D. Fiscal-year resolution
1. Explicit period end in metadata/title.
2. Explicit FY token (FY2024 / 2023-24).
3. First-page PDF text/metadata.
4. Known fiscal-year-end + filing-date heuristic.
5. REVIEW if confidence is insufficient.

### E. Transport
Defaults: discovery concurrency 8-16 globally, 1-4 per host; PDF workers 16 initially, 32 after smoke testing. Respect Retry-After. Exponential backoff on 429/5xx. Repeated 403 -> SOURCE_BLOCKED. Stream to .part and use HTTP Range resume where supported.

### F. Validation
DONE requires: classified AR + resolved FY + valid PDF + parser/page count + minimum sane size + SHA-256 + sufficient issuer identity.

### G. ZETA output
GLOBAL_SUSTAINABILITY_DATABASE/ISO3/MIC/LEI_ISIN_Ticker/FY2024/LEI_ISO3_MIC_Ticker_ISIN_FY2024_AR_EN.pdf

Missing identifiers go to staging/unresolved_identity.

## Control plane
SQLite WAL tables: issuers, issuer_aliases, source_profiles, expected_slots, candidates, candidate_evidence, downloads, files, discovery_state, events, source_health, manual_review.

Slot states: PENDING, DISCOVERING, CANDIDATE_FOUND, FY_REVIEW, READY, DOWNLOADING, DONE, MISSING, FAILED, SOURCE_BLOCKED, IDENTITY_MISSING, REVIEW.

## Source strategy
Tier 1: authorized/free aggregator.
Tier 2: official exchange disclosure archive.
Tier 3: authorized licensed feed.
Tier 4: issuer IR repair.
Tier 5: manual review.
Stop once a high-confidence validated AR is obtained for a slot.

## Multi-machine sharding
stable_hash(country + exchange + ticker) % shard_count.
Each shard has its own SQLite file; merge via deterministic issuer keys and hashes.

## Audits
audit/universe_summary.csv
audit/issuers.csv
audit/expected_slots.csv
audit/candidates.csv
audit/coverage.csv
audit/missing.csv
audit/repair_queue.csv
audit/source_health.csv
audit/identity_missing.csv
audit/fy_review.csv
audit/failed_downloads.csv
audit/duplicates.csv

## Release gates
10-issuer smoke -> 50-issuer test -> 100-issuer coverage benchmark -> false-positive review -> rerun idempotence -> interrupted-download resume -> 429/5xx simulation -> ZETA naming validation -> terms/rate-limit review -> country-wide run.

## Minimum production acceptance
- >=99.5% downloaded files parse as valid PDFs.
- 0 known false-positive AR classifications in validation sample.
- 100% completed files have SHA-256 and provenance.
- 0 final files with fabricated identifiers.
- Reruns are idempotent.
- Missing slots are explicit, never silently skipped.
