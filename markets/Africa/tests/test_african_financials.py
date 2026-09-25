from __future__ import annotations

import pytest
from africa_ar_bulk.models import Issuer
from africa_ar_bulk.sources.african_financials import AfricanFinancialsAdapter


SAMPLE_HTML = """
<html>
<body>
    <div class="company-reports">
        <h2>Financial Reports & Filings</h2>
        <ul>
            <li><a href="/docs/npn-integrated-annual-report-2023.pdf">Naspers Integrated Annual Report 2023</a></li>
            <li><a href="/docs/npn-sustainability-report-2023.pdf">Naspers Sustainability Report 2023</a></li>
            <li><a href="/docs/npn-annual-report-2022.pdf">Annual Report and Accounts 2022</a></li>
            <li><a href="/docs/npn-esg-report-2022.pdf">ESG and Climate Report 2022</a></li>
            <li><a href="/docs/npn-interim-results-h1-2023.pdf">Interim Results Six Months Ended June 2023</a></li>
            <li><a href="/docs/npn-agm-notice-2023.pdf">Notice of Annual General Meeting 2023</a></li>
        </ul>
    </div>
</body>
</html>
"""


def test_african_financials_html_extraction():
    adapter = AfricanFinancialsAdapter()
    issuer = Issuer(
        issuer_id="ZAF:XJSE:NPN",
        country_iso3="ZAF",
        exchange_mic="XJSE",
        ticker="NPN",
        company_name="Naspers Limited",
        isin="ZAE000015889",
        lei="213800COVT3N6B3Q5O74",
    )
    candidates = adapter.extract_candidates_from_html(
        SAMPLE_HTML,
        base_url="https://africanfinancials.com/company/za-npn/",
        issuer=issuer,
        start_year=2017,
        end_year=2025,
    )

    # Should extract 4 valid documents (2 AR, 2 SR); the interim and AGM notice must be excluded
    assert len(candidates) == 4

    cands_by_type = {}
    for c in candidates:
        cands_by_type.setdefault(c.classification, []).append(c)

    assert "AR" in cands_by_type
    assert "SR" in cands_by_type
    assert len(cands_by_type["AR"]) == 2
    assert len(cands_by_type["SR"]) == 2

    # Check years
    ar_fys = {c.resolved_fy for c in cands_by_type["AR"]}
    sr_fys = {c.resolved_fy for c in cands_by_type["SR"]}
    assert ar_fys == {2022, 2023}
    assert sr_fys == {2022, 2023}
