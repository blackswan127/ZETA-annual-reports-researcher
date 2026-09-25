import pytest, httpx
from canada_zeta_bulk.issuer_sites import IssuerSiteCrawler
from canada_zeta_bulk.models import Issuer

@pytest.mark.asyncio
async def test_issuer_site_extracts_annual_pdf(monkeypatch):
    html='''<html><body><a href="/docs/annual-report-2024.pdf">2024 Annual Report</a><a href="/docs/sustainability-2024.pdf">2024 Sustainability Report</a></body></html>'''
    def handler(req):
        if req.url.path=="/robots.txt": return httpx.Response(404)
        return httpx.Response(200,text=html,headers={"content-type":"text/html"})
    c=IssuerSiteCrawler(max_pages=1,obey_robots=False)
    await c.client.aclose(); c.client=httpx.AsyncClient(transport=httpx.MockTransport(handler),follow_redirects=True)
    issuer=Issuer("XTSE:ABC","ABC Corp","ABC","XTSE",website="https://example.com")
    try: out=await c.discover(issuer,2017,2025)
    finally: await c.close()
    assert len(out)==1 and out[0].fiscal_year==2024
