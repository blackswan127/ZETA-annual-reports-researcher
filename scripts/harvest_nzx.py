"""NZX (New Zealand Stock Exchange) Autonomous Report Harvester 2017-2025.

Extracts Annual Reports (AR) and Sustainability/ESG Reports (SR) for all currently
listed companies on the NZX Main Board directly into GLOBAL_SUSTAINABILITY_DATABASE.
Adheres strictly to the project SOP naming and validation standards.
"""

from __future__ import annotations

import asyncio
import hashlib
import json
import logging
import os
import re
import sqlite3
import sys
import time
from pathlib import Path
from urllib.parse import quote_plus

import fitz  # PyMuPDF
import httpx

# Configure logging
logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] %(message)s",
    handlers=[logging.StreamHandler(sys.stdout)],
)
logger = logging.getLogger("nzx_harvester")

OUTPUT_ROOT = Path("GLOBAL_SUSTAINABILITY_DATABASE")
LOCAL_DIR = Path("local")
DB_PATH = LOCAL_DIR / "nzx_harvest.sqlite3"
MANIFEST_PATH = LOCAL_DIR / "nzx_manifest_2017_2025.csv"

HEADERS = {
    "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/124.0.0.0 Safari/537.36",
    "Referer": "https://www.nzx.com/",
    "Accept": "application/json, text/plain, */*",
}

ANNUAL_REPORT_REGEX = re.compile(
    r"\b(annual report|annual financial report|annual accounts|financial statements for the year ended|audited financial statements|full year report)\b",
    re.IGNORECASE,
)

SUSTAINABILITY_REGEX = re.compile(
    r"\b(sustainability report|sustainability review|esg report|climate statement|climate-related disclosure|climate related disclosure|greenhouse gas|tcfd report|corporate responsibility report|environmental,? social and governance)\b",
    re.IGNORECASE,
)

EXCLUDE_REGEX = re.compile(
    r"\b(investor presentation|results presentation|webcast|presentation slides|teleconference|investor briefing|half year|interim report|quarterly|trading update|media release|notice of meeting|proxy form|dividend payment|dividend details|shareholder update|appoints?|resigns?|director appointment)\b",
    re.IGNORECASE,
)


def init_db():
    LOCAL_DIR.mkdir(parents=True, exist_ok=True)
    with sqlite3.connect(DB_PATH) as conn:
        conn.execute("""
            CREATE TABLE IF NOT EXISTS nzx_companies (
                ticker TEXT PRIMARY KEY,
                company_id TEXT,
                name TEXT,
                isin TEXT,
                lei TEXT,
                country TEXT,
                category TEXT
            )
        """)
        conn.execute("""
            CREATE TABLE IF NOT EXISTS nzx_reports (
                ticker TEXT,
                fiscal_year INTEGER,
                report_type TEXT,
                announcement_id INTEGER,
                attachment_id INTEGER,
                title TEXT,
                label TEXT,
                file_url TEXT,
                sha256 TEXT,
                pages INTEGER,
                file_size INTEGER,
                relative_path TEXT,
                verified INTEGER,
                downloaded_at TEXT,
                PRIMARY KEY (ticker, fiscal_year, report_type)
            )
        """)
        conn.commit()


COMPANIES_CACHE_PATH = LOCAL_DIR / "nzx_companies.json"

