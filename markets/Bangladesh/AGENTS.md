# AGENTS.md — DSE ZETA Harvester

Agents modifying this repository must preserve these invariants:

1. **Never invent identity.** LEI and ISIN require authoritative or explicitly supplied evidence.
2. **Never place an unresolved identity in the final ZETA tree.** Use staging.
3. **Fiscal year is the covered reporting year, not publication year.** `2024-25` means FY2025.
4. **Annual Report means the full annual report.** Do not substitute Annual Return, quarterly/interim reports, AGM notices, sustainability reports or presentations.
5. **Current universe = verified DSE Equity profiles.** Do not treat DSE bonds/funds/government securities as companies.
6. **Official/authorized sources outrank generic issuer crawling.** Preserve source provenance.
7. **All network operations must be resumable and respectful.** No access-control bypasses.
8. **Every bug fix needs a regression test.** Follow `SELF_IMPROVEMENT_PROTOCOL.md`.
9. **Do not delete historical candidate/download state merely because a source changes.** Migrate schemas and preserve provenance.
10. **Before release:** tests, compilation, CLI check, clean ZIP extraction test, no corpus/database/cache/.venv in release.
