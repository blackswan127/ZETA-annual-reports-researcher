# Africa AR

Production-grade architecture blueprint for mass annual-report harvesting across English-report African equity markets.

Target period: FY2017-FY2025
Primary objective: current-listed equity issuers only
Output: ZETA-compatible annual-report corpus
Core rule: discovery and transport are separate stages.

Target markets: South Africa, Nigeria, Kenya, Ghana, Botswana, Namibia, Zimbabwe, Zambia, Uganda, Tanzania, Malawi, Mauritius, Rwanda, Eswatini, Seychelles, Sierra Leone.

Core flow:
Universe -> Expected Slots -> Discovery -> Candidate Normalization -> AR Classification -> Fiscal-Year Resolution -> Download -> Validation -> ZETA Placement -> Coverage Audit -> Repair Missing

Source waterfall:
1. Authorized/free aggregator where permitted and useful.
2. Official exchange disclosures / annual-report archive.
3. Licensed/authorized market-data feed where public bulk automation is restricted.
4. Company investor-relations site for missing slots only.
5. Manual review for unresolved identity/year/document ambiguity.

See ARCHITECTURE.md, SOURCES_MATRIX.csv, schema.sql, config.example.yaml, RUNBOOK.md and AGENTS.md.