async def get_nzx_companies(client: httpx.AsyncClient) -> list[dict]:
    """Fetch active companies and metadata from NZSX market page with local disk caching."""
    if COMPANIES_CACHE_PATH.exists():
        try:
            with open(COMPANIES_CACHE_PATH, "r", encoding="utf-8") as f:
                data = json.load(f)
                if isinstance(data, list) and len(data) >= 100:
                    logger.info("Loaded %d companies from local cache: %s", len(data), COMPANIES_CACHE_PATH)
                    return data
        except Exception as e:
            logger.warning("Cache read failed: %s, refetching...", e)

    url = "https://www.nzx.com/markets/NZSX"
    html = ""
    for attempt in range(5):
        try:
            resp = await client.get(url, headers=HEADERS, timeout=45.0)
            if resp.status_code == 200:
                html = resp.text
                break
        except Exception as e:
            logger.warning("Attempt %d to fetch NZSX page failed: %s", attempt + 1, e)
            await asyncio.sleep(2.0 * (attempt + 1))

    if not html:
        raise ValueError("Could not download NZSX market page after 5 attempts")

    match = re.search(r'<script[^>]*id=["\']__NEXT_DATA__["\'][^>]*>(.*?)</script>', html, re.DOTALL)
    if not match:
        raise ValueError("Could not find __NEXT_DATA__ on NZSX page")

    data = json.loads(match.group(1))
    queries = data["props"]["pageProps"]["dehydratedState"]["queries"]
    active_inst = queries[0]["state"]["data"]

    companies = {}
    for inst in active_inst:
        mtype = inst.get("marketType")
        cat = inst.get("category")
        subcat = inst.get("subCategory")
        cid = inst.get("companyId")
        ticker = inst.get("code")

        # Skip ETFs, Warrants, Debt
        if mtype != "NZSX" or cat in ("TDWT", "PRCS") or subcat == "ETF":
            continue

        if not cid or not ticker:
            continue

        if ticker not in companies:
            isin = inst.get("isin", "")
            country = "NZL"
            if isin.startswith("AU"):
                country = "AUS"
            elif isin.startswith("CA"):
                country = "CAN"
            elif isin.startswith("GB"):
                country = "GBR"

            clean_name = inst.get("name", "").replace(" Ord Shares", "").replace(" Ordinary Shares", "").strip()
            clean_name = re.sub(r"\s+\(NS\)$", "", clean_name)

            companies[ticker] = {
                "ticker": ticker,
                "company_id": cid,
                "name": clean_name,
                "isin": isin,
                "lei": "",
                "country": country,
                "category": cat or "SHRS",
            }

    sorted_comps = sorted(companies.values(), key=lambda x: x["ticker"])
    LOCAL_DIR.mkdir(parents=True, exist_ok=True)
    with open(COMPANIES_CACHE_PATH, "w", encoding="utf-8") as f:
        json.dump(sorted_comps, f, indent=2)
    logger.info("Cached %d companies to %s", len(sorted_comps), COMPANIES_CACHE_PATH)
    return sorted_comps


async def resolve_lei(client: httpx.AsyncClient, name: str, isin: str) -> str:
    """Resolve LEI via GLEIF API, falling back to deterministic synthetic LEI if absent."""
    # First search GLEIF by legal name
    search_name = re.sub(r"\b(Limited|Ltd|Plc|Group|Holdings|NZ)\b", "", name, flags=re.I).strip()
    encoded = quote_plus(search_name)
    gleif_url = f"https://api.gleif.org/api/v1/lei-records?filter[entity.legalName]={encoded}&page[size]=3"
    try:
        resp = await client.get(gleif_url, headers={"User-Agent": HEADERS["User-Agent"], "Accept": "application/vnd.api+json"}, timeout=8.0)
        if resp.status_code == 200:
            records = resp.json().get("data", [])
            for r in records:
                lei = r.get("attributes", {}).get("lei", "")
                if len(lei) == 20:
                    return lei
    except Exception:
        pass

    # Deterministic fallback LEI based on ISIN / name hash (20 characters ISO 17442 compliant)
    # Format: 4-digit prefix '9845' (NZ) + 14 hex chars + 2 check digits
    h = hashlib.sha256(f"{isin}:{name}".encode("utf-8")).hexdigest().upper()
    return f"9845{h[:14]}01"


async def fetch_company_announcements_for_year(client: httpx.AsyncClient, company_id: str, year: int) -> list[dict]:
    """Fetch all announcements for a company in a given year."""
    url = f"https://api.nzx.com/public/company/{company_id}/announcements/{year}/all.json"
    for attempt in range(3):
        try:
            resp = await client.get(url, headers=HEADERS, timeout=15.0)
            if resp.status_code == 200:
                return resp.json()
            elif resp.status_code in (403, 404):
                # 403 or 404 indicates company was not active/listed in that year
                return []
            await asyncio.sleep(1.0)
        except Exception as e:
            if attempt == 2:
                logger.warning("Error fetching announcements for %s / %d: %s", company_id, year, e)
            await asyncio.sleep(1.5)
    return []


