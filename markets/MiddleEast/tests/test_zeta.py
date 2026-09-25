from __future__ import annotations

import tempfile
from pathlib import Path
import pytest

from me_ar_bulk.zeta import (
    build_final_path,
    build_staging_path,
    is_valid_isin,
    is_valid_lei,
    promote_part_file,
    sanitize_token,
)


def test_sanitize_token():
    assert sanitize_token("BKMB") == "BKMB"
    assert sanitize_token("EMAAR/N") == "EMAARN"
    assert sanitize_token("2222:SA") == "2222SA"
    assert sanitize_token("  saudi  ") == "saudi"


def test_lei_isin_validation():
    # Valid 20-char LEI and 12-char ISIN
    assert is_valid_lei("549300H4Y0C0R46L4A57") is True
    assert is_valid_lei("invalid_short") is False
    assert is_valid_isin("OM0000001004") is True
    assert is_valid_isin("SA14TG012N13") is True
    assert is_valid_isin("BAD_ISIN") is False


def test_build_final_path_valid():
    with tempfile.TemporaryDirectory() as tmpdir:
        root = Path(tmpdir)
        path = build_final_path(
            zeta_root=root,
            iso3="OMN",
            mic="XMUS",
            lei="549300H4Y0C0R46L4A57",
            isin="OM0000001004",
            ticker="BKMB",
            fiscal_year=2023,
            lang="EN",
            report_type="AR",
        )
        assert path is not None
        assert "OMN" in path.parts
        assert "XMUS" in path.parts
        assert "549300H4Y0C0R46L4A57_OM0000001004_BKMB" in path.parts
        assert "FY2023" in path.parts
        assert path.name == "549300H4Y0C0R46L4A57_OMN_XMUS_BKMB_OM0000001004_FY2023_AR_EN.pdf"


def test_build_final_path_unresolved():
    with tempfile.TemporaryDirectory() as tmpdir:
        root = Path(tmpdir)
        # Missing LEI and ISIN -> build_final_path must return None
        path = build_final_path(
            zeta_root=root,
            iso3="JOR",
            mic="XAMM",
            lei="",
            isin="",
            ticker="ARBK",
            fiscal_year=2022,
        )
        assert path is None

        # But build_staging_path succeeds in local staging
        staging = build_staging_path(
            staging_root=root,
            iso3="JOR",
            mic="XAMM",
            ticker="ARBK",
            fiscal_year=2022,
        )
        assert "unresolved_identity" in staging.parts
        assert "JOR" in staging.parts
        assert "XAMM" in staging.parts
        assert "ARBK_FY2022" in staging.parts


def test_promote_part_file():
    with tempfile.TemporaryDirectory() as tmpdir:
        dest = Path(tmpdir) / "final" / "report.pdf"
        part = dest.with_suffix(".pdf.part")
        part.parent.mkdir(parents=True, exist_ok=True)
        part.write_bytes(b"%PDF-1.4 test")

        assert not dest.exists()
        assert part.exists()

        promote_part_file(part, dest)
        assert dest.exists()
        assert not part.exists()
        assert dest.read_bytes() == b"%PDF-1.4 test"
