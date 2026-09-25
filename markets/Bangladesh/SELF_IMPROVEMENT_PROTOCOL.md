# Self-Improvement Protocol

When a live run exposes a failure:

1. Record a minimal example in `work/audit/events` or a reproducible fixture.
2. Identify the root cause: universe, identity, source discovery, classification, fiscal-year mapping, download, validation, or storage.
3. Write a failing regression test first.
4. Fix the generalized rule; avoid company-specific patches unless the source itself is company-specific.
5. Run the full deterministic suite.
6. Run a bounded live smoke test.
7. Update `SOURCES.md`/`README.md` if source behavior changed.
8. Replace obsolete logic rather than keeping competing pathways with unclear precedence.

Never weaken PDF/identity/year validation simply to increase the apparent coverage percentage.
