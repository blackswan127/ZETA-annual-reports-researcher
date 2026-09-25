# ASX annual-report harvesting runbook

## Mission

Operate this project as a resumable downloader of annual reports for currently listed ASX companies. When the user says “download N companies,” interpret N as **distinct issuers**, not N PDFs, filing rows, or fiscal-year slots. Prepare the company cohort, discover reports, download them, validate the files, and report the audit in the same task. Do not stop after producing a manifest or asking whether to proceed.

## Defaults and cohort selection

- Unless the user specifies otherwise, use fiscal years 2017–2025 inclusive. ASX searches by **publication calendar year**; include the following publication year to find reports for the final requested fiscal year (`capture_following_year=True`). Keep publication year distinct from fiscal year.
- Resolve the current company list at run time through the ASX company-directory endpoint, with the official `ASXListedCompanies.csv` fallback. Do not substitute a security master containing ETFs, options, warrants, or other non-company instruments.
- For a specific ticker/company list, resolve it against the live universe and record unresolved or ambiguous names instead of silently substituting another issuer.
- For “next N companies,” maintain a durable cohort ledger (issuer ticker, name, chosen position, run ID, completed years, status). Exclude companies already completed for the requested years, then select the next N in stable ticker order. For an unqualified “N companies,” use the first N eligible companies in stable ticker order.
- `download --limit N` limits **reports**, not companies. Never use it to satisfy an N-company request. The CLI's `discover --ticker` filters discovery, but the download queue is database-wide: use an isolated cohort output/manifest or add and test an issuer filter to both stages before invoking download. Never allow the selected cohort's run to download unrelated pending issuers.
- Preserve the normal output root and SQLite `manifest.sqlite3`. Do not delete or replace existing state. An isolated batch may use a dedicated child output directory with its own manifest; record its relationship to the parent cohort ledger.

## ASX access and source rules

- Before every live operation, honor `ASX_ACKNOWLEDGE_TERMS=1`. The launcher's `YES` response is the intended acknowledgement path. If acknowledgement is absent, stop before making requests and ask the user to review the exchange terms and acknowledge. Never set or bypass the gate on the user's behalf.
- Use the current ASX directory/official listed-company CSV for current issuers and the official historical announcements search for history. Do not replace the historical search with the modern per-company announcements JSON; it is capped to recent announcements and cannot provide the 2017–2025 archive.
- Keep the configured metadata/download rate limits and server `Retry-After` behavior. Do not evade blocks, CAPTCHAs, authentication, or access restrictions. Commercial/systematic use requires any permissions ASX's terms require.
- Select genuine annual reports. Reject half-year/quarterly, ESG/sustainability, governance-only, AGM/proxy, dispatch-only, results-only, and supplementary-information documents. A combined Appendix 4E plus annual report may qualify if the actual report is present.
- Treat explicit reporting-period years as fiscal years. Keep publication-date-derived years marked as heuristic and include them in `heuristic_years.csv` for audit; never silently present a heuristic as confirmed.

## Required execution

1. Inspect the existing output manifest and audits; record the requested fiscal-year range and whether the request is all eligible companies, a named cohort, or the next N not yet completed.
2. Run offline tests before changing behavior: `py -m pytest -q`. For a source/parser/classifier/downloader change, add fixture coverage and rerun the full suite.
3. Refresh and persist the current issuer universe before discovery. Save the exact selected company cohort to a CSV/manifest before querying reports. Do not count a ticker multiple times.
4. Discover historical ASX announcements for selected tickers and all needed publication years. Persist each ticker/year scan outcome (`DONE` or `FAILED`) and all candidates before file transfer. Retry failed scans; do not interpret a technical failure as “no filing.”
5. Select the best supported report per company/FY while retaining all candidates. Resolve each selected announcement to its official PDF URL, then download with the project's bounded workers and rate limits.
6. Stream to `.part`, retain partial bytes only for resumable transfers, verify the PDF signature and completed transfer, atomically rename, compute SHA-256, and record the local path and digest in SQLite. Never overwrite a valid completed PDF with a partial file. A PDF signature proves file type, not report identity or semantic completeness.
7. Export and inspect `issuers.csv`, `coverage.csv`, `missing.csv`, `multiple_candidates.csv`, `heuristic_years.csv`, and `failed_downloads.csv`. Resume failed/missing transfer work until no authorized work remains or a genuine source/rate/terms blocker prevents progress.

## Live smoke and reporting

- Before a production run after any ASX source-contract change, run the user-authorized ASX smoke test (default BHP, FY2025) and confirm current-universe resolution, historical result parsing, official PDF URL resolution, and initial `%PDF-` bytes. A smoke test does not certify full-file transfer.
- For download verification, complete at least one authorized representative PDF through the real downloader; inspect the PDF, page count/text when a parser is available, byte count, SHA-256, and audit state. Do not claim the entire cohort is verified based on one sample.
- Report distinct companies requested/selected/completed, report-year slots requested, candidates found, PDFs verified, failed and unresolved slots separately; include universe snapshot date, fiscal years, elapsed time, output path, and the exact reason for any blocker. `MISSING` is not a transfer failure unless a report was expected and evidence supports that conclusion.
- Never claim complete coverage while failed scans, unresolved titles, ambiguous years, failed downloads, or unreviewed candidates remain. Preserve those states in the audit.

## Safe implementation changes

- Keep issuer refresh, discovery, selection, downloading, and audit as separate resumable phases.
- Before increasing concurrency, fix data/source/classification mistakes and prove the change with deterministic fixtures. Any added company-cohort feature must filter both discovery **and** download queues and test that no out-of-cohort issuer is transferred.
- Update `SOURCES.md`, `README.md`, and tests when endpoint or source semantics change. Retain SQLite schema compatibility or write a migration; never solve a migration problem by deleting the user's manifest.
