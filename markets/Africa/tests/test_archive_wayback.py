from __future__ import annotations

import pytest
from africa_ar_bulk.models import Issuer
from africa_ar_bulk.sources.archive_wayback import WaybackArchiveAdapter


@pytest.mark.asyncio
async def test_wayback_archive_adapter_empty_source():
    adapter = WaybackArchiveAdapter()
    issuer = Issuer(
        issuer_id="ZWE:XZIM:CBZ",
        country_iso3="ZWE",
        exchange_mic="XZIM",
        ticker="CBZ",
        company_name="CBZ Holdings Limited",
        source_url="",
    )
    cands = await adapter.discover_candidates(issuer, 2017, 2021)
    assert cands == []
    await adapter.close()


@pytest.mark.asyncio
async def test_wayback_archive_adapter_domain_parsing():
    adapter = WaybackArchiveAdapter(timeout=2.0)
    issuer = Issuer(
        issuer_id="ZWE:XZIM:CBZ",
        country_iso3="ZWE",
        exchange_mic="XZIM",
        ticker="CBZ",
        company_name="CBZ Holdings Limited",
        source_url="https://www.cbz.co.zw/investor-relations/",
    )
    # Testing with short timeout to ensure graceful non-blocking return on timeout
    cands = await adapter.discover_candidates(issuer, 2017, 2021)
    assert isinstance(cands, list)
    await adapter.close()
