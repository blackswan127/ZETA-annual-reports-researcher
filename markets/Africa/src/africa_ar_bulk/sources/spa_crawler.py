from __future__ import annotations

import asyncio
import hashlib
import logging
import os
import re
from pathlib import Path
from typing import Any, Dict, List, Optional, Set
from urllib.parse import urljoin

from ..classify import classify_document
from ..fy import resolve_fy
from ..models import Candidate, Issuer

logger = logging.getLogger(__name__)

# Known Chrome and Edge paths on Windows
CHROME_CANDIDATE_PATHS = [
    r"C:\Program Files\Google\Chrome\Application\chrome.exe",
    r"C:\Program Files (x86)\Google\Chrome\Application\chrome.exe",
    r"C:\Program Files (x86)\Microsoft\Edge\Application\msedge.exe",
    r"C:\Program Files\Microsoft\Edge\Application\msedge.exe",
]


def get_chrome_executable() -> Optional[str]:
    for p in CHROME_CANDIDATE_PATHS:
        if os.path.exists(p):
            return p
    return None


def stable_candidate_id(issuer_id: str, fy: Optional[int], report_type: str, url: str) -> str:
    seed = f"{issuer_id}:{fy or ''}:{report_type}:{url}".encode("utf-8")
    return hashlib.sha256(seed).hexdigest()[:24]


class DynamicSPACrawler:
    """Headless Chromium dynamic DOM & network extractor for JavaScript/React/SPA corporate portals."""

    def __init__(self, timeout: float = 20.0):
        self.timeout = timeout
        self.chrome_path = get_chrome_executable()
        self._playwright = None
        self._browser = None
        self._lock = asyncio.Lock()

    async def _ensure_browser(self):
        if self._browser is None and self.chrome_path:
            try:
                from playwright.async_api import async_playwright
                self._playwright = await async_playwright().start()
                self._browser = await self._playwright.chromium.launch(
                    executable_path=self.chrome_path,
                    headless=True,
                    args=[
                        "--no-sandbox",
                        "--disable-gpu",
                        "--disable-dev-shm-usage",
                        "--disable-extensions",
                    ],
                )
            except Exception as e:
                logger.debug(f"Could not launch Playwright browser: {e}")
                self._browser = None

    async def close(self):
        if self._browser:
            try:
                await self._browser.close()
            except Exception:
                pass
            self._browser = None
        if self._playwright:
            try:
                await self._playwright.stop()
            except Exception:
                pass
            self._playwright = None

    async def extract_dynamic_candidates(
        self,
        issuer: Issuer,
        target_url: str,
        start_year: int,
        end_year: int,
    ) -> List[Candidate]:
        if not self.chrome_path:
            return []

        async with self._lock:
            await self._ensure_browser()
            if not self._browser:
                return []

        candidates: List[Candidate] = []
        seen_urls: Set[str] = set()

        try:
            ctx = await self._browser.new_context(
                user_agent="Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36",
                viewport={"width": 1280, "height": 800},
                java_script_enabled=True,
            )
            page = await ctx.new_page()

            # Intercept any direct PDF responses triggered by dynamic scripts
            page.on(
                "response",
                lambda res: seen_urls.add(res.url) if ".pdf" in res.url.lower() or "application/pdf" in res.headers.get("content-type", "").lower() else None,
            )

            try:
                await page.goto(target_url, timeout=int(self.timeout * 1000), wait_until="domcontentloaded")
                # Wait briefly for React / Angular hydration
                await asyncio.sleep(2.5)

                # Extract all anchor tags, buttons, and data attributes rendered dynamically
                raw_items = await page.evaluate("""() => {
                    const results = [];
                    // 1. All anchor tags
                    document.querySelectorAll('a').forEach(a => {
                        const href = a.href || '';
                        const text = (a.innerText || a.textContent || '').trim();
                        if (href && (href.toLowerCase().includes('.pdf') || href.toLowerCase().includes('/download/') || href.toLowerCase().includes('/report/'))) {
                            results.push({url: href, title: text});
                        }
                    });
                    // 2. Clickable elements with data attributes
                    document.querySelectorAll('[data-href], [data-url], [data-file], [data-src]').forEach(el => {
                        const u = el.getAttribute('data-href') || el.getAttribute('data-url') || el.getAttribute('data-file') || el.getAttribute('data-src');
                        if (u && (u.includes('.pdf') || u.includes('/download/'))) {
                            results.push({url: u, title: (el.innerText || '').trim()});
                        }
                    });
                    return results;
                }""")

                for item in raw_items:
                    href = item.get("url", "")
                    title = item.get("title", "")
                    if not href:
                        continue
                    full_url = urljoin(target_url, href)
                    if full_url in seen_urls:
                        continue
                    seen_urls.add(full_url)

                    clean_title = re.sub(r"<[^>]+>", " ", title).strip()
                    if not clean_title:
                        clean_title = full_url.split("/")[-1].replace(".pdf", "").replace("-", " ").replace("_", " ")

                    is_ar, label, cls_score = classify_document(clean_title, full_url)
                    if not is_ar:
                        continue

                    fy, fy_conf, _ = resolve_fy(clean_title)
                    if not fy:
                        fy, fy_conf, _ = resolve_fy(full_url)

                    if fy and not (start_year <= fy <= end_year):
                        continue

                    cid = stable_candidate_id(issuer.issuer_id, fy, label, full_url)
                    candidates.append(Candidate(
                        candidate_id=cid,
                        issuer_id=issuer.issuer_id,
                        source_name="SPA_DYNAMIC_DOM",
                        source_url=full_url,
                        title=clean_title[:250],
                        resolved_fy=fy,
                        fy_confidence=fy_conf,
                        classification=label,
                        classification_score=cls_score,
                        direct_pdf_url=full_url,
                    ))

            finally:
                await page.close()
                await ctx.close()

        except Exception as e:
            logger.debug(f"Dynamic SPA extraction error for {issuer.ticker} on {target_url}: {e}")

        return candidates
