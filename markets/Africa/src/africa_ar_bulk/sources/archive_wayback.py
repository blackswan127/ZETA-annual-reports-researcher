from __future__ import annotations

import asyncio
import hashlib
import logging
import re
from typing import Any, Dict, List, Optional, Set
from urllib.parse import urlsplit

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


def stable_candidate_id(issuer_id: str, fy: Optional[int], report_type: str, url: str) -> str:
    seed = f"{issuer_id}:{fy or ''}:{report_type}:{url}".encode("utf-8")
    return hashlib.sha256(seed).hexdigest()[:24]


class WaybackArchiveAdapter(BaseSourceAdapter):
    """Historical archive backfill adapter using Internet Archive Wayback Machine CDX API."""

    def __init__(
        self,
        timeout: float = 8.0,
        user_agent: str = "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36",
    ):
        self.timeout = timeout
        self.headers = {"User-Agent": user_agent}
        self.client = httpx.AsyncClient(
            timeout=httpx.Timeout(timeout, connect=5.0),
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

        # Extract domain from source_url
        parts = urlsplit(issuer.source_url)
        domain = parts.netloc.lower()
        if domain.startswith("www."):
            domain = domain[4:]
        if not domain:
            return []

        cdx_url = (
            f"https://web.archive.org/cdx/search/cdx?"
            f"url={domain}/*&output=json&filter=mimetype:application/pdf"
            f"&from={start_year}0101&to={end_year}1231&limit=60&collapse=urlkey"
        )

        candidates: List[Candidate] = []
        seen_urls: Set[str] = set()

        try:
            r = await asyncio.wait_for(self.client.get(cdx_url), timeout=self.timeout)
            if r.status_code != 200:
                return []
            data = r.json()
            if not isinstance(data, list) or len(data) < 2:
                return []

            headers = [h.lower() for h in data[0]]
            url_idx = headers.index("original") if "original" in headers else 2
            ts_idx = headers.index("timestamp") if "timestamp" in headers else 1

            for row in data[1:]:
                orig_url = row[url_idx]
                ts = row[ts_idx]

                clean_name = orig_url.split("/")[-1].replace(".pdf", "").replace("-", " ").replace("_", " ")
                is_ar, label, cls_score = classify_document(clean_name, orig_url)
                if not is_ar:
                    continue

                fy, fy_conf, _ = resolve_fy(clean_name)
                if not fy:
                    fy, fy_conf, _ = resolve_fy(orig_url)

                if fy and not (start_year <= fy <= end_year):
                    continue

                raw_pdf_url = f"https://web.archive.org/web/{ts}id_/{orig_url}"
                if raw_pdf_url in seen_urls:
                    continue
                seen_urls.add(raw_pdf_url)

                cid = stable_candidate_id(issuer.issuer_id, fy, label, raw_pdf_url)
                candidates.append(Candidate(
                    candidate_id=cid,
                    issuer_id=issuer.issuer_id,
                    source_name="WAYBACK_ARCHIVE",
                    source_url=raw_pdf_url,
                    title=clean_name[:250],
                    resolved_fy=fy,
                    fy_confidence=fy_conf,
                    classification=label,
                    classification_score=cls_score,
                    direct_pdf_url=raw_pdf_url,
                ))

        except (asyncio.TimeoutError, Exception) as e:
            logger.debug(f"Wayback CDX backfill skipped for {issuer.ticker}: {e}")

        return candidates
