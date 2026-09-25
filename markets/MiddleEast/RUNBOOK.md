# Middle East AR v2 Runbook

## Wave 0 — adapter proof
For every market, select 5 current issuers including a bank, industrial, consumer/service issuer and smaller issuer.
Test FY2017, FY2021 and FY2025 where applicable.

## Wave 1
1. Oman / XMUS
2. Dubai / XDFM
3. Jordan / XAMM

Run 20 issuers × FY2017-FY2025. Manually inspect every selected AR for the first 20 issuers.

## Wave 2
4. Abu Dhabi / XADS
5. Saudi Arabia / XSAU
6. Qatar / DSMD

Use component-aware classification for Qatar.

## Wave 3
7. Bahrain / XBAH
8. Kuwait / XKUW

Do not count annual financial statements as full AR. Full-report repair must continue until AR_FULL is found or the slot remains explicitly missing.

## Per-market release gates

- current equity universe verified
- MIC verified from latest ISO 10383 list
- 20-issuer pilot completed
- 0 known false-positive ARs in manual validation set
- FY precision verified
- English classification verified
- direct PDF success measured
- 403/429 rate measured
- rerun downloads zero DONE files
- interrupted PDF resumes successfully
- coverage and missing queue reconcile exactly

## Scale settings

Start:
- discovery: 2 requests/sec/host, 2 workers/host
- PDFs: 16 workers globally, max 4/host

Increase only when aggregate throughput scales and error rate remains low.
Never raise worker counts merely because local bandwidth is available.
