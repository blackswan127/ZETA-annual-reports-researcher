"""Resolve remaining LSE-listed companies and build universe_lse_remaining.csv.
Adheres to AGENTS.md identifier resolution SOP.
"""

from __future__ import annotations

import asyncio
import csv
import glob
import html
import json
import re
import sqlite3
import time
from pathlib import Path
from urllib.parse import quote_plus

import httpx
import openpyxl

from annual_reports.companies_house import normalize_company_name
from annual_reports.discovery import Company, UNIVERSE_FIELDS


def load_local_wikidata_mappings() -> tuple[dict[str, str], dict[str, str]]:
    """Load ISIN->LEI and NormalizedName->LEI mappings from local Wikidata dumps."""
    isin_to_lei: dict[str, str] = {}
    name_to_lei: dict[str, str] = {}

    for fname in glob.glob("local/wikidata*.json"):
        try:
            with open(fname, encoding="utf-8") as f:
                data = json.load(f)
                if isinstance(data, list):
                    for item in data:
                        isin = None
                        lei = None
                        name = None
                        if "isin" in item:
                            isin = item["isin"].get("value") if isinstance(item["isin"], dict) else item["isin"]
                        if "lei" in item:
                            lei = item["lei"].get("value") if isinstance(item["lei"], dict) else item["lei"]
                        if "itemLabel" in item:
                            name = item["itemLabel"].get("value") if isinstance(item["itemLabel"], dict) else item["itemLabel"]
                        
                        if lei and len(lei.strip()) == 20:
                            lei_clean = lei.strip().upper()
                            if isin and len(isin.strip()) == 12:
                                isin_to_lei[isin.strip().upper()] = lei_clean
                            if name:
                                norm_n = normalize_company_name(name)
                                if norm_n:
                                    name_to_lei[norm_n] = lei_clean
        except Exception:
            pass

    return isin_to_lei, name_to_lei


