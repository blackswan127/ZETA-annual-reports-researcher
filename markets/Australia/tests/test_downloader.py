import asyncio
from pathlib import Path
import httpx
from asx_bulk.downloader import PDFDownloader

PDF = b"%PDF-1.7\n" + b"x" * 5000

def test_download_pdf_and_resume(tmp_path: Path):
    calls=[]
    def handler(request: httpx.Request):
        rng=request.headers.get("range")
        calls.append(rng)
        if rng:
            start=int(rng.split("=")[1].split("-")[0])
            return httpx.Response(206, content=PDF[start:], headers={"content-type":"application/pdf","content-range":f"bytes {start}-{len(PDF)-1}/{len(PDF)}"})
        return httpx.Response(200, content=PDF, headers={"content-type":"application/pdf"})
    async def run():
        dl=PDFDownloader(workers=1,rps=100,retries=2)
        await dl.client.aclose()
        dl.client=httpx.AsyncClient(transport=httpx.MockTransport(handler))
        dest=tmp_path/"a.pdf"
        part=dest.with_suffix(".pdf.part")
        part.write_bytes(PDF[:1000])
        size,digest=await dl.download("https://example.test/a.pdf",dest)
        await dl.close()
        assert size==len(PDF)
        assert dest.read_bytes()==PDF
        assert calls[0]=="bytes=1000-"
        assert len(digest)==64
    asyncio.run(run())

def test_download_rejects_html(tmp_path: Path):
    def handler(request: httpx.Request):
        return httpx.Response(200, content=b"<html>no</html>", headers={"content-type":"text/html"})
    async def run():
        dl=PDFDownloader(workers=1,rps=100,retries=1)
        await dl.client.aclose()
        dl.client=httpx.AsyncClient(transport=httpx.MockTransport(handler))
        try:
            await dl.download("https://example.test/a.pdf",tmp_path/"x.pdf")
        except RuntimeError as e:
            assert "HTML" in str(e) or "failed" in str(e)
        else:
            raise AssertionError("expected failure")
        await dl.close()
    asyncio.run(run())

def test_incomplete_range_response_is_resumed_before_commit(tmp_path: Path):
    calls=[]
    def handler(request: httpx.Request):
        rng=request.headers.get("range")
        start=int(rng.split("=")[1].split("-")[0]) if rng else 0
        calls.append(start)
        end=min(start+999,len(PDF)-1)
        return httpx.Response(206, content=PDF[start:end+1], headers={
            "content-type":"application/pdf",
            "content-range":f"bytes {start}-{end}/{len(PDF)}",
        })
    async def run():
        dl=PDFDownloader(workers=1,rps=100,retries=6)
        await dl.client.aclose()
        dl.client=httpx.AsyncClient(transport=httpx.MockTransport(handler))
        dest=tmp_path/"complete.pdf"
        size,_=await dl.download("https://example.test/complete.pdf",dest)
        await dl.close()
        assert size==len(PDF)
        assert dest.read_bytes()==PDF
        assert calls==[0,1000,2000,3000,4000,5000]
    asyncio.run(run())

def test_416_only_commits_partial_when_server_confirms_exact_size(tmp_path: Path):
    calls=[]
    def handler(request: httpx.Request):
        rng=request.headers.get("range")
        calls.append(rng)
        if rng:
            return httpx.Response(416, headers={"content-range":f"bytes */{len(PDF)}"})
        return httpx.Response(200, content=PDF, headers={"content-type":"application/pdf"})
    async def run():
        dl=PDFDownloader(workers=1,rps=100,retries=2)
        await dl.client.aclose()
        dl.client=httpx.AsyncClient(transport=httpx.MockTransport(handler))
        dest=tmp_path/"recovered.pdf"
        dest.with_suffix(".pdf.part").write_bytes(PDF[:1000])
        size,_=await dl.download("https://example.test/recovered.pdf",dest)
        await dl.close()
        assert size==len(PDF)
        assert dest.read_bytes()==PDF
        assert calls==["bytes=1000-",None]
    asyncio.run(run())
