# Test report

Build date: 2026-09-24

## Offline deterministic suite

Run with:

```bash
python -m pytest
```

Packaged result: **12 passed / 12 total**.

The suite checks:
- current issuer filtering (Mainboard/Catalist stocks only)
- annual-report classification
- current-issuer name mapping
- SGX announcement ID validation
- PDF attachment allowlisting and scoring
- rejection of sustainability attachments as the main report
- SQLite resumability state
- coverage CSV semantics
- Windows-safe filenames
- streamed PDF download after HTTP 429 retry
- partial `.part` resume using HTTP Range
- rejection of non-PDF attachment content

## Live source-contract checks

The build environment cannot make ordinary outbound DNS connections, so the CLI smoke test cannot be completed inside the artifact container. The live SGX source contract was separately verified against current public SGX endpoints while packaging:

- the public stock feed responds
- the public financial-reports feed responds and contains `Annual Report` rows
- an SGX annual-report detail page exposes `Report Type: Annual Report` and a fiscal period
- the selected attachment resolves to a real PDF

On an internet-connected machine run:

```bash
python -m sgx_bulk smoke
```

The smoke test resolves current ticker `S68`, fetches its annual-report history, opens the latest detail page and resolves the annual-report PDF without downloading the full mass corpus.
