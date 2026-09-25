# Sources and endpoint notes

Checked during build: 24 September 2026.

## NSE

Current main-board equity master:
`https://archives.nseindia.com/content/equities/EQUITY_L.csv`

NSE annual-report page:
`https://www.nseindia.com/companies-listing/corporate-filings-annual-reports`

Dedicated annual-report API:
`https://www.nseindia.com/api/annual-reports?index=equities&symbol=RELIANCE`

The API returns structured rows including `companyName`, `fromYr`, `toYr`, `submission_type`, `broadcast_dttm`, and `fileName`. Historical rows can point to ZIP archives as well as PDFs.

NSE May 2026 corporate presentation (2,979 total companies listed as of 31 Mar 2026):
`https://nsearchives.nseindia.com/web/mediaattachment/2026-05/NSEIL_Corporate_Presentation_May_2026_20260515133050.pdf`

NSE Terms of Use / data policies must be reviewed before use. The project does not attempt to defeat access controls.

## BSE

Active equity-security list API used by established BSE client implementations:
`https://api.bseindia.com/BseIndiaAPI/api/ListofScripData/w`

BSE annual-report page pattern:
`https://www.bseindia.com/stock-share-price/stockreach_annualreports.aspx?scripcode=<SCRIP>`

BSE company-announcement API (optional deep fallback):
`https://api.bseindia.com/BseIndiaAPI/api/AnnSubCategoryGetData/w`

Historic direct annual-report files are commonly found under:
`https://www.bseindia.com/bseplus/AnnualReport/...`

Recent filing attachments are commonly served from:
`https://www.bseindia.com/xml-data/corpfiling/AttachHis/...`

Latest official BSE market-statistics snapshot found during build:
4 Nov 2025 16:00 — 5,032 companies with listed equity capital; 518 suspended; 4,514 available for trade.

## Design rule

The project does not treat the NSE and BSE headline counts as additive. It deduplicates issuer records primarily by ISIN and emits both raw-exchange counts and the deduplicated union.
