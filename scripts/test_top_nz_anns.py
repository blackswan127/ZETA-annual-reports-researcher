import asyncio
import httpx
import json
import re

HEADERS = {
    "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64)",
    "Referer": "https://www.nzx.com/",
}

sample_cids = [
    ("AIA", "AIA000000"),
    ("AIR", "AIR000000"),
    ("SPK", "TEL000000"),  # Spark NZ was Telecom NZ
    ("MEL", "MEL000000"),  # Meridian Energy
    ("FPH", "FPH000000"),  # Fisher & Paykel
    ("MCY", "MCY000000"),  # Mercury NZ
    ("CNU", "CNU000000"),  # Chorus
    ("POT", "POT000000"),  # Port of Tauranga
    ("RYM", "RYM000000"),  # Ryman Healthcare
    ("EBO", "EBO000000"),  # EBOS Group
]

async def check_cids():
    async with httpx.AsyncClient(timeout=30.0, headers=HEADERS) as client:
        for ticker, cid in sample_cids:
            print(f"\n--- Checking {ticker} ({cid}) ---")
            for year in [2024, 2023, 2022, 2021, 2020]:
                url = f"https://api.nzx.com/public/company/{cid}/announcements/{year}/all.json"
                try:
                    resp = await client.get(url)
                    if resp.status_code == 200:
                        anns = resp.json()
                        ar_matches = []
                        sr_matches = []
                        for a in anns:
                            title = a.get("title", "")
                            atype = a.get("type", "")
                            t_lower = title.lower()
                            if atype == "ANNREP" or "annual report" in t_lower:
                                ar_matches.append((a["id"], atype, title))
                            elif any(k in t_lower for k in ["sustainability", "esg", "climate", "tcfd"]):
                                sr_matches.append((a["id"], atype, title))
                        print(f"  FY{year}: found {len(ar_matches)} AR, {len(sr_matches)} SR")
                        for m in ar_matches:
                            print(f"    AR: [{m[0]}] ({m[1]}) {m[2]}")
                        for m in sr_matches:
                            print(f"    SR: [{m[0]}] ({m[1]}) {m[2]}")
                except Exception as e:
                    print(f"  FY{year} err: {e}")

asyncio.run(check_cids())
