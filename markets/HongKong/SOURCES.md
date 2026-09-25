# Technical sources used for endpoint design

- HKEXnews Title Search (official): https://www1.hkexnews.hk/search/titlesearch.xhtml?lang=en
- HKEXnews active securities JSON (official): https://www1.hkexnews.hk/ncms/script/eds/activestock_sehk_e.json
- hkex-tools reference implementation: https://github.com/leofisG/hkex-tools
- Filings Atlas HK adapter reference: https://github.com/Eric-KY-Zhang/Filings-Atlas
- HKEx Annual Report Downloader reference for category codes: https://github.com/fatal-cling/HKEx-Annual-Report-Downloader

Observed Annual Report headline category:
- t1code=40000
- t2code=40100
- t2Gcode=-2

The HKEXnews JSON/search interfaces are public website endpoints, not a formally documented public API. Treat them as changeable and keep the smoke test in the workflow.
