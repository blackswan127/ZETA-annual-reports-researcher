from pathlib import Path
import json

from sgx_bulk.htmlparse import safe_pdf_links, attachment_score, announcement_id_from_url
from sgx_bulk.models import Issuer
from sgx_bulk.sgx import SGXSource
from sgx_bulk.util import normalize_name, safe_component

FIX = Path(__file__).parent / "fixtures"


def test_normalize_name():
    assert normalize_name("DBS Group Holdings Ltd.") == "dbsgroupholdingsltd"


def test_safe_filename_windows_chars():
    assert ":" not in safe_component('A:B?C*.pdf')


def test_attachment_parser_and_scoring():
    html = (FIX / "detail.html").read_text()
    url = "https://links.sgx.com/1.0.0/corporate-announcements/2J4PCEOQYA3WTBWP/aaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaa"
    links = safe_pdf_links(html, url)
    assert len(links) == 2
    scores = {name: attachment_score(name, 2025) for _, name in links}
    assert scores["859054_2025_SGX_Annual_Report.pdf"] > scores["859055_2025_SGX_Sustainability_Report.pdf"]


def test_announcement_id():
    u = "https://links.sgx.com/1.0.0/corporate-announcements/2J4PCEOQYA3WTBWP/hash"
    assert announcement_id_from_url(u) == "2J4PCEOQYA3WTBWP"


def test_report_mapping():
    reports = json.loads((FIX / "reports.json").read_text())["data"]
    issuer = Issuer("1J26", "S68", "SINGAPORE EXCHANGE LIMITED", "SGX", "MAINBOARD")
    idx = SGXSource.issuer_alias_index([issuer])
    mapped, reason = SGXSource.map_row(reports[0], idx)
    assert mapped == issuer
    assert reason == "companyName"
    filing = SGXSource.filing_from_row(reports[0], issuer)
    assert filing is not None
    assert filing.announcement_id == "2J4PCEOQYA3WTBWP"
    assert filing.fiscal_year == 2025


def test_non_annual_rejected():
    reports = json.loads((FIX / "reports.json").read_text())["data"]
    assert not SGXSource.is_annual(reports[1])
