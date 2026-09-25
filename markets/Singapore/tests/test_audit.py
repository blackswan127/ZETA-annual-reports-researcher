from datetime import UTC, date, datetime
import csv

from sgx_bulk.audit import write_audits
from sgx_bulk.db import Database
from sgx_bulk.models import Issuer, Filing


def test_coverage_csv(tmp_path):
    db_path = tmp_path / "m.sqlite3"
    db = Database(db_path)
    i = Issuer("1J26", "S68", "SINGAPORE EXCHANGE LIMITED", "SGX", "MAINBOARD")
    db.upsert_issuers([i])
    f = Filing("2J4PCEOQYA3WTBWP", i.ibm_code, i.stock_code, i.issuer_name, i.short_name,
               2025, date(2025,6,30), datetime(2025,9,15,tzinfo=UTC),
               "https://links.sgx.com/1.0.0/corporate-announcements/2J4PCEOQYA3WTBWP/"+"a"*64)
    db.upsert_filing(f, "global", "companyName")
    db.close()
    out = tmp_path / "audit"
    write_audits(db_path, out, 2024, 2025)
    rows = list(csv.DictReader((out / "coverage.csv").open(encoding="utf-8-sig")))
    assert len(rows) == 2
    assert rows[0]["status"] == "NO_FILING_FOUND"
    assert rows[1]["status"] == "FOUND_NOT_DOWNLOADED"
