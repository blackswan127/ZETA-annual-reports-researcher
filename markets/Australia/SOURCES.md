# Source notes

Primary ASX sources used by the project:

- Current company directory API: `https://asx.api.markitdigital.com/asx-research/1.0/companies/directory?itemsPerPage=2500`
- Current listed-company CSV fallback: `https://www.asx.com.au/asx/research/ASXListedCompanies.csv`
- Historical announcements: `https://www.asx.com.au/asx/v2/statistics/announcements.do?asxCode=CODE&by=asxCode&timeframe=Y&year=YYYY`
- Announcement display/PDF resolution: links emitted by the historical search and the `pdfURL` field on ASX's display page.

Verified examples include official ASX historical pages showing titles such as `Annual Report for Year Ended 2025`, `FY25 Annual Report and Financial Statements`, and `2025 Annual Report`.

The modern ASX front-end JSON per-company announcement feed is intentionally not used for history because independent live testing shows it is capped to the latest five announcements regardless of requested count.

## Rights/terms

The ASX announcement display page states that private/personal access is free but commercial use requires express written authority from ASX. This project requires an explicit acknowledgement environment variable before network access and does not include any access-control bypass.
