# AGENTS.md — Canada ZETA Harvester

Agents modifying this repository must preserve these invariants.

1. **Read first:** `README.md`, `ARCHITECTURE.md`, `SOURCES.md`, `SELF_IMPROVEMENT_PROTOCOL.md`.
2. Target remains current TSX/TSXV operating companies and FY2017-FY2025 Annual Reports unless the operator explicitly changes scope.
3. Final storage MUST follow ZETA exactly:
   `ROOT/CAN/<MIC>/<LEI>_<ISIN>_<Ticker>/FYyyyy/<LEI>_CAN_<MIC>_<Ticker>_<ISIN>_FYyyyy_AR_<LANG>.pdf`
4. Never invent or silently infer LEI/ISIN. Ambiguous identifiers remain unresolved/staged.
5. Do not implement automated scraping/searching of the SEDAR+ public website. Use licensed/authorized SEDAR+ DDS inputs or issuer-owned sources.
6. Never bypass CAPTCHA, login, paywall, robots/access controls or rate protection.
7. Preserve SQLite as the source of truth for issuers, expected slots, candidates, downloads, source profiles and events.
8. Discovery and downloading remain separable stages. Do not collapse them into an opaque loop.
9. Preserve `.part` + atomic rename semantics; never mark a slot DONE before PDF validation succeeds.
10. A rerun must be resumable and idempotent. Repair must target MISSING/FAILED slots only.
11. Add/modify tests for every parser/classifier/state change. The test suite must pass before release.
12. Do not delete old working logic silently. Record production-changing decisions in `SELF_IMPROVEMENT_PROTOCOL.md`.
13. Prefer official/issuer-owned sources. Record provenance and source health.
14. Do not loosen false-positive filters merely to improve coverage numbers.
15. `coverage.csv`, not raw PDF count, is the primary completion metric.
