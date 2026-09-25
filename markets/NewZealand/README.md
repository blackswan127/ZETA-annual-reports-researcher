# New Zealand NZX — ZETA Annual Reports Bulk Downloader

Production-oriented annual-report harvester for **current NZX equity issuers** and **FY2017–FY2025**, built to follow the ZETA-AI folder/file SOP.

## Why this architecture

NZX's Main Board contains both equities and funds, so raw instrument count is not a company count. The pipeline enumerates the current NZSX board, resolves each company profile, and keeps equity issuers while excluding obvious funds/debt products. The exact current issuer count is written at runtime to `work/audit/universe_summary.csv`.

NZX annual-report discovery is unusually structured:

- many company `Documents` pages expose direct `Annual Report - YYYY` PDFs;
- market announcements use the dedicated `ANNREP` type for annual reports;
- NZX also sells/licences historical data products such as Company Research Centre and i-search, which are the preferred source for commercial or industrial-scale historical collection;
- issuer investor-relations websites are used as a repair/fallback source.

## ZETA SOP output

Country ISO-3: `NZL`

Exchange MIC: `XNZE`

Final hierarchy:

```text
GLOBAL_SUSTAINABILITY_DATABASE/
└── NZL/
    └── XNZE/
        └── LEI_ISIN_Ticker/
            └── FY2025/
                └── LEI_NZL_XNZE_Ticker_ISIN_FY2025_AR_EN.pdf
```

The fiscal year is the period covered by the report, **not publication year**.

If LEI or ISIN is unresolved, the PDF is kept in:

```text
work/staging/unresolved_identity/TICKER/FYyyyy/
```

It is not admitted to the final ZETA tree until identity is complete.

## Source priority

1. `NZX_AUTHORIZED` — normalized licensed/authorized NZX historical export or local delivery
2. `NZX_DOCUMENTS` — company Documents page direct annual-report PDF
3. `NZX_ANNREP` — annual-report announcement/attachment records when supplied through an authorized export
4. `ISSUER_IR` — official issuer investor-relations website repair path

## Windows quick start

1. `install_windows.bat`
2. `run_smoke_test.bat`
3. optionally fill `templates/identity_overrides.csv`
4. optionally normalize an authorized NZX export to `templates/authorized_nzx_manifest.csv`
5. `run_all_2017_2025.bat`
6. inspect `work/audit/coverage.csv`
7. run `run_repair_missing.bat` until the remaining queue is understood

## Important access/licensing note

NZX's public Website Terms state that website content may not be used/copied/modified for purposes other than viewing information about NZX products/services, and NZX separately offers data products/licensing. The public-site adapter therefore requires an explicit `NZX_ACKNOWLEDGE_TERMS=1` acknowledgement and does not bypass login, CAPTCHA, paywalls, robots, or other access controls. For a commercial ZETA corpus, use an authorized NZX Data Product/Company Research Centre/i-search delivery as the primary source.

## Expected-slot model

For each current issuer the system creates nine slots:

`FY2017 ... FY2025`

Each slot becomes one of:

- `MISSING`
- `FOUND`
- `DONE`
- `FAILED`

A successful download is not considered final merely because a URL returned HTTP 200. The project checks PDF signature, parses the PDF, requires at least two pages, hashes the result, and commits it atomically.

## Audit files

`work/audit/` contains:

- `universe_summary.csv`
- `issuers.csv`
- `coverage.csv`
- `missing.csv`
- `repair_queue.csv`
- `identity_missing.csv`
- `candidates.csv`
- `source_profiles.csv`

## Current-universe logic

The live NZSX board is the starting point. Each code is resolved through its NZX company page to collect company name, ordinary-share ISIN, website, listing venue and financial-year end. Funds, bonds, notes, ETFs, warrants, options and debt instruments are rejected.

This intentionally avoids hard-coding a stale number of companies.

## Identifier rules

NZX company pages normally expose the security ISIN. LEI is not invented. You can supply verified LEIs through `templates/identity_overrides.csv`; optional GLEIF exact-name enrichment is available through the CLI `universe --gleif` path, but only a single exact legal-name match is accepted.

## Authorized historical manifest

The normalized manifest may be CSV, JSON or JSONL. Useful fields:

```text
ticker,title,fiscal_year,document_url,local_path,announcement_type,announcement_id,publication_date
```

`document_url` or `local_path` can point directly to the report. Local bulk deliveries are ingested without downloading them again.

## Resume and failure recovery

Downloads stream to `.part`. If the server supports HTTP Range, interrupted files resume. Completed PDFs are atomically renamed only after validation. SQLite uses WAL mode and stores issuers, expected slots, candidates, download state, source priorities, discovery state and events.

Rerunning is safe; completed slots remain completed.

## Performance

Start with the normal launcher. Only move to `run_fast_2017_2025.bat` after the smoke test and an initial bounded run are stable. Higher concurrency is not automatically faster if the remote source throttles requests.

## Testing

Run:

```bash
python -m pytest -q
```

The deterministic suite uses local fixtures; it does not require NZX network access.

## Multi-PC sharding

For two machines/processes:

```bash
nzx-zeta --work work_0 --zeta-root E:\GLOBAL_SUSTAINABILITY_DATABASE --shard-count 2 --shard-index 0 --start-year 2017 --end-year 2025 run
nzx-zeta --work work_1 --zeta-root E:\GLOBAL_SUSTAINABILITY_DATABASE --shard-count 2 --shard-index 1 --start-year 2017 --end-year 2025 run
```

Shard membership is based on a stable SHA-256 hash of the ticker, so shards are deterministic and disjoint.
