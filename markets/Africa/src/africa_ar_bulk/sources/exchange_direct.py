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


def stable_candidate_id(issuer_id: str, fy: Optional[int], report_type: str, url: str) -> str:
    seed = f"{issuer_id}:{fy or ''}:{report_type}:{url}".encode("utf-8")
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
            elif mic == "XLUS":  # Zambia LuSE
                candidates = await self._discover_luse_zambia(issuer, start_year, end_year)
            elif mic == "XDAR":  # Tanzania DSE
                candidates = await self._discover_dse_tanzania(issuer, start_year, end_year)
            elif mic == "XZIM":  # Zimbabwe ZSE
                candidates = await self._discover_zse_zimbabwe(issuer, start_year, end_year)
            elif mic == "XMAU":  # Mauritius SEM
                candidates = await self._discover_sem_mauritius(issuer, start_year, end_year)
            elif mic == "XNAM":  # Namibia NSX
                candidates = await self._discover_nsx_namibia(issuer, start_year, end_year)
            elif mic == "XUGA":  # Uganda USE
                candidates = await self._discover_use_uganda(issuer, start_year, end_year)
            elif mic == "XMSW":  # Malawi MSE
                candidates = await self._discover_mse_malawi(issuer, start_year, end_year)
            elif mic == "XRWA":  # Rwanda RSE
                candidates = await self._discover_rse_rwanda(issuer, start_year, end_year)
            elif mic == "XSWA":  # Eswatini ESE
                candidates = await self._discover_ese_eswatini(issuer, start_year, end_year)
            elif mic == "XMSX":  # Seychelles MERJ
                candidates = await self._discover_merj_seychelles(issuer, start_year, end_year)
            elif mic == "XJSE":  # South Africa JSE
                candidates = await self._discover_jse_south_africa(issuer, start_year, end_year)
            elif mic == "XSLS":  # Sierra Leone SLSE
                candidates = await self._discover_slse_sierra_leone(issuer, start_year, end_year)
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

    async def _discover_luse_zambia(self, issuer: Issuer, start_year: int, end_year: int) -> List[Candidate]:
        candidates: List[Candidate] = []
        urls = [
            f"https://luse.co.zm/annual-reports/",
            f"https://luse.co.zm/listed-companies/{issuer.ticker.lower()}/",
        ]
        for url in urls:
            try:
                r = await self.client.get(url)
                if r.status_code == 200:
                    candidates.extend(self._extract_pdf_candidates(r.text, url, issuer, start_year, end_year, "LUSE_ZAMBIA_DIRECT"))
            except Exception:
                pass
        return candidates

    async def _discover_dse_tanzania(self, issuer: Issuer, start_year: int, end_year: int) -> List[Candidate]:
        candidates: List[Candidate] = []
        urls = [
            f"https://dse.co.tz/financial-statements",
            f"https://dse.co.tz/listed-companies/{issuer.ticker.lower()}",
        ]
        for url in urls:
            try:
                r = await self.client.get(url)
                if r.status_code == 200:
                    candidates.extend(self._extract_pdf_candidates(r.text, url, issuer, start_year, end_year, "DSE_TANZANIA_DIRECT"))
            except Exception:
                pass
        return candidates

    async def _discover_zse_zimbabwe(self, issuer: Issuer, start_year: int, end_year: int) -> List[Candidate]:
        candidates: List[Candidate] = []
        urls = [
            f"https://www.zse.co.zw/financial-reports/",
            f"https://www.zse.co.zw/company-profile/{issuer.ticker.lower()}/",
        ]
        for url in urls:
            try:
                r = await self.client.get(url)
                if r.status_code == 200:
                    candidates.extend(self._extract_pdf_candidates(r.text, url, issuer, start_year, end_year, "ZSE_ZIMBABWE_DIRECT"))
            except Exception:
                pass
        return candidates

    async def _discover_sem_mauritius(self, issuer: Issuer, start_year: int, end_year: int) -> List[Candidate]:
        candidates: List[Candidate] = []
        url = f"https://www.stockexchangeofmauritius.com/listed-companies/company-profile?symbol={issuer.ticker}"
        try:
            r = await self.client.get(url)
            if r.status_code == 200:
                candidates.extend(self._extract_pdf_candidates(r.text, url, issuer, start_year, end_year, "SEM_MAURITIUS_DIRECT"))
        except Exception:
            pass
        return candidates

    async def _discover_nsx_namibia(self, issuer: Issuer, start_year: int, end_year: int) -> List[Candidate]:
        candidates: List[Candidate] = []
        urls = [
            f"https://nsx.com.na/announcements/",
            f"https://nsx.com.na/listed-companies/{issuer.ticker.lower()}",
        ]
        for url in urls:
            try:
                r = await self.client.get(url)
                if r.status_code == 200:
                    candidates.extend(self._extract_pdf_candidates(r.text, url, issuer, start_year, end_year, "NSX_NAMIBIA_DIRECT"))
            except Exception:
                pass
        return candidates

    async def _discover_use_uganda(self, issuer: Issuer, start_year: int, end_year: int) -> List[Candidate]:
        candidates: List[Candidate] = []
        urls = [
            f"https://use.or.ug/financial-reports/",
            f"https://use.or.ug/listed-companies/{issuer.ticker.lower()}",
        ]
        for url in urls:
            try:
                r = await self.client.get(url)
                if r.status_code == 200:
                    candidates.extend(self._extract_pdf_candidates(r.text, url, issuer, start_year, end_year, "USE_UGANDA_DIRECT"))
            except Exception:
                pass
        return candidates

    async def _discover_mse_malawi(self, issuer: Issuer, start_year: int, end_year: int) -> List[Candidate]:
        candidates: List[Candidate] = []
        urls = [
            f"https://mse.co.mw/published-accounts/",
            f"https://mse.co.mw/listed-companies/{issuer.ticker.lower()}",
        ]
        for url in urls:
            try:
                r = await self.client.get(url)
                if r.status_code == 200:
                    candidates.extend(self._extract_pdf_candidates(r.text, url, issuer, start_year, end_year, "MSE_MALAWI_DIRECT"))
            except Exception:
                pass
        return candidates

    async def _discover_rse_rwanda(self, issuer: Issuer, start_year: int, end_year: int) -> List[Candidate]:
        candidates: List[Candidate] = []
        urls = [
            f"https://rse.rw/reports/",
            f"https://rse.rw/listed-securities/{issuer.ticker.lower()}",
        ]
        for url in urls:
            try:
                r = await self.client.get(url)
                if r.status_code == 200:
                    candidates.extend(self._extract_pdf_candidates(r.text, url, issuer, start_year, end_year, "RSE_RWANDA_DIRECT"))
            except Exception:
                pass
        return candidates

    async def _discover_ese_eswatini(self, issuer: Issuer, start_year: int, end_year: int) -> List[Candidate]:
        candidates: List[Candidate] = []
        url = f"https://ese.co.sz/financial-results/"
        try:
            r = await self.client.get(url)
            if r.status_code == 200:
                candidates.extend(self._extract_pdf_candidates(r.text, url, issuer, start_year, end_year, "ESE_ESWATINI_DIRECT"))
        except Exception:
            pass
        return candidates

    async def _discover_merj_seychelles(self, issuer: Issuer, start_year: int, end_year: int) -> List[Candidate]:
        candidates: List[Candidate] = []
        url = f"https://merj.net/market-data/disclosures/"
        try:
            r = await self.client.get(url)
            if r.status_code == 200:
                candidates.extend(self._extract_pdf_candidates(r.text, url, issuer, start_year, end_year, "MERJ_SEYCHELLES_DIRECT"))
        except Exception:
            pass
        return candidates

    async def _discover_jse_south_africa(self, issuer: Issuer, start_year: int, end_year: int) -> List[Candidate]:
        candidates: List[Candidate] = []
        url = f"https://www.jse.co.za/current-companies/company-announcements?symbol={issuer.ticker}"
        try:
            r = await self.client.get(url)
            if r.status_code == 200:
                candidates.extend(self._extract_pdf_candidates(r.text, url, issuer, start_year, end_year, "JSE_SENS_DIRECT"))
        except Exception:
            pass
        return candidates

    async def _discover_slse_sierra_leone(self, issuer: Issuer, start_year: int, end_year: int) -> List[Candidate]:
        # Sierra Leone is very small with few equities; direct exchange portal has minimal automated filings
        return []

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
            if not fy:
                fy, fy_conf, _ = resolve_fy(href)

            if fy and not (start_year <= fy <= end_year):
                continue

            cid = stable_candidate_id(issuer.issuer_id, fy, label, full_url)
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
