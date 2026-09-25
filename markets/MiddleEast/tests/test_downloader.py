from __future__ import annotations

import tempfile
from pathlib import Path
import pytest

from me_ar_bulk.downloader import Downloader, sha256_file


def test_sha256_file(tmp_path: Path):
    f = tmp_path / "sample.txt"
    f.write_bytes(b"middle east annual reports test content")
    digest = sha256_file(f)
    assert len(digest) == 64
    assert isinstance(digest, str)


def test_validate_pdf_valid(dummy_pdf_bytes):
    with tempfile.TemporaryDirectory() as tmpdir:
        pdf_path = Path(tmpdir) / "valid.pdf"
        pdf_path.write_bytes(dummy_pdf_bytes)

        valid, pages, msg = Downloader.validate_pdf(pdf_path, min_bytes=1000)
        assert valid is True
        assert pages >= 1
        assert msg == "OK"


def test_validate_pdf_invalid_header(tmp_path: Path):
    bad_pdf = tmp_path / "corrupt.pdf"
    bad_pdf.write_bytes(b"<html>Not a PDF file</html>" * 200)

    valid, pages, msg = Downloader.validate_pdf(bad_pdf, min_bytes=100)
    assert valid is False
    assert "Missing '%PDF-'" in msg


def test_validate_pdf_too_small(tmp_path: Path):
    small_pdf = tmp_path / "small.pdf"
    small_pdf.write_bytes(b"%PDF-1.4 header only")

    valid, pages, msg = Downloader.validate_pdf(small_pdf, min_bytes=35000)
    assert valid is False
    assert "below minimum" in msg
