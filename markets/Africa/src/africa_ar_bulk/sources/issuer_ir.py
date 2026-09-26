from __future__ import annotations

import asyncio
import hashlib
import logging
import re
from typing import List, Optional, Set
from urllib.parse import urljoin, urlsplit

import httpx

from ..classify import classify_document
from ..fy import resolve_fy
from ..models import Candidate, Issuer
from .base import BaseSourceAdapter

logger = logging.getLogger(__name__)

try:
    from curl_cffi.requests import AsyncSession
    HAS_CURL_CFFI = True
except ImportError:
    HAS_CURL_CFFI = False

from .archive_wayback import WaybackArchiveAdapter
from .spa_crawler import DynamicSPACrawler

IR_SUBPATHS = [
    "/investors",
    "/investor-relations",
    "/financial-results",
    "/financial-reports",
    "/reports",
    "/annual-reports",
    "/financials",
    "/publications",
    "/results-and-reports",
    "/sustainability",
    "/esg",
    "/integrated-reports",
]


def stable_candidate_id(issuer_id: str, fy: Optional[int], report_type: str, url: str) -> str:
    seed = f"{issuer_id}:{fy or ''}:{report_type}:{url}".encode("utf-8")
    return hashlib.sha256(seed).hexdigest()[:24]


class IssuerIRCrawler(BaseSourceAdapter):
    """Autonomous Corporate IR Crawler with WAF bypass, dynamic SPA extraction, and archive backfill."""

    def __init__(
        self,
        timeout: float = 25.0,
        user_agent: str = "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36",
    ):
        self.timeout = timeout
        self.user_agent = user_agent
        self.headers = {
            "User-Agent": user_agent,
            "Accept": "text/html,application/xhtml+xml,application/xml;q=0.9,*/*;q=0.8",
            "Accept-Language": "en-US,en;q=0.9",
        }
        self.session: Optional[Any] = None
        if HAS_CURL_CFFI:
            try:
                self.session = AsyncSession(impersonate="chrome120", timeout=timeout, headers=self.headers)
            except Exception as e:
                logger.debug(f"Failed to initialize curl_cffi AsyncSession in IR crawler: {e}")
                self.session = None

        self.client = httpx.AsyncClient(
            timeout=httpx.Timeout(timeout, connect=10.0),
            follow_redirects=True,
            headers=self.headers,
        )
        self.spa_crawler = DynamicSPACrawler(timeout=15.0)
        self.wayback_adapter = WaybackArchiveAdapter(timeout=6.0, user_agent=user_agent)

    async def close(self):
        if self.session:
            try:
                await self.session.close()
            except Exception:
                pass
        await self.client.aclose()
        await self.spa_crawler.close()
        await self.wayback_adapter.close()

    async def _fetch_html(self, u: str) -> Optional[str]:
        if self.session:
            try:
                r = await asyncio.wait_for(self.session.get(u), timeout=8.0)
                if r.status_code == 200:
                    return r.text
            except Exception:
                pass

        try:
            r = await self.client.get(u, timeout=8.0)
            if r.status_code == 200:
                return r.text
        except Exception:
            pass

        return None

    async def discover_candidates(
        self,
        issuer: Issuer,
        start_year: int,
        end_year: int,
    ) -> List[Candidate]:
        if not issuer.source_url:
            return []

        candidates: List[Candidate] = []
        base_url = issuer.source_url.rstrip("/")
        seen_pdf_urls: Set[str] = set()

        target_urls = [base_url] + [urljoin(base_url, path) for path in IR_SUBPATHS]
        url_lock = asyncio.Lock()

        async def fetch_page(u: str):
            try:
                html = await asyncio.wait_for(self._fetch_html(u), timeout=9.0)
                if not html:
                    return
                links = re.findall(r'<a\s+[^>]*href=["\']([^"\']+\.pdf[^"\']*)["\'][^>]*>(.*?)</a>', html, re.I | re.DOTALL)
                for href, anchor_text in links:
                    full_pdf = urljoin(u, href)
                    async with url_lock:
                        if full_pdf in seen_pdf_urls:
                            continue
                        seen_pdf_urls.add(full_pdf)

                    clean_title = re.sub(r"<[^>]+>", " ", anchor_text).strip()
                    if not clean_title:
                        clean_title = href.split("/")[-1].replace(".pdf", "").replace("-", " ").replace("_", " ")

                    is_ar, label, cls_score = classify_document(clean_title, full_pdf)
                    if not is_ar:
                        continue

                    fy, fy_conf, _ = resolve_fy(clean_title)
                    if not fy:
                        fy, fy_conf, _ = resolve_fy(href)

                    if fy and not (start_year <= fy <= end_year):
                        continue

                    cid = stable_candidate_id(issuer.issuer_id, fy, label, full_pdf)
                    cand = Candidate(
                        candidate_id=cid,
                        issuer_id=issuer.issuer_id,
                        source_name="ISSUER_IR",
                        source_url=full_pdf,
                        title=clean_title[:250],
                        resolved_fy=fy,
                        fy_confidence=fy_conf,
                        classification=label,
                        classification_score=cls_score,
                        direct_pdf_url=full_pdf,
                    )
                    async with url_lock:
                        candidates.append(cand)
            except Exception as e:
                logger.debug(f"IR crawl error for {issuer.ticker} on {u}: {e}")

        # 1. Fast concurrent HTML crawling with WAF bypass (strict 20s total cap)
        try:
            await asyncio.wait_for(asyncio.gather(*(fetch_page(u) for u in target_urls)), timeout=20.0)
        except Exception:
            pass

        # 2. Dynamic SPA Crawling fallback if static HTML found 0 candidates (strict 15s cap)
        if len(candidates) == 0:
            try:
                spa_cands = await asyncio.wait_for(
                    self.spa_crawler.extract_dynamic_candidates(
                        issuer=issuer,
                        target_url=base_url,
                        start_year=start_year,
                        end_year=end_year,
                    ),
                    timeout=15.0,
                )
                for sc in spa_cands:
                    if sc.direct_pdf_url not in seen_pdf_urls:
                        seen_pdf_urls.add(sc.direct_pdf_url)
                        candidates.append(sc)
            except Exception as e:
                logger.debug(f"SPA crawl error for {issuer.ticker}: {e}")

        # 3. Wayback Machine Historical Archive Backfill for missing earlier years (2017-2021)
        found_years = {c.resolved_fy for c in candidates if c.resolved_fy}
        missing_early_years = [y for y in range(start_year, min(end_year, 2022) + 1) if y not in found_years]
        if missing_early_years:
            try:
                wb_cands = await asyncio.wait_for(
                    self.wayback_adapter.discover_candidates(
                        issuer=issuer,
                        start_year=start_year,
                        end_year=min(end_year, 2022),
                    ),
                    timeout=8.0,
                )
                for wc in wb_cands:
                    if wc.direct_pdf_url not in seen_pdf_urls:
                        seen_pdf_urls.add(wc.direct_pdf_url)
                        candidates.append(wc)
            except Exception as e:
                logger.debug(f"Wayback archive error for {issuer.ticker}: {e}")

        return candidates
