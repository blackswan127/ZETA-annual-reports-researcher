# Architecture

```text
DSE current directory
       |
       v
/company/TICKER profile ----> instrument filter (Equity only)
       |                      website / financials URL / FYE / board
       v
CDBL ISIN list -------------> conservative name -> ISIN enrichment
       |
       v
optional GLEIF exact match -> LEI
       |
       v
SQLite issuers + expected_slots FY2017..FY2025
       |
       +--> Authorized manifest (priority 100)
       |
       +--> DSE-provided issuer Financial Statement URL (priority 92)
       |
       +--> issuer IR repair crawler (priority 75)
       |
       v
candidate classification + fiscal-year inference
       |
       v
best candidate per issuer/FY
       |
       v
concurrent streaming downloader
       |
       +--> .part resume / HTTP Range
       +--> 429/5xx retry & backoff
       +--> %PDF + pypdf validation
       +--> SHA-256
       |
       v
identity complete? ---- no ----> work/staging/unresolved_identity
       |
      yes
       v
GLOBAL_SUSTAINABILITY_DATABASE/BGD/XDHA/LEI_ISIN_Ticker/FYyyyy/exact_ZETA_filename.pdf
       |
       v
coverage.csv + repair_queue.csv
```

## State model

Each current equity issuer has nine expected slots by default: FY2017..FY2025.

- `MISSING`: no accepted annual-report candidate yet.
- `FOUND`: candidate selected, not yet successfully downloaded.
- `DONE`: validated PDF stored/staged and hashed.
- `FAILED`: selected candidate failed download/validation and is eligible for retry.

## Why discovery and downloading are separated

Discovery is lightweight and should be repeatable without downloading PDFs. Downloads are performed only after source classification, year inference and source-priority selection. This reduces duplicate traffic and makes retries deterministic.
