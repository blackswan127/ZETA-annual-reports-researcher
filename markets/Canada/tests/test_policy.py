from pathlib import Path

def test_no_public_sedar_scraper_module():
    root=Path(__file__).resolve().parents[1]/"src"/"canada_zeta_bulk"
    text="\n".join(p.read_text(encoding="utf-8") for p in root.glob("*.py"))
    assert "sedarplus.ca/csa-party" not in text
    assert "scrape_sedar" not in text
