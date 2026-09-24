import asyncio
import io
import shutil
import zipfile
from pathlib import Path

import pytest

from annual_reports.discovery import Company, DiscoveryStore
from annual_reports.engine import verify_store
from annual_reports.fca_conversion import _jobs, _safe_extract, render_fca_originals


def _chrome() -> Path | None:
    paths = [
        Path("C:/Program Files/Google/Chrome/Application/chrome.exe"),
        Path("C:/Program Files (x86)/Microsoft/Edge/Application/msedge.exe"),
    ]
    for path in paths:
        if path.is_file():
            return path
    binary = shutil.which("google-chrome") or shutil.which("chromium")
    return Path(binary) if binary else None


def test_jobs_filter_by_company_keys(tmp_path: Path):
    state_path = tmp_path / "state.sqlite3"
    store = DiscoveryStore(state_path)
    c1 = Company("GBR", "Company 1 PLC", "XLON", "2138007ZFQYRUSLU3J98", "GB00BHJYC057", "TCK1", "")
    c2 = Company("GBR", "Company 2 PLC", "XLON", "213800ZJ7PFEV1U4Z315", "GB0003576021", "TCK2", "")
    try:
        store.add_universe([c1, c2], [2024])
        store.upsert_candidate(
            company_key=c1.key, report_year=2024, source="FCA_NSM",
            source_record_id="rec1", source_url="https://data.fca.org.uk/artefacts/NSM/1.zip",
            source_format="zip", form_type="AFR", status="MANUAL_REVIEW", verified=False,
        )
        store.upsert_candidate(
            company_key=c2.key, report_year=2024, source="FCA_NSM",
            source_record_id="rec2", source_url="https://data.fca.org.uk/artefacts/NSM/2.zip",
            source_format="zip", form_type="AFR", status="MANUAL_REVIEW", verified=False,
        )
        store.commit()

        # Without filter: both jobs
        all_jobs = _jobs(store, limit=None)
        assert len(all_jobs) == 2

        # With filter: only c1
        c1_jobs = _jobs(store, limit=None, company_keys={c1.key})
        assert len(c1_jobs) == 1
        assert c1_jobs[0].report.ticker == "TCK1"

        # With empty filter: 0 jobs
        none_jobs = _jobs(store, limit=None, company_keys=set())
        assert len(none_jobs) == 0
    finally:
        store.close()
