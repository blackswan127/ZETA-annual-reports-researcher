import asyncio
import json
import httpx
from asx_bulk.source import ASXSource
import pytest


def test_current_universe_from_directory_json():
    async def run():
        src = ASXSource(metadata_rps=100)
        async def fake_get(url, *, params=None):
            payload = {"data": {"items": [
                {"symbol": "BHP", "displayName": "BHP GROUP LIMITED", "sector": "Materials"},
                {"symbol": "CBA", "displayName": "COMMONWEALTH BANK OF AUSTRALIA", "sector": "Financials"},
            ] * 300}}
            req = httpx.Request("GET", url)
            return httpx.Response(200, request=req, content=json.dumps(payload).encode(), headers={"content-type":"application/json"})
        src._get = fake_get
        issuers = await src.current_issuers()
        await src.close()
        assert {i.ticker for i in issuers} == {"BHP", "CBA"}
    asyncio.run(run())

def test_final_retryable_http_status_is_reported():
    async def run():
        src = ASXSource(retries=1, metadata_rps=100)
        await src.client.aclose()
        src.client = httpx.AsyncClient(transport=httpx.MockTransport(
            lambda request: httpx.Response(429, request=request)
        ))
        try:
            with pytest.raises(RuntimeError, match="429") as exc:
                await src._get("https://example.test/rate-limited")
            assert "None" not in str(exc.value)
        finally:
            await src.close()
    asyncio.run(run())
