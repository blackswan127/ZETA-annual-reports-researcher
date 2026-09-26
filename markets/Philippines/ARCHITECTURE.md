# Philippines PSE Annual & Sustainability Report - Production Architecture

## 1. Universe Discovery

- **Endpoint**: `POST https://edge.pse.com.ph/companyDirectory/search.ax`
- **Alternative**: `GET/POST https://edge.pse.com.ph/cm/companySearch.ax`
- **Scale**: ~283 active listed companies on the Philippine Stock Exchange.
- **Fields Extracted**:
  - `cmpyId` (PSE Company ID)
  - `securityId` (PSE Security ID)
  - Legal Company Name
  - Ticker Symbol
  - Sector & Subsector
  - Listing Date
  - Fiscal-Year End
  - Website URL
- **Exclusion Filters**:
  - ETF sector and exchange-traded funds
  - Clearly non-operating product rows (e.g. preferred shares deduplicated to primary common equity)
  - Delisted securities table

---

## 2. Expected Slot Generation

For each active operating equity issuer, generate slots across the requested fiscal years (FY2017–FY2025 = 9 fiscal years):
- Slot type 1: `AR` (Statutory Annual Report SEC Form 17-A)
- Slot type 2: `SR` (Sustainability / ESG / CSR Report, if present)

---

## 3. Financial Reports & Disclosure Search

- **Endpoint**: `POST https://edge.pse.com.ph/financialReports/search.ax`
- **Method**: HTTP POST with form data:
  - `companyId=<cmpyId>`
  - `fromDate=2017-01-01`
  - `toDate=2026-06-30` (extended into 2026 since FY2025 reports are filed in 2026)
  - `keyword=`
  - `pageNo=1`
- **Regulatory Template Filter**:
  - `17-1` = `Annual Report` (SEC Form 17-A)
  - Captures disclosure key `edge_no`.

---

## 4. Three-Hop PSE Document Flow

1. **Hop 1 — Document Viewer**:
   - `GET https://edge.pse.com.ph/openDiscViewer.do?edge_no=<edge_no>`
   - Parses:
     - Iframe source: `/downloadHtml.do?file_id=<body_file_id>`
     - Attachment selector: `<select id="file_list">` with `<option value="<attachment_file_id>">Label</option>`
2. **Hop 2 — Body Parser & Exact Fiscal Year Resolution**:
   - `GET https://edge.pse.com.ph/downloadHtml.do?file_id=<body_file_id>`
   - Scans text for exact covered period:
     - `For the fiscal year ended[\s\S]{0,80}?(20\d{2})`
     - `For the fiscal year ended\s*\|?\s*[A-Za-z]{3,9}\s+\d{1,2},\s*(20\d{2})`
3. **Hop 3 — High-Speed Binary Streaming**:
   - `GET https://edge.pse.com.ph/downloadFile.do?file_id=<attachment_file_id>`
   - Stream directly to local SSD temporary `.part` file.
   - Execute in-RAM PyMuPDF zero-copy structural verification (`%PDF-`, >= 1 readable page, valid trailer).
   - Atomic rename into permanent destination:
     `GLOBAL_SUSTAINABILITY_DATABASE/PHL/XPHS/<LEI>/<ISIN>/<Ticker>/FY<YYYY>/<LEI>_PHL_XPHS_<Ticker>_<ISIN>_FY<YYYY>_<ReportType>_EN.pdf`

---

## 5. Attachment Classification Taxonomy

| Attachment Label / Name Keywords | Classified Type | ZETA Target Slot |
|---|---|---|
| `17-A`, `SEC Form 17-A`, `Annual Report`, `Annual_Report` | `AR_FULL` | `_AR_EN.pdf` |
| `Audited Financial Statement`, `AFS`, `Supplementary Schedule`, `Auditor` | `AR_COMPONENT` | Staged (Does not satisfy full AR) |
| `Sustainability`, `ESG`, `CSR`, `Corporate Social Responsibility`, `Climate` | `SR` | `_SR_EN.pdf` |
| `Quarterly`, `17-Q`, `Governance`, `Information Statement`, `AGM`, `Notice` | `OTHER` | Discarded |

---

## 6. SSRF Boundary Invariant

All network connections must target `https://edge.pse.com.ph`. Any external hyperlinked URLs found within issuer disclosure text are blocked by the SSRF security guard.