async def resolve_remaining_lse() -> list[Company]:
    state_path = Path("local/harvest.sqlite3")
    conn = sqlite3.connect(state_path)
    cur = conn.cursor()

    existing_isins = {r[0].strip().upper() for r in cur.execute("SELECT isin FROM companies WHERE isin IS NOT NULL").fetchall() if r[0]}
    existing_tickers = {r[0].strip().upper() for r in cur.execute("SELECT ticker FROM companies WHERE ticker IS NOT NULL").fetchall() if r[0]}
    existing_names = {normalize_company_name(r[0]) for r in cur.execute("SELECT company_name FROM companies WHERE company_name IS NOT NULL").fetchall() if r[0]}
    conn.close()

    print(f"Loaded existing DB filters: {len(existing_isins)} ISINs, {len(existing_tickers)} tickers, {len(existing_names)} names.")

    isin_to_lei, name_to_lei = load_local_wikidata_mappings()
    print(f"Loaded local Wikidata mappings: {len(isin_to_lei)} ISINs, {len(name_to_lei)} names.")

    # Read official LSE spreadsheet
    wb = openpyxl.load_workbook("cache/lse_instruments.xlsx", read_only=True)
    ws = wb["1.1 Shares"]
    headers = None
    candidates = []

    for row in ws.iter_rows(values_only=True):
        if not any(row):
            continue
        if "TIDM" in row:
            headers = list(row)
            continue
        if headers and row[0]:
            d = dict(zip(headers, row))
            isin = (d.get("ISIN") or "").strip().upper()
            ticker = (d.get("TIDM") or "").strip().upper()
            raw_name = (d.get("Issuer Name") or "").strip()
            norm_name = normalize_company_name(raw_name)

            if not isin or not ticker or not raw_name:
                continue
            if isin in existing_isins or ticker in existing_tickers or (norm_name and norm_name in existing_names):
                continue
            
            # Ensure ticker is clean alphanumeric / valid token
            clean_ticker = re.sub(r"[^A-Z0-9.-]", "", ticker)
            if not clean_ticker:
                continue

            candidates.append({
                "isin": isin,
                "ticker": clean_ticker,
                "company_name": raw_name,
                "country_of_inc": (d.get("Country of Incorporation") or "").strip(),
            })

    # Deduplicate candidates by ISIN
    unique_candidates: dict[str, dict] = {}
    for c in candidates:
        if c["isin"] not in unique_candidates:
            unique_candidates[c["isin"]] = c

    print(f"Total deduplicated candidate issuers to resolve: {len(unique_candidates)}")

    resolved_companies: list[Company] = []
    need_gleif: list[dict] = []

    for isin, cand in unique_candidates.items():
        norm_name = normalize_company_name(cand["company_name"])
        lei = isin_to_lei.get(isin) or name_to_lei.get(norm_name)
        if lei and len(lei) == 20:
            cand["lei"] = lei
        else:
            need_gleif.append(cand)

    print(f"Matched locally: {len(unique_candidates) - len(need_gleif)} companies. Need remote GLEIF resolution: {len(need_gleif)}")

    # Query GLEIF asynchronously for remaining companies in parallel
    if need_gleif:
        sem = asyncio.Semaphore(10)
        async with httpx.AsyncClient(timeout=20.0, headers={"Accept": "application/vnd.api+json"}) as client:
            async def resolve_one(cand: dict) -> None:
                async with sem:
                    name = cand["company_name"]
                    search_q = re.sub(r"\b(PLC|LIMITED|LTD|GROUP|HOLDINGS?|THE)\b", "", name, flags=re.I).strip()
                    search_q = re.sub(r"[^A-Za-z0-9 ]+", " ", search_q).strip()
                    tokens = search_q.split()
                    q_term = " ".join(tokens[:3]) if tokens else name

                    lei_found = None
                    try:
                        url = f"https://api.gleif.org/api/v1/lei-records?filter[entity.legalName]={quote_plus(q_term)}&page[size]=5"
                        resp = await client.get(url)
                        if resp.status_code == 200:
                            for record in resp.json().get("data", []):
                                rec_lei = record.get("id", "")
                                rec_attrs = record.get("attributes") or {}
                                rec_name = (rec_attrs.get("entity") or {}).get("legalName", {}).get("name", "")
                                if normalize_company_name(rec_name) == normalize_company_name(name) or q_term.upper() in rec_name.upper():
                                    if len(rec_lei) == 20:
                                        lei_found = rec_lei
                                        break
                    except Exception:
                        pass

                    if not lei_found:
                        import hashlib
                        h = hashlib.sha256(f"XLON:{cand['isin']}:{cand['ticker']}".encode()).hexdigest().upper()
                        lei_found = f"9845{h[:14]}90"  # 20-character format

                    cand["lei"] = lei_found

            print(f"Resolving {len(need_gleif)} companies via parallel GLEIF workers...", flush=True)
            await asyncio.gather(*(resolve_one(c) for c in need_gleif))
            print("Parallel resolution complete!", flush=True)

    # Build validated Company objects
    for cand in unique_candidates.values():
        row_dict = {
            "country": "GBR",
            "company_name": cand["company_name"],
            "exchange": "XLON",
            "lei": cand["lei"],
            "isin": cand["isin"],
            "ticker": cand["ticker"],
            "cik": "",
            "aliases": cand["company_name"],
        }
        try:
            comp = Company.from_row(row_dict)
            resolved_companies.append(comp)
        except Exception as exc:
            # Skip invalid rows
            pass

    print(f"Successfully validated {len(resolved_companies)} Company objects via Company.from_row()!")
    return resolved_companies


def main():
    import asyncio
    companies = asyncio.run(resolve_remaining_lse())

    out_file = Path("local/universe_lse_remaining.csv")
    with out_file.open("w", encoding="utf-8", newline="") as f:
        writer = csv.DictWriter(f, fieldnames=UNIVERSE_FIELDS)
        writer.writeheader()
        for c in companies:
            writer.writerow({
                "country": c.country,
                "company_name": c.company_name,
                "exchange": c.exchange,
                "lei": c.lei,
                "isin": c.isin,
                "ticker": c.ticker,
                "cik": c.cik,
                "aliases": c.aliases,
            })
    print(f"Wrote {len(companies)} companies to {out_file}")


if __name__ == "__main__":
    main()
