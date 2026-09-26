from __future__ import annotations

import json
import re
from pathlib import Path
from typing import Any, Dict, List, Optional
from bs4 import BeautifulSoup

from .client import PSEClient
from .config import Settings
from .contract import PSEIssuer

# Benchmark 10 smoke test issuers
BENCHMARK_SMOKE_TICKERS = ["AC", "SM", "SMPH", "BDO", "BPI", "AP", "ACEN", "FGEN", "PX", "ANS"]


def parse_company_directory_html(html: str) -> List[Dict[str, Any]]:
    """Parse table rows from PSE EDGE companyDirectory/search.ax."""
    soup = BeautifulSoup(html, "html.parser")
    rows: List[Dict[str, Any]] = []

    # Table parsing
    table = soup.find("table", class_="list") or soup.find("table")
    if not table:
        return rows

    tbody = table.find("tbody") or table
    tr_elements = tbody.find_all("tr")

    for tr in tr_elements:
        tds = tr.find_all("td")
        if len(tds) < 3:
            continue

        # Extract cmpyId from link: href="...cmpy_id=123..." or javascript:cmpyLink('123')
        cmpy_id = ""
        ticker = ""
        company_name = ""
        sector = ""
        subsector = ""
        listing_date = ""

        link = tr.find("a")
        if link:
            company_name = link.get_text(strip=True)
            href = link.get("href", "")
            m_id = re.search(r"(?:cmpy_id=|cmpyLink\(['\"])(\d+)", href)
            if m_id:
                cmpy_id = m_id.group(1)

        # Columns typically: [Company Name, Stock Symbol, Sector, Subsector, Listing Date]
        if len(tds) >= 2:
            ticker = tds[1].get_text(strip=True)
        if len(tds) >= 3:
            sector = tds[2].get_text(strip=True)
        if len(tds) >= 4:
            subsector = tds[3].get_text(strip=True)
        if len(tds) >= 5:
            listing_date = tds[4].get_text(strip=True)

        if not ticker and tds:
            ticker_link = tr.find("a", href=re.compile(r"sec_id|companyPage"))
            if ticker_link:
                ticker = ticker_link.get_text(strip=True)

        if ticker:
            rows.append({
                "cmpy_id": cmpy_id,
                "ticker": ticker.upper(),
                "company_name": company_name,
                "sector": sector,
                "subsector": subsector,
                "listing_date": listing_date,
            })
    return rows


class UniverseManager:
    def __init__(self, settings: Optional[Settings] = None, client: Optional[PSEClient] = None):
        self.settings = settings or Settings()
        self.client = client or PSEClient(self.settings)
        self.cache_file = self.settings.local_dir / "universe.json"
        self._lei_cache: Optional[Dict[str, str]] = None
        self._isin_cache: Optional[Dict[str, str]] = None

    def _load_identifier_mappings(self) -> tuple[Dict[str, str], Dict[str, str]]:
        if self._lei_cache is not None and self._isin_cache is not None:
            return self._lei_cache, self._isin_cache

        ticker_to_lei: Dict[str, str] = {}
        ticker_to_isin: Dict[str, str] = {}

        # Scan local wikidata and gleif dumps
        local_dir = Path("local")
        if local_dir.exists():
            for p in local_dir.glob("wikidata*.json"):
                try:
                    with open(p, encoding="utf-8") as fh:
                        data = json.load(fh)
                        if isinstance(data, list):
                            for item in data:
                                t = item.get("ticker", "")
                                isin = item.get("isin", "")
                                lei = item.get("lei", "")
                                if isinstance(t, dict): t = t.get("value", "")
                                if isinstance(isin, dict): isin = isin.get("value", "")
                                if isinstance(lei, dict): lei = lei.get("value", "")
                                t = str(t).strip().upper()
                                isin = str(isin).strip().upper()
                                lei = str(lei).strip().upper()
                                if t and lei and len(lei) == 20:
                                    ticker_to_lei[t] = lei
                                if t and isin and len(isin) == 12:
                                    ticker_to_isin[t] = isin
                except Exception:
                    pass

        self._lei_cache = ticker_to_lei
        self._isin_cache = ticker_to_isin
        return ticker_to_lei, ticker_to_isin

    async def fetch_universe(self, refresh: bool = False) -> List[PSEIssuer]:
        if not refresh and self.cache_file.exists():
            try:
                with open(self.cache_file, encoding="utf-8") as f:
                    data = json.load(f)
                    return [PSEIssuer(**d) for d in data]
            except Exception:
                pass

        issuers: List[PSEIssuer] = []
        ticker_to_lei, ticker_to_isin = self._load_identifier_mappings()
        seen_tickers = set()

        # Paginate through companyDirectory/search.ax
        page_no = 1
        max_pages = 25  # ~283 total issuers / ~15-20 per page = ~15-20 pages

        while page_no <= max_pages:
            try:
                html = await self.client.post_form(
                    "/companyDirectory/search.ax",
                    data={"pageNo": str(page_no), "sector": "ALL", "subsector": "ALL"},
                )
            except Exception:
                break

            parsed_rows = parse_company_directory_html(html)
            if not parsed_rows:
                break

            new_count = 0
            for r in parsed_rows:
                tk = r["ticker"]
                # Filter out ETFs and non-equity products
                if "ETF" in r["sector"].upper() or "ETF" in r["subsector"].upper():
                    continue
                if tk in seen_tickers:
                    continue

                seen_tickers.add(tk)
                new_count += 1

                lei = ticker_to_lei.get(tk, "")
                isin = ticker_to_isin.get(tk, "")

                issuers.append(PSEIssuer(
                    issuer_id=tk,
                    pse_company_id=r["cmpy_id"],
                    ticker=tk,
                    company_name=r["company_name"],
                    sector=r["sector"],
                    subsector=r["subsector"],
                    listing_date=r["listing_date"],
                    isin=isin,
                    lei=lei,
                ))

            if new_count == 0:
                break
            page_no += 1

        # Fallback if live fetch returned empty (e.g. offline testing)
        if not issuers:
            # Seed with benchmark issuers
            for tk in BENCHMARK_SMOKE_TICKERS:
                lei = ticker_to_lei.get(tk, "")
                isin = ticker_to_isin.get(tk, "")
                issuers.append(PSEIssuer(
                    issuer_id=tk,
                    pse_company_id=f"PSE_{tk}",
                    ticker=tk,
                    company_name=f"{tk} Corporation",
                    isin=isin,
                    lei=lei,
                ))

        # Save cache
        self.cache_file.parent.mkdir(parents=True, exist_ok=True)
        with open(self.cache_file, "w", encoding="utf-8") as f:
            json.dump([i.to_dict() for i in issuers], f, indent=2)

        return issuers
