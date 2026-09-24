import csv
import io
import sqlite3
import zipfile
from pathlib import Path

from annual_reports.discovery import Company, DiscoveryStore
from annual_reports.fca_catalog import (build_or_open_fca_catalog,
                                        discover_fca_candidates,
                                        query_fca_catalog)


def test_build_and_query_fca_catalog(tmp_path: Path):
    # 1. Create a mock mapping.zip
    zip_path = tmp_path / "mapping.zip"
    with zipfile.ZipFile(zip_path, "w") as z:
        out = io.StringIO()
        writer = csv.writer(out)
        writer.writerow(["Company Name", "Title", "Published Date", "Morningstar URL", "FCA URL"])
        writer.writerow(["Saga PLC", "Annual Report and Accounts 2017", "31/1/2017 00:00:00", "http://m/1", "https://data.fca.org.uk/artefacts/NSM/data-migration/132547738.pdf"])
        writer.writerow(["Saga PLC", "Annual Report and Accounts 2018", "31/1/2018 00:00:00", "http://m/2", "https://data.fca.org.uk/artefacts/NSM/data-migration/171391686.pdf"])
        writer.writerow(["Other PLC", "Interim Report 2017", "30/6/2017 00:00:00", "http://m/3", "https://data.fca.org.uk/artefacts/NSM/data-migration/999.pdf"])
        z.writestr("Mapping 20170101 to 20181231.csv", out.getvalue().encode("utf-8"))

    # 2. Build catalog
    cache_dir = tmp_path / "cache"
    conn = build_or_open_fca_catalog(cache_dir, zip_path)
    assert conn is not None

    # 3. Query catalog
    results = query_fca_catalog(conn, "Saga PLC", years=[2017, 2018])
    assert len(results) == 2
    assert results[0]["year"] in {2017, 2018}
    assert results[0]["fca_url"].startswith("https://data.fca.org.uk/")

    # 4. Discover candidates into DiscoveryStore
    state_path = tmp_path / "state.sqlite3"
    store = DiscoveryStore(state_path)
    try:
        company = Company("GBR", "Saga PLC", "XLON", "2138004O6UZY9WR66W12", "GB00BSQNQZ79", "SAGA", "")
        store.add_universe([company], [2017, 2018])
        summary = discover_fca_candidates(store, conn, {company.key})
        assert summary["candidates_discovered"] == 2

        # Check candidate rows in store
        candidates = store.connection.execute(
            "SELECT report_year, source_url, source_format, status, verified FROM candidates WHERE company_key=?",
            (company.key,)
        ).fetchall()
        assert len(candidates) == 2
        for row in candidates:
            assert row["source_format"] == "pdf"
            assert row["status"] == "DISCOVERED"
            assert row["verified"] == 1
    finally:
        store.close()
        conn.close()
