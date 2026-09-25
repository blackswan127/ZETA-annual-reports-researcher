from __future__ import annotations

import pytest
from africa_ar_bulk.models import Issuer
from africa_ar_bulk.sources.exchange_direct import DirectExchangeAdapter


SAMPLE_EXCHANGE_HTML = """
<html>
<body>
    <div class="financial-reports">
        <h2>Company Filings</h2>
        <ul>
            <li><a href="/filings/cec-ar-2023.pdf">Copperbelt Energy Corporation Annual Report 2023</a></li>
            <li><a href="/filings/cec-sustainability-2023.pdf">Copperbelt Energy Corporation Sustainability Report 2023</a></li>
            <li><a href="/filings/cec-ar-2022.pdf">Integrated Annual Report 2022</a></li>
            <li><a href="/filings/cec-q1-2024.pdf">Quarterly Report Q1 2024</a></li>
        </ul>
    </div>
</body>
</html>
"""


def test_exchange_direct_pdf_extraction():
    adapter = DirectExchangeAdapter()
    issuer = Issuer(
        issuer_id="ZMB:XLUS:CEC",
        country_iso3="ZMB",
        exchange_mic="XLUS",
        ticker="CEC",
        company_name="Copperbelt Energy Corporation Plc",
        isin="ZM0000000136",
    )
    candidates = adapter._extract_pdf_candidates(
        SAMPLE_EXCHANGE_HTML,
        base_url="https://luse.co.zm/annual-reports/",
        issuer=issuer,
        start_year=2017,
        end_year=2025,
        source_name="LUSE_ZAMBIA_DIRECT",
    )

    # 3 valid candidates: 2 AR (2022, 2023), 1 SR (2023). Q1 2024 excluded.
    assert len(candidates) == 3

    labels = {c.classification for c in candidates}
    assert labels == {"AR", "SR"}

    fys = {c.resolved_fy for c in candidates}
    assert fys == {2022, 2023}
