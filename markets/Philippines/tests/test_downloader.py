import fitz
import pytest
from pathlib import Path

from phl_pse_bulk.downloader import (
    build_zeta_destination_path,
    compute_sha256_and_size,
    validate_pdf_file,
)


def create_minimal_pdf(path: Path, page_text: str = "Philippine Stock Exchange Annual Report"):
    doc = fitz.open()
    page = doc.new_page()
    page.insert_text((50, 72), page_text)
    doc.save(str(path))
    doc.close()


def test_validate_pdf_file(tmp_path: Path):
    pdf_path = tmp_path / "valid.pdf"
    create_minimal_pdf(pdf_path)

    valid, pages, msg = validate_pdf_file(pdf_path)
    assert valid is True
    assert pages >= 1
    assert msg == "OK"

    # Corrupt / text file
    txt_path = tmp_path / "fake.pdf"
    txt_path.write_bytes(b"Not a PDF file content")
    v2, p2, msg2 = validate_pdf_file(txt_path)
    assert v2 is False


def test_build_zeta_destination_path(tmp_path: Path):
    p = build_zeta_destination_path(
        output_root=tmp_path,
        iso3="PHL",
        mic="XPHS",
        ticker="AC",
        fiscal_year=2024,
        lei="549300VLM6N2CPL1N479",
        isin="PHY0488V1004",
        report_type="AR",
        lang="EN",
    )
    expected_rel = Path("PHL/XPHS/549300VLM6N2CPL1N479/PHY0488V1004/AC/FY2024/549300VLM6N2CPL1N479_PHL_XPHS_AC_PHY0488V1004_FY2024_AR_EN.pdf")
    assert p == tmp_path / expected_rel


def test_compute_sha256_and_size(tmp_path: Path):
    test_file = tmp_path / "sample.bin"
    test_file.write_bytes(b"Sample payload for SHA-256 computation")
    h, sz = compute_sha256_and_size(test_file)
    assert len(h) == 64
    assert sz == len(b"Sample payload for SHA-256 computation")
