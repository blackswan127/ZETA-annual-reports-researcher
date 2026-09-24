"""Companies House UK statutory accounts discovery, company matching, and rate-budget enforcement."""

from __future__ import annotations

import asyncio
import csv
import html
import json
import os
import re
import sqlite3
import time
from dataclasses import dataclass
from datetime import datetime, timezone
from email.utils import parsedate_to_datetime
from pathlib import Path
from typing import Any
from urllib.parse import quote_plus, urljoin, urlsplit

import httpx

from .catalog import FIELDS, Report
from .discovery import Company, DiscoveryStore
from .engine import native_path

EXCEL_FORMULA_PREFIXES = ("=", "+", "-", "@", "\t", "\r")


CH_API_BASE = "https://api.company-information.service.gov.uk"
CH_DOC_API_BASE = "https://document-api.company-information.service.gov.uk"
CH_WEB_BASE = "https://find-and-update.company-information.service.gov.uk"

CH_API_HOSTS = {
    "api.company-information.service.gov.uk",
    "document-api.company-information.service.gov.uk",
}
CH_ALL_HOSTS = CH_API_HOSTS | {
    "find-and-update.company-information.service.gov.uk",
}

# Strict classification patterns for Companies House accounts descriptions
EXCLUDED_DESCRIPTION_PATTERNS = (
    (re.compile(r"\bdormant\b|accounts-with-accounts-type-dormant", re.I), "dormant_accounts"),
    (re.compile(r"\bmicro[- ]?entity\b|accounts-with-accounts-type-micro-entity", re.I), "micro_entity_accounts"),
    (re.compile(r"\babbreviated\b|accounts-with-accounts-type-abbreviated", re.I), "abbreviated_accounts"),
    (re.compile(r"\babridged\b", re.I), "abridged_accounts"),
    (re.compile(r"\bfilleted\b|accounts-with-accounts-type-filleted", re.I), "filleted_accounts"),
    (re.compile(r"\btotal exemption\b|accounts-with-accounts-type-total-exemption-small", re.I), "total_exemption_small_accounts"),
    (re.compile(r"\bsmall company\b|accounts-with-accounts-type-small", re.I), "small_company_accounts"),
    (re.compile(r"\bunaudited\b|accounts-with-accounts-type-unaudited", re.I), "unaudited_accounts"),
    (re.compile(r"\binterim accounts\b", re.I), "interim_accounts"),
    (re.compile(r"\binitial accounts\b", re.I), "initial_accounts"),
    (re.compile(r"\bchange of accounting reference date\b", re.I), "accounting_ref_date_change"),
)

ELIGIBLE_AR_PATTERNS = (
    re.compile(r"\bgroup of companies['\u2019]?\s*accounts\b", re.I),
    re.compile(r"\bfull accounts\b", re.I),
    re.compile(r"accounts-with-accounts-type-group", re.I),
    re.compile(r"accounts-with-accounts-type-full", re.I),
)

EXCLUDED_FORM_TYPES = {"AA01", "AA02", "ARD"}

MADE_UP_TO_RE = re.compile(
    r"made up to\s+(\d{1,2}\s+[A-Za-z]+\s+20\d{2}|20\d{2}-\d{2}-\d{2})",
    re.I,
)
PAGES_RE = re.compile(r"\((\d+)\s+pages?\)", re.I)
UK_CRN_RE = re.compile(r"^(?:[0-9]{8}|(?:SC|NI|OC|SO|NC|RO|RC|IC|SI|NP|NO|LP|SL|NL|CE|CS|PC|RS|SR|IP|SP|ES)[0-9]{6})$", re.I)
NON_UK_PREFIX_RE = re.compile(r"^(?:FC|BR|SF|NF|GE|GS)", re.I)


def _cell(value: str) -> str:
    return f"'{value}" if value and value[0] in EXCEL_FORMULA_PREFIXES else value


def normalize_company_name(name: str) -> str:
    """Normalize UK company names for comparison against Companies House profiles."""
    if not name:
        return ""
    cleaned = html.unescape(name).upper()
    cleaned = re.sub(r"/NEW/?$", "", cleaned)
    cleaned = re.sub(r"\(.*?\)", " ", cleaned)
    cleaned = re.sub(
        r"\b(PUBLIC LIMITED COMPANY|P\.?L\.?C\.?|LIMITED|LTD\.?|GROUP|HOLDINGS?|THE|AND|&|UK|U\.K\.)\b",
        " ",
        cleaned,
    )
    cleaned = re.sub(r"[^A-Z0-9]+", " ", cleaned)
    return re.sub(r"\s+", " ", cleaned).strip()


def normalize_uk_crn(raw_crn: str | None) -> str:
    """Normalize a UK company registration number to 8 characters."""
    if not raw_crn:
        return ""
    val = raw_crn.strip().upper().replace(" ", "")
    if val.isdigit() and len(val) < 8:
        val = val.zfill(8)
    return val


def parse_period_end_date(text_or_date: str) -> tuple[str, int | None]:
    """Parse 'made up to 31 December 2024' or '2024-12-31' into ('YYYY-MM-DD', 2024)."""
    if not text_or_date:
        return "", None
    val = html.unescape(text_or_date).strip()
    if re.fullmatch(r"20\d{2}-\d{2}-\d{2}", val):
        return val, int(val[:4])
    m = MADE_UP_TO_RE.search(val)
    candidate = m.group(1).strip() if m else val
    for fmt in ("%d %B %Y", "%d %b %Y", "%Y-%m-%d"):
        try:
            dt = datetime.strptime(candidate, fmt)
            return dt.strftime("%Y-%m-%d"), dt.year
        except ValueError:
            continue
    return "", None


