# Test report — ASX Annual Reports Bulk Downloader v1.0.0

Date: 2026-09-24

## Offline deterministic tests

Result: **13 passed**.

Covered behaviours:

1. Accepts realistic ASX annual-report titles.
2. Rejects half-year, quarterly, sustainability, governance, AGM, dispatch-only and supplementary false positives.
3. Extracts explicit FY/year and applies auditable publication-date fallback when a title contains no year.
4. Parses official ASX historical announcement table structure.
5. Extracts announcement `idsId` and page/size metadata.
6. Extracts the ASX hidden `pdfURL` target from an announcement display page.
7. Creates SQLite issuer/slot/filing/download state.
8. Selects the strongest candidate when multiple annual-report candidates exist.
9. Exports coverage/audit CSVs.
10. Streams a PDF and resumes an existing `.part` file with HTTP Range.
11. Rejects HTML returned in place of a PDF.
12. Parses/deduplicates the current-company directory response.
13. Blocks network access unless ASX terms acknowledgement is explicitly enabled.

Additional checks:

- `python -m compileall -q src` — PASS
- CLI argument/help load — PASS
- editable package build/install with no build isolation — PASS

## Live-source verification

The build container has no direct outbound DNS, so the packaged CLI itself could not perform a live network smoke test here. Current source behaviour was independently checked through live web access before packaging:

- ASX current company directory is available on the ASX site/front-end data service.
- Official historical announcement search supports company + calendar-year pages.
- Live 2025 pages show annual-report variants such as `Annual Report for Year Ended 2025`, `FY25 Annual Report and Financial Statements`, `2025 Annual Report`, and combined `Appendix 4E and Annual Report` titles.
- The modern per-company ASX JSON announcement endpoint is unsuitable for historical harvesting because current independent live testing shows a hard latest-five cap.
- ASX announcement access/terms restrict automation/commercial usage unless permitted; the project therefore ships with a mandatory acknowledgement gate and no access-control bypass.

Run `run_smoke_test.bat` on the target Windows machine before launching the mass corpus.
