from __future__ import annotations

import asyncio
import hashlib
import logging
import re
from typing import Any, Dict, List, Optional, Set
from urllib.parse import urljoin

import httpx

from ..classify import classify_document
from ..fy import resolve_fy
from ..models import Candidate, Issuer
from .base import BaseSourceAdapter

logger = logging.getLogger(__name__)

# Map ISO3 to country codes / slugs on AfricanFinancials
ISO3_TO_AF_SLUG: Dict[str, str] = {
    "ZAF": "za",
    "NGA": "ng",
    "KEN": "ke",
    "GHA": "gh",
    "BWA": "bw",
    "ZMB": "zm",
    "TZA": "tz",
    "ZWE": "zw",
    "MUS": "mu",
    "NAM": "na",
    "UGA": "ug",
    "MWI": "mw",
    "RWA": "rw",
    "SWZ": "sz",
    "SYC": "sc",
    "SLE": "sl",
}


def stable_candidate_id(issuer_id: str, fy: Optional[int], report_type: str, url: str) -> str:
    seed = f"{issuer_id}:{fy or ''}:{report_type}:{url}".encode("utf-8")
    return hashlib.sha256(seed).hexdigest()[:24]


try:
    from curl_cffi.requests import AsyncSession
    HAS_CURL_CFFI = True
except ImportError:
    HAS_CURL_CFFI = False


