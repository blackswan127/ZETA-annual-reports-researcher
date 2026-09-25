from __future__ import annotations

import tempfile
from pathlib import Path
import pytest

from me_ar_bulk.db import MiddleEastDB
from me_ar_bulk.models import Candidate, Issuer


@pytest.fixture
def db():
    with tempfile.TemporaryDirectory() as tmpdir:
        db_path = Path(tmpdir) / "test_me.sqlite3"
        database = MiddleEastDB(db_path)
        yield database
        database.close()


def test_db_schema_initialization(db: MiddleEastDB):
    stats = db.get_coverage_stats()
    assert stats["total_issuers"] == 0
    assert stats["total_slots"] == 0
    assert stats["done_slots"] == 0


def test_issuer_crud(db: MiddleEastDB):
    issuer = Issuer(
        issuer_id="OMN:XMUS:BKMB",
        iso3="OMN",
        mic="XMUS",
        ticker="BKMB",
        company_name="Bank Muscat SAOG",
        isin="OM0000001004",
        lei="549300H4Y0C0R46L4A57",
        active=1,
    )
    db.upsert_issuer(issuer)

    issuers = db.get_issuers()
    assert len(issuers) == 1
    assert issuers[0].ticker == "BKMB"
    assert issuers[0].mic == "XMUS"
    assert issuers[0].isin == "OM0000001004"

    # Query by country
    omn_issuers = db.get_issuers("OMN")
    assert len(omn_issuers) == 1
    assert omn_issuers[0].ticker == "BKMB"

    sau_issuers = db.get_issuers("SAU")
    assert len(sau_issuers) == 0


def test_slots_and_candidates(db: MiddleEastDB):
    issuer = Issuer(
        issuer_id="ARE:XDFM:EMAAR",
        iso3="ARE",
        mic="XDFM",
        ticker="EMAAR",
        company_name="Emaar Properties PJSC",
        isin="AEE000301011",
        active=1,
    )
    db.upsert_issuer(issuer)
    db.make_slots("ARE:XDFM:EMAAR", start_yr=2022, end_yr=2023, required_class="AR_FULL")

    stats = db.get_coverage_stats()
    assert stats["total_slots"] == 2

    # Insert an AR_FULL candidate
    cand = Candidate(
        candidate_id="cand_emaar_2023",
        issuer_id="ARE:XDFM:EMAAR",
        source_name="DFM_UAE",
        source_url="https://feeds.dfm.ae/reports/emaar_2023_ar.pdf",
        direct_url="https://feeds.dfm.ae/reports/emaar_2023_ar.pdf",
        title="Emaar Properties Annual Report 2023",
        resolved_fy=2023,
        fy_confidence=0.95,
        language="EN",
        language_confidence=1.0,
        document_class="AR_FULL",
        class_confidence=0.95,
    )
    db.add_candidate(cand)

    # Check candidates for download
    candidates = db.get_selected_candidates(required_class="AR_FULL")
    assert len(candidates) == 1
    assert candidates[0]["ticker"] == "EMAAR"
    assert candidates[0]["fiscal_year"] == 2023

    # Mark download as done
    db.mark_download(
        candidate_id="cand_emaar_2023",
        state="DONE",
        attempts=1,
        bytes_downloaded=150000,
        http_status=200,
        sha256="1234567890abcdef",
        local_path="/fake/path/emaar_ar2023.pdf",
    )
    db.update_slot_status("ARE:XDFM:EMAAR", 2023, "DONE", selected_candidate_id="cand_emaar_2023")

    stats = db.get_coverage_stats()
    assert stats["total_issuers"] == 1
    assert stats["total_slots"] == 2
    assert stats["done_slots"] == 1
