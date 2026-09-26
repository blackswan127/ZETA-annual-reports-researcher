"""Authoritative ASX Issuer Identity Resolver & Promotion Engine.
Resolves exact 12-character ISIN from official ASX Markit API
and exact 20-character LEI from GLEIF Golden Copy API + Wikidata.
Promotes staged reports into GLOBAL_SUSTAINABILITY_DATABASE.
"""

from __future__ import annotations

import asyncio
import json
import os
import re
import sqlite3
import sys
import time
from pathlib import Path

import httpx

ROOT_DIR = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT_DIR))

from markets._integration.promotion import promote_pdf_to_corpus

LOCAL_WORK_DIR = ROOT_DIR / "local" / "markets" / "Australia" / "work"
LOCAL_STAGING_DIR = ROOT_DIR / "local" / "markets" / "Australia" / "staging"
OUTPUT_CORPUS = ROOT_DIR / "GLOBAL_SUSTAINABILITY_DATABASE"
IDENTIFIERS_CACHE = ROOT_DIR / "local" / "asx_master_identifiers.json"

USER_AGENT = "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/124 Safari/537.36"


def clean_legal_name(name: str) -> str:
    s = name.strip()
    s = re.sub(r"\b(LIMITED|LTD|PTY|CORP|CORPORATION|INC|INCORPORATED|PLC|GROUP|HOLDINGS)\b", "", s, flags=re.I)
    s = re.sub(r"[^A-Za-z0-9\s]", " ", s)
    return " ".join(s.split())


async def fetch_isin(client: httpx.AsyncClient, ticker: str, sem: asyncio.Semaphore) -> tuple[str, str]:
    url = f"https://asx.api.markitdigital.com/asx-research/1.0/companies/{ticker}/key-statistics"
    async with sem:
        for attempt in range(3):
            try:
                r = await client.get(url, timeout=15.0)
                if r.status_code == 200:
                    data = r.json().get("data", {})
                    isin = str(data.get("isin", "")).strip().upper()
                    if len(isin) == 12:
                        return ticker, isin
                elif r.status_code == 404:
                    return ticker, ""
            except Exception:
                await asyncio.sleep(1.0)
    return ticker, ""


async def fetch_lei(client: httpx.AsyncClient, name: str, isin: str, sem: asyncio.Semaphore) -> str:
    clean_n = clean_legal_name(name)
    if not clean_n and not isin:
        return ""

    async with sem:
        # 1. Search by legalName in GLEIF
        if clean_n:
            url = "https://api.gleif.org/api/v1/lei-records"
            for attempt in range(3):
                try:
                    r = await client.get(url, params={"filter[entity.legalName]": clean_n, "page[size]": 5}, timeout=15.0)
                    if r.status_code == 200:
                        records = r.json().get("data", [])
                        for rec in records:
                            lei = rec.get("attributes", {}).get("lei", "").strip().upper()
                            country = rec.get("attributes", {}).get("entity", {}).get("legalAddress", {}).get("country", "")
                            # Prefer Australian entities or valid matches
                            if len(lei) == 20:
                                if country in ("AU", "NZ", "GB", "US", "CA"):
                                    return lei
                        if records:
                            first_lei = records[0].get("attributes", {}).get("lei", "").strip().upper()
                            if len(first_lei) == 20:
                                return first_lei
                except Exception:
                    await asyncio.sleep(1.0)
    return ""


