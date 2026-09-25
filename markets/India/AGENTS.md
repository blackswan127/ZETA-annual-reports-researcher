# India NSE/BSE annual-report harvesting runbook

## Mission and batch semantics

Operate this repository as a resumable annual-report harvester for currently listed NSE and/or BSE equity issuers. A request for “N companies” means N **distinct issuers after NSE/BSE deduplication**, not N exchange rows, reports, ZIP members, or issuer/FY slots. Complete universe resolution, discovery, source fallback, downloading, validation, and audit autonomously in the same task; do not stop after staging.

- Unless the user states another range, use fiscal years ending 2017–2025 inclusive. NSE's `toYr` is the fiscal-year-end year: FY 2024–25 maps to 2025. Keep publication date, from-year, and to-year separate.
- Refresh both current NSE equity universes (main board and SME, unless explicitly excluded) and BSE active equity groups at runtime. Merge dual-listed issuers primarily by valid ISIN, preserving NSE symbol, SME status/series, BSE scrip, group, and provenance. Do not add exchange headline counts; report NSE rows, BSE rows, dual-listed, NSE-only, BSE-only, and the deduplicated issuer count separately.
- For a named company, resolve its identifiers against the live refreshed roster and retain both exchange identifiers where available. For “next N companies,” use a persistent cohort ledger keyed primarily by ISIN, exclude issuers already complete for the requested fiscal-year range, then select the next N in deterministic ISIN/code order. If the user only says “N companies,” take N eligible distinct issuers in that order.
- `download --limit N` limits **reports**, not companies. Never treat it as an N-company cap. This CLI has no company filter on download; implement and test a durable issuer allow-list that constrains discovery and download, or use an isolated cohort output/manifest. Do not run a cohort against a shared queue that can include other issuers' pending reports.
- Preserve `manifest.sqlite3`, prior batch ledgers, and PDFs. Do not delete output or state to restart a batch. Use separate output roots for shards/cohorts that may execute concurrently.

## Official sources and priority

- NSE: use the official current equity CSVs and dedicated annual-reports page/API (`index=equities` or `index=sme`, symbol-specific), keeping `fromYr`, `toYr`, `submission_type`, broadcast timestamp, filename, and source URL. Prime the official filing page as implemented. On 401/403, use only the supported session-refresh behavior; if access still fails, stop/retry later and record it. Never evade a challenge.
- BSE: use the official active-equity list by configured security groups, the official annual-report page, and—only when enabled and still needed—the bounded annual-report announcement API fallback. The BSE announcement fallback is expensive and remains off by default; enable it only for audited missing BSE slots after the primary NSE/BSE-page paths.
- Prefer the NSE annual-report API for NSE-listed issuers; use BSE annual-report page for BSE-only issuers and as the configured fallback for uncovered dual-listed issuer-years. Keep every source candidate and source choice in SQLite.
- A partial NSE/BSE universe is not a complete universe. The current source adapter can skip inaccessible BSE groups and optional NSE SME data after errors; expose those omissions in audit output, retry them, and do not claim complete coverage/counts while a required group/list is unresolved. Distinguish deliberate SME exclusion from a failed SME fetch.
- Do not bypass NSE/BSE terms, CAPTCHA, authentication, access restrictions, or rate limits. Keep the `INDIA_AR_ACKNOWLEDGE_TERMS=1` gate. If it is absent, stop before network calls and request the user's explicit review/acknowledgement of applicable terms; do not set it yourself.

## Candidate and artifact rules

- Keep every NSE/BSE candidate even when one is selected. Choose one best-supported annual report per issuer/FY and retain alternatives/multi-file records for audit.
- Use the strict FY-end year (`toYr`) from NSE. For BSE candidates, derive FY from the actual reporting period/title where possible and retain source/confidence evidence. Do not use publication year as a silent substitute for fiscal year.
- Download PDFs and NSE ZIP archives as streamed files; never load whole reports into RAM. Resume `.part` only with valid range semantics, restart cleanly when Range is ignored, validate `%PDF-` or ZIP signature, safely extract archive entries (no path traversal), retain every legitimate report part, record which part is selected as primary, and hash final PDFs.
- ZIPs containing multiple PDFs must retain all valid parts and be explicitly flagged in `multi_file_archives.csv`; do not silently discard pieces or claim the largest PDF is semantically the complete annual report.
- Treat network errors, 401/403, 429, 5xx, HTML challenge pages, malformed API output, absent source rows, and true no-filing cases as distinct states. Never convert a failed exchange request into `MISSING`/no report.

## Required execution for “download N companies”

1. Inspect the current output database/audits and cohort ledger. Translate the request into N unique deduplicated issuers, fiscal years, and whether the cohort is named, new, or “next N.”
2. Run `.venv\Scripts\python -m pytest -q` before behavior changes and after them. Add deterministic fixtures for identifier merging, NSE/BSE source priority, BSE group/SME omissions, FY parsing, ZIP safety, resumability, and cohort limits as relevant.
3. With user authorization, refresh NSE/BSE lists, validate/deduplicate identifiers, write `universe_summary.csv` and the exact selected cohort manifest, and resolve all BSE group/SME fetch errors. Never count dual-listed companies twice.
4. Discover NSE annual reports first where available; discover BSE-only issuer reports and targeted BSE fallback for uncovered slots. Commit each issuer's candidates and discovery state to SQLite; keep retryable failures distinct from no-filing results.
5. Select the best candidate per issuer/FY without discarding alternatives. For unresolved eligible BSE slots, run the deep BSE announcement fallback only when the user request and audited gap justify its additional traffic.
6. Download the selected cohort queue using configured exchange-specific rates and bounded workers. Check transfer completeness and file signatures before atomic finalization, compute SHA-256, record bytes/path/source/attempts in SQLite, and resume interrupted work. Do not exceed exchange limits to meet a deadline.
7. Regenerate and inspect `universe_summary.csv`, `coverage.csv`, `missing.csv`, `multiple_candidates.csv`, `failed_downloads.csv`, `multi_file_archives.csv`, and `source_counts.csv`. Retry authorized transient failures and leave genuine unresolved records visible.

## Completion and reporting

- Before expanding a changed parser/source/downloader to a large run, use the authorized NSE `RELIANCE` smoke test or an equivalent current issuer, then complete a representative full PDF/ZIP through the real downloader and verify structure, content, bytes, hash, and SQLite state. A first-byte smoke is not full-download proof.
- Report distinct issuers requested/selected/completed; NSE/BSE/deduplicated universe counts and snapshot date; issuer/FY slots; selected candidates; verified PDFs; ZIP multi-part cases; failed and unresolved source slots; elapsed time; throughput; and output path separately.
- Claim completion only when every requested cohort transfer is validated and no in-scope retryable or failed work remains. Keep `MISSING`, multi-part archives, low-confidence FYs, and incomplete exchange-universe fetches explicit. Do not equate structurally valid PDFs with semantic issuer/year confirmation.
- Update `SOURCES.md`, tests, and this runbook whenever source priority or endpoint behavior changes. Preserve SQLite state and write explicit migrations instead of deleting user data.
