# Self-Improvement Protocol

This file is the permanent decision log for production changes.

## Rule

When a real run reveals a repeatable failure mode:

1. Save a minimal reproducible example (HTML/manifest row/URL metadata where licensing permits).
2. Classify root cause: universe, identity, source discovery, fiscal-year inference, false positive, download, validation, storage, or audit.
3. Add a failing regression test FIRST.
4. Implement the smallest generalized fix.
5. Run the full deterministic suite.
6. Run a bounded live smoke test against an authorized source.
7. Record the change below with date, symptom, root cause, fix, coverage impact and rollback notes.
8. Replace obsolete logic rather than accumulating multiple competing code paths.

## Release gates

A new build is production-eligible only if:

- deterministic tests pass;
- CLI starts from a clean extraction;
- no cache/database/test artifact is included in the release ZIP;
- final ZETA naming tests pass;
- expected-slot and repair-queue exports pass;
- downloader interruption/resume tests pass;
- public SEDAR scraping remains absent;
- source/provenance fields remain populated.

## Change log

### 2026-09-25 — v1.0.0
- Created current TSX/TSXV universe + product filtering.
- Added ZETA exact-path gate and unresolved-identity staging.
- Added authorized SEDAR DDS manifest/local-file adapter.
- Added issuer-site fallback with bounded robots-aware crawling.
- Added SQLite expected-slot/candidate/download/source-profile state.
- Added resumable streaming downloader and PDF/hash validation.
- Added universe summary, coverage, missing and repair-queue audits.
- Added deterministic sharding and Windows launchers.
