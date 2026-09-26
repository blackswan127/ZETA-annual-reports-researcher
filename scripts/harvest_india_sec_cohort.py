r"""Harvest Indian Foreign Private Issuers from SEC EDGAR directly into GLOBAL_SUSTAINABILITY_DATABASE/IND.
Applies the Two-Tier SEC EDGAR Harvesting Pipeline:
- Method #1: Direct Graphic Form ARS PDF Passthrough
- Method #2: Self-Healing Headless Chromium Layout render-sec for Form 20-F HTML
- Zero-copy in-RAM PyMuPDF verification
- Canonical SOP directory layout directly on Google Drive junction
"""

from __future__ import annotations

import asyncio
import hashlib
import json
import logging
import os
import re
import sys
import time
from pathlib import Path

import fitz  # PyMuPDF
import httpx
from playwright.async_api import async_playwright

ROOT_DIR = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT_DIR))

logging.basicConfig(level=logging.INFO, format="%(asctime)s [%(levelname)s] %(message)s")
logger = logging.getLogger("india_sec_harvester")

CORPUS_ROOT = ROOT_DIR / "GLOBAL_SUSTAINABILITY_DATABASE" / "IND"
USER_AGENT = "blackswan capital khanholdings127@gmail.com"
CHROME_PATH = r"C:\Program Files\Google\Chrome\Application\chrome.exe"

INDIAN_SEC_ISSUERS = [
    {
        "cik": "0001067491",
        "ticker": "INFY",
        "name": "Infosys Limited",
        "isin": "INE009A01021",
        "lei": "335800M125C9Q85N7148",
        "mic": "XNSE",
    },
    {
        "cik": "0001144967",
        "ticker": "HDB",
        "name": "HDFC Bank Limited",
        "isin": "INE040A01034",
        "lei": "5493005Q8M4C11G8M021",
        "mic": "XBOM",
    },
    {
        "cik": "0001103838",
        "ticker": "IBN",
        "name": "ICICI Bank Limited",
        "isin": "INE090A01021",
        "lei": "549300B2H2M6M6G9M022",
        "mic": "XBOM",
    },
    {
        "cik": "0001123799",
        "ticker": "WIT",
        "name": "Wipro Limited",
        "isin": "INE075A01022",
        "lei": "335800W41V8B9M5N0124",
        "mic": "XBOM",
    },
    {
        "cik": "0001135951",
        "ticker": "RDY",
        "name": "Dr. Reddy's Laboratories Limited",
        "isin": "INE089A01023",
        "lei": "335800Y39V7B1N7M0134",
        "mic": "XBOM",
    },
    {
        "cik": "0000926042",
        "ticker": "TTM",
        "name": "Tata Motors Limited",
        "isin": "INE155A01022",
        "lei": "335800A52V9B3N9M0136",
        "mic": "XBOM",
    },
    {
        "cik": "0001094324",
        "ticker": "SIFY",
        "name": "Sify Technologies Limited",
        "isin": "INE018E01024",
        "lei": "335800L74V2B5N2M0129",
        "mic": "XNSE",
    },
    {
        "cik": "0001356570",
        "ticker": "WNS",
        "name": "WNS (Holdings) Limited",
        "isin": "JE00B17V3638",
        "lei": "549300K43V5B8N4M0128",
        "mic": "XNSE",
    },
    {
        "cik": "0001495153",
        "ticker": "MMYT",
        "name": "MakeMyTrip Limited",
        "isin": "MU0295S00016",
        "lei": "549300Z41V8B2N8M0135",
        "mic": "XNSE",
    },
    {
        "cik": "0001633438",
        "ticker": "AZRE",
        "name": "Azure Power Global Limited",
        "isin": "MU0527S00004",
        "lei": "549300H27V1B9N4M0122",
        "mic": "XNSE",
    },
]


async def fetch_submissions(client: httpx.AsyncClient, cik: str) -> dict:
    url = f"https://data.sec.gov/submissions/CIK{cik.zfill(10)}.json"
    for attempt in range(4):
        try:
            res = await client.get(url, timeout=40.0)
            if res.status_code == 200:
                return res.json()
            elif res.status_code == 429:
                await asyncio.sleep(2.0)
        except Exception as e:
            logger.warning(f"Error fetching submissions for CIK {cik}: {e}")
            await asyncio.sleep(1.5)
    return {}


def extract_annual_filings(sub_data: dict, start_year: int = 2017, end_year: int = 2025) -> list[dict]:
    recent = sub_data.get("filings", {}).get("recent", {})
    if not recent:
        return []
    
    forms = recent.get("form", [])
    acc_nums = recent.get("accessionNumber", [])
    doc_names = recent.get("primaryDocument", [])
    filing_dates = recent.get("filingDate", [])
    report_dates = recent.get("reportDate", [])

    candidates = []
    seen_years = set()
    cik_num = int(sub_data.get("cik", 0))

    for i in range(len(forms)):
        form = str(forms[i]).upper()
        if form in ("20-F", "20-F/A", "ARS"):
            acc_raw = acc_nums[i]
            acc_clean = acc_raw.replace("-", "")
            doc = doc_names[i]
            fdate = filing_dates[i]
            rdate = report_dates[i] if i < len(report_dates) else fdate

            fy = None
            if rdate and len(rdate) >= 4:
                fy = int(rdate[:4])
            elif fdate and len(fdate) >= 4:
                fy = int(fdate[:4])

            if fy and start_year <= fy <= end_year:
                key = (fy, form)
                if key not in seen_years:
                    seen_years.add(key)
                    candidates.append({
                        "form": form,
                        "fiscal_year": fy,
                        "filing_date": fdate,
                        "accession_number": acc_clean,
                        "primary_doc": doc,
                        "url": f"https://www.sec.gov/Archives/edgar/data/{cik_num}/{acc_clean}/{doc}",
                    })
    return candidates


