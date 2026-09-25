# Architecture

```text
CURRENT NZSX BOARD
      ↓
PROFILE RESOLUTION
      ↓
EQUITY/FUND FILTER
      ↓
ISSUER + ISIN + FYE
      ↓
IDENTITY OVERRIDES / CONSERVATIVE LEI ENRICHMENT
      ↓
EXPECTED SLOTS FY2017-FY2025
      ↓
┌──────────────────────────────┐
│ Authorized NZX historical   │ priority 100
│ Documents pages             │ priority 90
│ ANNREP records              │ priority 85
│ Issuer IR                   │ priority 70
└──────────────────────────────┘
      ↓
CANDIDATES + PROVENANCE
      ↓
BEST-SOURCE SELECTION
      ↓
STREAM / RANGE RESUME
      ↓
PDF SIGNATURE + PARSE + PAGES
      ↓
SHA-256
      ↓
IDENTITY COMPLETE?
  YES ↓        ↓ NO
ZETA tree     staging quarantine
      ↓
AUDIT / GAP ANALYSIS
      ↓
REPAIR-MISSING
```

## Invariants

1. Never invent LEI/ISIN.
2. Never classify by publication year when a reporting-period year is available.
3. Never overwrite a verified final PDF with an unverified response.
4. Never silently discard a failed or ambiguous slot.
5. Never treat raw NZSX instrument count as current company count.
6. Never bypass NZX access controls.
7. Prefer licensed/authorized NZX data products for commercial/bulk production.