class AfricanFinancialsAdapter(BaseSourceAdapter):
    """Universal AfricanFinancials Aggregator Adapter covering 16 African equity markets with Cloudflare bypass."""

    def __init__(
        self,
        timeout: float = 25.0,
        user_agent: str = "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36",
    ):
        self.timeout = timeout
        self.user_agent = user_agent
        self.headers = {
            "User-Agent": user_agent,
            "Accept": "text/html,application/xhtml+xml,application/json,*/*",
            "Accept-Language": "en-US,en;q=0.9",
        }
        self.session: Optional[Any] = None
        if HAS_CURL_CFFI:
            try:
                self.session = AsyncSession(impersonate="chrome120", timeout=timeout, headers=self.headers)
            except Exception as e:
                logger.debug(f"Failed to initialize curl_cffi AsyncSession: {e}")
                self.session = None

        self.client = httpx.AsyncClient(
            timeout=httpx.Timeout(timeout, connect=15.0),
            follow_redirects=True,
            headers=self.headers,
        )

    async def close(self):
        if self.session:
            try:
                await self.session.close()
            except Exception:
                pass
        await self.client.aclose()

    async def _ensure_sitemap(self):
        if hasattr(self, "_slug_map") and self._slug_map is not None:
            return
        self._slug_map = {}
        try:
            xml = await self._get_page("https://africanfinancials.com/company-sitemap.xml")
            if xml:
                locs = [u.rstrip("/") for u in re.findall(r"<loc>(.*?)</loc>", xml) if "/company/" in u and u.rstrip("/") != "https://africanfinancials.com/company"]
                for url in locs:
                    slug = url.split("/company/")[-1]
                    self._slug_map[slug] = url
        except Exception as e:
            logger.debug(f"Failed to fetch AfricanFinancials company sitemap: {e}")

    def get_candidate_urls(self, issuer: Issuer) -> List[str]:
        slug = ISO3_TO_AF_SLUG.get(issuer.country_iso3.upper(), issuer.country_iso3.lower())
        ticker_slug = issuer.ticker.lower().replace(".", "-").replace("_", "-")
        t_clean = issuer.ticker.lower().replace(".", "").replace("-", "").replace("_", "")

        urls = []
        if hasattr(self, "_slug_map") and self._slug_map:
            # 1. Direct slug candidates
            candidates = [
                f"{slug}-{ticker_slug}",
                f"{slug}-{t_clean}",
                f"{slug}-{t_clean[:6]}",
                f"{slug}-{t_clean[:5]}",
                f"{slug}-{t_clean[:4]}",
            ]
            for c in candidates:
                if c in self._slug_map:
                    urls.append(self._slug_map[c])
                    break

            # 2. Company name token matching
            if not urls:
                name_tokens = [w.lower() for w in re.findall(r"\w+", issuer.company_name) if len(w) > 3 and w.lower() not in ("group", "limited", "bank", "holdings", "company", "plc", "africa", "corporation")]
                for s_key, s_url in self._slug_map.items():
                    if s_key.startswith(f"{slug}-"):
                        slug_part = s_key[len(slug)+1:]
                        if any(slug_part.startswith(tok) or tok.startswith(slug_part) for tok in name_tokens):
                            urls.append(s_url)
                            break

        # Standard fallback URLs
        urls.extend([
            f"https://africanfinancials.com/company/{slug}-{ticker_slug}/",
            f"https://africanfinancials.com/company/{slug}-{ticker_slug}/reports/",
            f"https://africanfinancials.com/document-library/{slug}-{ticker_slug}/",
            f"https://africanfinancials.com/company/{ticker_slug}/",
        ])
        # Deduplicate preserving order
        seen = set()
        deduped = []
        for u in urls:
            if u not in seen:
                seen.add(u)
                deduped.append(u)
        return deduped

    async def _get_page(self, url: str) -> Optional[str]:
        if self.session:
            try:
                r = await self.session.get(url)
                if r.status_code == 200:
                    return r.text
            except Exception as e:
                logger.debug(f"curl_cffi get error for {url}: {e}")

        try:
            r = await self.client.get(url)
            if r.status_code == 200:
                return r.text
        except Exception as e:
            logger.debug(f"httpx get error for {url}: {e}")

        return None

    async def discover_candidates(
        self,
        issuer: Issuer,
        start_year: int,
        end_year: int,
    ) -> List[Candidate]:
        await self._ensure_sitemap()
        candidates: List[Candidate] = []
        urls_to_try = self.get_candidate_urls(issuer)
        seen_urls: Set[str] = set()

        for url in urls_to_try:
            try:
                html = await self._get_page(url)
                if not html:
                    continue

                # 1. Direct PDF links in HTML
                extracted = self.extract_candidates_from_html(html, url, issuer, start_year, end_year)
                for c in extracted:
                    if c.source_url not in seen_urls:
                        seen_urls.add(c.source_url)
                        candidates.append(c)

                # 2. Document page links (/document/{slug}-{year}-{type}-00/)
                doc_links = re.findall(r'href=["\'](https://africanfinancials\.com/document/[^"\']+)["\']', html)
                target_docs = []
                for d_url in doc_links:
                    d_url = d_url.rstrip("/") + "/"
                    # Check if document URL matches target years and types
                    m = re.search(r'-(\d{4})-(ar|sr|ir|esg|sus)-00/?', d_url, re.I)
                    if m:
                        d_fy = int(m.group(1))
                        d_code = m.group(2).lower()
                        if start_year <= d_fy <= end_year:
                            label = "SR" if d_code in ("sr", "esg", "sus") else "AR"
                            target_docs.append((d_url, d_fy, label))

                # Concurrently resolve document pages to Google Drive download links
                if target_docs:
                    sem = asyncio.Semaphore(8)

                    async def resolve_doc(item):
                        doc_u, fy, rep_type = item
                        async with sem:
                            try:
                                d_html = await self._get_page(doc_u)
                                if d_html:
                                    m_drive = re.search(r'drive\.google\.com/file/d/([a-zA-Z0-9_-]+)/', d_html)
                                    if m_drive:
                                        fid = m_drive.group(1)
                                        pdf_dl = f"https://drive.google.com/uc?export=download&id={fid}"
                                        cid = stable_candidate_id(issuer.issuer_id, fy, rep_type, pdf_dl)
                                        title = f"{issuer.company_name} FY{fy} {'Annual Report' if rep_type == 'AR' else 'Sustainability Report'}"
                                        return Candidate(
                                            candidate_id=cid,
                                            issuer_id=issuer.issuer_id,
                                            source_name="AFRICAN_FINANCIALS",
                                            source_url=doc_u,
                                            title=title,
                                            resolved_fy=fy,
                                            fy_confidence=1.0,
                                            classification=rep_type,
                                            classification_score=1.0,
                                            direct_pdf_url=pdf_dl,
                                        )
                            except Exception:
                                pass
                        return None

                    resolved = await asyncio.gather(*(resolve_doc(t) for t in target_docs))
                    for c in resolved:
                        if c and c.source_url not in seen_urls:
                            seen_urls.add(c.source_url)
                            candidates.append(c)

                if candidates:
                    break
            except Exception as e:
                logger.debug(f"AfricanFinancials fetch error for {issuer.ticker} on {url}: {e}")

        return candidates

    def extract_candidates_from_html(
        self,
        html: str,
        base_url: str,
        issuer: Issuer,
        start_year: int,
        end_year: int,
    ) -> List[Candidate]:
        candidates: List[Candidate] = []
        # Find <a> tags containing .pdf hrefs
        links = re.findall(r'<a\s+[^>]*href=["\']([^"\']+\.pdf[^"\']*)["\'][^>]*>(.*?)</a>', html, re.I | re.DOTALL)
        seen_pdf = set()

        for href, anchor_text in links:
            full_url = urljoin(base_url, href)
            if full_url in seen_pdf:
                continue
            seen_pdf.add(full_url)

            clean_title = re.sub(r"<[^>]+>", " ", anchor_text).strip()
            if not clean_title:
                clean_title = href.split("/")[-1].replace(".pdf", "").replace("-", " ").replace("_", " ")

            is_valid, label, cls_score = classify_document(clean_title, full_url)
            if not is_valid:
                continue

            fy, fy_conf, _ = resolve_fy(clean_title)
            if not fy:
                # Try URL-based year extraction
                fy, fy_conf, _ = resolve_fy(href)

            if fy and not (start_year <= fy <= end_year):
                continue

            cid = stable_candidate_id(issuer.issuer_id, fy, label, full_url)
            candidates.append(Candidate(
                candidate_id=cid,
                issuer_id=issuer.issuer_id,
                source_name="AFRICAN_FINANCIALS",
                source_url=full_url,
                title=clean_title[:250],
                resolved_fy=fy,
                fy_confidence=fy_conf,
                classification=label,
                classification_score=cls_score,
                direct_pdf_url=full_url,
            ))

        return candidates

