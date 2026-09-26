"""Discover and catalog HKEX Annual Reports and ESG/Sustainability Reports (2017-2025).
Directly queries HKEXnews JSON disclosure endpoint across all months.
Generates an auditable SQLite database and canonical manifest CSV.
"""

from __future__ import annotations

import argparse
import asyncio
import csv
import json
import logging
import re
import sqlite3
import sys
import time
from calendar import monthrange
from datetime import datetime
from pathlib import Path
from typing import Dict, List, Optional, Tuple

import httpx

from annual_reports.catalog import FIELDS, Report
from annual_reports.discovery import Company, parse_years


HKEX_BASE_URL = "https://www1.hkexnews.hk"
HKEX_API_URL = f"{HKEX_BASE_URL}/search/titleSearchServlet.do"
HKEX_REFERER = f"{HKEX_BASE_URL}/search/titlesearch.xhtml"

YEAR_REGEX = re.compile(r"\b(20(?:1[7-9]|2[0-5]))\b")
MULTI_YEAR_REGEX = re.compile(r"\b20(?:1[7-9]|2[0-5])\s*[-/]\s*(20(?:1[7-9]|2[0-5]))\b")

logging.basicConfig(level=logging.INFO, format="%(asctime)s [%(levelname)s] %(message)s")
logger = logging.getLogger("hkex_discovery")


def extract_fiscal_year(title: str, release_date_str: str) -> Optional[str]:
    """Derive fiscal year (FY2017-FY2025) from filing title and release date."""
    clean_title = title.replace("\xa0", " ").strip()
    
    # Check multi-year e.g. "2023-2024" or "2023/2024" -> FY2024
    m_multi = MULTI_YEAR_REGEX.search(clean_title)
    if m_multi:
        return f"FY{m_multi.group(1)}"

    # Check single 4-digit year in title
    years = YEAR_REGEX.findall(clean_title)
    if years:
        return f"FY{years[-1]}"

    # Fallback to release date if available
    try:
        # Format usually: DD/MM/YYYY HH:MM
        date_part = release_date_str.split()[0]
        day, month, year = map(int, date_part.split("/"))
        if 2017 <= year <= 2026:
            # If released Jan-June of year Y, usually FY(Y-1)
            # If released July-Dec of year Y, usually FY(Y)
            if month <= 6:
                fy = year - 1
            else:
                fy = year
            if 2017 <= fy <= 2025:
                return f"FY{fy}"
    except Exception:
        pass

    return None


def init_db(db_path: Path) -> sqlite3.Connection:
    conn = sqlite3.connect(db_path)
    cur = conn.cursor()
    cur.execute("""
        CREATE TABLE IF NOT EXISTS hkex_filings (
            news_id TEXT PRIMARY KEY,
            ticker TEXT,
            company_name TEXT,
            lei TEXT,
            isin TEXT,
            fiscal_year TEXT,
            report_type TEXT,
            release_datetime TEXT,
            title TEXT,
            file_info TEXT,
            pdf_url TEXT,
            verified INTEGER DEFAULT 0,
            sha256 TEXT,
            pages INTEGER,
            file_size INTEGER,
            local_path TEXT,
            downloaded_at TEXT
        )
    """)
    cur.execute("CREATE INDEX IF NOT EXISTS idx_hkex_ticker_fy ON hkex_filings (ticker, fiscal_year, report_type)")
    conn.commit()
    return conn


async def fetch_month_category(
    client: httpx.AsyncClient,
    year: int,
    month: int,
    t2code: str,
    report_type: str,
    companies: Dict[str, dict],
    conn: sqlite3.Connection,
    sem: asyncio.Semaphore,
) -> int:
    """Fetch all filings for a single month and category."""
    from_date = f"{year}{month:02d}01"
    _, last_day = monthrange(year, month)
    to_date = f"{year}{month:02d}{last_day:02d}"

    params = {
        "sortDir": "0",
        "sortByOptions": "DateTime",
        "category": "0",
        "market": "SEHK",
        "stockId": "-1",
        "documentType": "-1",
        "fromDate": from_date,
        "toDate": to_date,
        "title": "",
        "searchType": "0",
        "t1code": "40000",
        "t2Gcode": "-1",
        "t2code": t2code,
        "rowRange": "5000",
        "lang": "E",
    }

    async with sem:
        for attempt in range(3):
            try:
                resp = await client.get(HKEX_API_URL, params=params)
                if resp.status_code == 200:
                    data = resp.json()
                    raw_result = data.get("result", "[]")
                    if not raw_result or raw_result == "null":
                        return 0
                    records = json.loads(raw_result)
                    
                    saved_count = 0
                    cur = conn.cursor()
                    for rec in records:
                        raw_code = str(rec.get("STOCK_CODE") or "").split("<br/>")[0].strip()
                        if not raw_code:
                            continue
                        ticker = raw_code.zfill(5)
                        comp = companies.get(ticker)
                        if not comp:
                            # Not an active equity/reit security on HKEX
                            continue

                        news_id = str(rec.get("NEWS_ID") or "").strip()
                        file_link = str(rec.get("FILE_LINK") or "").strip()
                        if not file_link or not file_link.lower().endswith(".pdf"):
                            continue
                        pdf_url = f"{HKEX_BASE_URL}{file_link}"

                        title = str(rec.get("TITLE") or "").replace("&#x3b;", ";").replace("&amp;", "&").strip()
                        date_time = str(rec.get("DATE_TIME") or "").strip()
                        file_info = str(rec.get("FILE_INFO") or "").strip()

                        fiscal_year = extract_fiscal_year(title, date_time)
                        if not fiscal_year:
                            continue

                        cur.execute("""
                            INSERT OR REPLACE INTO hkex_filings (
                                news_id, ticker, company_name, lei, isin,
                                fiscal_year, report_type, release_datetime,
                                title, file_info, pdf_url
                            ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                        """, (
                            news_id, ticker, comp["company_name"], comp["lei"], comp["isin"],
                            fiscal_year, report_type, date_time, title, file_info, pdf_url
                        ))
                        saved_count += 1

                    conn.commit()
                    return saved_count
                await asyncio.sleep(1.0)
            except Exception as exc:
                if attempt == 2:
                    logger.warning(f"Error fetching {year}-{month:02d} ({report_type}): {exc}")
                await asyncio.sleep(1.5)

    return 0


