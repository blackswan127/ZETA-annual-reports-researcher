from __future__ import annotations

import asyncio
import logging
import os
import random
import re
from datetime import datetime
from pathlib import Path
from typing import Iterable, Optional

import httpx

from .classify import annual_report_score, fiscal_year_from_text
from .config import (
    BSE_ANN_API,
    BSE_AR_PAGE,
    BSE_ATTACH_HIS_URL,
    BSE_ATTACH_LIVE_URL,
    BSE_GROUPS,
    BSE_LIST_API,
    USER_AGENT,
    require_terms_acknowledgement,
)
from .models import AnnualReportMetadata, Candidate, Issuer
from .parsers import (
    merge_issuers,
    parse_bse_announcements,
    parse_bse_annual_html,
    parse_bse_list,
    parse_nse_annual_json,
    parse_nse_csv,
)
from .util import AsyncRateLimiter

logger = logging.getLogger(__name__)


class BSEFilingIngestor:
    """Production-grade ingestion client for BSE corporate filings.
    Uses SEBI (LODR) Regulation 34 statutory reporting endpoints and deterministic storage paths.
    """
    BASE_API_URL = BSE_ANN_API
    PDF_BASE_URL = BSE_ATTACH_HIS_URL
    LIVE_PDF_BASE_URL = BSE_ATTACH_LIVE_URL

    def __init__(self, timeout: float = 45.0, retries: int = 5, rps: float = 3.0, proxy: str = ""):
        self.timeout = timeout
        self.retries = retries
        self.rate = AsyncRateLimiter(rps)
        proxy_url = proxy or os.environ.get("INDIA_AR_PROXY") or os.environ.get("HTTPS_PROXY") or os.environ.get("HTTP_PROXY")
        headers = {
            "User-Agent": USER_AGENT,
            "Referer": "https://www.bseindia.com/",
            "Accept": "application/json, text/plain, */*",
            "Accept-Language": "en-US,en;q=0.9",
        }
        self.client = httpx.AsyncClient(
            timeout=httpx.Timeout(timeout, read=max(90.0, timeout)),
            follow_redirects=True,
            headers=headers,
            proxy=proxy_url if proxy_url else None,
            trust_env=True,
            limits=httpx.Limits(max_connections=20, max_keepalive_connections=10),
        )

    async def close(self):
        await self.client.aclose()

    async def fetch_filing_metadata(
        self,
        from_date: str,
        to_date: str,
        scrip_code: str = "",
        page_no: int = 1,
    ) -> tuple[list[AnnualReportMetadata], int]:
        """Queries BSE Corporate Announcements specifically for Annual Reports."""
        params = {
            "pageno": page_no,
            "strCat": "Company Update",
            "strPrevDate": from_date,
            "strToDate": to_date,
            "strScrip": scrip_code,
            "strSearch": "P",
            "strType": "C",
            "subcategory": "Annual Report",
        }

        for attempt in range(self.retries):
            try:
                await self.rate.acquire()
                response = await self.client.get(self.BASE_API_URL, params=params)
                if response.status_code in (429, 500, 502, 503, 504):
                    await asyncio.sleep(min(30.0, 1.7 ** attempt) + random.random() * 0.25)
                    continue
                response.raise_for_status()
                payload = response.json()

                table = payload.get("Table") or [] if isinstance(payload, dict) else []
                table1 = payload.get("Table1") or [] if isinstance(payload, dict) else []
                total = 0
                if table1 and isinstance(table1, list) and isinstance(table1[0], dict):
                    try:
                        total = int(table1[0].get("ROWCNT") or 0)
                    except Exception:
                        total = 0

                records: list[AnnualReportMetadata] = []
                for rec in table:
                    fn = rec.get("ATTACHMENTNAME")
                    if not fn or not (fn.lower().endswith(".pdf") or fn.lower().endswith(".zip")):
                        continue

                    news_id = str(rec.get("NEWSID") or "")
                    scrip = str(rec.get("SCRIP_CD") or scrip_code)
                    company = str(rec.get("SLONGNAME") or "").strip()
                    headline = str(rec.get("HEADLINE") or rec.get("NEWSSUB") or "").strip()
                    dt_raw = str(rec.get("DT_TM") or rec.get("NEWS_DT") or "")
                    xbrl = rec.get("XBR_link") or None
                    pdf_url = f"{self.PDF_BASE_URL}{fn.lstrip('/')}"

                    records.append(AnnualReportMetadata(
                        news_id=news_id,
                        scrip_code=scrip,
                        company_name=company,
                        headline=headline,
                        filing_datetime=dt_raw,
                        attachment_filename=fn,
                        pdf_url=pdf_url,
                        xbrl_url=xbrl if xbrl else None,
                    ))
                return records, total
            except Exception as err:
                logger.warning(f"BSE metadata fetch error (attempt {attempt + 1}/{self.retries}): {err}")
                if attempt + 1 < self.retries:
                    await asyncio.sleep(min(30.0, 1.7 ** attempt) + random.random() * 0.25)

        return [], 0