def classify_ch_accounts_filing(
    *,
    form_type: str,
    description: str,
    period_end: str,
    has_pdf: bool,
    pages: int | None = None,
    is_amended: bool = False,
) -> tuple[str, str]:
    """Classify a Companies House filing into ('AR', ''), ('REVIEW', reason), or ('EXCLUDED', reason)."""
    ft = (form_type or "").strip().upper()
    desc = html.unescape(description or "").strip()
    if ft in EXCLUDED_FORM_TYPES:
        return "EXCLUDED", f"non_accounts_form:{ft}"
    for pattern, reason in EXCLUDED_DESCRIPTION_PATTERNS:
        if pattern.search(desc):
            return "EXCLUDED", reason
    if not period_end:
        return "REVIEW", "missing_period_end_date"
    if not has_pdf:
        return "EXCLUDED", "pdf_unavailable"
    if is_amended or "amend" in desc.lower() or ft == "AAMD":
        return "REVIEW", "amended_accounts_requires_review"
    is_eligible = any(p.search(desc) for p in ELIGIBLE_AR_PATTERNS) or ft == "AA"
    if not is_eligible:
        return "REVIEW", f"unconfirmed_accounts_subtype:{desc[:80]}"
    if pages is not None and 0 < pages < 8:
        return "REVIEW", f"short_page_count:{pages}"
    return "AR", ""


def ensure_ch_schema(conn: sqlite3.Connection) -> None:
    """Ensure Companies House tables exist in the SQLite state database."""
    conn.executescript(
        """
        CREATE TABLE IF NOT EXISTS company_house_matches (
            company_key TEXT PRIMARY KEY REFERENCES companies(company_key),
            company_number TEXT NOT NULL,
            match_evidence_json TEXT NOT NULL,
            status TEXT NOT NULL,
            checked_at TEXT NOT NULL
        );
        CREATE INDEX IF NOT EXISTS idx_ch_matches_status ON company_house_matches(status);

        CREATE TABLE IF NOT EXISTS ch_audit_log (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            company_key TEXT NOT NULL,
            company_number TEXT NOT NULL,
            transaction_id TEXT NOT NULL,
            document_id TEXT NOT NULL DEFAULT '',
            source_url TEXT NOT NULL DEFAULT '',
            report_year INTEGER,
            period_end TEXT NOT NULL DEFAULT '',
            filing_date TEXT NOT NULL DEFAULT '',
            form_type TEXT NOT NULL DEFAULT '',
            description TEXT NOT NULL DEFAULT '',
            content_type TEXT NOT NULL DEFAULT '',
            pages INTEGER NOT NULL DEFAULT 0,
            classification TEXT NOT NULL,
            rejection_reason TEXT NOT NULL DEFAULT '',
            sha256 TEXT NOT NULL DEFAULT '',
            checked_at TEXT NOT NULL,
            UNIQUE(company_key, company_number, transaction_id)
        );
        CREATE INDEX IF NOT EXISTS idx_ch_audit_company_year ON ch_audit_log(company_key, report_year);

        CREATE TABLE IF NOT EXISTS ch_rate_budget (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            ts REAL NOT NULL
        );
        CREATE INDEX IF NOT EXISTS idx_ch_rate_budget_ts ON ch_rate_budget(ts);
        """
    )
    conn.commit()


class PersistedRollingRateGate:
    """Shared persisted 5-minute rolling rate gate across discovery, metadata, and PDF transfers.

    Companies House enforces a hard 600 requests per 5-minute window (2.0 req/s average).
    We persist request timestamps in SQLite (`ch_rate_budget`) and enforce both a minimum
    spacing (`min_interval_s`) and a strict sliding 300-second window cap (`max_requests`).
    """

    def __init__(
        self,
        state_path: Path | None = None,
        max_requests: int = 550,
        window_s: float = 300.0,
        min_interval_s: float = 0.55,
    ):
        self.state_path = state_path
        self.max_requests = max_requests
        self.window_s = window_s
        self.min_interval_s = min_interval_s
        self.next_allowed = 0.0
        self.lock = asyncio.Lock()
        self._mem_timestamps: list[float] = []
        if self.state_path is not None:
            self.state_path.parent.mkdir(parents=True, exist_ok=True)
            conn = sqlite3.connect(self.state_path, timeout=30.0)
            try:
                ensure_ch_schema(conn)
            finally:
                conn.close()

    def _sync_acquire_slot(self, now_wall: float) -> float:
        cutoff = now_wall - self.window_s
        if self.state_path is not None:
            try:
                conn = sqlite3.connect(self.state_path, timeout=30.0)
                try:
                    conn.execute("DELETE FROM ch_rate_budget WHERE ts < ?", (cutoff,))
                    row = conn.execute("SELECT count(*), min(ts) FROM ch_rate_budget").fetchone()
                    count = row[0] if row else 0
                    oldest = row[1] if row and row[1] is not None else now_wall
                    if count >= self.max_requests:
                        return max(0.5, (oldest + self.window_s) - now_wall + 0.25)
                    conn.execute("INSERT INTO ch_rate_budget(ts) VALUES (?)", (now_wall,))
                    conn.commit()
                    return 0.0
                finally:
                    conn.close()
            except sqlite3.Error:
                pass
        # Fallback to in-memory sliding window
        self._mem_timestamps = [t for t in self._mem_timestamps if t >= cutoff]
        if len(self._mem_timestamps) >= self.max_requests:
            return max(0.5, (self._mem_timestamps[0] + self.window_s) - now_wall + 0.25)
        self._mem_timestamps.append(now_wall)
        return 0.0

    async def wait(self) -> None:
        while True:
            async with self.lock:
                now_mono = time.monotonic()
                delay_spacing = max(0.0, self.next_allowed - now_mono)
                if delay_spacing > 0:
                    await asyncio.sleep(delay_spacing)
                now_wall = time.time()
                window_wait = await asyncio.to_thread(self._sync_acquire_slot, now_wall)
                if window_wait <= 0.0:
                    self.next_allowed = time.monotonic() + self.min_interval_s
                    return
            await asyncio.sleep(window_wait)