async def run_discovery(
    universe_path: Path,
    db_path: Path,
    years_range: str = "2017:2025",
    manifest_out: Path = Path("local/hkex_manifest_2017_2025.csv"),
) -> None:
    years = parse_years(years_range)
    print(f"Starting HKEX discovery for years {years[0]} to {years[-1]}...")

    # Load universe
    companies: Dict[str, dict] = {}
    with universe_path.open("r", encoding="utf-8-sig") as f:
        reader = csv.DictReader(f)
        for row in reader:
            t = row["ticker"].zfill(5)
            companies[t] = row

    print(f"Loaded {len(companies)} companies from {universe_path}.")

    conn = init_db(db_path)

    # Categories to harvest
    # 40100 = Annual Report (AR)
    # 40400 = Environmental, Social and Governance Information/Report (SR)
    categories = [
        ("40100", "AR"),
        ("40400", "SR"),
    ]

    tasks = []
    sem = asyncio.Semaphore(5)  # Safe rate limit: 5 concurrent workers
    headers = {
        "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/122.0.0.0 Safari/537.36",
        "Accept": "application/json, text/javascript, */*; q=0.01",
        "Referer": HKEX_REFERER,
        "X-Requested-With": "XMLHttpRequest",
    }

    async with httpx.AsyncClient(headers=headers, timeout=45.0) as client:
        start_t = time.perf_counter()
        month_tasks = []
        for y in range(years[0], years[-1] + 2):  # Include filings up to year+1 for reporting lag
            for m in range(1, 13):
                for t2code, rtype in categories:
                    month_tasks.append(
                        fetch_month_category(client, y, m, t2code, rtype, companies, conn, sem)
                    )

        print(f"Dispatched {len(month_tasks)} monthly queries across {years[0]}-{years[-1]+1}...")
        results = await asyncio.gather(*month_tasks)
        elapsed = time.perf_counter() - start_t
        total_found = sum(results)
        print(f"Discovery completed in {elapsed:.1f}s. Total filings ingested into SQLite: {total_found}")

    # Build canonical deduplicated manifest
    cur = conn.cursor()
    cur.execute("""
        SELECT ticker, company_name, lei, isin, fiscal_year, report_type, pdf_url, release_datetime
        FROM hkex_filings
        WHERE fiscal_year BETWEEN 'FY2017' AND 'FY2025'
        ORDER BY ticker, fiscal_year, report_type, release_datetime DESC
    """)
    rows = cur.fetchall()

    deduped: Dict[Tuple[str, str, str], dict] = {}
    for r in rows:
        ticker, name, lei, isin, fy, rtype, url, rdate = r
        key = (ticker, fy, rtype)
        if key not in deduped:
            deduped[key] = {
                "country": "HKG",
                "exchange": "XHKG",
                "lei": lei,
                "isin": isin,
                "ticker": ticker,
                "fiscal_year": fy,
                "report_type": rtype,
                "language": "EN",
                "pdf_url": url,
                "source_page": HKEX_REFERER,
                "verified": "false",
            }

    print(f"Deduplicated to {len(deduped)} distinct company-year reports.")

    # Write manifest CSV
    manifest_out.parent.mkdir(parents=True, exist_ok=True)
    with manifest_out.open("w", encoding="utf-8-sig", newline="") as f:
        writer = csv.DictWriter(f, fieldnames=FIELDS)
        writer.writeheader()
        for item in deduped.values():
            writer.writerow(item)

    print(f"Exported canonical manifest: {manifest_out}")

    # Print summary statistics
    cur.execute("""
        SELECT fiscal_year, report_type, COUNT(DISTINCT ticker)
        FROM hkex_filings
        WHERE fiscal_year BETWEEN 'FY2017' AND 'FY2025'
        GROUP BY fiscal_year, report_type
        ORDER BY fiscal_year DESC, report_type
    """)
    stats = cur.fetchall()
    print("\n--- HKEX Reporting Coverage Breakdown (2017-2025) ---")
    print(f"{'Fiscal Year':<12} | {'Type':<6} | {'Unique Issuers':<15}")
    print("-" * 38)
    for fy, rtype, count in stats:
        print(f"{fy:<12} | {rtype:<6} | {count:<15}")

    conn.close()


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description="HKEX Filings Discovery")
    parser.add_argument("--universe", type=Path, default=Path("local/universe_hkex_all.csv"))
    parser.add_argument("--state", type=Path, default=Path("local/harvest.sqlite3"))
    parser.add_argument("--years", type=str, default="2017:2025")
    parser.add_argument("--out", type=Path, default=Path("local/hkex_manifest_2017_2025.csv"))
    args = parser.parse_args()

    asyncio.run(run_discovery(args.universe, args.state, args.years, args.out))