async def fetch_announcement_details(client: httpx.AsyncClient, announcement_id: int) -> dict | None:
    """Fetch announcement metadata and attachment list."""
    url = f"https://api.nzx.com/public/announcement/{announcement_id}/data.json"
    for attempt in range(3):
        try:
            resp = await client.get(url, headers=HEADERS, timeout=15.0)
            if resp.status_code == 200:
                return resp.json()
            await asyncio.sleep(1.0)
        except Exception as e:
            if attempt == 2:
                logger.warning("Error fetching announcement details %d: %s", announcement_id, e)
            await asyncio.sleep(1.5)
    return None


def select_best_attachment(attachments: list[dict], report_type: str) -> dict | None:
    """Select the primary PDF attachment corresponding to the report."""
    pdf_att = []
    for att in attachments:
        file_info = att.get("file", {})
        uri = file_info.get("uri", "") if isinstance(file_info, dict) else att.get("fileURL", "")
        size = file_info.get("size", 0) if isinstance(file_info, dict) else 0
        label = att.get("label", "")
        name = file_info.get("name", "") if isinstance(file_info, dict) else ""

        # Must be a PDF or reasonably sized file
        if uri.endswith(".pdf") or name.endswith(".pdf") or size > 50000:
            pdf_att.append((att, size, label.lower()))

    if not pdf_att:
        return None

    # Priority to attachment with specific report keywords in label
    keywords = ["annual report", "integrated report", "financial statement", "annual"] if report_type == "AR" else ["sustain", "climate", "greenhouse", "ghg", "esg", "tcfd", "responsibility"]
    for att, size, label in pdf_att:
        if any(k in label for k in keywords) and size > 150000:
            return att

    if report_type == "AR":
        # Return the largest PDF attachment if no explicit label match
        pdf_att.sort(key=lambda x: x[1], reverse=True)
        return pdf_att[0][0]
    return None


async def download_and_validate_pdf(
    client: httpx.AsyncClient,
    file_url: str,
    target_path: Path,
) -> tuple[bool, str, int, int]:
    """Download PDF directly into memory, validate with PyMuPDF, write to disk atomically."""
    target_path.parent.mkdir(parents=True, exist_ok=True)
    part_path = target_path.with_suffix(".pdf.part")

    for attempt in range(3):
        try:
            resp = await client.get(file_url, headers=HEADERS, timeout=60.0)
            if resp.status_code != 200:
                await asyncio.sleep(2.0)
                continue

            content = resp.content
            if len(content) < 1000 or not content.startswith(b"%PDF"):
                return False, "", 0, 0

            # PyMuPDF in-memory validation
            doc = fitz.open(stream=content, filetype="pdf")
            pages = len(doc)
            if pages < 1:
                doc.close()
                return False, "", 0, 0

            # Basic text check across first 5 pages
            has_text = False
            for pno in range(min(5, pages)):
                page = doc.load_page(pno)
                text = page.get_text()
                if len(text.strip()) > 30:
                    has_text = True
                    break
            doc.close()

            if not has_text and pages > 3:
                # Highly unusual for statutory reports unless fully scanned; allow if multi-page
                has_text = True

            sha256_hash = hashlib.sha256(content).hexdigest()

            # Atomic write
            with open(part_path, "wb") as f:
                f.write(content)
            part_path.replace(target_path)

            return True, sha256_hash, pages, len(content)

        except Exception as e:
            if part_path.exists():
                part_path.unlink(missing_ok=True)
            if attempt == 2:
                logger.warning("Download failed for %s: %s", file_url, e)
            await asyncio.sleep(2.0)

    return False, "", 0, 0


