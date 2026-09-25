"""Network smoke test: metadata only, no PDF download."""
import subprocess
import sys

metadata_status = subprocess.call([sys.executable, "run.py", "smoke", "--stock-code", "00700", "--smoke-year", "2025"])
company_count_status = subprocess.call([sys.executable, "run.py", "companies"])
raise SystemExit(metadata_status or company_count_status)
