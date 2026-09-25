from __future__ import annotations

import tempfile
from pathlib import Path
import pytest

from me_ar_bulk.config import resolve_middle_east_market, MIDDLE_EAST_MARKETS
from me_ar_bulk.sources.universe import load_universe, DEFAULT_MIDDLE_EAST_UNIVERSE


def test_resolve_middle_east_market():
    # Test Oman
    meta = resolve_middle_east_market("Oman")
    assert meta is not None
    assert meta["mic"] == "XMUS"
    assert meta["iso3"] == "OMN"

    # Test Jordan
    meta = resolve_middle_east_market("XAMM")
    assert meta is not None
    assert meta["iso3"] == "JOR"

    # Test Dubai UAE
    meta = resolve_middle_east_market("DFM")
    assert meta is not None
    assert meta["iso3"] == "ARE"
    assert meta["mic"] == "XDFM"

    # Test Saudi Arabia
    meta = resolve_middle_east_market("Tadawul")
    assert meta is not None
    assert meta["iso3"] == "SAU"
    assert meta["mic"] == "XSAU"

    # Test Qatar
    meta = resolve_middle_east_market("QSE")
    assert meta is not None
    assert meta["iso3"] == "QAT"


def test_strict_exclusion_of_palestine_and_israel():
    # User directive: ignore palestine & israel
    assert resolve_middle_east_market("Palestine") is None
    assert resolve_middle_east_market("PSE") is None
    assert resolve_middle_east_market("PEX") is None
    assert resolve_middle_east_market("XPSX") is None
    assert resolve_middle_east_market("Israel") is None
    assert resolve_middle_east_market("ISR") is None
    assert resolve_middle_east_market("TASE") is None
    assert resolve_middle_east_market("XTAE") is None


def test_seed_universe_generation():
    issuers = load_universe()
    assert len(issuers) >= 40  # 5 per market across 8 markets
    countries = {i.iso3 for i in issuers}
    assert "OMN" in countries
    assert "JOR" in countries
    assert "ARE" in countries
    assert "SAU" in countries
    assert "QAT" in countries
    assert "BHR" in countries
    assert "KWT" in countries

    # Verify Palestine and Israel are NOT in universe
    assert "PSE" not in countries
    assert "ISR" not in countries

    # Filter by country
    omn_only = load_universe(iso3="OMN")
    assert len(omn_only) == 5
    assert all(i.iso3 == "OMN" for i in omn_only)


def test_custom_csv_universe_load():
    csv_content = """iso3,mic,ticker,company_name,isin,lei
OMN,XMUS,TEST1,Test Oman SAOG,OM1234567890,
SAU,XSAU,TEST2,Test Saudi SJSC,,SA123456789012345678
PSE,XPSX,EXCLUDE_ME,Should be ignored,,
ISR,XTAE,EXCLUDE_ME_TOO,Should be ignored,,
"""
    with tempfile.TemporaryDirectory() as tmpdir:
        csv_file = Path(tmpdir) / "custom_universe.csv"
        csv_file.write_text(csv_content, encoding="utf-8")

        issuers = load_universe(universe_csv=csv_file)
        assert len(issuers) == 2  # The 2 excluded are dropped
        assert issuers[0].ticker == "TEST1"
        assert issuers[0].isin == "OM1234567890"
        assert issuers[1].ticker == "TEST2"
