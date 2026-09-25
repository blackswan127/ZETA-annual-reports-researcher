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

IR_SUBPATHS = [
    "/investors",
    "/investor-relations",
    "/financial-results",
    "/reports",
    "/annual-reports",
    "/financials",
    "/publications",
]


def stable_candidate_id(issuer_id: str, fy: Optional[int], report_type: str, url: str) -> str:
    seed = f"{issuer_id}:{fy or ''}:{report_type}:{url}".encode("utf-8")
    return hashlib.sha256(seed).hexdigest()[:24]


class IssuerIRCrawler(BaseSourceAdapter):
    """Autonomous Corporate IR Crawler for African listed issuers."""

    def __init__(
        self,
        timeout: float = 25.0,
        user_agent: str = "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36",
    ):
        self.timeout = timeout
        self.headers = {
            "User-Agent": user_agent,
            "Accept": "text/html,application/xhtml+xml,application/xml;q=0.9,*/*;q=0.8",
        }
        self.client = httpx.AsyncClient(
            timeout=httpx.Timeout(timeout, connect=15.0),
            follow_redirects=True,
            headers=self.headers,
        )

    async def close(self):
        await self.client.aclose()

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
        visited_urls: Set[str] = set()
        seen_pdf_urls: Set[str] = set()

        target_urls = [base_url] + [urljoin(base_url, path) for path in IR_SUBPATHS]
        url_lock = asyncio.Lock()

        async def fetch_page(u: str):
            try:
                r = await self.client.get(u, timeout=12.0)
                if r.status_code != 200:
                    return
                links = re.findall(r'<a\s+[^>]*href=["\']([^"\']+\.pdf[^"\']*)["\'][^>]*>(.*?)</a>', r.text, re.I | re.DOTALL)
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

        await asyncio.gather(*(fetch_page(u) for u in target_urls))
        return candidates