class CompaniesHouseClient:
    """Client supporting both the official Companies House REST API and public web fallback under one rate gate."""

    def __init__(
        self,
        api_key: str = "",
        rate_gate: PersistedRollingRateGate | None = None,
        timeout_s: float = 25.0,
        max_retries: int = 3,
    ):
        self.api_key = (api_key or os.environ.get("COMPANIES_HOUSE_API_KEY", "")).strip()
        self.rate_gate = rate_gate or PersistedRollingRateGate()
        self.timeout_s = timeout_s
        self.max_retries = max_retries
        self._client: httpx.AsyncClient | None = None

    async def __aenter__(self) -> "CompaniesHouseClient":
        self._client = httpx.AsyncClient(
            timeout=self.timeout_s,
            follow_redirects=False,
            headers={
                "User-Agent": (
                    "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 "
                    "(KHTML, like Gecko) Chrome/124.0.0.0 Safari/537.36"
                )
            },
        )
        return self

    async def __aexit__(self, *_: object) -> None:
        if self._client is not None:
            await self._client.aclose()
            self._client = None

    async def _request(
        self,
        url: str,
        *,
        headers: dict[str, str] | None = None,
        cookies: dict[str, str] | None = None,
    ) -> httpx.Response:
        assert self._client is not None, "Client must be used as an async context manager"
        current_url = url
        for attempt in range(self.max_retries):
            for _redirect in range(6):
                host = urlsplit(current_url).hostname or ""
                if host in CH_ALL_HOSTS:
                    await self.rate_gate.wait()
                req_headers = dict(headers or {})
                # Attach Basic auth ONLY to official Companies House API hosts, never to S3/CDN redirects
                auth = (self.api_key, "") if (self.api_key and host in CH_API_HOSTS) else None
                resp = await self._client.get(
                    current_url,
                    headers=req_headers,
                    cookies=cookies if host in CH_ALL_HOSTS else None,
                    auth=auth,
                )
                if resp.status_code in {301, 302, 303, 307, 308}:
                    loc = resp.headers.get("location")
                    if not loc:
                        break
                    current_url = urljoin(current_url, loc)
                    continue
                break
            if resp.status_code in {429, 500, 502, 503, 504} and attempt + 1 < self.max_retries:
                retry_after = resp.headers.get("retry-after", "")
                delay = 2.0 * (2 ** attempt)
                if retry_after:
                    try:
                        delay = min(300.0, max(1.0, float(retry_after)))
                    except ValueError:
                        try:
                            delay = min(
                                300.0,
                                max(
                                    1.0,
                                    (parsedate_to_datetime(retry_after) - datetime.now(timezone.utc)).total_seconds(),
                                ),
                            )
                        except Exception:
                            pass
                await asyncio.sleep(delay)
                current_url = url
                continue
            return resp
        return resp

    async def get_company_profile(self, company_number: str) -> dict[str, Any] | None:
        crn = normalize_uk_crn(company_number)
        if not crn:
            return None
        if self.api_key:
            resp = await self._request(
                f"{CH_API_BASE}/company/{crn}",
                headers={"Accept": "application/json"},
            )
            if resp.status_code == 200:
                return resp.json()
            if resp.status_code == 404:
                return None
        # Fallback to official public web profile
        resp = await self._request(f"{CH_WEB_BASE}/company/{crn}")
        if resp.status_code != 200:
            return None
        text = resp.text
        name_m = re.search(r'<p class="heading-xlarge"[^>]*>(.*?)</p>', text, re.S) or re.search(
            r'<h1 class="heading-xlarge"[^>]*>(.*?)</h1>', text, re.S
        )
        company_name = html.unescape(re.sub(r"<[^>]+>", "", name_m.group(1)).strip()) if name_m else ""
        status_m = re.search(r'id="company-status"[^>]*>\s*([^<\n]+)', text, re.I)
        company_status = status_m.group(1).strip().lower() if status_m else "active"
        type_m = re.search(r'id="company-type"[^>]*>\s*([^<\n]+)', text, re.I)
        company_type = type_m.group(1).strip().lower() if type_m else ""
        inc_m = re.search(r'id="company-creation-date"[^>]*>\s*([^<\n]+)', text, re.I)
        inc_date = inc_m.group(1).strip() if inc_m else ""
        prev_names = [
            html.unescape(re.sub(r"<[^>]+>", "", m).strip())
            for m in re.findall(r'id="previous-name-\d+"[^>]*>(.*?)</td>', text, re.S)
        ]
        return {
            "company_number": crn,
            "company_name": company_name,
            "company_status": company_status,
            "type": company_type,
            "date_of_creation": inc_date,
            "previous_company_names": [{"name": n} for n in prev_names],
            "source_mode": "public_web",
        }

    async def search_companies(self, query: str) -> list[dict[str, Any]]:
        if not query.strip():
            return []
        if self.api_key:
            resp = await self._request(
                f"{CH_API_BASE}/search/companies?q={quote_plus(query)}&items_per_page=10",
                headers={"Accept": "application/json"},
            )
            if resp.status_code == 200:
                return resp.json().get("items", [])
        resp = await self._request(f"{CH_WEB_BASE}/search/companies?q={quote_plus(query)}")
        if resp.status_code != 200:
            return []
        items: list[dict[str, Any]] = []
        for match in re.finditer(
            r'<a[^>]+href="/company/([A-Z0-9]{6,8})"[^>]*>(.*?)</a>',
            resp.text,
            re.S | re.I,
        ):
            crn = normalize_uk_crn(match.group(1))
            title = html.unescape(re.sub(r"<[^>]+>", "", match.group(2)).strip())
            items.append({"company_number": crn, "title": title})
        return items

    async def get_accounts_filings(self, company_number: str) -> list[dict[str, Any]]:
        """Return accounts filing items for a verified UK company number."""
        crn = normalize_uk_crn(company_number)
        if not crn:
            return []
        if self.api_key:
            items: list[dict[str, Any]] = []
            start_index = 0
            items_per_page = 100
            while True:
                url = (
                    f"{CH_API_BASE}/company/{crn}/filing-history"
                    f"?category=accounts&items_per_page={items_per_page}&start_index={start_index}"
                )
                resp = await self._request(url, headers={"Accept": "application/json"})
                if resp.status_code != 200:
                    break
                payload = resp.json()
                batch = payload.get("items", [])
                if not batch:
                    break
                for raw in batch:
                    tx_id = raw.get("transaction_id", "")
                    filing_date = raw.get("date", "")
                    form_type = raw.get("type", "")
                    desc_vals = raw.get("description_values") or {}
                    made_up_date = desc_vals.get("made_up_date") or raw.get("action_date") or ""
                    desc_text = raw.get("description", "")
                    if made_up_date:
                        desc_text = f"{desc_text} made up to {made_up_date}"
                    links = raw.get("links") or {}
                    doc_meta_link = links.get("document_metadata") or ""
                    if doc_meta_link and doc_meta_link.startswith("/"):
                        doc_meta_url = f"{CH_DOC_API_BASE}{doc_meta_link}"
                    else:
                        doc_meta_url = doc_meta_link
                    pages = raw.get("pages")
                    has_pdf = bool(doc_meta_url)
                    content_type = "application/pdf" if has_pdf else ""
                    doc_id = doc_meta_url.rstrip("/").split("/")[-1] if doc_meta_url else ""
                    pdf_url = f"{doc_meta_url.rstrip('/')}/content" if doc_meta_url else ""
                    period_end, fy = parse_period_end_date(made_up_date or desc_text)
                    items.append(
                        {
                            "transaction_id": tx_id,
                            "filing_date": filing_date,
                            "form_type": form_type,
                            "description": desc_text,
                            "period_end": period_end,
                            "report_year": fy,
                            "pages": int(pages) if pages else 0,
                            "has_pdf": has_pdf,
                            "content_type": content_type,
                            "document_id": doc_id,
                            "source_url": pdf_url,
                            "source_page": f"{CH_WEB_BASE}/company/{crn}/filing-history",
                        }
                    )
                total_count = int(payload.get("total_count", len(items)))
                start_index += len(batch)
                if start_index >= total_count or len(batch) < items_per_page:
                    break
            return items

        # Public Web fallback with cookie sft=fh=accounts
        items = []
        seen_tx: set[str] = set()
        for page_num in range(1, 4):
            url = f"{CH_WEB_BASE}/company/{crn}/filing-history?page={page_num}"
            resp = await self._request(url, cookies={"sft": "fh=accounts"})
            if resp.status_code != 200:
                break
            rows = re.findall(r"<tr[^>]*>.*?</tr>", resp.text, re.S)
            page_new = 0
            for row in rows:
                doc_m = re.search(
                    r'href="(/company/[^/]+/filing-history/([^/"]+)/document\?format=pdf[^"]*)"',
                    row,
                    re.I,
                )
                tx_id = doc_m.group(2) if doc_m else ""
                if not tx_id:
                    # Check if row is an accounts filing without PDF
                    tx_alt = re.search(r"/filing-history/([A-Za-z0-9_-]{15,})", row)
                    tx_id = tx_alt.group(1) if tx_alt else ""
                if not tx_id or tx_id in seen_tx:
                    continue
                seen_tx.add(tx_id)
                page_new += 1
                cells = [
                    html.unescape(re.sub(r"\s+", " ", re.sub(r"<[^>]+>", " ", td)).strip())
                    for td in re.findall(r"<td[^>]*>(.*?)</td>", row, re.S)
                ]
                filing_date = ""
                if cells:
                    dm = re.search(r"(\d{1,2}\s+[A-Za-z]{3}\s+20\d{2})", cells[0])
                    if dm:
                        try:
                            filing_date = datetime.strptime(dm.group(1), "%d %b %Y").strftime("%Y-%m-%d")
                        except ValueError:
                            filing_date = dm.group(1)
                form_type = cells[1].strip() if len(cells) >= 3 else ""
                desc_cell = cells[2] if len(cells) >= 3 else (" ".join(cells))
                period_end, fy = parse_period_end_date(desc_cell)
                pages_m = PAGES_RE.search(row)
                pages = int(pages_m.group(1)) if pages_m else 0
                has_pdf = doc_m is not None
                pdf_url = f"{CH_WEB_BASE}{html.unescape(doc_m.group(1))}" if doc_m else ""
                items.append(
                    {
                        "transaction_id": tx_id,
                        "filing_date": filing_date,
                        "form_type": form_type,
                        "description": desc_cell,
                        "period_end": period_end,
                        "report_year": fy,
                        "pages": pages,
                        "has_pdf": has_pdf,
                        "content_type": "application/pdf" if has_pdf else "none",
                        "document_id": tx_id,
                        "source_url": pdf_url,
                        "source_page": f"{CH_WEB_BASE}/company/{crn}/filing-history",
                    }
                )
            if page_new == 0 or "page=" not in resp.text:
                break
        return items


