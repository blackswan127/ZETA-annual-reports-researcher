# Seven Market Annual Reports Harvesting Subtree

This directory contains the independent, modular annual-report harvesting engines for seven international markets, integrated with a unified coordinator, common data contract, deterministic exact-N cohort freezer, and atomic SOP promotion into `GLOBAL_SUSTAINABILITY_DATABASE` (Google Drive).

## Directory Structure

```
markets/
├── AGENTS.md               # Common integration contract & SOP specification
├── Australia/              # ASX Annual Reports Bulk Downloader (XASX, AUS)
├── Bangladesh/             # DSE ZETA Annual Reports Bulk Downloader (XDHA, BGD)
├── Canada/                 # TSX / TSXV ZETA Annual Reports Bulk Downloader (XTSE/XTSX, CAN)
├── HongKong/               # HKEX Annual Reports Bulk Downloader (XHKG, HKG)
├── India/                  # BSE / NSE Annual Reports Bulk Downloader (XNSE/XBOM, IND)
├── NewZealand/             # NZX ZETA Annual Reports Bulk Downloader (XNZE, NZL)
├── Singapore/              # SGX Annual Reports Bulk Downloader (XSES, SGP)
└── _integration/           # Common data contract, adapters, and coordinator
    ├── contract.py         # Standard dataclasses (Issuer, Slot, Candidate, Result)
    ├── promotion.py        # In-RAM PyMuPDF validation & atomic Drive SOP promotion
    ├── cohort.py           # Deterministic exact-N selection & manifest freezing
    ├── adapters.py         # Unified market adapters
    ├── coordinator.py      # Plain-English directive parser & autonomous orchestrator
    ├── cli.py              # markets-ar CLI entry point
    └── tests/              # Multi-market integration test suite
```

## Quick Start CLI (`markets-ar`)

### 1. Plain-English Autonomous Directive
```bash
py -m markets._integration.cli auto "download the next 100 current listed companies in Australia for FY2024"
py -m markets._integration.cli auto "harvest 50 companies from SGX for FY2023-FY2025"
```

### 2. Inspect Active Issuer Rosters
```bash
py -m markets._integration.cli roster Australia
py -m markets._integration.cli roster HongKong
py -m markets._integration.cli roster Singapore
py -m markets._integration.cli roster India
py -m markets._integration.cli roster Canada
py -m markets._integration.cli roster NewZealand
py -m markets._integration.cli roster Bangladesh
```

### 3. Freeze an Exact-N Cohort Manifest
```bash
py -m markets._integration.cli cohort Australia --count 50 --fy 2024
```
Manifests are frozen to: `local/markets/<Market>/manifests/<Run_ID>.json` and `.csv`.

## Market Release Gates & Status

| Market | MIC | ISO3 | Active Roster | Report Source | Live Smoke | Test Suite | Gate Status |
|---|---|---|---|---|---|---|---|
| **Australia (ASX)** | `XASX` | `AUS` | 1,832 live issuers | ASX Official Directory & History | PASS (BHP FY25) | 17/17 PASS | **PRODUCTION READY** |
| **Hong Kong (HKEX)** | `XHKG` | `HKG` | 17,737 securities | HKEX Title Search & Files | PASS (00700 FY25) | 7/7 PASS | **PRODUCTION READY** |
| **Singapore (SGX)** | `XSES` | `SGP` | 670 live issuers | SGX Corporate Info & Reports | PASS (S68 FY25) | 12/12 PASS | **PRODUCTION READY** |
| **New Zealand (NZX)** | `XNZE` | `NZL` | Verified equity roster | NZX Documents & Authorized | PASS (NZX FY25) | 19/19 PASS | **PRODUCTION READY** |
| **Bangladesh (Dhaka)**| `XDHA` | `BGD` | Verified equity roster | DSE Public & Authorized | PASS (UNITEDFIN) | 20/20 PASS | **PRODUCTION READY** |
| **Canada (TSX/TSXV)** | `XTSE`/`XTSX`| `CAN` | TSX/TSXV Roster | Authorized SEDAR+ DDS & IR | PASS (RBC Sample) | 24/24 PASS | **PRODUCTION READY** (Bulk DDS dependent) |
| **India (BSE/NSE)** | `XNSE`/`XBOM`| `IND` | 25 seed NIFTY issuers | NSE/BSE Page APIs | Blocked (403)| 15/15 PASS | **BLOCKED (Perimeter 403)** |

## Invariants & Production Boundaries

1. **Root Isolation**: `src/annual_reports/` and the US/UK statutory harvesting pipeline remain completely untouched. Zero regressions across the 44 parent tests.
2. **Permanent Output**: Final PDFs are written directly to Google Drive via `GLOBAL_SUSTAINABILITY_DATABASE` following canonical ZETA SOP:
   `GLOBAL_SUSTAINABILITY_DATABASE/<ISO3>/<MIC>/<LEI>_<ISIN>_<Ticker>/FYyyyy/<LEI>_<ISO3>_<MIC>_<Ticker>_<ISIN>_FYyyyy_AR_EN.pdf`
3. **Identity Verification**: Missing LEI or ISIN is never fabricated; reports are staged under `local/markets/<market>/staging/unresolved_identity/` with auditable reasons.
4. **Resumability**: Completed files in Google Drive are detected idempotently; conflicts enter `conflicts/` without silent overwrites.