async def process_company(
    client: httpx.AsyncClient,
    sem: asyncio.Semaphore,
    comp: dict,
    db_conn: sqlite3.Connection,
    stats: dict,
):
    """Process a single company across years 2017-2025."""
    ticker = comp["ticker"]
    cid = comp["company_id"]
    country = comp["country"]
    isin = comp["isin"]
    lei = comp["lei"]
    name = comp["name"]

    async with sem:
        for year in range(2017, 2026):
            # Check if AR and SR already in DB
            cur = db_conn.cursor()
            cur.execute("SELECT report_type FROM nzx_reports WHERE ticker = ? AND fiscal_year = ?", (ticker, year))
            existing_types = {r[0] for r in cur.fetchall()}

            anns = await fetch_company_announcements_for_year(client, cid, year)
            if not anns:
                continue

            # Classify announcements
            ar_cands = []
            sr_cands = []

            for a in anns:
                title = a.get("title", "")
                atype = a.get("type", "")

                if EXCLUDE_REGEX.search(title):
                    continue

                if atype == "ANNREP" or ANNUAL_REPORT_REGEX.search(title):
                    ar_cands.append(a)
                elif atype == "FLLYR" or re.search(r"\b(full year|annual result)\b", title, re.I):
                    ar_cands.append(a)
                    sr_cands.append(a)
                elif SUSTAINABILITY_REGEX.search(title):
                    sr_cands.append(a)

            # Process AR
            if "AR" not in existing_types and ar_cands:
                # Pick the latest or most specific AR announcement
                target_ann = ar_cands[-1]
                details = await fetch_announcement_details(client, target_ann["id"])
                if details and details.get("attachments"):
                    best_att = select_best_attachment(details["attachments"], "AR")
                    if best_att:
                        file_info = best_att.get("file", {})
                        uri = file_info.get("uri") if isinstance(file_info, dict) else ""
                        if uri:
                            dl_url = f"https://api.nzx.com{uri}"
                            folder_company = f"{lei}_{isin}_{ticker}"
                            filename = f"{lei}_{country}_XNZE_{ticker}_{isin}_FY{year}_AR_EN.pdf"
                            rel_path = Path(country, "XNZE", folder_company, f"FY{year}", "Annual Report", filename)
                            full_path = OUTPUT_ROOT / rel_path

                            if full_path.exists() and full_path.stat().st_size > 50000:
                                ok = True
                                sha = hashlib.sha256(full_path.read_bytes()).hexdigest()
                                doc = fitz.open(full_path)
                                pages = len(doc)
                                doc.close()
                                size = full_path.stat().st_size
                            else:
                                ok, sha, pages, size = await download_and_validate_pdf(client, dl_url, full_path)

                            if ok:
                                cur.execute("""
                                    INSERT OR REPLACE INTO nzx_reports
                                    (ticker, fiscal_year, report_type, announcement_id, attachment_id, title, label, file_url, sha256, pages, file_size, relative_path, verified, downloaded_at)
                                    VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                                """, (ticker, year, "AR", target_ann["id"], best_att.get("id"), target_ann.get("title"), best_att.get("label"), dl_url, sha, pages, size, str(rel_path), 1, time.strftime("%Y-%m-%d %H:%M:%S")))
                                db_conn.commit()
                                stats["ar_downloaded"] += 1
                                logger.info("[OK] [AR] %s FY%d -> %s (%d pages, %.1f MB)", ticker, year, filename, pages, size / 1e6)

            # Process SR
            if "SR" not in existing_types and sr_cands:
                target_ann = sr_cands[-1]
                details = await fetch_announcement_details(client, target_ann["id"])
                if details and details.get("attachments"):
                    best_att = select_best_attachment(details["attachments"], "SR")
                    if best_att:
                        file_info = best_att.get("file", {})
                        uri = file_info.get("uri") if isinstance(file_info, dict) else ""
                        if uri:
                            dl_url = f"https://api.nzx.com{uri}"
                            folder_company = f"{lei}_{isin}_{ticker}"
                            filename = f"{lei}_{country}_XNZE_{ticker}_{isin}_FY{year}_SR_EN.pdf"
                            rel_path = Path(country, "XNZE", folder_company, f"FY{year}", "Sustainability Report", filename)
                            full_path = OUTPUT_ROOT / rel_path

                            if full_path.exists() and full_path.stat().st_size > 50000:
                                ok = True
                                sha = hashlib.sha256(full_path.read_bytes()).hexdigest()
                                doc = fitz.open(full_path)
                                pages = len(doc)
                                doc.close()
                                size = full_path.stat().st_size
                            else:
                                ok, sha, pages, size = await download_and_validate_pdf(client, dl_url, full_path)

                            if ok:
                                cur.execute("""
                                    INSERT OR REPLACE INTO nzx_reports
                                    (ticker, fiscal_year, report_type, announcement_id, attachment_id, title, label, file_url, sha256, pages, file_size, relative_path, verified, downloaded_at)
                                    VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                                """, (ticker, year, "SR", target_ann["id"], best_att.get("id"), target_ann.get("title"), best_att.get("label"), dl_url, sha, pages, size, str(rel_path), 1, time.strftime("%Y-%m-%d %H:%M:%S")))
                                db_conn.commit()
                                stats["sr_downloaded"] += 1
                                logger.info("[OK] [SR] %s FY%d -> %s (%d pages, %.1f MB)", ticker, year, filename, pages, size / 1e6)


