# Architecture

```text
OFFICIAL CURRENT TMX ISSUER LIST
          |
          v
 normalize + filter current operating companies
          |
          v
 TSX=XTSE / TSXV=XTSX / optional NEX=XTNX
          |
          v
 expected_slots FY2017..FY2025 (respect known listing date)
          |
          +-------------------------------+
          |                               |
          v                               v
AUTHORIZED SEDAR+ DDS              OFFICIAL ISSUER SITES
manifest/local delivery            robots-aware bounded crawler
(priority 1)                       (priority 2)
          |                               |
          +---------------+---------------+
                          v
                  candidate ledger
                          |
            classify / FY / language
                          |
                 best candidate/slot
                          |
                    download queue
                          |
        stream + .part + Range + retry
                          |
                 PDF/QC + SHA-256
                          |
              +-----------+-----------+
              |                       |
       identity complete?              no
              |                       |
             yes             staging/unresolved_identity
              |                       |
              v                       v
     EXACT ZETA FINAL TREE      identity_missing.csv
              |
              v
        coverage + repair queue
```

## Invariants

- No fabricated identifiers.
- No direct automated SEDAR+ public-site access.
- Fiscal year is the report period, never blindly the publication year.
- Existing `DONE` slots are not redownloaded on ordinary reruns.
- Incomplete/failed writes never masquerade as final PDFs.
- Final paths are deterministic from verified identifiers and ZETA SOP fields.
- Missing data is explicit and auditable.
