from __future__ import annotations

import hashlib
import os
import sys
import time
from pathlib import Path

import fitz  # PyMuPDF
from curl_cffi import requests

ROOT_DIR = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT_DIR))
from markets._integration.promotion import build_sop_relative_path

DEFAULT_CORPUS_ROOT = ROOT_DIR / "GLOBAL_SUSTAINABILITY_DATABASE"

bm_archive_reports = [
    (2017, "https://www.annualreports.com/HostedData/AnnualReportArchive/b/bank-muscat_2017.pdf"),
    (2018, "https://www.annualreports.com/HostedData/AnnualReportArchive/b/bank-muscat_2018.pdf"),
    (2019, "https://www.annualreports.com/HostedData/AnnualReportArchive/b/bank-muscat_2019.pdf"),
    (2020, "https://www.annualreports.com/HostedData/AnnualReportArchive/b/bank-muscat_2020.pdf"),
    (2021, "https://www.annualreports.com/HostedData/AnnualReportArchive/b/bank-muscat_2021.pdf"),
    (2022, "https://www.annualreports.com/HostedData/AnnualReportArchive/b/bank-muscat_2022.pdf"),
]

print("======================================================================")
print("RESOLVING BANK MUSCAT HISTORICAL ANNUAL REPORTS (FY2017-FY2022)")
print("======================================================================", flush=True)

success = 0
for year, url in bm_archive_reports:
    sop_rel = build_sop_relative_path(
        iso3="OMN", mic="XMUS", ticker="BKMB", fiscal_year=year,
        lei="558600FG4CZB5EAVK341", isin="OM0000001004", report_type="AR", lang="EN"
    )
    final_path = DEFAULT_CORPUS_ROOT / sop_rel

    if final_path.exists() and final_path.stat().st_size > 35_000:
        print(f"  = [EXISTING] OMN:BKMB FY{year} AR: {final_path.stat().st_size//1024:,} KB -> {final_path.name}", flush=True)
        success += 1
        continue

    print(f"Downloading OMN:BKMB FY{year} AR from {url}...", flush=True)
    try:
        t0 = time.time()
        r = requests.get(url, impersonate="chrome120", verify=False, timeout=180.0)
        elapsed = time.time() - t0

        if r.status_code != 200:
            print(f"  x [FAILED] HTTP {r.status_code} for FY{year}", flush=True)
            continue

        if not r.content.startswith(b"%PDF-"):
            print(f"  x [FAILED] Content not PDF for FY{year}", flush=True)
            continue

        doc = fitz.open(stream=r.content, filetype="pdf")
        pages = len(doc)
        doc.close()

        sha = hashlib.sha256(r.content).hexdigest()
        sz = len(r.content)

        final_path.parent.mkdir(parents=True, exist_ok=True)
        tmp = final_path.with_suffix(final_path.suffix + f".tmp_{time.time_ns()}")
        tmp.write_bytes(r.content)
        tmp.replace(final_path)

        print(f"  + [PROMOTED] OMN:BKMB FY{year} AR: {sz//1024:,} KB ({pages} pages, {elapsed:.1f}s) -> {final_path.name}", flush=True)
        success += 1

    except Exception as e:
        print(f"  x [ERROR] FY{year}: {e}", flush=True)

print(f"\nBank Muscat Complete: {success}/{len(bm_archive_reports)} resolved and promoted.", flush=True)
