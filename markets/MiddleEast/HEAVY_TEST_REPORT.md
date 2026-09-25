# Middle East AR v2 — Heavy Source Test Report

Test date: 2026-09-25
Target: FY2017-FY2025 English Annual Reports for current-listed equity issuers.

## What was tested

For each core market the checks were:

1. Does a centralized exchange-level discovery surface exist?
2. Is English content available at the exchange level?
3. Can the source expose a direct PDF/document attachment?
4. Is FY2017-era history visible or otherwise evidenced?
5. Does the source expose a true combined Annual Report, or only annual financial statements?
6. Can the pipeline avoid crawling every issuer website?
7. What failure mode must the adapter handle before a whole-market run?

## Results

### Oman — PASS, strongest first rollout

Official MSX home/financial-reports interface exposes company, reporting period and explicit `AR EN` download links. This is unusually clean because the exchange itself identifies the English Annual Report object rather than forcing the crawler to classify all disclosures.

Production rule: use `AR EN` first. Only fall back to company IR for missing FY slots.

Risk: historical depth must be measured across a 100-company-year pilot; do not infer that every current issuer has all nine years simply because current `AR EN` is available.

### Jordan — PASS, very strong centralized history

ASE company disclosure pages have a dedicated `Annual Financial Report` category. Live historical pages show annual-report-category filings in 2017 and continue through recent years.

Production rule: discover centrally by issuer/category/date. Underlying PDF must still be language-checked and classified as `AR_FULL` or `ANNUAL_FS_COMPONENT`.

Risk: category name says Annual Financial Report, so some filings may be financial statements rather than a narrative annual report.

### UAE / DFM — PASS

DFM directly hosts English Annual Report PDFs on `feeds.dfm.ae`. Live samples include full 2023 and 2024 Annual Reports. Archive material also exists back into the 2017 period.

Production rule: exchange-hosted report/document feed is primary. Prefer documents explicitly labelled Annual Report. DFM feed URL becomes transport target; do not browser-render PDFs.

Risk: annual-results press releases and standalone financial statements also exist, so classifier must reject them as AR replacements.

### UAE / ADX — PASS

ADX provides centralized listed-company disclosures and direct CDN downloads through `apigateway.adx.ae`. Live samples include full English Annual Reports (e.g. Investcorp Capital 2024) and direct annual-report/financial-report PDF objects. ADX rules require companies to submit an annual report including board report, audited financials and auditor report within 90 days after fiscal year end.

Production rule: ADX disclosure API/CDN is primary. Use attachment metadata/title plus PDF first-page validation to distinguish full AR from annual FS.

Risk: older historical completeness should be benchmarked before full-market run.

### Saudi Arabia — PASS with stricter classifier

Saudi Exchange's disclosure system supports bilingual Arabic/English disclosures. Company profile pages expose a distinct `Annual Report` financial category alongside financial reports and quarterly reports. English Annual Report PDFs are directly hosted by Saudi Exchange for exchange/group publications, demonstrating transport behavior.

Production rule: query issuer financial category for `Annual Report`, require English attachment, resolve FY by report period/title, then download.

Risk: company-profile results can include multiple annual document types. Do not use annual financial statements as AR unless the PDF is actually a full report.

### Qatar — PASS, component-aware

QSE has one centralized Financial Statements page with an `Annual` column for all listed companies. Q-Disclosure became mandatory in October 2020 and is available in English; older financial disclosures are also indexed, including 2017-era annual financial statements.

Production rule: Q-Disclosure/Financial Statements is excellent discovery for annual filing components. A candidate becomes `AR_FULL` only if the attachment itself is a combined Annual Report. Otherwise persist `ANNUAL_FS_COMPONENT` and continue repair.

Risk: annual financial statements are not necessarily the full annual report.

### Bahrain — PASS for annual components, mixed for full AR

Bahrain Bourse company profiles expose historical year-end financial statements back through 2017 for long-listed issuers. English is standard on the site and direct PDFs exist. Exchange/company notices also state that Annual Reports can be made available in English and Arabic.

Production rule: use Bahrain Bourse profiles to resolve annual FS slots cheaply. Search exchange disclosures/issuer archive for true `AR_FULL` only when necessary.

Risk: profile history commonly labels the object `Financial Statements`, not `Annual Report`. Do not mislabel.

### Kuwait — PASS for structured annual filings, component-aware

Boursa Kuwait / IFSah exposes structured English annual financial statements and explicit reporting periods. Direct PDF documents exist, and the exchange offers Financial Statements as a data product. Live 2017 and 2024 annual materials prove historical/direct-document availability.

Production rule: IFSah is the primary annual-filing metadata source. Use frequency=Annual and English version. Classify the object as `ANNUAL_FS_COMPONENT` unless the attachment or package is explicitly a full Annual Report.

Risk: IFSah is excellent for audited statements but not every issuer/year yields a single narrative Annual Report.

## Architecture conclusions

### Recommended wave order

Wave 1 — cleanest full-report acquisition:
- Oman
- DFM
- Jordan

Wave 2 — strong centralized sources, moderate classification complexity:
- ADX
- Saudi Arabia
- Qatar

Wave 3 — excellent annual filing coverage but higher full-AR/component ambiguity:
- Bahrain
- Kuwait

### No issuer-by-issuer web crawling as primary discovery

Every core adapter begins at an exchange/centralized disclosure system. Issuer IR crawling is only a repair layer for slots that remain `MISSING_AR_FULL` after centralized discovery.

### Required benchmark before market-wide launch

For each exchange:
- 20 issuers x 9 FY slots (or all issuers if the market is smaller)
- measure discovery coverage
- English-document coverage
- `AR_FULL` precision
- direct-PDF success
- 403/429/5xx rate
- median metadata requests/issuer
- median download MB/s
- FY resolution precision

Do not scale until 0 known AR false positives are observed in the manually reviewed validation sample.