async def fetch_gleif_crn_map(leis: list[str]) -> dict[str, dict[str, Any]]:
    """Batch-resolve UK Companies House registration numbers (`registeredAs`) from the GLEIF API."""
    result: dict[str, dict[str, Any]] = {}
    unique_leis = [lei.strip() for lei in dict.fromkeys(leis) if lei and len(lei.strip()) == 20]
    if not unique_leis:
        return result
    async with httpx.AsyncClient(timeout=25.0, headers={"Accept": "application/vnd.api+json"}) as client:
        for i in range(0, len(unique_leis), 80):
            batch = unique_leis[i : i + 80]
            url = f"https://api.gleif.org/api/v1/lei-records?filter[lei]={','.join(batch)}&page[size]=100"
            try:
                resp = await client.get(url)
                if resp.status_code != 200:
                    continue
                for item in resp.json().get("data", []):
                    lei = item.get("id", "")
                    attrs = item.get("attributes") or {}
                    entity = attrs.get("entity") or {}
                    legal_name = (entity.get("legalName") or {}).get("name") or ""
                    reg_as = normalize_uk_crn(entity.get("registeredAs") or "")
                    jurisdiction = entity.get("legalJurisdiction") or ""
                    status = entity.get("status") or ""
                    creation_date = entity.get("creationDate") or ""
                    other_names = [
                        n.get("name", "") for n in (entity.get("otherNames") or []) if n.get("name")
                    ]
                    result[lei] = {
                        "lei": lei,
                        "legal_name": legal_name,
                        "registered_as": reg_as,
                        "jurisdiction": jurisdiction,
                        "status": status,
                        "creation_date": creation_date,
                        "other_names": other_names,
                    }
            except Exception:
                continue
    return result


