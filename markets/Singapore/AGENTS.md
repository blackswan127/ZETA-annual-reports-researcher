# SGX annual-report harvesting runbook

## Mission

Run this repository as a resumable bulk harvester of annual reports for current SGX Mainboard/Catalist issuers. When the user requests “N companies,” N means **distinct issuer profiles** (deduplicated by SGX IBM code), not N reports or company-year rows. Stage the cohort, complete the requested discovery and downloads, validate/audit results, and report completion without pausing after preparation.

## Defaults and cohort selection

- Unless specified, target fiscal/report years 2017–2025 inclusive. Use the project's SGX report-date/year interpretation; distinguish document/report year from broadcast/publication date and preserve the original dates.
- Resolve current Mainboard/Catalist issuer profiles at run time from SGX Corporate Information, union them with current Mainboard/Catalist stock counters, and deduplicate by IBM code. The universe includes reporting entities such as trusts and funds. Do not hard-code a company count or compare issuer profiles directly to a listed-securities count.
- On each successful refresh, reconcile SQLite issuer state with the current snapshot: mark/remove absent issuers from the active download/coverage universe while preserving their historic filings and PDFs. Do not let an old selected/pending issuer remain eligible merely because it is still in the manifest.
- Prefer a live counter code where SGX supplies one. For a profile-only issuer use its SGX IBM code as the stable identifier; never fabricate an exchange ticker from a historical metadata counter.
- For specific names/codes, resolve against the current roster and persist unresolved/ambiguous identities. For “next N companies,” maintain a durable cohort ledger keyed by IBM code, exclude issuers already complete for the requested years, and select the next N in stable identifier order. For a plain “N companies,” select N eligible unique issuer profiles in that order.
- The CLI currently has no issuer-count option, and its run/discover/download phases operate on the full database selection. A report limit must never be treated as a company limit. If company-scoped work is requested, implement/test a persisted issuer allow-list that filters discovery, attachment resolution, **and** download selection, or use a cohort-isolated manifest/output. Do not let an N-company batch download unrelated pending filings.
- Preserve `manifest.sqlite3` and existing outputs. Never reset state or delete completed PDFs to start a cohort.

## Official SGX sources and classification

- Use only SGX Corporate Information, `securities/v1.1/stocks`, `marketmetadata/v2`, `financialreports/v1.0`, and the official SGX announcement-detail/PDF links described in `SOURCES.md`.
- Keep the issuer-profile universe distinct from security-counter totals. Treat these sources as dynamic and record the roster snapshot/run date in the audit summary.
- The global financial-reports feed is the first discovery pass; retain its page completeness checks and the targeted company-name recovery for unresolved years. Do not silently skip pagination or turn API errors into “no report.”
- Only exact annual-report records qualify under the current classifier. Exclude interim/half-year, quarterly, ESG/sustainability-only, circulars, AGM/proxy, governance notices, and supplements. Preserve split-file annual reports only when attachment scoring identifies actual report parts; keep every candidate and ambiguous result in the audit.
- Treat `NO_FILING_FOUND` as a coverage/audit state, not necessarily a downloader error: issuers may have listed later, changed names, or lack an SGX report for that year. Never inflate coverage with non-annual documents.

## Required execution

1. Inspect current output/database state; establish the requested issuer count, report years, cohort rule, and an auditable batch ID.
2. Run `py -m pytest -q` before any behavioral code change and after it. Add fixtures for SGX response changes, pagination, code/name mapping, title classification, and cohort boundaries as relevant.
3. Refresh the live issuer profile/counter universe and persist the exact selected cohort before discovery. The generated `audit/issuers.csv` should be the reproducible cohort evidence.
4. Discover the requested years from the paginated financial-reports feed, persist candidates and scan outcomes in SQLite, run targeted recovery only for genuinely uncovered issuer-years, and keep failed queries separate from missing filings.
5. Select one strongest candidate per issuer/FY while preserving alternatives. Resolve official PDF attachments before queueing transfers; reject notices, proxies, ESG supplements, and unrelated appendices.
6. Download only the selected cohort's queue. Keep bounded concurrency and backoff; stream to `.part`; resume only when range semantics are valid; check `%PDF-`; atomically commit; record byte size and SHA-256 in SQLite. Never overwrite a validated PDF with an incomplete transfer.
7. Resume failed/pending work, regenerate audits, and inspect `coverage.csv`, `unmapped_annual_reports.csv`, `multiple_annual_candidates.csv`, and failed-download outputs. Preserve unresolved company-years rather than silently dropping them.

## Smoke test and final accounting

- Any SGX source-contract change requires updated fixtures and a live S68 smoke test before production harvesting. The current `smoke` command checks current-universe membership, S68 annual-report discovery, and official PDF attachment resolution; it does **not** download a complete PDF.
- For a new transfer implementation, download one authorized representative report through the real downloader and validate full file size, SHA-256, PDF structure/readability, and database state before broadening the batch.
- Report companies requested/selected, issuer snapshot count and date, issuer-years requested, annual candidates, verified PDFs, failed downloads, unresolved slots, elapsed time, throughput, and output path separately. Do not report security rows or report count as company count.
- Claim completion only when all in-scope transferable reports are validated and no in-scope failed/pending work remains. Keep `NO_FILING_FOUND`, multi-file edge cases, and semantic review items explicit.

## Change safety

- Keep refresh, discovery, selection, attachment resolution, download, and audit independently resumable.
- Do not bypass authentication, WAF, CAPTCHA, throttling, or access controls. Honor published SGX restrictions and backoff responses.
- Update `SOURCES.md`, `README.md`, and fixture tests for endpoint/contract changes. Preserve SQLite compatibility with a migration; never discard user state to make a change easier.
