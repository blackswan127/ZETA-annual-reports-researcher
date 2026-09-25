from pathlib import Path
from asx_bulk.parser import parse_announcements_html, parse_pdf_url

FIX = Path(__file__).parent / "fixtures"

def test_parse_announcement_page():
    html = (FIX / "announcements.html").read_text()
    rows = parse_announcements_html(html, "AHN", 2025)
    assert len(rows) == 1
    first = rows[0]
    assert first.announcement_id == "02999901"
    assert first.fiscal_year == 2025
    assert first.pages == 56
    assert first.display_url.startswith("https://www.asx.com.au/")

def test_parse_pdf_url():
    html = (FIX / "display.html").read_text()
    assert parse_pdf_url(html) == "https://www.asx.com.au/asxpdf/20250930/pdf/abc123.pdf"
