from __future__ import annotations

import asyncio
import hashlib
import io
import logging
import re
import time
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, AsyncGenerator, Dict, List, Optional, Set, Tuple
from urllib.parse import urljoin, urlparse

import httpx

from .contract import CandidateFiling
from .promotion import (
    promote_pdf_bytes_to_corpus,
    validate_pdf_bytes_or_file,
)

logger = logging.getLogger(__name__)

# Regex for annual and sustainability report links in sitemaps and indexes
REPORT_URL_PATTERN = re.compile(
    r"(?i)(?:annual|integrated|sustainability|esg|csr|climate|tcfd|databook).*(?:201[7-9]|202[0-5]).*\.pdf"
)

# Common predictable corporate IR URL patterns for matrix probing
COMMON_MATRIX_TEMPLATES = [
    # Annual Reports (AR)
    "/ir/reports/{year}/annual-report.pdf",
    "/ir/reports/{year}/annual_report.pdf",
    "/investor-relations/reports/{year}/annual-report.pdf",
    "/investors/annual-report-{year}.pdf",
    "/reports/{year}/annual-report.pdf",
    "/assets/investors/reports/FY{year}_AR.pdf",
    "/files/{year}-annual-report.pdf",
    "/media/{year}-annual-report.pdf",
    "/annual-report-{year}.pdf",
    # Sustainability / ESG Reports (SR)
    "/sustainability/{year}/sustainability-report.pdf",
    "/sustainability/{year}/sustainability_report.pdf",
    "/esg/{year}/esg-report.pdf",
    "/esg/{year}/sustainability-report.pdf",
    "/assets/investors/reports/FY{year}_SR.pdf",
    "/sustainability-report-{year}.pdf",
    "/esg-report-{year}.pdf",
    # Integrated Reports (IR)
    "/ir/reports/{year}/integrated-report.pdf",
    "/investors/{year}/integrated-report.pdf",
    "/integrated-report-{year}.pdf",
]


@dataclass
class ProbedReport:
    """Discovered or probed report URL with metadata."""
    url: str
    fiscal_year: int
    report_type: str  # "AR", "SR", "IR"
    source_type: str  # "SITEMAP", "MATRIX_PROBE", "FEED"
    title: str = ""
    content_length: int = 0
    confidence: float = 0.90


class DomainSharder:
    """Manages host concurrency and jitter to prevent WAF / CDN rate limits."""

    def __init__(self, max_concurrent_per_domain: int = 2, default_jitter: float = 0.05):
        self.max_concurrent_per_domain = max_concurrent_per_domain
        self.default_jitter = default_jitter
        self._semaphores: Dict[str, asyncio.Semaphore] = {}
        self._last_request_time: Dict[str, float] = {}

    def _get_domain(self, url: str) -> str:
        netloc = urlparse(url).netloc.lower()
        # Strip port
        return netloc.split(":")[0]

    def get_semaphore(self, url: str) -> asyncio.Semaphore:
        domain = self._get_domain(url)
        if domain not in self._semaphores:
            self._semaphores[domain] = asyncio.Semaphore(self.max_concurrent_per_domain)
        return self._semaphores[domain]

    async def throttle_domain(self, url: str) -> None:
        domain = self._get_domain(url)
        now = time.time()
        last = self._last_request_time.get(domain, 0.0)
        diff = now - last
        if diff < self.default_jitter:
            await asyncio.sleep(self.default_jitter - diff)
        self._last_request_time[domain] = time.time()