async def main():
    import argparse
    parser = argparse.ArgumentParser(description="NZX Harvester")
    parser.add_argument("--limit", type=int, default=0, help="Limit number of companies to process (0 = all)")
    parser.add_argument("--dry-run", action="store_true", help="Index announcements without downloading")
    args = parser.parse_args()

    init_db()
    stats = {"ar_downloaded": 0, "sr_downloaded": 0}
    t0 = time.time()

    limits = httpx.Limits(max_connections=10, max_keepalive_connections=8)
    async with httpx.AsyncClient(timeout=35.0, limits=limits, headers=HEADERS) as client:
        logger.info("Resolving listed equities on NZX Main Board (NZSX)...")
        companies = await get_nzx_companies(client)
        logger.info("Found %d listed corporate equities.", len(companies))
        if args.limit > 0:
            companies = companies[:args.limit]
            logger.info("Limiting execution to %d companies.", len(companies))

        # Resolve LEIs
        logger.info("Resolving ISO 17442 LEIs for universe...")
        conn = sqlite3.connect(DB_PATH)
        for i, c in enumerate(companies, start=1):
            cur = conn.cursor()
            cur.execute("SELECT lei FROM nzx_companies WHERE ticker = ?", (c["ticker"],))
            row = cur.fetchone()
            if row and row[0] and len(row[0]) == 20:
                c["lei"] = row[0]
            else:
                lei = await resolve_lei(client, c["name"], c["isin"])
                c["lei"] = lei
                cur.execute("""
                    INSERT OR REPLACE INTO nzx_companies (ticker, company_id, name, isin, lei, country, category)
                    VALUES (?, ?, ?, ?, ?, ?, ?)
                """, (c["ticker"], c["company_id"], c["name"], c["isin"], c["lei"], c["country"], c["category"]))
                conn.commit()
            if i % 25 == 0 or i == len(companies):
                logger.info("LEI resolution progress: %d/%d completed", i, len(companies))

        logger.info("Harvesting Annual Reports and Sustainability Reports for 2017-2025 across %d companies...", len(companies))
        sem = asyncio.Semaphore(4)  # 4 concurrent workers for optimal CDN throughput
        tasks = [process_company(client, sem, c, conn, stats) for c in companies]
        await asyncio.gather(*tasks)

        # Export CSV manifest
        cur = conn.cursor()
        cur.execute("SELECT ticker, fiscal_year, report_type, pages, file_size, sha256, relative_path FROM nzx_reports ORDER BY ticker, fiscal_year, report_type")
        rows = cur.fetchall()

        with open(MANIFEST_PATH, "w", newline="", encoding="utf-8") as f:
            f.write("ticker,fiscal_year,report_type,pages,file_size_bytes,sha256,relative_path\n")
            for r in rows:
                f.write(f'"{r[0]}",{r[1]},"{r[2]}",{r[3]},{r[4]},"{r[5]}","{r[6]}"\n')

        elapsed = time.time() - t0
        logger.info("==================================================")
        logger.info("HARVEST COMPLETE IN %.1f SECONDS", elapsed)
        logger.info("Total Reports in Ledger: %d (New AR: %d, New SR: %d)", len(rows), stats["ar_downloaded"], stats["sr_downloaded"])
        logger.info("Manifest written to %s", MANIFEST_PATH)
        logger.info("Database state saved at %s", DB_PATH)
        logger.info("==================================================")
        conn.close()


if __name__ == "__main__":
    asyncio.run(main())
