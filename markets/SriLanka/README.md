# Sri Lanka CSE ZETA Annual Reports Bulk Downloader

Production-oriented downloader for current Colombo Stock Exchange issuers, FY2017-FY2025.

## Source architecture
- Current universe: CSE `alphabetical` A-Z endpoint; fallback `todaySharePrice`.
- Annual-report archive: `POST https://www.cse.lk/api/financials` with `symbol`.
- Primary records: `infoAnnualData` only.
- PDF host: `https://cdn.cse.lk/`.
- Legacy 2012-2018 archive paths are normalized with the `cmt/` prefix when required.

The financial-history call is made once per issuer, not once per company-year.

## ZETA output
`GLOBAL_SUSTAINABILITY_DATABASE/LKA/XCOL/LEI_ISIN_Ticker/FY2024/LEI_LKA_XCOL_Ticker_ISIN_FY2024_AR_EN.pdf`

If LEI/ISIN is not verified, the file stays under `work/staging/unresolved_identity/`; identifiers are never fabricated.

## Windows
1. `install_windows.bat`
2. `run_smoke_test.bat`
3. Fill verified LEI/ISIN in `identity_overrides_TEMPLATE.csv` if needed.
4. `run_all_2017_2025.bat`
5. `run_repair_missing.bat`

The public CSE website endpoints are not a guaranteed developer API. Keep rates conservative and review CSE policies for your intended use. No access-control bypass is implemented.