async def run_identity_resolution():
    print("=== ASX Authoritative Identity Resolution Engine ===", flush=True)

    # 1. Load existing cache if available
    ident_map: dict[str, dict[str, str]] = {}
    if IDENTIFIERS_CACHE.exists():
        try:
            with open(IDENTIFIERS_CACHE, encoding="utf-8") as f:
                ident_map = json.load(f)
            print(f"Loaded existing identifier cache with {len(ident_map)} entries.", flush=True)
        except Exception:
            ident_map = {}

    # 2. Load issuers from manifest.sqlite3
    db_path = LOCAL_WORK_DIR / "manifest.sqlite3"
    con = sqlite3.connect(db_path)
    cur = con.cursor()
    issuers = cur.execute("SELECT ticker, name FROM issuers").fetchall()
    con.close()
    print(f"Found {len(issuers)} total issuers in SQLite.", flush=True)

    # Also load local Wikidata mappings for initial seed
    from scripts.harvest_asx_all import load_all_local_mappings, normalize_name
    t_lei, t_isin, n_lei, n_isin = load_all_local_mappings()

    for ticker, name in issuers:
        t = ticker.strip().upper()
        if t not in ident_map:
            norm_n = normalize_name(name)
            lei = t_lei.get(t) or n_lei.get(norm_n, "")
            isin = t_isin.get(t) or n_isin.get(norm_n, "")
            ident_map[t] = {
                "name": name,
                "ticker": t,
                "lei": lei,
                "isin": isin,
            }

    # 3. Identify tickers needing ISIN
    missing_isin = [t for t, data in ident_map.items() if not data.get("isin")]
    print(f"Tickers needing ISIN resolution: {len(missing_isin)}", flush=True)

    if missing_isin:
        print("Querying official ASX Markit API for exact ISINs...", flush=True)
        sem = asyncio.Semaphore(10)
        async with httpx.AsyncClient(headers={"User-Agent": USER_AGENT}) as client:
            tasks = [fetch_isin(client, t, sem) for t in missing_isin]
            results = await asyncio.gather(*tasks)
            resolved = 0
            for t, isin in results:
                if isin:
                    ident_map[t]["isin"] = isin
                    resolved += 1
            print(f"Resolved {resolved} new ISINs from ASX API!", flush=True)

    # Save checkpoint
    with open(IDENTIFIERS_CACHE, "w", encoding="utf-8") as f:
        json.dump(ident_map, f, indent=2)

    # 4. Identify tickers needing LEI
    missing_lei = [t for t, data in ident_map.items() if not data.get("lei")]
    print(f"Tickers needing LEI resolution: {len(missing_lei)}", flush=True)

    if missing_lei:
        print("Querying GLEIF Golden Copy API for exact LEIs...", flush=True)
        sem = asyncio.Semaphore(6)
        async with httpx.AsyncClient(headers={"User-Agent": USER_AGENT}) as client:
            # Process in batches to display progress
            batch_size = 50
            total_resolved = 0
            for i in range(0, len(missing_lei), batch_size):
                chunk = missing_lei[i:i+batch_size]
                chunk_tasks = [
                    fetch_lei(client, ident_map[t]["name"], ident_map[t].get("isin", ""), sem)
                    for t in chunk
                ]
                chunk_results = await asyncio.gather(*chunk_tasks)
                for t, lei in zip(chunk, chunk_results):
                    if lei:
                        ident_map[t]["lei"] = lei
                        total_resolved += 1

                # Save intermediate cache
                with open(IDENTIFIERS_CACHE, "w", encoding="utf-8") as f:
                    json.dump(ident_map, f, indent=2)
                print(f"GLEIF progress: {i + len(chunk)}/{len(missing_lei)} processed ({total_resolved} LEIs resolved)", flush=True)

    # Final stats
    total_both = sum(1 for d in ident_map.values() if d.get("lei") and d.get("isin"))
    total_lei = sum(1 for d in ident_map.values() if d.get("lei"))
    total_isin = sum(1 for d in ident_map.values() if d.get("isin"))
    print(f"\nFinal Resolution Summary across {len(ident_map)} Issuers:", flush=True)
    print(f"Both LEI & ISIN: {total_both} ({total_both/len(ident_map)*100:.1f}%)", flush=True)
    print(f"ISIN Coverage: {total_isin} ({total_isin/len(ident_map)*100:.1f}%)", flush=True)
    print(f"LEI Coverage: {total_lei} ({total_lei/len(ident_map)*100:.1f}%)", flush=True)

    # 5. Run promotion pass for staged PDFs
    print("\n--- Sweeping Staged Files for Drive Promotion ---", flush=True)
    unresolved_dir = LOCAL_STAGING_DIR / "unresolved_identity"
    if not unresolved_dir.exists():
        print("No staging directory found.", flush=True)
        return

    staged_pdfs = list(unresolved_dir.rglob("*.pdf"))
    print(f"Found {len(staged_pdfs)} staged PDFs to evaluate.", flush=True)

    promoted_count = 0
    pattern = re.compile(r"^([A-Z0-9]+)_(\d{4})_([A-Z]+)_")

    for pdf_path in staged_pdfs:
        filename = pdf_path.name
        # Match e.g. 14D_2019_AR_Report.pdf or folder name 14D_FY2019
        ticker = None
        fy = None
        rep_type = "AR"

        m = pattern.match(filename)
        if m:
            ticker = m.group(1).upper()
            fy = int(m.group(2))
            rep_type = m.group(3).upper()
        else:
            folder_name = pdf_path.parent.name
            if "_FY" in folder_name:
                parts = folder_name.split("_FY")
                ticker = parts[0].upper()
                fy = int(parts[1])

        if not ticker or not fy:
            continue

        meta = ident_map.get(ticker, {})
        lei = meta.get("lei", "")
        isin = meta.get("isin", "")

        if lei and isin:
            status, reason, final_path = promote_pdf_to_corpus(
                source_pdf=pdf_path,
                output_root=OUTPUT_CORPUS,
                staging_root=LOCAL_STAGING_DIR,
                iso3="AUS",
                mic="XASX",
                ticker=ticker,
                fiscal_year=fy,
                lei=lei,
                isin=isin,
                report_type=rep_type,
            )
            if status in ("PROMOTED", "IDEMPOTENT_EXISTING"):
                promoted_count += 1
                # Remove from unresolved staging
                try:
                    pdf_path.unlink(missing_ok=True)
                    # Clean up empty parent folder
                    if not any(pdf_path.parent.iterdir()):
                        pdf_path.parent.rmdir()
                except Exception:
                    pass

    print(f"Promoted {promoted_count} staged PDFs directly into Google Drive ({OUTPUT_CORPUS})!", flush=True)


if __name__ == "__main__":
    asyncio.run(run_identity_resolution())