def evaluate_company_match(
    company: Company,
    gleif_info: dict[str, Any] | None,
    ch_profile: dict[str, Any] | None,
) -> tuple[str, str, dict[str, Any]]:
    """Evaluate multi-factor match between an LSE/UK company and a Companies House profile.

    Returns `(status, company_number, evidence_dict)` where status is one of:
    - `VERIFIED`: Exact issuer match confirmed by multi-factor evidence
    - `REVIEW`: Ambiguous match, private subsidiary (`ltd`) of PLC, or unconfirmed name collision
    - `UNAVAILABLE`: Non-UK incorporated issuer (Jersey, Guernsey, Isle of Man, Cayman, etc.) with no UK CRN
    """
    gleif_crn = normalize_uk_crn((gleif_info or {}).get("registered_as"))
    jurisdiction = (gleif_info or {}).get("jurisdiction") or ""
    isin_prefix = (company.isin or "")[:2].upper()

    # Check if non-UK incorporated offshore/overseas issuer
    if isin_prefix not in {"GB", ""} and not UK_CRN_RE.match(gleif_crn):
        return (
            "UNAVAILABLE",
            gleif_crn,
            {
                "reason": f"non_uk_isin_jurisdiction:{isin_prefix}:{jurisdiction}",
                "gleif": gleif_info or {},
            },
        )
    if gleif_crn and (NON_UK_PREFIX_RE.match(gleif_crn) or not UK_CRN_RE.match(gleif_crn)):
        return (
            "UNAVAILABLE",
            gleif_crn,
            {
                "reason": f"non_uk_registration_number:{gleif_crn}:{jurisdiction}",
                "gleif": gleif_info or {},
            },
        )
    if ch_profile is None:
        return (
            "UNAVAILABLE" if (jurisdiction and not jurisdiction.startswith("GB")) else "REVIEW",
            gleif_crn,
            {
                "reason": "no_companies_house_profile_found",
                "gleif": gleif_info or {},
            },
        )

    ch_crn = normalize_uk_crn(ch_profile.get("company_number"))
    ch_name = ch_profile.get("company_name") or ""
    ch_type = (ch_profile.get("type") or "").lower()
    ch_status = (ch_profile.get("company_status") or "").lower()
    prev_names = [
        p.get("name", "") for p in (ch_profile.get("previous_company_names") or []) if isinstance(p, dict)
    ]

    norm_target = normalize_company_name(company.company_name)
    norm_gleif = normalize_company_name((gleif_info or {}).get("legal_name") or "")
    norm_ch = normalize_company_name(ch_name)
    norm_prevs = {normalize_company_name(n) for n in prev_names if n}
    norm_aliases = {
        normalize_company_name(a)
        for a in (company.aliases.split("|") if company.aliases else [])
        if a.strip()
    } | {normalize_company_name(n) for n in ((gleif_info or {}).get("other_names") or []) if n}

    name_exact = bool(
        norm_ch
        and (
            norm_ch == norm_target
            or norm_ch == norm_gleif
            or norm_ch in norm_prevs
            or norm_target in norm_prevs
            or norm_ch in norm_aliases
        )
    )
    tokens_target = set(norm_target.split())
    tokens_ch = set(norm_ch.split())
    token_overlap = (
        len(tokens_target & tokens_ch) / max(1, min(len(tokens_target), len(tokens_ch)))
        if (tokens_target and tokens_ch)
        else 0.0
    )
    crn_confirmed_by_gleif = bool(gleif_crn and gleif_crn == ch_crn and UK_CRN_RE.match(ch_crn))

    # Guard against matching a private Limited subsidiary when the listed issuer is a PLC
    target_is_plc = "PLC" in company.company_name.upper() or "PLC" in ((gleif_info or {}).get("legal_name") or "").upper()
    ch_is_private_ltd = (
        ("private" in ch_type or ch_name.upper().endswith(" LIMITED") or ch_name.upper().endswith(" LTD"))
        and "plc" not in ch_type
        and "public" not in ch_type
        and not ch_name.upper().endswith(" PLC")
    )

    evidence = {
        "company_name": company.company_name,
        "ch_company_number": ch_crn,
        "ch_company_name": ch_name,
        "ch_type": ch_type,
        "ch_status": ch_status,
        "gleif_crn": gleif_crn,
        "crn_confirmed_by_gleif": crn_confirmed_by_gleif,
        "name_exact": name_exact,
        "token_overlap": round(token_overlap, 3),
        "previous_names": prev_names[:5],
    }

    if target_is_plc and ch_is_private_ltd and not crn_confirmed_by_gleif:
        evidence["reason"] = "listed_plc_matched_to_private_ltd_subsidiary"
        return "REVIEW", ch_crn, evidence

    if crn_confirmed_by_gleif and (name_exact or token_overlap >= 0.5):
        evidence["reason"] = "confirmed_by_gleif_crn_and_name"
        return "VERIFIED", ch_crn, evidence

    if crn_confirmed_by_gleif:
        # Even if company rebranded, GLEIF LEI -> CRN is authoritative if historical names or LEI match
        evidence["reason"] = "confirmed_by_authoritative_gleif_lei_crn"
        return "VERIFIED", ch_crn, evidence

    if name_exact and not ch_is_private_ltd:
        evidence["reason"] = "confirmed_by_exact_legal_name_and_plc_type"
        return "VERIFIED", ch_crn, evidence

    evidence["reason"] = "ambiguous_company_match_requires_review"
    return "REVIEW", ch_crn, evidence


