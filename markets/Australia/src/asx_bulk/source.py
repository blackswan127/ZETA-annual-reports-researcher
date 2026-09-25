from __future__ import annotations

import asyncio
import csv
import io
import random
from urllib.parse import urlencode

import httpx

from .config import ASX_COMPANIES_CSV, ASX_DIR_API, ASX_HISTORY_URL, USER_AGENT
from .models import Issuer
from .parser import parse_announcements_html, parse_pdf_url
from .util import AsyncRateLimiter

class ASXSource:
    def __init__(self, timeout: float = 45.0, retries: int = 5, metadata_rps: float = 3.0):
        self.timeout = timeout
        self.retries = retries
        self.rate = AsyncRateLimiter(metadata_rps)
        self.client = httpx.AsyncClient(
            timeout=httpx.Timeout(timeout),
            follow_redirects=True,
            headers={
                "User-Agent": USER_AGENT,
                "Accept-Language": "en-AU,en;q=0.9",
                "Accept": "text/html,application/xhtml+xml,application/json,text/csv,*/*;q=0.8",
            },
            limits=httpx.Limits(max_connections=30, max_keepalive_connections=15),
        )

    async def close(self):
        await self.client.aclose()

    async def _get(self, url: str, *, params=None) -> httpx.Response:
        err = None
        for attempt in range(self.retries):
            await self.rate.acquire()
            try:
                r = await self.client.get(url, params=params)
                if r.status_code == 429 or 500 <= r.status_code < 600:
                    err = httpx.HTTPStatusError(
                        f"retryable HTTP status {r.status_code}", request=r.request, response=r
                    )
                    if attempt + 1 >= self.retries:
                        break
                    retry_after = r.headers.get("Retry-After")
                    try:
                        delay = float(retry_after) if retry_after else min(30, 1.5 ** attempt)
                    except ValueError:
                        delay = min(30, 1.5 ** attempt)
                    await asyncio.sleep(delay + random.random() * 0.25)
                    continue
                r.raise_for_status()
                return r
            except (httpx.HTTPError, OSError) as exc:
                err = exc
                if attempt + 1 < self.retries:
                    await asyncio.sleep(min(30, 1.5 ** attempt) + random.random() * 0.25)
        raise RuntimeError(f"GET failed after {self.retries} attempts: {url}: {err}")

    async def current_issuers(self) -> list[Issuer]:
        # Primary: the current ASX front-end company directory. It is company-focused,
        # unlike a security master that also contains ETFs/options/warrants.
        try:
            r = await self._get(ASX_DIR_API, params={"itemsPerPage": 2500, "page": 0})
            data = r.json()
            items = data.get("data", {}).get("items", []) if isinstance(data, dict) else []
            issuers: list[Issuer] = []
            for item in items:
                if not isinstance(item, dict):
                    continue
                ticker = str(item.get("symbol") or item.get("code") or item.get("asxCode") or "").strip().upper()
                name = str(item.get("displayName") or item.get("name") or item.get("companyName") or "").strip()
                if not ticker or not name:
                    continue
                industry = str(item.get("industry") or item.get("industryGroup") or item.get("sector") or "").strip()
                listing_date = str(item.get("listingDate") or item.get("listing_date") or "").strip()
                issuers.append(Issuer(ticker=ticker, name=name, industry=industry, listing_date=listing_date, source="markit_directory"))
            # Protect against an upstream schema change returning a tiny/empty set.
            if len(issuers) >= 500:
                dedup = {i.ticker: i for i in issuers}
                return sorted(dedup.values(), key=lambda x: x.ticker)
        except Exception:
            pass

        # Fallback: long-standing official ASX listed-companies CSV.
        r = await self._get(ASX_COMPANIES_CSV)
        text = r.text.lstrip("\ufeff")
        lines = text.splitlines()
        rows = list(csv.reader(io.StringIO("\n".join(lines[3:] if len(lines) > 3 else lines))))
        issuers = []
        for row in rows:
            if len(row) < 2:
                continue
            name, ticker = row[0].strip(), row[1].strip().upper()
            industry = row[2].strip() if len(row) > 2 else ""
            if ticker and name:
                issuers.append(Issuer(ticker=ticker, name=name, industry=industry, source="asx_csv"))
        dedup = {i.ticker: i for i in issuers}
        if not dedup:
            raise RuntimeError("ASX current-company universe returned no usable issuers")
        return sorted(dedup.values(), key=lambda x: x.ticker)

    async def annual_candidates(self, ticker: str, publication_year: int):
        params = {"asxCode": ticker, "by": "asxCode", "timeframe": "Y", "year": publication_year}
        r = await self._get(ASX_HISTORY_URL, params=params)
        return parse_announcements_html(r.text, ticker, publication_year)

    async def resolve_pdf_url(self, display_url: str) -> str:
        r = await self._get(display_url)
        url = parse_pdf_url(r.text)
        if not url:
            # Search result can occasionally redirect directly to a PDF.
            if r.headers.get("content-type", "").lower().startswith("application/pdf"):
                return str(r.url)
            raise RuntimeError("ASX display page did not expose a pdfURL")
        return url
