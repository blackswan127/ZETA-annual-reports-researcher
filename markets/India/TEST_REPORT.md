# Test report

Build date: 24 September 2026

## Deterministic test suite

Result: **15 passed / 15 total**.

Coverage includes:

- NSE company CSV parsing
- NSE annual-report API parsing
- PDF vs ZIP detection
- BSE active-security JSON parsing
- ISIN-based NSE/BSE deduplication
- BSE legacy annual-report year extraction
- Annual Report positive classification
- Annual Return / BRSR false-positive rejection
- Indian FY-end parsing (`2024-25`, `FY2023`, `year ended March 31, 2022`)
- NSE-over-BSE candidate priority
- CSV audit creation
- safe filenames / ISIN validation
- deterministic multi-machine sharding
- terms-acknowledgement network gate
- PDF streaming
- HTTP Range resume from `.part`
- ZIP extraction and largest-valid-PDF primary selection
- zip-slip-safe basename extraction
- HTML/non-document rejection

(The suite contains 15 pytest test functions; several functions assert multiple behaviors.)

## Live-source verification

The build environment used for packaging does not provide normal outbound DNS/network access to the Python runtime, so the packaged CLI was not used to perform a full live mass crawl from that environment.

Separately, live web verification during construction confirmed:

- NSE's current dedicated annual-report page/API exists.
- A live RELIANCE annual-report API response returns structured fiscal-year rows and official `nsearchives.nseindia.com/annual_reports/...` attachments.
- Both PDF and older ZIP annual-report formats occur in that API.
- NSE's May 2026 corporate presentation reports 2,979 total listed companies as of 31 March 2026.
- BSE exposes current equity-market statistics and official annual-report/corporate-filing document paths.

`run_smoke_test.bat` performs the required live check on the user's authorized network before starting the corpus.

## First-run rule

Do not start the mass run unless `run_smoke_test.bat` prints `SMOKE TEST PASS`.