async def match_uk_companies(
    state_path: Path,
    companies: list[Company] | None = None,
    api_key: str = "",
    limit: int | None = None,
    refresh: bool = False,
) -> dict[str, Any]:
    """Match UK (`GBR`) companies to Companies House registration numbers and store in `company_house_matches`."""
    store = DiscoveryStore(state_path)
    ensure_ch_schema(store.connection)
    try:
        target_companies = companies if companies is not None else store.companies(country="GBR")
        target_companies = [c for c in target_companies if c.country == "GBR"]
        if limit is not None:
            target_companies = target_companies[:limit]

        existing_matches: dict[str, tuple[str, str]] = {}
        if not refresh:
            for row in store.connection.execute(
                "SELECT company_key, company_number, status FROM company_house_matches"
            ):
                existing_matches[row["company_key"]] = (row["company_number"], row["status"])

        to_resolve = [
            c for c in target_companies if refresh or c.key not in existing_matches
        ]
        gleif_map = await fetch_gleif_crn_map([c.lei for c in to_resolve])
        rate_gate = PersistedRollingRateGate(state_path)

        counts = {"VERIFIED": 0, "REVIEW": 0, "UNAVAILABLE": 0, "cached": 0}
        for c in target_companies:
            if not refresh and c.key in existing_matches:
                _, st = existing_matches[c.key]
                counts[st] = counts.get(st, 0) + 1
                counts["cached"] += 1

        async with CompaniesHouseClient(api_key=api_key, rate_gate=rate_gate) as client:
            for comp in to_resolve:
                g_info = gleif_map.get(comp.lei)
                candidate_crn = normalize_uk_crn((g_info or {}).get("registered_as"))
                ch_profile = None
                if candidate_crn and UK_CRN_RE.match(candidate_crn):
                    ch_profile = await client.get_company_profile(candidate_crn)
                if ch_profile is None and (comp.isin or "").startswith("GB"):
                    search_hits = await client.search_companies(comp.company_name)
                    if len(search_hits) == 1:
                        ch_profile = await client.get_company_profile(search_hits[0]["company_number"])
                    elif len(search_hits) > 1:
                        norm_c = normalize_company_name(comp.company_name)
                        exact_hits = [
                            h
                            for h in search_hits
                            if normalize_company_name(h.get("title", "")) == norm_c
                        ]
                        if len(exact_hits) == 1:
                            ch_profile = await client.get_company_profile(exact_hits[0]["company_number"])
                        else:
                            # Ambiguous collision across multiple search hits -> REVIEW
                            now_iso = datetime.now(timezone.utc).isoformat()
                            evidence = {
                                "reason": "multiple_search_candidates_collision",
                                "candidates": search_hits[:5],
                                "gleif": g_info or {},
                            }
                            store.connection.execute(
                                """INSERT INTO company_house_matches
                                (company_key, company_number, match_evidence_json, status, checked_at)
                                VALUES (?, ?, ?, 'REVIEW', ?)
                                ON CONFLICT(company_key) DO UPDATE SET
                                company_number=excluded.company_number,
                                match_evidence_json=excluded.match_evidence_json,
                                status=excluded.status,
                                checked_at=excluded.checked_at""",
                                (comp.key, search_hits[0]["company_number"], json.dumps(evidence), now_iso),
                            )
                            store.connection.commit()
                            counts["REVIEW"] += 1
                            continue

                status, resolved_crn, evidence = evaluate_company_match(comp, g_info, ch_profile)
                now_iso = datetime.now(timezone.utc).isoformat()
                store.connection.execute(
                    """INSERT INTO company_house_matches
                    (company_key, company_number, match_evidence_json, status, checked_at)
                    VALUES (?, ?, ?, ?, ?)
                    ON CONFLICT(company_key) DO UPDATE SET
                    company_number=excluded.company_number,
                    match_evidence_json=excluded.match_evidence_json,
                    status=excluded.status,
                    checked_at=excluded.checked_at""",
                    (comp.key, resolved_crn or "", json.dumps(evidence), status, now_iso),
                )
                store.connection.commit()
                counts[status] = counts.get(status, 0) + 1

        return {
            "requested_companies": len(target_companies),
            "verified_matches": counts.get("VERIFIED", 0),
            "review_matches": counts.get("REVIEW", 0),
            "unavailable_matches": counts.get("UNAVAILABLE", 0),
            "cached_matches": counts.get("cached", 0),
        }
    finally:
        store.close()


def get_existing_verified_slots(
    conn: sqlite3.Connection,
    output_root: Path | None = None,
    check_disk: bool = False,
) -> set[tuple[str, int]]:
    """Return `(company_key, fiscal_year)` slots that already have a verified PDF in SQLite or on disk."""
    verified_slots: set[tuple[str, int]] = set()
    # Map (country, exchange, lei, isin, ticker) -> company_key
    key_map: dict[tuple[str, str, str, str, str], str] = {}
    for row in conn.execute("SELECT company_key, country, exchange, lei, isin, ticker FROM companies"):
        key_map[(row[1], row[2], row[3], row[4], row[5])] = row[0]

    # Check reports table if present
    has_reports = conn.execute("SELECT 1 FROM sqlite_master WHERE type='table' AND name='reports'").fetchone() is not None
    if has_reports:
        for rel_path, verified, status in conn.execute(
            "SELECT relative_path, verified, status FROM reports WHERE status='downloaded'"
        ):
            norm = rel_path.replace("\\", "/")
            parts = norm.split("/")
            if len(parts) >= 4:
                country, exchange, folder = parts[0], parts[1], parts[2]
                fy_str = parts[3]
                id_parts = folder.split("_")
                if len(id_parts) >= 3 and fy_str.startswith("FY") and fy_str[2:].isdigit():
                    lei, isin, ticker = id_parts[0], id_parts[1], "_".join(id_parts[2:])
                    ck = key_map.get((country, exchange, lei, isin, ticker))
                    if ck:
                        if not check_disk or output_root is None or os.path.isfile(native_path(output_root / rel_path)):
                            verified_slots.add((ck, int(fy_str[2:])))

    # Check conversions table if present
    has_conversions = conn.execute("SELECT 1 FROM sqlite_master WHERE type='table' AND name='conversions'").fetchone() is not None
    if has_conversions:
        for ck, fy, out_rel in conn.execute(
            """SELECT c.company_key, c.report_year, conv.output_relative_path
               FROM conversions conv
               JOIN candidates c ON conv.candidate_id = c.id
               WHERE conv.status IN ('downloaded', 'converted') AND c.report_year IS NOT NULL"""
        ):
            if not check_disk or output_root is None or (out_rel and os.path.isfile(native_path(output_root / out_rel))):
                verified_slots.add((ck, int(fy)))

    return verified_slots


