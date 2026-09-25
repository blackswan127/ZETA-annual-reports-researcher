# Sources and Access Policy

## TMX — current company universe

Preferred operator input is the official current TSX/TSXV issuer list linked from TMX's **Listed Company Directory** / Current Market Statistics pages.

- Listed Company Directory: `https://www.tsx.com/en/listings/listing-with-us/listed-company-directory`
- Current Market Statistics: `https://www.tsx.com/en/listings/current-market-statistics`

The code supports local CSV/XLSX/JSON universe files. A best-effort one-file TMX fetch exists behind `CANADA_AR_ACKNOWLEDGE_TMX_TERMS=1`; it is intentionally not a broad crawler.

Market identifier codes used by ZETA:

- TSX: `XTSE`
- TSX Venture Exchange: `XTSX`
- NEX: `XTNX` (optional/excluded by default)

## SEDAR+

The public SEDAR+ website is NOT an automated source in this project.

SEDAR+ Public Website Terms of Use prohibit, among other things, using Public Information to construct a database and scraping/automated reproduction of multiple pieces of Public Information. The Privacy Statement explains that the ASC offers bulk data distribution services to subscribers under licence.

Production regulatory source supported here:

- **authorized SEDAR+ Data Distribution Service (DDS)** delivery/manifest
- HTTP(S) licensed document URL, or local delivered PDF file

The adapter never assumes a secret/private SEDAR endpoint and contains no CAPTCHA/access-control bypass.

## Issuer-owned investor-relations sites

These are secondary/fallback sources. The crawler:

- obeys `robots.txt` by default;
- stays on the issuer's site;
- has depth/page limits;
- rate-limits requests;
- records provenance;
- seeks full Annual Reports, not standalone sustainability/proxy/MD&A documents.

## Identity sources

- GLEIF public API: conservative unique exact legal-name LEI enrichment.
- OpenFIGI: optional ISIN enrichment; only a unique returned ISIN is auto-accepted.
- Manual overrides remain the preferred route for ambiguous companies.