class SpeedEngine:
    """High-Throughput Parallel Corporate Report Speed Engine.
    Executes automated XML sitemap probing, async HTTP HEAD/Range matrix probing,
    domain-sharded connections, and RAM-pipelined PyMuPDF verification.
    """

    def __init__(
        self,
        max_workers: int = 32,
        max_concurrent_per_domain: int = 2,
        timeout: float = 15.0,
        user_agent: str = "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36",
    ):
        self.max_workers = max_workers
        self.timeout = timeout
        self.sharder = DomainSharder(max_concurrent_per_domain=max_concurrent_per_domain)
        self.headers = {
            "User-Agent": user_agent,
            "Accept": "text/html,application/xhtml+xml,application/xml;q=0.9,application/pdf,*/*;q=0.8",
            "Accept-Language": "en-US,en;q=0.9",
        }

    async def probe_sitemap(
        self,
        client: httpx.AsyncClient,
        base_url: str,
        fiscal_years: List[int],
    ) -> List[ProbedReport]:
        """Rule 1: Automated Sitemap & Index Probing (<500ms).
        Queries /sitemap.xml and robots.txt -> sitemap_index.xml, extracting matching PDF URLs.
        """
        parsed = urlparse(base_url)
        scheme_host = f"{parsed.scheme}://{parsed.netloc}"
        sitemap_candidates = [
            f"{scheme_host}/sitemap.xml",
            f"{scheme_host}/sitemap_index.xml",
            f"{scheme_host}/sitemaps/sitemap.xml",
            f"{scheme_host}/robots.txt",
        ]

        found_reports: List[ProbedReport] = []
        seen_urls: Set[str] = set()

        for s_url in sitemap_candidates:
            try:
                sem = self.sharder.get_semaphore(s_url)
                async with sem:
                    await self.sharder.throttle_domain(s_url)
                    resp = await client.get(s_url, headers=self.headers, timeout=5.0)

                if resp.status_code != 200:
                    continue

                body = resp.text

                # If robots.txt, check for Sitemap directives
                if "robots.txt" in s_url:
                    extra_sitemaps = re.findall(r"(?i)^sitemap:\s*(https?://[^\s]+)", body, re.M)
                    for sm in extra_sitemaps[:3]:
                        if sm not in sitemap_candidates:
                            sitemap_candidates.append(sm)
                    continue

                # Extract all URLs ending in .pdf
                pdf_urls = re.findall(r"(https?://[^\s<\"'>]+?\.pdf)", body, re.I)
                for u in pdf_urls:
                    if u in seen_urls:
                        continue
                    seen_urls.add(u)

                    # Match with report pattern
                    m = REPORT_URL_PATTERN.search(u)
                    if m:
                        u_lower = u.lower()
                        # Detect year
                        year_match = re.search(r"(?:201[7-9]|202[0-5])", u_lower)
                        if not year_match:
                            continue
                        fy = int(year_match.group(0))
                        if fy not in fiscal_years:
                            continue

                        # Classify report type
                        if "integrated" in u_lower:
                            rtype = "IR"
                        elif any(w in u_lower for w in ["sustain", "esg", "csr", "climate", "tcfd", "databook"]):
                            rtype = "SR"
                        else:
                            rtype = "AR"

                        found_reports.append(
                            ProbedReport(
                                url=u,
                                fiscal_year=fy,
                                report_type=rtype,
                                source_type="SITEMAP",
                                title=Path(urlparse(u).path).stem.replace("-", " ").replace("_", " ").title(),
                            )
                        )
                if found_reports:
                    break  # Found primary sitemap matches
            except Exception as e:
                logger.debug("Sitemap probe error for %s: %s", s_url, e)

        return found_reports

    async def probe_matrix_slot(
        self,
        client: httpx.AsyncClient,
        base_url: str,
        year: int,
        template: str,
    ) -> Optional[ProbedReport]:
        """Rule 2: Async HTTP HEAD Matrix Probing (1-2ms per slot).
        Probes a single template URL with HEAD / Range byte-check.
        """
        parsed = urlparse(base_url)
        scheme_host = f"{parsed.scheme}://{parsed.netloc}"
        url = urljoin(scheme_host, template.format(year=year))

        sem = self.sharder.get_semaphore(url)
        try:
            async with sem:
                await self.sharder.throttle_domain(url)
                # First try fast HEAD
                resp = await client.head(url, headers=self.headers, timeout=4.0)
                if resp.status_code == 200:
                    ctype = resp.headers.get("content-type", "").lower()
                    clen = int(resp.headers.get("content-length", 0))
                    if ("application/pdf" in ctype or "octet-stream" in ctype) and clen > 50_000:
                        u_lower = url.lower()
                        rtype = "IR" if "integrated" in u_lower else ("SR" if any(w in u_lower for w in ["sustain", "esg"]) else "AR")
                        return ProbedReport(
                            url=url,
                            fiscal_year=year,
                            report_type=rtype,
                            source_type="MATRIX_PROBE",
                            title=f"FY{year} {rtype} Probed",
                            content_length=clen,
                            confidence=0.85,
                        )

                # Fallback to byte-range request Range: bytes=0-2048
                range_headers = {**self.headers, "Range": "bytes=0-2048"}
                resp_range = await client.get(url, headers=range_headers, timeout=4.0)
                if resp_range.status_code in (200, 206):
                    ctype = resp_range.headers.get("content-type", "").lower()
                    if ("application/pdf" in ctype or "octet-stream" in ctype or b"%PDF-" in resp_range.content[:10]):
                        clen = int(resp_range.headers.get("content-length", len(resp_range.content)))
                        u_lower = url.lower()
                        rtype = "IR" if "integrated" in u_lower else ("SR" if any(w in u_lower for w in ["sustain", "esg"]) else "AR")
                        return ProbedReport(
                            url=url,
                            fiscal_year=year,
                            report_type=rtype,
                            source_type="MATRIX_PROBE",
                            title=f"FY{year} {rtype} Range-Probed",
                            content_length=clen,
                            confidence=0.85,
                        )
        except Exception:
            pass
        return None

    async def probe_matrix(
        self,
        client: httpx.AsyncClient,
        base_url: str,
        fiscal_years: List[int],
        report_types: List[str],
    ) -> List[ProbedReport]:
        """Fire async matrix probing across predictable templates."""
        templates_to_test = []
        for tmpl in COMMON_MATRIX_TEMPLATES:
            is_sr = any(w in tmpl for w in ["sustain", "esg", "_SR"])
            is_ar = not is_sr
            if "AR" in report_types and is_ar:
                templates_to_test.append(tmpl)
            if "SR" in report_types and is_sr:
                templates_to_test.append(tmpl)

        tasks = []
        for fy in fiscal_years:
            for tmpl in templates_to_test:
                tasks.append(self.probe_matrix_slot(client, base_url, fy, tmpl))

        results = await asyncio.gather(*tasks, return_exceptions=True)
        found: List[ProbedReport] = []
        for r in results:
            if isinstance(r, ProbedReport):
                found.append(r)
        return found

    async def download_and_promote_ram(
        self,
        client: httpx.AsyncClient,
        report: ProbedReport,
        output_root: Path,
        staging_root: Path,
        iso3: str,
        mic: str,
        ticker: str,
        lei: str = "",
        isin: str = "",
    ) -> Tuple[str, str, Path, str, int, int]:
        """Rule 4: Zero-copy RAM pipelining.
        Downloads bytes directly into in-memory buffer, performs PyMuPDF zero-copy parsing,
        computes SHA-256, and writes once directly to target corpus.
        Returns: (status, reason, final_path, sha256, page_count, size_bytes)
        """
        sem = self.sharder.get_semaphore(report.url)
        async with sem:
            await self.sharder.throttle_domain(report.url)
            resp = await client.get(report.url, headers=self.headers, timeout=self.timeout)
            if resp.status_code != 200:
                return "FAILED", f"HTTP {resp.status_code} on download", Path(""), "", 0, 0
            pdf_bytes = resp.content

        return promote_pdf_bytes_to_corpus(
            pdf_bytes=pdf_bytes,
            output_root=output_root,
            staging_root=staging_root,
            iso3=iso3,
            mic=mic,
            ticker=ticker,
            fiscal_year=report.fiscal_year,
            lei=lei,
            isin=isin,
            lang="EN",
            report_type=report.report_type,
        )
