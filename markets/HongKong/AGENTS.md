# HKEX annual-report harvesting runbook

## Mission and company-count meaning

Operate this repository as a resumable bulk downloader for current HKEX-listed issuers' annual-report PDFs. Interpret “N companies” as N **distinct current issuer stock codes** in the selected annual-report cohort, not N securities, raw filings, PDF parts, or fiscal-year slots. Carry a user request from universe selection through validated downloads and audits in the same task; do not stop at discovery or ask whether to begin after staging.

- Default fiscal-year range is 2017–2025 unless the user specifies another range. Publication searches must include the needed following-year window; report/FY year and publication date are separate values.
- `activestock_sehk_e.json` is an active **securities** list, not a company master. Never describe its raw row count as a company count. The working annual-report issuer cohort is the distinct active stock codes with qualifying annual-report filings in the requested FY range.
- For official exchange-wide company totals use `python run.py companies`; record the official month-end as-of date, Main Board total, GEM total, and total. Keep this statistic separate from the active-securities count and the report-producing issuer cohort.
- For “next N,” keep a durable cohort ledger of stock code, issuer name, years requested, selected filing IDs, validated years, status, and run ID. Exclude issuers complete for that requested scope. For a new N-company cohort, choose distinct eligible active stock codes in deterministic numeric/code order. Preserve aliases and multi-code filings in the underlying evidence.
- `--limit-reports N` caps **PDF reports**, not companies. Do not use it for an N-company request. The current `all`/`discover` path is global and the download selector is report-based; implement and test an issuer allow-list through both selection and transfer, or use a cohort-isolated manifest/output, before claiming an exact company-limited run. A batch must not download unrelated pending issuers.

## HKEX source contract

- Use HKEXnews's official active securities JSON and title-search servlet, with Annual Report headline category codes `t1code=40000`, `t2code=40100`, `t2Gcode=-2`, and official HKEXnews `FILE_LINK` document URLs. These are public website interfaces and can change; do not substitute third-party mirrors by default.
- Retain the current active-list intersection and its correct semantics. Refreshing the active list must replace the current snapshot (or explicitly deactivate codes absent from the new snapshot) so a delisted code in old SQLite state cannot be called current. Preserve historical filings/downloads separately for audit.
- Preserve adaptive date-window splitting whenever results are saturated or `hasNextRow` is true. Never quietly accept a truncated result set. If a single-day search remains saturated at the maximum row limit, mark it unresolved for manual follow-up rather than claiming full coverage.
- Keep all candidates in SQLite. Select one best supported primary report per active stock code/FY; retain duplicate candidates and flag multi-file wrappers. Never label a multi-file wrapper or attachment set as one valid PDF unless its pieces have been safely resolved and validated.
- Infer fiscal year from title/period evidence first. Preserve `year_source` and `year_confidence`; publication-date heuristics remain low-confidence and visible in `ambiguous_years.csv`. Do not silently fill missing years with another year or report type.
- Do not count pre-listing periods as missing. Audit missing coverage only after the first observed target-year report and keep the official company-count statistic separate from the annual-report cohort count.

## Required execution for a plain-English batch

1. Read the existing `output/manifest.sqlite3`, CSV audit state, user-specified company count, FY range, and whether the request means named companies, the next N, or a new N-company cohort. Preserve run history and the requested cohort in a durable manifest.
2. Run `python -m unittest discover -s tests -v` before behavior changes and after them. Add fixtures for servlet pagination/saturation, current-code replacement, code matching, FY confidence, and out-of-cohort filtering when relevant.
3. Refresh active securities and obtain the official listed-company total/date. Print all three values with precise labels: active securities, official listed companies, and distinct active codes with qualifying report candidates.
4. Search global annual-report date shards across publication years required by the target FYs. Commit each shard to SQLite before continuing; adaptively split saturated windows; deduplicate by `NEWS_ID`/official file link.
5. Intersect records to the refreshed active stock-code set, normalize each candidate, assign FY/confidence, preserve all candidates, and select the primary report for each in-scope issuer/FY.
6. Download only selected, in-scope rows at configured rates/workers. Keep transient `.part` files for valid resume; restart safely if the server ignores Range; validate complete content and `%PDF-` before atomic rename; record HTTP status, bytes, SHA-256, path, and state in SQLite. Existing DONE files must be revalidated before skipped.
7. Multi-file rows, invalid/missing URLs, unresolved years, and exhausted failures stay explicit in audit outputs. Continue retrying pending/failed authorized work with backoff; do not loosen quality checks to improve the coverage number.
8. Run audit/status and inspect coverage, ambiguous-year, multi-file, and failed-download outputs before reporting.

## Safe scaling and completion claims

- Defaults are 2.5 metadata requests/sec, 8 PDF requests/sec, and 16 workers. Respect `Retry-After`, HKEX access restrictions, and configured bounds; never bypass access controls or multiply rate budgets across processes.
- Source-contract changes require unit fixtures and an updated live smoke-test workflow. `smoke` refreshes the current active list and verifies a requested stock code's annual category search; it does not verify a full PDF transfer. Before broadening a changed downloader, complete one representative official PDF transfer and verify its readable page structure, bytes, hash, and database state.
- Report companies requested/selected/completed, FY slots, raw annual-category rows, active matched issuers, selected primary reports, validated PDFs, pending/failed/unresolved cases, elapsed time, throughput, as-of date, and output path separately.
- Claim completion only when every in-scope transfer is validated and no in-scope pending/failed work remains. `NO_FILING_FOUND`, low-confidence years, and special multi-file filings remain auditable exceptions, not silent successes.

## State and safety

- Keep discovery and download as separate resumable stages. The SQLite manifest is the source of truth; never delete it to rerun a job.
- Do not bypass CAPTCHA, login, WAF, authentication, access controls, or published rate restrictions. Honor applicable HKEX data-use terms.
- Update `SOURCES.md`, fixtures/tests, and smoke workflow when endpoints or response contracts change. Make migrations explicit and non-destructive.
