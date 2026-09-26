from curl_cffi import requests
import fitz
import hashlib
import time
from pathlib import Path
import sys

ROOT_DIR = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT_DIR))
from markets._integration.promotion import build_sop_relative_path

url = "https://www.bankfab.com/-/media/fab-uds/about-fab/sustainability/reports-policy-frameworks/documents/2019-esg-report.pdf"
out_corpus = ROOT_DIR / "GLOBAL_SUSTAINABILITY_DATABASE"

print(f"Downloading FAB 2019 SR from {url}...")
t0 = time.time()
r = requests.get(url, impersonate="chrome120", verify=False, timeout=300)
elapsed = time.time() - t0
print(f"Downloaded {len(r.content):,} bytes in {elapsed:.1f}s (Status: {r.status_code})")

if r.status_code == 200 and r.content.startswith(b"%PDF-"):
    doc = fitz.open(stream=r.content, filetype="pdf")
    pages = len(doc)
    doc.close()
    sha = hashlib.sha256(r.content).hexdigest()
    print(f"PyMuPDF validated: {pages} pages, SHA: {sha}")

    sop_rel = build_sop_relative_path(
        iso3="ARE", mic="XADS", ticker="FAB", fiscal_year=2019,
        lei="259400TPPDBP7TDL0O61", isin="AEA000201011", report_type="SR", lang="EN"
    )
    final_path = out_corpus / sop_rel
    final_path.parent.mkdir(parents=True, exist_ok=True)
    tmp_path = final_path.with_suffix(final_path.suffix + f".tmp_{time.time_ns()}")
    tmp_path.write_bytes(r.content)
    tmp_path.replace(final_path)
    print(f"Successfully promoted to: {final_path}")
else:
    print("Download failed or not PDF!")
