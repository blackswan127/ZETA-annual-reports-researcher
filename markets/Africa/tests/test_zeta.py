from __future__ import annotations

from pathlib import Path
import tempfile
import pytest

from africa_ar_bulk.zeta import (
    is_valid_lei,
    is_valid_isin,
    sanitize_token,
    build_final_path,
    build_staging_path,
)


def test_sanitize_token():
    assert sanitize_token("DANGCEM") == "DANGCEM"
    assert sanitize_token("MTN/N") == "MTNN"
    assert sanitize_token("ABC:SJ") == "ABCSJ"
    assert sanitize_token("  xyz  ") == "xyz"


def test_lei_isin_validation():
    assert is_valid_lei("02920084323281141784") is True
    assert is_valid_lei("short") is False
    assert is_valid_isin("NGDANGCEM008") is True
    assert is_valid_isin("bad_isin") is False


def test_build_final_path_valid():
    with tempfile.TemporaryDirectory() as tmpdir:
        root = Path(tmpdir)
        path = build_final_path(
            zeta_root=root,
            country_iso3="ZAF",
            exchange_mic="XJSE",
            lei="213800COVT3N6B3Q5O74",
            isin="ZAE000015889",
            ticker="NPN",
            fiscal_year=2023,
            lang="EN",
            report_type="AR",
        )
        assert path is not None
        assert "ZAF" in path.parts
        assert "XJSE" in path.parts
        assert "213800COVT3N6B3Q5O74_ZAE000015889_NPN" in path.parts
        assert "FY2023" in path.parts
        assert path.name.endswith(".pdf")
        assert "213800COVT3N6B3Q5O74_ZAF_XJSE_NPN_ZAE000015889_FY2023_AR_EN.pdf" == path.name


def test_build_final_path_unresolved():
    with tempfile.TemporaryDirectory() as tmpdir:
        root = Path(tmpdir)
        # Missing LEI and ISIN -> should return None for final path
        path = build_final_path(
            zeta_root=root,
            country_iso3="GHA",
            exchange_mic="XGHA",
            lei="",
            isin="",
            ticker="GCB",
            fiscal_year=2022,
        )
        assert path is None

        # But build_staging_path should work
        staging = build_staging_path(
            staging_root=root,
            country_iso3="GHA",
            exchange_mic="XGHA",
            ticker="GCB",
            fiscal_year=2022,
        )
        assert "unresolved_identity" in staging.parts
        assert "GHA" in staging.parts
        assert "XGHA" in staging.parts
        assert "GCB_FY2022" in staging.parts
