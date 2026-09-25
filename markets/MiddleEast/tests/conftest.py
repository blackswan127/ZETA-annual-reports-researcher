import pytest
from pathlib import Path
from pypdf import PdfWriter


@pytest.fixture
def dummy_pdf_generator(tmp_path):
    def _create(name="test.pdf", pages=2, min_bytes=40000):
        p = tmp_path / name
        w = PdfWriter()
        for _ in range(pages):
            w.add_blank_page(width=300, height=300)
        p.parent.mkdir(parents=True, exist_ok=True)
        with open(p, "wb") as f:
            w.write(f)
        # Pad with PDF comment to exceed min_bytes if needed
        curr_sz = p.stat().st_size
        if curr_sz < min_bytes:
            with open(p, "ab") as f:
                f.write(b"\n% " + b"X" * (min_bytes - curr_sz) + b"\n")
        return p
    return _create


@pytest.fixture
def dummy_pdf_bytes(dummy_pdf_generator):
    p = dummy_pdf_generator("sample.pdf", pages=2, min_bytes=40000)
    return p.read_bytes()
