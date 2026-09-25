import asyncio
from pathlib import Path

import httpx

from sgx_bulk.downloader import PDFDownloader


class FakeDB:
    def __init__(self):
        self.calls = []

    def mark_download(self, url, **kwargs):
        self.calls.append((url, kwargs))


class FakeHTTP:
    def __init__(self, handler, retries=2):
        self.retries = retries
        self.client = httpx.AsyncClient(transport=httpx.MockTransport(handler))

    async def close(self):
        await self.client.aclose()


def row(filename="annual.pdf"):
    return {
        "url": "https://links.sgx.com/1.0.0/corporate-announcements/ABCDEFGHIJKLMNOP/1_annual.pdf",
        "stock_code": "S68",
        "issuer_name": "Singapore Exchange Limited",
        "fiscal_year": 2025,
        "filename": filename,
    }


def test_stream_download_retries_429_then_succeeds(tmp_path: Path):
    calls = {"n": 0}
    pdf = b"%PDF-1.4\n" + b"x" * 2048

    def handler(request):
        calls["n"] += 1
        if calls["n"] == 1:
            return httpx.Response(429, headers={"Retry-After": "0"}, request=request)
        return httpx.Response(200, content=pdf, request=request)

    async def run():
        db = FakeDB()
        http = FakeHTTP(handler)
        d = PDFDownloader(http, db, tmp_path, workers=1)
        ok, msg = await d.download_row(row())
        await http.close()
        return db, ok, msg

    db, ok, _ = asyncio.run(run())
    assert ok is True
    assert calls["n"] == 2
    target = next(tmp_path.rglob("annual.pdf"))
    assert target.read_bytes() == pdf
    assert db.calls[-1][1]["status"] == "done"


def test_resume_partial_pdf_with_range(tmp_path: Path):
    pdf = b"%PDF-1.7\n" + b"abcdef" * 500
    cut = 700
    seen_range = []

    def handler(request):
        seen_range.append(request.headers.get("Range"))
        return httpx.Response(206, content=pdf[cut:], request=request)

    async def run():
        db = FakeDB()
        http = FakeHTTP(handler)
        d = PDFDownloader(http, db, tmp_path, workers=1)
        target = d._target(row("resume.pdf"))
        target.parent.mkdir(parents=True, exist_ok=True)
        Path(str(target) + ".part").write_bytes(pdf[:cut])
        ok, msg = await d.download_row(row("resume.pdf"))
        await http.close()
        return target, ok, msg

    target, ok, msg = asyncio.run(run())
    assert ok is True
    assert "resumed" in msg
    assert seen_range == [f"bytes={cut}-"]
    assert target.read_bytes() == pdf


def test_rejects_non_pdf_attachment(tmp_path: Path):
    def handler(request):
        return httpx.Response(200, content=b"<html>not a pdf</html>", request=request)

    async def run():
        db = FakeDB()
        http = FakeHTTP(handler, retries=0)
        d = PDFDownloader(http, db, tmp_path, workers=1)
        ok, msg = await d.download_row(row("bad.pdf"))
        await http.close()
        return db, ok, msg

    db, ok, msg = asyncio.run(run())
    assert ok is False
    assert "not a PDF" in msg
    assert db.calls[-1][1]["status"] == "failed"