async def discover_ch_accounts(
    state_path: Path,
    years: list[int],
    output_root: Path | None = None,
    companies: list[Company] | None = None,
    api_key: str = "",
    limit_companies: int | None = None,
) -> dict[str, Any]:
    """Discover Companies House statutory accounts for verified UK company matches."""
    store = DiscoveryStore(state_path)
    ensure_ch_schema(store.connection)
    try:
        year_set = set(years)
        verified_slots = get_existing_verified_slots(store.connection, output_root)

        target_keys = {c.key for c in companies} if companies is not None else None
        rows = store.connection.execute(
            """SELECT m.company_key, m.company_number, m.status, c.company_name
               FROM company_house_matches m
               JOIN companies c ON m.company_key = c.company_key
               WHERE m.status = 'VERIFIED' AND m.company_number != ''"""
        ).fetchall()
        if target_keys is not None:
            rows = [r for r in rows if r["company_key"] in target_keys]
        if limit_companies is not None:
            rows = rows[:limit_companies]

        rate_gate = PersistedRollingRateGate(state_path)
        stats = {
            "companies_scanned": 0,
            "filings_examined": 0,
            "ar_verified_new": 0,
            "skipped_already_verified_slot": 0,
            "review_candidates": 0,
            "excluded_candidates": 0,
        }

        async with CompaniesHouseClient(api_key=api_key, rate_gate=rate_gate) as client:
            for row in rows:
                ck = row["company_key"]
                crn = row["company_number"]
                # Check if this company actually has any missing target years
                missing_years = {y for y in year_set if (ck, y) not in verified_slots}
                if not missing_years:
                    continue

                stats["companies_scanned"] += 1
                filings = await client.get_accounts_filings(crn)
                stats["filings_examined"] += len(filings)

                # Group filings by report_year to detect multiple/amended filings in the same year
                by_year: dict[int | None, list[dict[str, Any]]] = {}
                for f in filings:
                    fy = f.get("report_year")
                    if fy is not None and fy not in year_set:
                        continue
                    by_year.setdefault(fy, []).append(f)

                now_iso = datetime.now(timezone.utc).isoformat()
                for fy, fy_filings in by_year.items():
                    # Classify each filing in this fiscal year
                    classified_list: list[tuple[dict[str, Any], str, str]] = []
                    for f in fy_filings:
                        cls_status, reason = classify_ch_accounts_filing(
                            form_type=f.get("form_type", ""),
                            description=f.get("description", ""),
                            period_end=f.get("period_end", ""),
                            has_pdf=bool(f.get("has_pdf")),
                            pages=f.get("pages") or None,
                        )
                        classified_list.append((f, cls_status, reason))

                    ar_candidates = [item for item in classified_list if item[1] == "AR"]
                    # If multiple distinct AR candidates exist for the same company-year, require review
                    if len(ar_candidates) > 1:
                        classified_list = [
                            (f, "REVIEW" if st == "AR" else st, "multiple_accounts_filings_same_fy" if st == "AR" else rsn)
                            for (f, st, rsn) in classified_list
                        ]

                    for f, cls_status, reason in classified_list:
                        tx_id = f.get("transaction_id") or ""
                        doc_id = f.get("document_id") or ""
                        src_url = f.get("source_url") or f.get("source_page") or ""
                        period_end = f.get("period_end") or ""
                        filing_date = f.get("filing_date") or ""
                        form_type = f.get("form_type") or ""
                        desc = f.get("description") or ""
                        content_type = f.get("content_type") or ""
                        pages = int(f.get("pages") or 0)

                        store.connection.execute(
                            """INSERT INTO ch_audit_log
                            (company_key, company_number, transaction_id, document_id, source_url,
                             report_year, period_end, filing_date, form_type, description,
                             content_type, pages, classification, rejection_reason, checked_at)
                            VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)
                            ON CONFLICT(company_key, company_number, transaction_id) DO UPDATE SET
                            source_url=excluded.source_url, report_year=excluded.report_year,
                            period_end=excluded.period_end, filing_date=excluded.filing_date,
                            form_type=excluded.form_type, description=excluded.description,
                            content_type=excluded.content_type, pages=excluded.pages,
                            classification=excluded.classification,
                            rejection_reason=excluded.rejection_reason,
                            checked_at=excluded.checked_at""",
                            (
                                ck, crn, tx_id, doc_id, src_url,
                                fy, period_end, filing_date, form_type, desc,
                                content_type, pages, cls_status, reason, now_iso,
                            ),
                        )

                        if cls_status == "AR" and fy is not None:
                            if (ck, fy) in verified_slots:
                                stats["skipped_already_verified_slot"] += 1
                                continue
                            store.upsert_candidate(
                                company_key=ck,
                                report_year=fy,
                                source="COMPANIES_HOUSE",
                                source_record_id=f"{crn}:{tx_id}",
                                source_url=src_url,
                                source_format="PDF",
                                form_type=form_type or "AA",
                                filing_date=filing_date,
                                publication_date=filing_date,
                                report_date=period_end,
                                description=desc,
                                status="VERIFIED_DIRECT_PDF",
                                verified=True,
                                metadata={
                                    "company_number": crn,
                                    "transaction_id": tx_id,
                                    "document_id": doc_id,
                                    "period_end": period_end,
                                    "pages": pages,
                                    "source_page": f.get("source_page", ""),
                                },
                            )
                            stats["ar_verified_new"] += 1
                        elif cls_status == "REVIEW":
                            stats["review_candidates"] += 1
                            store.upsert_candidate(
                                company_key=ck,
                                report_year=fy,
                                source="COMPANIES_HOUSE",
                                source_record_id=f"{crn}:{tx_id}",
                                source_url=src_url,
                                source_format="PDF" if f.get("has_pdf") else "UNKNOWN",
                                form_type=form_type,
                                filing_date=filing_date,
                                publication_date=filing_date,
                                report_date=period_end,
                                description=desc,
                                status="REVIEW",
                                verified=False,
                                metadata={
                                    "company_number": crn,
                                    "transaction_id": tx_id,
                                    "rejection_reason": reason,
                                    "period_end": period_end,
                                    "pages": pages,
                                },
                            )
                        else:
                            stats["excluded_candidates"] += 1
                store.connection.commit()

        return stats
    finally:
        store.close()


