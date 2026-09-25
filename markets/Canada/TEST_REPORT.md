# Test Report

Build target: Canada ZETA Annual Reports Bulk Downloader v1.0.0

Deterministic tests cover:

- TSX/TSXV universe parsing and product filtering
- exchange MIC normalization
- annual-report positive/negative classification
- fiscal-year inference
- exact ZETA folder/filename generation
- hard refusal of final paths with missing identifiers
- authorized SEDAR manifest matching
- authorized local-file manifest conversion
- source-priority selection
- expected-slot creation
- identity overrides
- universe-summary + repair-queue export
- PDF validation
- issuer-site candidate extraction
- deterministic sharding
- HTTP downloader PDF acceptance
- HTML rejection
- licensed local-file downloader
- access-policy guard behavior

Release validation before packaging:

- `24 passed` deterministic tests
- Python compile check passed
- CLI help/entrypoint check passed
- wheel build passed using installed local build tools (`--no-build-isolation`)
- clean offline universe/audit smoke passed
- final ZIP is extracted and the same suite is rerun before delivery

Live-source note: public SEDAR+ scraping is intentionally not part of testing. The production regulatory path requires an authorized DDS input. Issuer-site live behavior should be smoke-tested from the operator's network because websites and robots policies can change.
