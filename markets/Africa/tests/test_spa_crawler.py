from __future__ import annotations

import pytest
from africa_ar_bulk.models import Issuer
from africa_ar_bulk.sources.spa_crawler import DynamicSPACrawler, get_chrome_executable


def test_chrome_executable_discovery():
    chrome = get_chrome_executable()
    # On this machine Chrome or Edge is installed
    assert chrome is not None
    assert "chrome.exe" in chrome.lower() or "msedge.exe" in chrome.lower()


@pytest.mark.asyncio
async def test_spa_crawler_empty_when_no_executable():
    crawler = DynamicSPACrawler()
    issuer = Issuer(
        issuer_id="ZAF:XJSE:TEST",
        country_iso3="ZAF",
        exchange_mic="XJSE",
        ticker="TEST",
        company_name="Test Company Limited",
    )
    # Invalid target URL
    cands = await crawler.extract_dynamic_candidates(issuer, "http://localhost:59999/not_found", 2020, 2023)
    assert cands == []
    await crawler.close()