def export_ch_review(
    state_path: Path,
    output_csv: Path,
    companies: list[Company] | None = None,
) -> dict[str, Any]:
    """Export Companies House match review items and filing review/exclusion audit rows to CSV."""
    conn = sqlite3.connect(state_path)
    conn.row_factory = sqlite3.Row
    ensure_ch_schema(conn)
    try:
        target_keys = {c.key for c in companies} if companies is not None else None
        output_csv.parent.mkdir(parents=True, exist_ok=True)
        fields = [
            "review_kind",
            "company_key",
            "company_name",
            "company_number",
            "status",
            "report_year",
            "period_end",
            "filing_date",
            "form_type",
            "description",
            "reason",
            "source_url",
        ]
        rows_written = 0
        with output_csv.open("w", encoding="utf-8", newline="") as f:
            writer = csv.DictWriter(f, fieldnames=fields)
            writer.writeheader()

            for m in conn.execute(
                """SELECT m.company_key, c.company_name, m.company_number, m.status, m.match_evidence_json
                   FROM company_house_matches m
                   JOIN companies c ON m.company_key = c.company_key
                   WHERE m.status != 'VERIFIED'
                   ORDER BY c.company_name"""
            ):
                if target_keys is not None and m["company_key"] not in target_keys:
                    continue
                ev = json.loads(m["match_evidence_json"] or "{}")
                writer.writerow(
                    {
                        "review_kind": "COMPANY_MATCH",
                        "company_key": _cell(m["company_key"]),
                        "company_name": _cell(m["company_name"]),
                        "company_number": _cell(m["company_number"]),
                        "status": m["status"],
                        "report_year": "",
                        "period_end": "",
                        "filing_date": "",
                        "form_type": "",
                        "description": "",
                        "reason": _cell(ev.get("reason", "")),
                        "source_url": f"{CH_WEB_BASE}/company/{m['company_number']}" if m["company_number"] else "",
                    }
                )
                rows_written += 1

            for a in conn.execute(
                """SELECT a.*, c.company_name
                   FROM ch_audit_log a
                   JOIN companies c ON a.company_key = c.company_key
                   WHERE a.classification != 'AR'
                   ORDER BY c.company_name, a.report_year DESC"""
            ):
                if target_keys is not None and a["company_key"] not in target_keys:
                    continue
                writer.writerow(
                    {
                        "review_kind": "FILING_CANDIDATE",
                        "company_key": _cell(a["company_key"]),
                        "company_name": _cell(a["company_name"]),
                        "company_number": _cell(a["company_number"]),
                        "status": a["classification"],
                        "report_year": a["report_year"] or "",
                        "period_end": a["period_end"],
                        "filing_date": a["filing_date"],
                        "form_type": a["form_type"],
                        "description": _cell(a["description"]),
                        "reason": _cell(a["rejection_reason"]),
                        "source_url": a["source_url"],
                    }
                )
                rows_written += 1

        return {"output_csv": str(output_csv), "rows_written": rows_written}
    finally:
        conn.close()


def export_ch_manifest(
    state_path: Path,
    output_csv: Path,
    output_root: Path | None = None,
    companies: list[Company] | None = None,
    years: list[int] | None = None,
) -> int:
    """Export verified `COMPANIES_HOUSE` `AR` PDF candidates for missing slots to a manifest CSV."""
    conn = sqlite3.connect(state_path)
    conn.row_factory = sqlite3.Row
    ensure_ch_schema(conn)
    try:
        verified_slots = get_existing_verified_slots(conn, output_root)
        target_keys = {c.key for c in companies} if companies is not None else None
        year_set = set(years) if years is not None else None

        rows = conn.execute(
            """SELECT c.country, c.company_name, c.exchange, c.lei, c.isin, c.ticker,
                      d.company_key, d.report_year, d.source_url, d.metadata_json, d.filing_date
               FROM candidates d
               JOIN companies c ON c.company_key = d.company_key
               WHERE d.source = 'COMPANIES_HOUSE'
                 AND d.verified = 1
                 AND d.source_format = 'PDF'
                 AND d.status = 'VERIFIED_DIRECT_PDF'
                 AND d.report_year IS NOT NULL
               ORDER BY c.country, c.exchange, c.ticker, d.report_year, d.filing_date DESC"""
        ).fetchall()

        output_csv.parent.mkdir(parents=True, exist_ok=True)
        chosen: dict[tuple[str, int], sqlite3.Row] = {}
        for r in rows:
            ck = r["company_key"]
            fy = int(r["report_year"])
            if target_keys is not None and ck not in target_keys:
                continue
            if year_set is not None and fy not in year_set:
                continue
            if (ck, fy) in verified_slots:
                continue
            chosen.setdefault((ck, fy), r)

        with output_csv.open("w", encoding="utf-8", newline="") as f:
            writer = csv.DictWriter(f, fieldnames=FIELDS)
            writer.writeheader()
            for r in chosen.values():
                meta = json.loads(r["metadata_json"] or "{}")
                crn = meta.get("company_number", "")
                source_page = meta.get("source_page") or (
                    f"{CH_WEB_BASE}/company/{crn}/filing-history" if crn else ""
                )
                writer.writerow(
                    {
                        "country": _cell(r["country"]),
                        "exchange": _cell(r["exchange"]),
                        "lei": _cell(r["lei"]),
                        "isin": _cell(r["isin"]),
                        "ticker": _cell(r["ticker"]),
                        "fiscal_year": f"FY{r['report_year']}",
                        "report_type": "AR",
                        "language": "EN",
                        "pdf_url": r["source_url"],
                        "source_page": source_page,
                        "verified": "true",
                    }
                )
        return len(chosen)
    finally:
        conn.close()
