# Philippines PSE Annual & Sustainability Report Harvester

Autonomous, high-throughput extraction pipeline for Philippine Stock Exchange (`XPHS`, `PHL`) corporate annual reports (`AR_FULL` $\rightarrow$ `_AR_EN.pdf`) and sustainability/ESG reports (`SR` $\rightarrow$ `_SR_EN.pdf`) for fiscal years 2017–2025.

## Installation

```pwsh
pip install -e .
```

## Quick Start

```pwsh
# Run smoke test on 10 benchmark issuers
.\run_smoke_test.bat

# Run all issuers for FY2017-FY2025
.\run_fast_2017_2025.bat

# Run tests
.\run_tests.bat
```
