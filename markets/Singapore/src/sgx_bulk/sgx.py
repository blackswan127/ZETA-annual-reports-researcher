from __future__ import annotations

import asyncio
import re
from collections import defaultdict
from datetime import UTC, datetime
from typing import Any

from .htmlparse import attachment_score, safe_pdf_links
from .httpclient import RetryingClient
from .models import Attachment, Filing, Issuer
from .util import epoch_ms_date, epoch_ms_datetime, normalize_name

STOCKS_URL = "https://api.sgx.com/securities/v1.1/stocks"
METADATA_URL = "https://api.sgx.com/marketmetadata/v2"
CORPORATE_INFO_URL = "https://api.sgx.com/corporateinformation/v1.0"
REPORTS_URL = "https://api.sgx.com/financialreports/v1.0"
LISTED_MARKETS = {"MAINBOARD", "CATALIST"}
CODE_RE = re.compile(r"^[A-Z0-9]{3,4}$")
ANN_RE = re.compile(r"^[A-Z0-9]{16}$")


class SGXSource:
    def __init__(self, http: RetryingClient):
        self.http = http

    async def current_issuers(self) -> list[Issuer]:
        stocks_r, meta_r = await asyncio.gather(
            self.http.request("GET", STOCKS_URL, params={
                "params": "nc,n,type,ls,m,sc,bl,sip,ex,ej,clo,cr,cur,el,r,i,cc,ig,lf"
            }),
            self.http.request("GET", METADATA_URL),
        )
        stocks = stocks_r.json().get("data", {}).get("prices", [])
        metadata = meta_r.json().get("data", [])
        by_stock = {
            str(row.get("stockCode", "")).upper(): row
            for row in metadata
            if CODE_RE.fullmatch(str(row.get("stockCode", "")).upper())
        }
        # SGX's securities feed is a counter feed, not a complete issuer
        # directory: trusts and other listed reporting entities can be absent.
        # Corporate Information is the issuer roster; use live counters when
        # available and metadata counters as stable identifiers otherwise.
        profile_rows = await self._corporate_information_rows()
        out: dict[str, Issuer] = {}
        for row in stocks:
            if str(row.get("m", "")).upper() not in LISTED_MARKETS:
                continue
            if str(row.get("type", "")).casefold() != "stocks":
                continue
            stock = str(row.get("nc", "")).upper()
            if not CODE_RE.fullmatch(stock):
                continue
            meta = by_stock.get(stock)
            if not meta:
                continue
            ibm = str(meta.get("ibmCode", "")).upper()
            name = " ".join(str(meta.get("issuerName", "")).split())
            if not CODE_RE.fullmatch(ibm) or not name:
                continue
            short = " ".join(str(row.get("n", "")).split())
            out.setdefault(ibm, Issuer(ibm, stock, name, short, str(row.get("m", "")).upper()))

        for profile in profile_rows:
            market = str(profile.get("market", "")).strip().upper()
            if market not in LISTED_MARKETS:
                continue
            ibm = str(profile.get("ibmCode", "")).strip().upper()
            name = " ".join(str(profile.get("companyName", "")).split())
            if not CODE_RE.fullmatch(ibm) or not name:
                continue
            if ibm in out:
                # Corporate Information gives the official issuer name.
                current = out[ibm]
                out[ibm] = Issuer(ibm, current.stock_code, name, current.short_name or name, market)
                continue
            # Do not borrow a historical counter from the all-time metadata
            # table; the issuer code is the stable identifier for this row.
            out[ibm] = Issuer(ibm, ibm, name, name, market)
        return sorted(out.values(), key=lambda i: i.stock_code)

    async def _corporate_information_rows(self, page_size: int = 100) -> list[dict[str, Any]]:
        headers = {
            "Origin": "https://www.sgx.com",
            "Referer": "https://www.sgx.com/stock-exchange/corporate-information",
            "Accept": "application/json, text/plain, */*",
        }
        first = await self.http.request(
            "GET", CORPORATE_INFO_URL,
            params={"pagestart": 0, "pagesize": page_size}, headers=headers,
        )
        payload = first.json()
        if not isinstance(payload, dict) or not isinstance(payload.get("data"), list):
            raise RuntimeError("SGX returned invalid Corporate Information JSON")
        meta = payload.get("meta") or {}
        total_pages = int(meta.get("totalPages", 1))
        if total_pages < 1 or total_pages > 100:
            raise RuntimeError(f"Unexpected SGX Corporate Information totalPages={total_pages}")
        rows = list(payload["data"])

        async def get_page(page: int) -> list[dict[str, Any]]:
            response = await self.http.request(
                "GET", CORPORATE_INFO_URL,
                params={"pagestart": page, "pagesize": page_size}, headers=headers,
            )
            result = response.json()
            if not isinstance(result, dict) or not isinstance(result.get("data"), list):
                raise RuntimeError(f"SGX returned invalid Corporate Information page {page}")
            return result["data"]

        rows.extend(row for page in await asyncio.gather(*(get_page(p) for p in range(1, total_pages))) for row in page)
        return rows

    async def _report_page(self, page: int, page_size: int = 100, company_name: str | None = None) -> dict[str, Any]:
        params: dict[str, Any] = {
            "pagestart": page,
            "pagesize": page_size,
            "params": "id,companyName,documentDate,securityName,title,url,broadcastDateTime",
        }
        if company_name:
            params["companyname"] = company_name
        r = await self.http.request("GET", REPORTS_URL, params=params)
        payload = r.json()
        if not isinstance(payload, dict) or not isinstance(payload.get("data"), list):
            raise RuntimeError("SGX returned invalid financialreports JSON")
        return payload

    async def global_report_rows(self, workers: int = 6, page_size: int = 100) -> list[dict[str, Any]]:
        first = await self._report_page(0, page_size=page_size)
        meta = first.get("meta") or {}
        total_pages = int(meta.get("totalPages", 1))
        if total_pages < 1 or total_pages > 500:
            raise RuntimeError(f"Unexpected SGX totalPages={total_pages}")
        rows = list(first["data"])
        sem = asyncio.Semaphore(max(1, workers))

        async def get_page(p: int) -> list[dict[str, Any]]:
            async with sem:
                payload = await self._report_page(p, page_size=page_size)
                return payload["data"]

        tasks = [asyncio.create_task(get_page(p)) for p in range(1, total_pages)]
        for done in asyncio.as_completed(tasks):
            rows.extend(await done)
        return rows

    async def company_report_rows(self, issuer: Issuer) -> list[dict[str, Any]]:
        rows: list[dict[str, Any]] = []
        page = 0
        while page < 20:
            payload = await self._report_page(page, page_size=100, company_name=issuer.issuer_name)
            rows.extend(payload["data"])
            total = int((payload.get("meta") or {}).get("totalPages", 1))
            page += 1
            if page >= total:
                break
        return rows

    @staticmethod
    def issuer_alias_index(issuers: list[Issuer]) -> dict[str, list[Issuer]]:
        idx: dict[str, list[Issuer]] = defaultdict(list)
        for i in issuers:
            for value in (i.issuer_name, i.short_name):
                key = normalize_name(value)
                if key:
                    idx[key].append(i)
        return idx

    @staticmethod
    def row_year(row: dict[str, Any]) -> int | None:
        d = epoch_ms_date(row.get("documentDate"))
        return d.year if d else None

    @staticmethod
    def is_annual(row: dict[str, Any]) -> bool:
        return str(row.get("title", "")).strip().casefold() == "annual report"

    @classmethod
    def map_row(cls, row: dict[str, Any], alias_index: dict[str, list[Issuer]]) -> tuple[Issuer | None, str]:
        for field in ("companyName", "securityName"):
            key = normalize_name(str(row.get(field, "")))
            matches = alias_index.get(key, []) if key else []
            unique = {x.ibm_code: x for x in matches}
            if len(unique) == 1:
                return next(iter(unique.values())), field
            if len(unique) > 1:
                return None, f"ambiguous-{field}"
        return None, "no-current-issuer-name-match"

    @classmethod
    def filing_from_row(cls, row: dict[str, Any], issuer: Issuer) -> Filing | None:
        if not cls.is_annual(row):
            return None
        ann = str(row.get("id", "")).strip().upper()
        if not ANN_RE.fullmatch(ann):
            return None
        period = epoch_ms_date(row.get("documentDate"))
        broadcast = epoch_ms_datetime(row.get("broadcastDateTime"))
        detail = str(row.get("url", "")).strip()
        if not period or not broadcast or f"/{ann}/" not in detail:
            return None
        return Filing(
            announcement_id=ann,
            ibm_code=issuer.ibm_code,
            stock_code=issuer.stock_code,
            issuer_name=issuer.issuer_name,
            short_name=issuer.short_name,
            fiscal_year=period.year,
            period_end=period,
            broadcast_at=broadcast.astimezone(UTC),
            detail_url=detail,
        )

    async def resolve_attachments(self, filing: Filing) -> tuple[list[Attachment], set[str]]:
        r = await self.http.request("GET", filing.detail_url)
        links = safe_pdf_links(r.text, filing.detail_url)
        attachments = [
            Attachment(filing.announcement_id, url, filename, attachment_score(filename, filing.fiscal_year))
            for url, filename in links
        ]
        if not attachments:
            return [], set()
        ranked = sorted(attachments, key=lambda a: (a.score, a.filename), reverse=True)
        selected: set[str] = set()
        best = ranked[0]
        if best.score >= 0:
            selected.add(best.url)
        # Preserve genuinely split annual reports, but do not pull notices/proxies/ESG supplements.
        for a in ranked[1:]:
            if a.score >= 100 and best.score - a.score <= 25:
                selected.add(a.url)
        return attachments, selected
