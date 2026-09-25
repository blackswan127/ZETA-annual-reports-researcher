import asyncio
import json
from pathlib import Path
import httpx

from sgx_bulk.sgx import SGXSource, STOCKS_URL, METADATA_URL, CORPORATE_INFO_URL

FIX = Path(__file__).parent / "fixtures"


class FakeHTTP:
    async def request(self, method, url, **kwargs):
        if url == STOCKS_URL:
            payload = json.loads((FIX / "stocks.json").read_text())
        elif url == METADATA_URL:
            payload = json.loads((FIX / "metadata.json").read_text())
        elif url == CORPORATE_INFO_URL:
            payload = json.loads((FIX / "corporate_information.json").read_text())
        else:
            raise AssertionError(url)
        return httpx.Response(200, json=payload, request=httpx.Request(method, url))


def test_current_issuer_filtering():
    async def run():
        src = SGXSource(FakeHTTP())
        return await src.current_issuers()
    issuers = asyncio.run(run())
    assert {x.ibm_code for x in issuers} == {"1D05", "1ETF", "1J26", "2D63"}
    sample_reit = next(x for x in issuers if x.ibm_code == "2D63")
    assert sample_reit.issuer_name == "SAMPLE REIT"
    assert sample_reit.stock_code == sample_reit.ibm_code
    assert sample_reit.ticker == ""
    assert all(x.market == "MAINBOARD" for x in issuers)
