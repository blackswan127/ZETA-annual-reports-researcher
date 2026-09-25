from __future__ import annotations

import asyncio
import hashlib
import logging
import re
from typing import Any, Dict, List, Optional
from urllib.parse import urljoin

import httpx

from ..classify import classify_document
from ..fy import resolve_fy
from ..models import Candidate, Issuer
from .base import BaseSourceAdapter

logger = logging.getLogger(__name__)


def stable_candidate_id(issuer_id: str, fy: Optional[int], url: str) -> str:
    seed = f"{issuer_id}:{fy or ''}:{url}".encode("utf-8")
    return hashlib.sha256(seed).hexdigest()[:24]


class DirectExchangeAdapter(BaseSourceAdapter):
    """Direct exchange portal adapter for African financial disclosure feeds."""

    def __init__(
        self,
        timeout: float = 30.0,
        user_agent: str = "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36",
    ):
        self.timeout = timeout
        self.headers = {
            "User-Agent": user_agent,
            "Accept": "text/html,application/xhtml+xml,application/json,*/*",
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
        candidates: List[Candidate] = []
        mic = issuer.exchange_mic.upper()

        try:
            # Query based on market
            if mic == "XNSA":  # Nigeria NGX
                candidates = await self._discover_ngx(issuer, start_year, end_year)
            elif mic == "XNAI":  # Kenya NSE
                candidates = await self._discover_nse_kenya(issuer, start_year, end_year)
            elif mic == "XBOT":  # Botswana BSE
                candidates = await self._discover_bse_botswana(issuer, start_year, end_year)
            elif mic == "XGHA":  # Ghana GSE
                candidates = await self._discover_gse_ghana(issuer, start_year, end_year)
        except Exception as e:
            logger.debug(f"Direct exchange query error for {issuer.ticker} ({mic}): {e}")

        return candidates

    async def _discover_ngx(self, issuer: Issuer, start_year: int, end_year: int) -> List[Candidate]:
        candidates: List[Candidate] = []
        url = f"https://ngxgroup.com/exchange/data/company-profile/?symbol={issuer.ticker}"
        try:
            r = await self.client.get(url)
            if r.status_code == 200:
                candidates.extend(self._extract_pdf_candidates(r.text, url, issuer, start_year, end_year, "NGX_DIRECT"))
        except Exception:
            pass
        return candidates

    async def _discover_nse_kenya(self, issuer: Issuer, start_year: int, end_year: int) -> List[Candidate]:
        candidates: List[Candidate] = []
        url = f"https://www.nse.co.ke/listed-companies/{issuer.ticker.lower()}"
        try:
            r = await self.client.get(url)
            if r.status_code == 200:
                candidates.extend(self._extract_pdf_candidates(r.text, url, issuer, start_year, end_year, "NSE_KENYA_DIRECT"))
        except Exception:
            pass
        return candidates

    async def _discover_bse_botswana(self, issuer: Issuer, start_year: int, end_year: int) -> List[Candidate]:
        candidates: List[Candidate] = []
        url = f"https://www.bse.co.bw/listed-companies/{issuer.ticker.lower()}"
        try:
            r = await self.client.get(url)
            if r.status_code == 200:
                candidates.extend(self._extract_pdf_candidates(r.text, url, issuer, start_year, end_year, "BSE_BOTSWANA_DIRECT"))
        except Exception:
            pass
        return candidates

    async def _discover_gse_ghana(self, issuer: Issuer, start_year: int, end_year: int) -> List[Candidate]:
        candidates: List[Candidate] = []
        url = f"https://gse.com.gh/listed-company/{issuer.ticker.lower()}"
        try:
            r = await self.client.get(url)
            if r.status_code == 200:
                candidates.extend(self._extract_pdf_candidates(r.text, url, issuer, start_year, end_year, "GSE_GHANA_DIRECT"))
        except Exception:
            pass
        return candidates

    def _extract_pdf_candidates(
        self,
        html: str,
        base_url: str,
        issuer: Issuer,
        start_year: int,
        end_year: int,
        source_name: str,
    ) -> List[Candidate]:
        candidates: List[Candidate] = []
        # Find <a> tags with href containing .pdf
        links = re.findall(r'<a\s+[^>]*href=["\']([^"\']+\.pdf[^"\']*)["\'][^>]*>(.*?)</a>', html, re.I | re.DOTALL)
        seen_urls = set()

        for href, anchor_text in links:
            full_url = urljoin(base_url, href)
            if full_url in seen_urls:
                continue
            seen_urls.add(full_url)

            # Strip HTML tags from anchor text
            clean_title = re.sub(r"<[^>]+>", " ", anchor_text).strip()
            if not clean_title:
                clean_title = href.split("/")[-1].replace(".pdf", "").replace("-", " ").replace("_", " ")

            is_ar, label, cls_score = classify_document(clean_title, full_url)
            if not is_ar:
                continue

            fy, fy_conf, _ = resolve_fy(clean_title)
            if fy and not (start_year <= fy <= end_year):
                continue

            cid = stable_candidate_id(issuer.issuer_id, fy, full_url)
            candidates.append(Candidate(
                candidate_id=cid,
                issuer_id=issuer.issuer_id,
                source_name=source_name,
                source_url=full_url,
                title=clean_title[:250],
                resolved_fy=fy,
                fy_confidence=fy_conf,
                classification=label,
                classification_score=cls_score,
                direct_pdf_url=full_url,
            ))

        return candidates
