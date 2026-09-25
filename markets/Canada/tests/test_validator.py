from pypdf import PdfWriter
from canada_zeta_bulk.validator import validate_pdf

def test_valid_pdf(tmp_path):
    p=tmp_path/"a.pdf"; w=PdfWriter()
    for _ in range(6): w.add_blank_page(width=612,height=792)
    with p.open("wb") as f: w.write(f)
    v=validate_pdf(p,2024,min_bytes=100,min_pages=5)
    assert v.status=="PASS" and v.pages==6 and len(v.sha256)==64

def test_html_rejected(tmp_path):
    p=tmp_path/"a.pdf"; p.write_text("<html>bad</html>")
    assert validate_pdf(p,2024,min_bytes=1,min_pages=1).status=="FAIL"
