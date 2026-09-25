# Self-Improvement Protocol

When the harvester misses or misclassifies a report:

1. Reproduce the failure with the smallest real or sanitized fixture.
2. Record root cause: universe, identity, discovery, classification, fiscal year, download, validation, or source access.
3. Add a failing regression test first.
4. Implement the smallest generalized fix.
5. Run the entire deterministic test suite.
6. Run a bounded live smoke test only when authorized.
7. Update `SOURCES.md` or `ARCHITECTURE.md` if source behavior changed.
8. Do not retain superseded logic merely for compatibility if it causes ambiguity; migrate and remove it cleanly.

Every repair must improve the system for a class of issuers, not just one ticker.
