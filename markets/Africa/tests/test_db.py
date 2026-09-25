from __future__ import annotations

from pathlib import Path
import tempfile
import pytest

from africa_ar_bulk.db import AfricaDB
from africa_ar_bulk.models import Issuer, Candidate


@pytest.fixture
def db():
    with tempfile.TemporaryDirectory() as tmpdir:
        db_path = Path(tmpdir) / "test_africa.sqlite3"
        database = AfricaDB(db_path)
        yield database
        database.close()


def test_db_schema_initialization(db: AfricaDB):
    stats = db.get_coverage_stats()
    assert stats["total_issuers"] == 0
    assert stats["total_slots"] == 0
    assert stats["done_slots"] == 0


def test_issuer_crud(db: AfricaDB):
    issuer = Issuer(
        issuer_id="NGA:XNSA:DANGCEM",
        country_iso3="NGA",
        exchange_mic="XNSA",
        ticker="DANGCEM",
        company_name="Dangote Cement Plc",
        isin="NGDANGCEM008",
        lei="02920084323281141784",
        active=1,
    )
    db.upsert_issuer(issuer)
    
    issuers = db.get_issuers()
    assert len(issuers) == 1
    assert issuers[0].ticker == "DANGCEM"
    assert issuers[0].exchange_mic == "XNSA"
    assert issuers[0].isin == "NGDANGCEM008"

    # Test query by country
    nga_issuers = db.get_issuers("NGA")
    assert len(nga_issuers) == 1
    assert nga_issuers[0].ticker == "DANGCEM"

    ken_issuers = db.get_issuers("KEN")
    assert len(ken_issuers) == 0


def test_slots_and_candidates(db: AfricaDB):
    issuer = Issuer(
        issuer_id="KEN:XNAI:SCOM",
        country_iso3="KEN",
        exchange_mic="XNAI",
        ticker="SCOM",
        company_name="Safaricom Plc",
        isin="KE1000001402",
        active=1,
    )
    db.upsert_issuer(issuer)
    db.make_slots("KEN:XNAI:SCOM", start_yr=2022, end_yr=2023)

    stats = db.get_coverage_stats()
    assert stats["total_slots"] == 2

    # Insert a candidate
    candidate = Candidate(
        candidate_id="cand_scom_2023",
        issuer_id="KEN:XNAI:SCOM",
        source_name="EXCHANGE_DIRECT",
        source_url="https://example.com/scom_2023_ar.pdf",
        title="Safaricom Annual Report 2023",
        resolved_fy=2023,
        fy_confidence=0.95,
        classification="AR",
        classification_score=0.9,
        direct_pdf_url="https://example.com/scom_2023_ar.pdf",
    )
    db.add_candidate(candidate)

    # Check candidates for download
    candidates = db.get_selected_candidates()
    assert len(candidates) == 1
    assert candidates[0]["ticker"] == "SCOM"
    assert candidates[0]["fiscal_year"] == 2023

    # Mark download as done
    db.mark_download(
        candidate_id="cand_scom_2023",
        state="DONE",
        attempts=1,
        bytes_downloaded=102400,
        http_status=200,
        sha256="abc123456789",
        local_path="/fake/path.pdf",
    )
    db.update_slot_status("KEN:XNAI:SCOM", 2023, "DONE")

    stats = db.get_coverage_stats()
    assert stats["total_issuers"] == 1
    assert stats["total_slots"] == 2
    assert stats["done_slots"] == 1


def test_dual_slots_and_candidate_selection(db: AfricaDB):
    issuer = Issuer(
        issuer_id="ZAF:XJSE:NPN",
        country_iso3="ZAF",
        exchange_mic="XJSE",
        ticker="NPN",
        company_name="Naspers Limited",
        isin="ZAE000015889",
        lei="213800COVT3N6B3Q5O74",
        active=1,
    )
    db.upsert_issuer(issuer)
    db.make_slots("ZAF:XJSE:NPN", start_yr=2023, end_yr=2023, report_types=["AR", "SR"])

    slots = db.conn.execute("SELECT * FROM expected_slots WHERE issuer_id='ZAF:XJSE:NPN';").fetchall()
    assert len(slots) == 2
    types = {s["report_type"] for s in slots}
    assert types == {"AR", "SR"}

    # Insert both AR and SR candidates for FY2023
    cand_ar = Candidate(
        candidate_id="cand_npn_2023_ar",
        issuer_id="ZAF:XJSE:NPN",
        source_name="EXCHANGE_DIRECT",
        source_url="https://example.com/npn_2023_ar.pdf",
        title="Naspers Integrated Annual Report 2023",
        resolved_fy=2023,
        fy_confidence=0.95,
        classification="AR",
        classification_score=0.95,
        direct_pdf_url="https://example.com/npn_2023_ar.pdf",
    )
    cand_sr = Candidate(
        candidate_id="cand_npn_2023_sr",
        issuer_id="ZAF:XJSE:NPN",
        source_name="EXCHANGE_DIRECT",
        source_url="https://example.com/npn_2023_sr.pdf",
        title="Naspers Sustainability Report 2023",
        resolved_fy=2023,
        fy_confidence=0.95,
        classification="SR",
        classification_score=0.90,
        direct_pdf_url="https://example.com/npn_2023_sr.pdf",
    )
    db.add_candidate(cand_ar)
    db.add_candidate(cand_sr)

    # Both slots should now be CANDIDATE_FOUND
    updated_slots = db.conn.execute("SELECT report_type, status FROM expected_slots WHERE issuer_id='ZAF:XJSE:NPN';").fetchall()
    for s in updated_slots:
        assert s["status"] == "CANDIDATE_FOUND"

    # Query all selected candidates
    all_cands = db.get_selected_candidates()
    assert len(all_cands) == 2
    cand_types = {c["report_type"] for c in all_cands}
    assert cand_types == {"AR", "SR"}

    # Query specific report type
    ar_only = db.get_selected_candidates(report_type="AR")
    assert len(ar_only) == 1
    assert ar_only[0]["report_type"] == "AR"

    sr_only = db.get_selected_candidates(report_type="SR")
    assert len(sr_only) == 1
    assert sr_only[0]["report_type"] == "SR"
