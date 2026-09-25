import pytest, httpx
from canada_zeta_bulk.downloader import Downloader

@pytest.mark.asyncio
async def test_downloader_rejects_html(tmp_path):
    def handler(req): return httpx.Response(200,text="<html>no</html>",headers={"content-type":"text/html"})
    d=Downloader(workers=1,rps=100,retries=1)
    await d.client.aclose(); d.client=httpx.AsyncClient(transport=httpx.MockTransport(handler),follow_redirects=True)
    with pytest.raises(RuntimeError): await d.download("https://x/report.pdf",tmp_path/"r.pdf")
    await d.close()

@pytest.mark.asyncio
async def test_downloader_writes_pdf(tmp_path):
    payload=b"%PDF-1.4\n"+b"x"*100
    def handler(req): return httpx.Response(200,content=payload,headers={"content-type":"application/pdf"})
    d=Downloader(workers=1,rps=100,retries=1)
    await d.client.aclose(); d.client=httpx.AsyncClient(transport=httpx.MockTransport(handler),follow_redirects=True)
    p=tmp_path/"r.pdf"; await d.download("https://x/report.pdf",p); await d.close()
    assert p.read_bytes()==payload and not (tmp_path/"r.pdf.part").exists()

@pytest.mark.asyncio
async def test_downloader_accepts_local_file_uri(tmp_path):
    src=tmp_path/'licensed.pdf'; src.write_bytes(b'%PDF-1.4\n'+b'z'*100)
    d=Downloader(workers=1,rps=100,retries=1)
    dest=tmp_path/'copy.pdf'
    await d.download(src.resolve().as_uri(),dest); await d.close()
    assert dest.read_bytes()==src.read_bytes()
