# Companies House UK accounts discovery plan

## Goal and boundaries

Add Companies House as a source for missing `GBR` fiscal years, especially 2020–2025. Keep the existing FCA NSM and SEC paths. A Companies House statutory accounts filing enters the canonical `AR` output only when its issuer, period, document type, English language, and completeness are confirmed. Short, dormant, micro-entity, subsidiary, or abbreviated accounts stay in review and do not fill a listed issuer's annual-report slot automatically. A UK listing need not correspond one-to-one with a Companies House company number, so company matching is an explicit step.

The target is increased **verified coverage**, not an assumed 6,000 PDFs. Before implementation, record a fresh baseline from `local/harvest.sqlite3` by source and fiscal year. For each expected UK company-year, distinguish already verified, missing, ambiguous, and genuinely unavailable. Do not overwrite an existing canonical PDF.

## Source contract

- Authenticate public GET requests with HTTP Basic: API key as username, empty password. The Companies House account username is not used for API authentication. Read the key from `COMPANIES_HOUSE_API_KEY`; never store it in the repository, logs, manifests, URLs, or SQLite. Rotate the key shared in chat before production use.
- Search or read a company profile to establish its **company number**; cache the verified mapping from repository `company_key` to company number with provenance and review status. A name similarity alone cannot verify the match. Use the legal name, historical names, incorporation date, company type, registered address, and a trusted external identifier/link where available. Send collisions, subsidiaries, and uncertain matches to review.
- Request `/company/{company_number}/filing-history?category=accounts`, paginating with `start_index` and `items_per_page`. Store `transaction_id`, filing date, description, type, page count, and `links.document_metadata` as provenance. Dedupe by company number and transaction ID. Filing date is **not** fiscal year.
- Resolve the document metadata link on the official document API. Accept a direct-PDF candidate only if metadata advertises `application/pdf`; request `/document/{document_id}/content` with `Accept: application/pdf`. The content request may return a redirect. Revalidate redirected hosts and do not forward Basic credentials to an unrelated host.
- Respect the published default limit of **600 requests per 5 minutes** across discovery, metadata, and content requests using one shared persisted rate budget. Apply bounded retries and `Retry-After` on 429/5xx. Permit request concurrency only inside this budget. At three API calls per report, the theoretical ceiling is about **0.67 reports/second**, before search, pagination, network time, and review; do not promise three reports/second from this API alone.

## Repository changes

1. Add `src/annual_reports/companies_house.py` as a discovery client with strict official-host URL handling, pagination, resumable checkpoints, JSON schema checks, and structured errors. Reuse the download engine for verified PDF transfers after adapting its Companies House request headers and redirect handling.
2. Add a `company_house_matches` table (`company_key`, `company_number`, match evidence, status, checked_at) and source-specific filing metadata to the existing `candidates` records. Keep the current `companies` and report naming schema intact. Do not add company numbers to the canonical path.
3. Add CLI stages such as `ch-match`, `ch-discover`, and `ch-review` with `--state`, `--years`, `--limit`, and review CSV options. A separate `ch-export-manifest` should include only reviewed, verified direct PDFs for **missing** company-years. Feed that manifest through existing `plan`, `run`, and `verify` commands.
4. Update `engine.py` so the document API content request sends `Accept: application/pdf`, credentials are attached only to official Companies House API hosts, and the shared rate gate covers every Companies House API call. The existing `0.55` second gate in the downloader covers downloads only; it does not protect discovery calls or implement the rolling five-minute budget by itself.
5. Add audit output for company number, transaction ID, document ID, source URL, period-end evidence, content type, classification, rejection reason, and final SHA-256. Keep unresolved cases in a CSV and in SQLite.
6. Add README and `AGENTS.md` instructions that choose Companies House for missing UK slots, explain what statutory accounts can and cannot satisfy, and give an agent a single safe command sequence.

## Classification and quality gates

1. Derive fiscal year from the accounting period end in filing metadata when present, then corroborate it against the document's front matter. Never derive FY from filing/upload date alone. Check amended and duplicate filings separately and prefer the latest valid full filing only after review.
2. Separate full annual report and accounts, full group/consolidated accounts, ordinary statutory accounts, abridged/micro/dormant accounts, and unrelated accounts. Keep both the source category and repository SOP classification. Only a full issuer report that meets the existing `AR` contract can be exported as `AR`; otherwise retain as a sourced candidate with a review or excluded status.
3. Check the company identity against the verified listing, check the fiscal period, check title and language, and confirm the PDF is complete/readable. Page-tree checks, content length, and SHA-256 prove transfer integrity only. Conflicting evidence requires review.
4. For each company-year, compare FCA, SEC, official investor-relations, and Companies House candidates before selecting the canonical file. Do not let a smaller statutory document replace a verified full report. Count missing and excluded reasons separately.

## Implementation and rollout

1. Run the current test suite and snapshot UK coverage. Implement the client and SQLite migration with offline fixtures for pagination, company-name ambiguity, late filings, amendments, PDF-unavailable metadata, redirects, 429, and credential containment.
2. Dry-run 10 varied UK issuers, including a group parent, a post-2020 listing, an investment trust, a name mismatch, and a company with abbreviated accounts. Inspect every selected PDF and every rejected candidate.
3. Run a 100-company cohort for missing 2020–2025 slots. Measure matched companies, filings discovered, full reports eligible, verified downloads, unresolved reasons, elapsed seconds, API calls, 429s, bytes, and PDFs/second. Reconcile these counts with `local/harvest.sqlite3` before expanding to the remaining universe.
4. Expand in resumable cohorts, never launch multiple processes using the same API key without a shared rate budget, and checkpoint each stage. Preserve existing PDFs; use the current atomic-write and ledger verification path. Confirm Google Drive sync separately from local downloader success.

## Completion criteria

- Every selected candidate traces to a verified company number and official filing/document identifiers.
- No existing valid report is overwritten; every output follows the SOP path and filename.
- Every downloaded PDF passes structural checks and a later SHA-256 verification; sampled reports pass issuer, FY, type, language, and completeness review.
- The coverage report states requested, discovered, eligible, downloaded, verified, excluded, failed, and unresolved company-years separately, with measured elapsed time and API rate-limit outcomes.

## Official references

- [Authentication](https://developer.company-information.service.gov.uk/authentication)
- [Developer guidelines and API rate limits](https://developer.company-information.service.gov.uk/developer-guidelines)
- [Filing history list API](https://developer-specs.company-information.service.gov.uk/companies-house-public-data-api/reference/filing-history/list)
- [Document metadata](https://developer-specs.company-information.service.gov.uk/document-api/resources/documentmetadata?v=latest)
- [Document content API](https://developer-specs.company-information.service.gov.uk/document-api/reference/document-location/fetch-a-document)
- [Statutory accounts filing scope](https://www.gov.uk/annual-accounts/microentities-small-and-dormant-companies)
