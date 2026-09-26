"""Reconcile and ensure high-integrity English reports for SGX multi-attachment filings.

When multiple attachments exist for a company-year-type:
1. Resolve the genuine English Annual Report / Sustainability Report.
2. Filter out non-English translations (Chinese/Mandarin), circulars, notices, addenda, and errata.
3. If genuine multiple parts exist (Part 1, Part 2), promote both with proper part designations.
4. Download any missing winner directly from SGX and atomically place it at the SOP path on Drive.
"""
from __future__ import annotations

import asyncio
import os
import re
import shutil
import sqlite3
import time
from collections import defaultdict
from pathlib import Path
from typing import Any

import httpx
import fitz

BASE_DIR = Path(__file__).resolve().parent.parent
DB_PATH = BASE_DIR / "local" / "markets" / "Singapore" / "work" / "manifest.sqlite3"
DRIVE_ROOT = BASE_DIR / "GLOBAL_SUSTAINABILITY_DATABASE"
USER_AGENT = "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/122.0.0.0 Safari/537.36"


def sanitize_token(value: str) -> str:
    cleaned = re.sub(r"[^A-Za-z0-9._-]+", "_", value.strip())
    return cleaned.strip("._-") or "UNKNOWN"


def score_candidate(filename: str, size_bytes: int | None, rtype: str) -> int:
    fn = filename.lower()
    score = 0

    # Strong penalty for Chinese / non-English versions
    if (
        re.search(r"[-_ ]c(?:hi|hinese|\.pdf|_|\b)", fn)
        or fn.startswith("c_")
        or "cisdn" in fn
        or "mandarin" in fn
        or "chinese" in fn
    ):
        score -= 2000

    # Strong bonus for explicit English versions
    if (
        re.search(r"[-_ ]e(?:ng|nglish|\.pdf|_|\b)", fn)
        or fn.startswith("e_")
        or "eisdn" in fn
        or "english" in fn
    ):
        score += 300

    # Negative terms (non-report supplements)
    reject_terms = [
        "clarification", "corrigendum", "analysis", "shareholding", "notice",
        "proxy", "letter", "requestform", "request form", "market research",
        "addendum", "errata", "press release", "highlights", "presentation",
        "factsheet", "circular", "agm", "appendix", "statement", "summary"
    ]
    for term in reject_terms:
        if term in fn:
            score -= 500

    # Positive terms for primary reports
    if rtype == "AR":
        if "annual report" in fn or "annual_report" in fn or "annualreport" in fn:
            score += 250
        elif "ar20" in fn or "ar 20" in fn:
            score += 180
    elif rtype == "SR":
        if "sustainability" in fn or "sustainable" in fn:
            score += 250
        if "esg" in fn or "csr" in fn:
            score += 180

    # Resolution preferences
    if "low res" in fn or "lowres" in fn:
        score -= 50
    if "high res" in fn or "hires" in fn or "hi-res" in fn:
        score += 50

    # File size bonus: Complete annual reports are substantially larger than addenda/circulars
    if size_bytes:
        score += min(150, int(size_bytes / (100 * 1024)))

    return score


def detect_multipart(candidates: list[dict[str, Any]]) -> bool:
    """Check if candidates form genuine multiple parts (e.g., Part 1 and Part 2)."""
    part_patterns = [r"part\s*[1-9]", r"_p[1-9]\b", r"vol(?:ume)?\s*[1-9]"]
    found_parts = set()
    for c in candidates:
        fn = c["filename"].lower()
        for pat in part_patterns:
            m = re.search(pat, fn)
            if m:
                found_parts.add(m.group(0))
    return len(found_parts) >= 2


async def download_and_validate(client: httpx.AsyncClient, url: str) -> bytes | None:
    try:
        r = await client.get(url, timeout=30.0, follow_redirects=True)
        if r.status_code != 200:
            return None
        data = r.content
        if len(data) < 1000 or not data.startswith(b"%PDF"):
            return None
        # In-RAM PyMuPDF validation
        doc = fitz.open(stream=data, filetype="pdf")
        if doc.page_count < 1 or doc.is_encrypted:
            doc.close()
            return None
        doc.close()
        return data
    except Exception:
        return None


