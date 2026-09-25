from __future__ import annotations

from pathlib import Path
import tempfile
import pytest

from africa_ar_bulk.config import resolve_african_market, AFRICAN_MARKETS
from africa_ar_bulk.sources.universe import load_universe, DEFAULT_AFRICAN_UNIVERSE


def test_resolve_african_market():
    # Test by ISO3
    meta = resolve_african_market("ZAF")
    assert meta is not None
    assert meta["mic"] == "XJSE"
    assert meta["country"] == "South Africa"

    # Test by MIC
    meta = resolve_african_market("XNSA")
    assert meta is not None
    assert meta["iso3"] == "NGA"

    # Test by alias / name
    meta = resolve_african_market("nigeria")
    assert meta is not None
    assert meta["iso3"] == "NGA"

    meta = resolve_african_market("kenya")
    assert meta is not None
    assert meta["iso3"] == "KEN"

    # Test invalid
    assert resolve_african_market("INVALID_COUNTRY") is None


def test_seed_universe_generation():
    issuers = load_universe()
    assert len(issuers) >= 16  # At least 16 markets in seed
    countries = {i.country_iso3 for i in issuers}
    assert "ZAF" in countries
    assert "NGA" in countries
    assert "KEN" in countries
    assert "BWA" in countries

    # Filter by country
    nga_only = load_universe(country_iso3="NGA")
    assert len(nga_only) > 0
    assert all(i.country_iso3 == "NGA" for i in nga_only)


def test_custom_csv_universe_load():
    csv_content = """country_iso3,exchange_mic,ticker,company_name,isin,lei
KEN,XNAI,TEST1,Test Kenya PLC,KE1234567890,
NGA,XNSA,TEST2,Test Nigeria PLC,,02920084323281141784
"""
    with tempfile.TemporaryDirectory() as tmpdir:
        csv_file = Path(tmpdir) / "custom_universe.csv"
        csv_file.write_text(csv_content, encoding="utf-8")

        issuers = load_universe(universe_csv=csv_file)
        assert len(issuers) == 2
        assert issuers[0].ticker == "TEST1"
        assert issuers[0].isin == "KE1234567890"
        assert issuers[1].ticker == "TEST2"
        assert issuers[1].lei == "02920084323281141784"


def test_all_16_countries_present_in_universe():
    issuers = load_universe()
    countries = {i.country_iso3 for i in issuers}
    expected_16 = {
        "ZAF", "NGA", "KEN", "GHA", "BWA", "ZMB", "TZA", "ZWE",
        "MUS", "NAM", "UGA", "MWI", "RWA", "SWZ", "SYC", "SLE",
    }
    assert expected_16.issubset(countries), f"Missing countries: {expected_16 - countries}"
    assert len(issuers) >= 50
