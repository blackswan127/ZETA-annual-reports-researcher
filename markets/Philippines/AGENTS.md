# Philippines PSE annual and sustainability report harvesting runbook

## 1. Primary autonomous agentic directive

Operate this module as an autonomous, high-throughput annual and sustainability report harvesting engine for companies listed on the Philippine Stock Exchange (PSE, MIC: `XPHS`, Country ISO3: `PHL`).

Whenever a user requests to *"download N Philippine companies"* or *"harvest PSE reports"*, interpret N as **distinct listed operating equity issuers**, not raw PDF counts or individual filing slots. **Do not pause, hesitate, or ask for manual confirmation.** Autonomously execute the entire pipeline from universe resolution through candidate discovery, parallel downloading, PyMuPDF validation, and atomic promotion into `GLOBAL_SUSTAINABILITY_DATABASE`.

---

## 2. Core invariants & rules

1. **PSE Network Access Gate**: PSE network access is disabled unless `PSE_TERMS_ACKNOWLEDGED=1` (or `--acknowledge-terms` CLI flag). The adapter must refuse unacknowledged network calls.
2. **Access Control & Rate Limit Compliance**: Never circumvent login, CAPTCHA, WAF, rate limits, or access controls. Enforce token-bucket / rolling window rate limiting (recommended <= 1.5 - 2.0 req/s metadata, 8-16 parallel PDF streaming workers).
3. **Endpoint Parameter Integrity**: Preserve endpoint-specific parameter names (`companyId=<cmpyId>`, `fromDate`, `toDate`, `pageNo`).
4. **No Windowless Queries**: Never call a windowless `/financialReports/search.ax` and interpret zero rows as no filings. Always provide an explicit bounded date window (e.g. `2017-01-01` to `2026-06-30`).
5. **Exact Fiscal Year Evidence**: Never use publication or filing calendar year as fiscal year when body evidence exists. Extract exact fiscal year ended from SEC Form 17-A body (`For the fiscal year ended ...`).
6. **Strict Report Classification**:
   - `AR_FULL`: SEC Form 17-A / Annual Report complete statutory filing. Only `AR_FULL` satisfies canonical `_AR_EN.pdf`.
   - `AR_COMPONENT`: Standalone Audited Financial Statements (AFS), supplementary schedules, or auditor opinions only. Never treat audited statements-only as `AR_FULL`.
   - `SR` / `ESG`: Sustainability Report, ESG report, CSR report, or Climate disclosures. Satisfies canonical `_SR_EN.pdf`.
   - `OTHER`: Quarterly reports, governance reports, information statements, AGM notices.
7. **Identity Integrity**: Never synthesize or fabricate LEI or ISIN. Every canonical filing requires a valid 20-character ISO 17442 `LEI` and 12-character ISO 6166 `ISIN` (prefix `PHY`). Issuers with unresolved identifiers are staged locally (`staging/unresolved_identity/PHL/`) with zero data loss until enriched via official sources.
8. **SSRF Boundary Invariant**: All derived attachment URLs must strictly remain on `https://edge.pse.com.ph/`. Any off-host hyperlinks found inside filing bodies are discarded.
9. **Persistent Checkpointing & State**: Every network response used in production must be checkpointed and cached where immutable. Maintain SQLite state in `local/markets/Philippines/harvest.sqlite3`.
10. **Zero-Token High-Speed Execution**: Zero LLM tokens burned for scraping or downloading. Pure deterministic async Python (`httpx` + PyMuPDF).
11. **Centralized Exchange Architecture**: Do not replace the centralized PSE adapter with fragile per-issuer scrapers.
12. **Permanent Storage Destination**: All final validated PDFs are written directly to Google Drive (`GLOBAL_SUSTAINABILITY_DATABASE`, `G:\My Drive\GLOBAL_SUSTAINABILITY_DATABASE`), adhering strictly to the ZETA taxonomy:
    `GLOBAL_SUSTAINABILITY_DATABASE/PHL/XPHS/<LEI>/<ISIN>/<Ticker>/FY<YYYY>/<LEI>_PHL_XPHS_<Ticker>_<ISIN>_FY<YYYY>_<ReportType>_EN.pdf`

---

## 3. Official sources and priority hierarchy

```
[ PSE Listed Equity Universe (~283 Issuers) ]
                 │
                 ├──► Priority 1: Official PSE EDGE Directory & Disclosures
                 │    ├── POST /companyDirectory/search.ax (All listed active issuers)
                 │    ├── POST /financialReports/search.ax (Form 17-1 Annual Reports)
                 │    └── GET  /openDiscViewer.do (Viewer: iframe body + attachments)
                 │
                 └──► Priority 2: Direct Document Stream
                      ├── GET /downloadHtml.do?file_id=... (Exact FY body parser)
                      └── GET /downloadFile.do?file_id=... (Binary PDF streaming)
```

---

## 4. CLI recipes

### Universe Discovery
```pwsh
py -m phl_pse_bulk.cli universe --acknowledge-terms
```

### Harvest Batch FY2017-FY2025 (Annual Reports + Sustainability)
```pwsh
py -m phl_pse_bulk.cli run --years 2017-2025 --types AR,SR --acknowledge-terms --output-root GLOBAL_SUSTAINABILITY_DATABASE
```

### 10-Company Smoke Test
```pwsh
py -m phl_pse_bulk.cli smoke --acknowledge-terms
```
