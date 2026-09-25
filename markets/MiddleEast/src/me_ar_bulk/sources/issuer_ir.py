from __future__ import annotations

import asyncio
import logging
import re
from typing import List, Optional
from urllib.parse import urljoin

import httpx

from ..classify import classify_document, detect_language
from ..fy import resolve_fiscal_year
from ..models import Candidate, Issuer
from .base import BaseSourceAdapter

logger = logging.getLogger(__name__)


class IssuerIRCrawler(BaseSourceAdapter):
    """Fallback crawler that discovers full English Annual Reports from official corporate IR archives
    when centralized exchange disclosures only offer statements-only components.
    """

    def __init__(
        self,
        timeout: float = 25.0,
        user_agent: str = "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36",
    ):
        self.timeout = timeout
        headers = {
            "User-Agent": user_agent,
            "Accept": "text/html,application/xhtml+xml,application/xml;q=0.9,*/*;q=0.8",
            "Accept-Language": "en-US,en;q=0.9",
        }
        self.client = httpx.AsyncClient(timeout=timeout, follow_redirects=True, headers=headers)

    async def close(self):
        await self.client.aclose()

    async def discover_candidates(
        self,
        issuer: Issuer,
        start_year: int,
        end_year: int,
    ) -> List[Candidate]:
        candidates: List[Candidate] = []
        if not issuer.universe_source and not getattr(issuer, "source_url", ""):
            return candidates

        target_url = getattr(issuer, "source_url", "") or issuer.universe_source
        if not target_url.startswith("http"):
            return candidates

        try:
            r = await self.client.get(target_url)
            if r.status_code == 200:
                text = r.text
                matches = re.findall(r'href=[\'"]([^\'"]+?\.pdf)[\'"][^>]*>([^<]*(?:Annual\s+Report|Integrated|Financial)[^<]*)', text, re.I)
                for href, title in matches:
                    full_url = urljoin(target_url, href)
                    doc_class, c_conf = classify_document(title, url=full_url)
                    lang, l_conf = detect_language(title, filename=href)
                    fy, f_conf, _ = resolve_fiscal_year(title=title, url=full_url)
                    if fy and start_year <= fy <= end_year and doc_class == "AR_FULL" and lang == "EN":
                        candidates.append(Candidate(
                            candidate_id=f"IR_{issuer.ticker}_{fy}",
                            issuer_id=issuer.issuer_id,
                            source_name="ISSUER_IR_REPAIR",
                            source_url=full_url,
                            direct_url=full_url,
                            title=f"{issuer.company_name} {title.strip()}",
                            resolved_fy=fy,
                            fy_confidence=f_conf,
                            language=lang,
                            language_confidence=l_conf,
                            document_class=doc_class,
                            class_confidence=c_conf,
                        ))
        except Exception as e:
            logger.debug(f"IR crawler error for {issuer.ticker}: {e}")

        return candidates
