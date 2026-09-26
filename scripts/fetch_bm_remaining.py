import subprocess
import time
import hashlib
from pathlib import Path
import sys
import fitz

ROOT_DIR = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT_DIR))
from markets._integration.promotion import build_sop_relative_path

DEFAULT_CORPUS_ROOT = ROOT_DIR / "GLOBAL_SUSTAINABILITY_DATABASE"
STAGING_DIR = ROOT_DIR / "local" / "markets" / "MiddleEast" / "staging"
STAGING_DIR.mkdir(parents=True, exist_ok=True)

targets = [
    (2020, "https://www.annualreports.com/HostedData/AnnualReportArchive/b/bank-muscat_2020.pdf"),
    (2021, "https://www.annualreports.com/HostedData/AnnualReportArchive/b/bank-muscat_2021.pdf"),
    (2022, "https://www.annualreports.com/HostedData/AnnualReportArchive/b/bank-muscat_2022.pdf"),
]

for year, url in targets:
    sop_rel = build_sop_relative_path(
        iso3="OMN", mic="XMUS", ticker="BKMB", fiscal_year=year,
        lei="558600FG4CZB5EAVK341", isin="OM0000001004", report_type="AR", lang="EN"
    )
    final_path = DEFAULT_CORPUS_ROOT / sop_rel
    if final_path.exists() and final_path.stat().st_size > 35_000:
        print(f"OMN:BKMB FY{year} AR already exists ({final_path.stat().st_size//1024} KB)", flush=True)
        continue

    stg_file = STAGING_DIR / f"bm_{year}.pdf"
    print(f"Downloading OMN:BKMB FY{year} AR to {stg_file}...", flush=True)
    
    # Run curl with retry and resume
    cmd = [
        "curl.exe", "-k", "-L", "-C", "-",
        "--retry", "10", "--retry-delay", "3", "--retry-connrefused",
        "-o", str(stg_file),
        "-A", "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36",
        url
    ]
    subprocess.run(cmd, check=False)
    
    if stg_file.exists() and stg_file.stat().st_size > 35_000:
        content = stg_file.read_bytes()
        if content.startswith(b"%PDF-"):
            try:
                doc = fitz.open(stream=content, filetype="pdf")
                pages = len(doc)
                doc.close()
                final_path.parent.mkdir(parents=True, exist_ok=True)
                final_path.write_bytes(content)
                print(f"+ [PROMOTED] OMN:BKMB FY{year} AR: {len(content)//1024} KB ({pages} pages) -> {final_path.name}", flush=True)
                continue
            except Exception as e:
                print(f"Validation error for FY{year}: {e}", flush=True)
    print(f"Failed to complete OMN:BKMB FY{year}", flush=True)

print("Bank Muscat sweep complete.", flush=True)