async def main():
    conn = sqlite3.connect(DB_PATH)
    conn.row_factory = sqlite3.Row
    cur = conn.cursor()

    cur.execute("""
        SELECT f.ibm_code, f.stock_code, f.issuer_name, f.fiscal_year, f.report_type,
               a.url, a.filename, a.size_bytes, a.local_path
        FROM attachments a
        JOIN filings f ON a.announcement_id = f.announcement_id
        WHERE a.status = 'done'
    """)
    rows = cur.fetchall()

    # Load LEI cache
    import json
    lei_cache = {}
    lei_file = BASE_DIR / "local" / "markets" / "Singapore" / "lei_cache.json"
    if lei_file.exists():
        lei_cache = json.loads(lei_file.read_text(encoding="utf-8"))

    # Load issuer ISINs
    cur.execute("SELECT ibm_code, isin FROM issuers")
    isin_by_ibm = {r["ibm_code"]: r["isin"] or "NOISIN" for r in cur.fetchall()}

    # Group by (ibm_code, fiscal_year, report_type)
    groups = defaultdict(list)
    for r in rows:
        groups[(r["ibm_code"], r["fiscal_year"], r["report_type"])].append(dict(r))

    multis = {k: v for k, v in groups.items() if len(v) > 1}
    print(f"Total multi-candidate groups to reconcile: {len(multis)}")

    reconcile_actions = []
    for (ibm, fy, rtype), items in multis.items():
        is_mp = detect_multipart(items)
        if is_mp:
            # Multi-part: score and sort by filename
            items_sorted = sorted(items, key=lambda x: x["filename"].lower())
            for idx, it in enumerate(items_sorted, 1):
                reconcile_actions.append({
                    "action": "multipart",
                    "item": it,
                    "part_num": idx,
                    "ibm": ibm,
                    "fy": fy,
                    "rtype": rtype
                })
        else:
            # Single winner selection
            scored = [(score_candidate(it["filename"], it["size_bytes"], rtype), it) for it in items]
            scored.sort(key=lambda x: x[0], reverse=True)
            winner = scored[0][1]
            reconcile_actions.append({
                "action": "single_winner",
                "item": winner,
                "all_items": items,
                "ibm": ibm,
                "fy": fy,
                "rtype": rtype
            })

    print(f"Total planned reconciliation actions: {len(reconcile_actions)}")

    headers = {"User-Agent": USER_AGENT, "Accept": "application/pdf,*/*"}
    async with httpx.AsyncClient(headers=headers, timeout=30.0) as client:
        fixed_count = 0
        intact_count = 0
        multipart_count = 0

        for act in reconcile_actions:
            ibm = act["ibm"]
            fy = act["fy"]
            rtype = act["rtype"]
            it = act["item"]

            isin = isin_by_ibm.get(ibm, "NOISIN")
            stock_code = it["stock_code"] or ibm
            clean_ticker = sanitize_token(stock_code).upper()
            lei = lei_cache.get(ibm, "NOLEI")

            company_folder = f"{lei}_{isin}_{clean_ticker}"
            fy_folder = f"FY{fy}"
            dest_dir = DRIVE_ROOT / "SGP" / "XSES" / company_folder / fy_folder
            dest_dir.mkdir(parents=True, exist_ok=True)

            if act["action"] == "single_winner":
                sop_filename = f"{lei}_SGP_XSES_{clean_ticker}_{isin}_FY{fy}_{rtype}_EN.pdf"
                dest_file = dest_dir / sop_filename

                # Check if dest_file matches the winner
                needs_download = False
                if not dest_file.exists():
                    needs_download = True
                elif dest_file.stat().st_size != it["size_bytes"]:
                    needs_download = True

                if needs_download:
                    # Download winner bytes and write atomically
                    data = await download_and_validate(client, it["url"])
                    if data:
                        part_file = dest_dir / f"{sop_filename}.part"
                        part_file.write_bytes(data)
                        os.replace(part_file, dest_file)
                        fixed_count += 1
                        print(f"Fixed: {clean_ticker} FY{fy} {rtype} -> {it['filename']} ({len(data):,} bytes)")
                    else:
                        print(f"Error: failed to download winner {it['filename']} from {it['url']}")
                else:
                    intact_count += 1

            elif act["action"] == "multipart":
                part_num = act["part_num"]
                sop_filename = f"{lei}_SGP_XSES_{clean_ticker}_{isin}_FY{fy}_{rtype}_part{part_num}_EN.pdf"
                dest_file = dest_dir / sop_filename
                if not dest_file.exists() or dest_file.stat().st_size != it["size_bytes"]:
                    data = await download_and_validate(client, it["url"])
                    if data:
                        part_file = dest_dir / f"{sop_filename}.part"
                        part_file.write_bytes(data)
                        os.replace(part_file, dest_file)
                        multipart_count += 1
                        print(f"Multi-part: {clean_ticker} FY{fy} {rtype} part {part_num} -> {it['filename']}")

    print("\n" + "=" * 70)
    print("RECONCILIATION SUMMARY")
    print("=" * 70)
    print(f"Intact (already correct winner): {intact_count}")
    print(f"Fixed (restored correct English winner): {fixed_count}")
    print(f"Multi-part reports promoted:     {multipart_count}")
    print("=" * 70 + "\n")

    conn.close()


if __name__ == "__main__":
    asyncio.run(main())