class BSESource:
    """Primary Indian reporting source centered on the BSE listing centre."""

    def __init__(self, timeout: float = 45.0, retries: int = 5, rps: float = 3.0, proxy: str = ""):
        self.ingestor = BSEFilingIngestor(timeout=timeout, retries=retries, rps=rps, proxy=proxy)
        self.http = self.ingestor.client
        self.rate = self.ingestor.rate
        self.retries = retries

    async def close(self):
        await self.ingestor.close()

    async def universe(self) -> list[Issuer]:
        require_terms_acknowledgement()
        out = []
        for group in BSE_GROUPS:
            params = {"scripcode": "", "Group": group, "industry": "", "segment": "Equity", "status": "Active"}
            try:
                await self.rate.acquire()
                r = await self.http.get(BSE_LIST_API, params=params)
                r.raise_for_status()
                out.extend(parse_bse_list(r.json(), group))
            except Exception:
                continue

        # If live fetch returns empty (e.g. perimeter/offline), use authoritative seed universe
        if not out:
            csv_path = Path(__file__).resolve().parents[2] / "templates" / "current_universe.csv"
            if csv_path.exists():
                import csv
                with open(csv_path, "r", encoding="utf-8") as f:
                    for r in csv.DictReader(f):
                        scrip = r.get("bse_scrip", "").strip()
                        if scrip:
                            out.append(Issuer(
                                issuer_key=r.get("isin") or f"BSE:{scrip}",
                                isin=r.get("isin", ""),
                                name=r.get("name", ""),
                                nse_symbol=r.get("nse_symbol", ""),
                                bse_scrip=scrip,
                                bse_group="A",
                                source_flags="SEED_BSE",
                            ))

        uniq = {}
        for x in out:
            uniq[(x.bse_scrip, x.isin)] = x
        return list(uniq.values())

    async def annual_reports(self, issuer: Issuer, start_year: int, end_year: int) -> list[Candidate]:
        """Production discovery using BSE Corporate Announcements API."""
        if not issuer.bse_scrip:
            return []
        require_terms_acknowledgement()
        from_d = f"{start_year}0101"
        to_d = f"{end_year + 1}1231"
        candidates: list[Candidate] = []
        page = 1

        while page <= 100:
            records, total_rows = await self.ingestor.fetch_filing_metadata(
                from_date=from_d,
                to_date=to_d,
                scrip_code=issuer.bse_scrip,
                page_no=page,
            )
            for rec in records:
                fy = fiscal_year_from_text(rec.headline) or fiscal_year_from_text(rec.attachment_filename)
                if not fy and rec.filing_datetime:
                    m = re.search(r"(\d{4})", rec.filing_datetime)
                    if m:
                        fy = int(m.group(1))
                if not fy:
                    continue

                score = annual_report_score(rec.headline)
                file_kind = "ZIP" if rec.attachment_filename.lower().endswith(".zip") else "PDF"
                note = f"XBRL: {rec.xbrl_url}" if rec.xbrl_url else ""
                candidates.append(Candidate(
                    issuer_key=issuer.issuer_key,
                    fiscal_year=fy,
                    source="BSE_ANN",
                    source_id=rec.news_id or f"{fy}:{rec.attachment_filename}",
                    title=rec.headline or "Annual Report",
                    url=rec.pdf_url,
                    published_at=rec.filing_datetime,
                    from_year=None,
                    to_year=fy,
                    file_kind=file_kind,
                    score=150 + score,
                    note=note,
                    xbrl_url=rec.xbrl_url or "",
                ))

            if not records or (total_rows and page * len(records) >= total_rows):
                break
            page += 1

        return candidates

    async def annual_page(self, issuer: Issuer) -> list[Candidate]:
        """Secondary fallback to legacy BSE HTML page if announcement metadata was empty."""
        if not issuer.bse_scrip:
            return []
        require_terms_acknowledgement()
        try:
            await self.rate.acquire()
            r = await self.http.get(BSE_AR_PAGE, params={"scripcode": issuer.bse_scrip})
            r.raise_for_status()
            return parse_bse_annual_html(issuer.issuer_key, r.text)
        except Exception:
            return []


class NSESource:
    """Legacy NSE source retained for backward compatibility with parser fixtures.
    Reverse-engineered consumer frontend scraping has been eliminated from the critical path.
    """
    def __init__(self, timeout: float = 30.0, retries: int = 1, rps: float = 1.0):
        pass

    async def close(self):
        pass

    async def prime(self, force=False):
        pass

    async def universe(self, include_sme=True) -> list[Issuer]:
        return []

    async def annual_reports(self, issuer: Issuer) -> list[Candidate]:
        return []


async def current_india_universe(
    bse: BSESource,
    nse: Optional[NSESource] = None,
    include_sme: bool = True,
) -> tuple[list[Issuer], dict[str, int]]:
    """Loads deduplicated active Indian corporate universe primarily via BSE."""
    bse_rows = []
    try:
        bse_rows = await bse.universe()
    except Exception as e:
        logger.warning(f"BSE live universe fetch failed: {e}")

    nse_rows = []
    if nse:
        try:
            nse_rows = await nse.universe(include_sme)
        except Exception:
            pass

    merged = merge_issuers(nse_rows, bse_rows) if nse_rows else bse_rows
    dual = sum(1 for x in merged if x.nse_symbol and x.bse_scrip)
    stats = {
        "bse_raw": len(bse_rows),
        "nse_raw": len(nse_rows),
        "deduped": len(merged),
        "dual_listed": dual,
        "nse_only": sum(1 for x in merged if x.nse_symbol and not x.bse_scrip),
        "bse_only": sum(1 for x in merged if x.bse_scrip and not x.nse_symbol),
    }
    return merged, stats