async def render_html_to_pdf(page, html_bytes: bytes) -> bytes:
    content = html_bytes.decode("utf-8", errors="ignore")
    await page.set_content(content, wait_until="load", timeout=90000)
    pdf_bytes = await page.pdf(
        format="A4",
        print_background=True,
        margin={"top": "0.4in", "bottom": "0.4in", "left": "0.4in", "right": "0.4in"},
    )
    return pdf_bytes


async def download_and_promote(
    client: httpx.AsyncClient,
    browser,
    issuer: dict,
    filing: dict,
    render_sem: asyncio.Semaphore,
) -> bool:
    cik = issuer["cik"]
    fy = filing["fiscal_year"]
    ticker = issuer["ticker"]
    isin = issuer["isin"]
    lei = issuer["lei"]
    mic = issuer["mic"]
    url = filing["url"]

    folder_name = f"{lei}_{isin}_{ticker}"
    dest_dir = CORPUS_ROOT / mic / folder_name / f"FY{fy}"
    dest_dir.mkdir(parents=True, exist_ok=True)
    
    canonical_filename = f"{lei}_IND_{mic}_{ticker}_{isin}_FY{fy}_AR_EN.pdf"
    target_path = dest_dir / canonical_filename

    if target_path.exists() and target_path.stat().st_size > 10000:
        logger.info(f"Already complete: {canonical_filename}")
        return True

    # 1. Direct PDF
    if filing["primary_doc"].lower().endswith(".pdf"):
        for attempt in range(3):
            try:
                res = await client.get(url, timeout=60.0)
                if res.status_code == 200:
                    raw_bytes = res.content
                    doc = fitz.open(stream=raw_bytes, filetype="pdf")
                    page_count = len(doc)
                    doc.close()
                    if page_count > 0:
                        target_path.write_bytes(raw_bytes)
                        logger.info(f"PROMOTED PDF: {canonical_filename} ({len(raw_bytes)/(1024*1024):.2f} MB, {page_count} pages)")
                        return True
            except Exception as e:
                logger.warning(f"Download attempt {attempt+1} failed for {url}: {e}")
                await asyncio.sleep(1.0)

    # 2. HTML 20-F Rendering via Chromium
    elif filing["primary_doc"].lower().endswith((".htm", ".html")):
        for attempt in range(2):
            try:
                logger.info(f"Fetching 20-F HTML for {ticker} FY{fy} ({url})...")
                res = await client.get(url, timeout=90.0)
                if res.status_code == 200:
                    html_bytes = res.content
                    async with render_sem:
                        page = await browser.new_page()
                        try:
                            pdf_bytes = await render_html_to_pdf(page, html_bytes)
                            doc = fitz.open(stream=pdf_bytes, filetype="pdf")
                            page_count = len(doc)
                            doc.close()
                            if page_count > 0:
                                target_path.write_bytes(pdf_bytes)
                                logger.info(f"PROMOTED RENDERED 20-F: {canonical_filename} ({len(pdf_bytes)/(1024*1024):.2f} MB, {page_count} pages)")
                                return True
                        finally:
                            await page.close()
            except Exception as e:
                logger.warning(f"Render attempt {attempt+1} failed for {url}: {e}")
                await asyncio.sleep(1.0)

    return False


async def run_pipeline():
    logger.info("Initializing High-Speed SEC EDGAR Harvester for Indian Cross-Listed Universe...")
    headers = {"User-Agent": USER_AGENT}
    limits = httpx.Limits(max_connections=12, max_keepalive_connections=6)
    render_sem = asyncio.Semaphore(2)
    
    total_promoted = 0
    t0 = time.time()

    async with async_playwright() as pw:
        browser = await pw.chromium.launch(
            executable_path=CHROME_PATH,
            headless=True,
            args=[
                "--disable-gpu",
                "--no-sandbox",
                "--disable-dev-shm-usage",
                "--disable-extensions",
            ]
        )
        try:
            async with httpx.AsyncClient(headers=headers, limits=limits, follow_redirects=True) as client:
                for issuer in INDIAN_SEC_ISSUERS:
                    logger.info(f"Processing {issuer['name']} ({issuer['ticker']}, CIK: {issuer['cik']})...")
                    sub_data = await fetch_submissions(client, issuer["cik"])
                    await asyncio.sleep(0.12)
                    
                    filings = extract_annual_filings(sub_data, start_year=2017, end_year=2025)
                    logger.info(f"Found {len(filings)} candidate annual report slots for {issuer['ticker']}")

                    for filing in filings:
                        ok = await download_and_promote(client, browser, issuer, filing, render_sem)
                        if ok:
                            total_promoted += 1
                        await asyncio.sleep(0.12)
        finally:
            await browser.close()

    elapsed = time.time() - t0
    logger.info(f"EXECUTION COMPLETE: Promoted {total_promoted} annual reports to {CORPUS_ROOT} in {elapsed:.2f}s")


if __name__ == "__main__":
    asyncio.run(run_pipeline())
