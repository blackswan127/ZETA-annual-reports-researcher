# Sources and evidence

## Dhaka Stock Exchange current universe

- Current company/security directory: `https://dse.ternary.com.bd/companies`
- Issuer profile pattern: `https://dse.ternary.com.bd/company/<TICKER>`

DSE profiles expose the instrument type, operational status, website, year-end and (where supplied) a `Details of Financial Statement` link to the issuer's own financial-report page. The harvester verifies `Instrument · Equity` before accepting a current issuer.

## CDBL ISIN enrichment

- `https://www.cdbl.com.bd/list-of-isin`

CDBL is Bangladesh's central depository. The project uses only rows classified as Securities ISIN and performs conservative normalized legal-name matching. Ambiguous/non-matching rows are left unresolved.

## Annual-report sources

1. Authorized/licensed or manually verified DSE manifest (`DSE_AUTHORIZED`).
2. The issuer financial-statement URL published by DSE (`DSE_FINANCIAL_LINK`).
3. The issuer's official website/investor-relations archive (`ISSUER_IR`) for gap repair.

## Identity source

Optional exact-name LEI resolution uses GLEIF API. It accepts only a single exact normalized legal-name result with a valid registration status. Otherwise LEI remains blank.

## Regulatory context

Bangladesh Securities and Exchange Commission identifies Dhaka Stock Exchange as one of Bangladesh's two stock exchanges. CDBL is the central depository recognized by BSEC.

## Source policy

No CAPTCHA/login/paywall/access-control bypass logic exists in this project. Public DSE automation is gated behind explicit acknowledgement. An authorized universe CSV and authorized historical manifest can be used to run the core pipeline without public DSE universe/discovery calls.
