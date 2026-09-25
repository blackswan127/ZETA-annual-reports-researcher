# RUNBOOK.md

## Country launch sequence
1. Import current equity universe.
2. Verify MIC from current ISO 10383 list.
3. Create FY2017-FY2025 expected slots.
4. Run centralized/official discovery only.
5. Review 10 random candidates manually.
6. Run 10-issuer download smoke test.
7. Expand to 50 issuers.
8. Expand to 100 issuers and compute coverage/precision.
9. Enable full-country run only after gates pass.
10. Run repair-missing with secondary source.
11. Run issuer-IR repair only for remaining slots.

## Recommended waves
Wave 1: Zambia, Tanzania, Malawi, Ghana, Botswana, Zimbabwe.
Wave 2: Nigeria, Kenya, Namibia, Uganda, Mauritius, Rwanda, Eswatini.
Wave 3: South Africa (authorized JSE/SENS feed preferred), Seychelles, Sierra Leone.

## Throughput rule
Discovery and downloads are separate. Browser automation is for discovery only when necessary; never use a browser to stream PDFs. Persist URLs before transfer. Increase concurrency only after source-health metrics are stable.
