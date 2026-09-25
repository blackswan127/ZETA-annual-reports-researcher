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
