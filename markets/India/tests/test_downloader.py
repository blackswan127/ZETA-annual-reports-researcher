import io,zipfile
import httpx,pytest
from india_ar_bulk.downloader import ArtifactDownloader

@pytest.mark.asyncio
async def test_pdf_download(tmp_path):
    async def handler(req): return httpx.Response(200,headers={'content-type':'application/pdf'},content=b'%PDF-1.4\nabc')
    c=httpx.AsyncClient(transport=httpx.MockTransport(handler)); d=ArtifactDownloader(client=c,retries=1)
    p,size,h,parts=await d.fetch('https://x/a.pdf',tmp_path/'a.pdf','PDF'); assert p.read_bytes().startswith(b'%PDF-') and parts==0; await c.aclose()

@pytest.mark.asyncio
async def test_resume_range(tmp_path):
    content=b'%PDF-1.4\n'+b'x'*100; calls=[]
    async def handler(req):
        calls.append(req.headers.get('range'))
        if req.headers.get('range'):
            off=int(req.headers['range'].split('=')[1].split('-')[0]); return httpx.Response(206,content=content[off:],headers={'content-type':'application/pdf'})
        return httpx.Response(200,content=content,headers={'content-type':'application/pdf'})
    part=tmp_path/'a.pdf.part'; part.write_bytes(content[:20])
    c=httpx.AsyncClient(transport=httpx.MockTransport(handler)); d=ArtifactDownloader(client=c,retries=1)
    p,_,_,_=await d.fetch('https://x/a.pdf',tmp_path/'a.pdf','PDF'); assert p.read_bytes()==content and calls[0]=='bytes=20-'; await c.aclose()

@pytest.mark.asyncio
async def test_zip_extracts_largest_pdf_and_keeps_parts(tmp_path):
    bio=io.BytesIO()
    with zipfile.ZipFile(bio,'w') as z:
        z.writestr('../evil.pdf',b'%PDF-1.4\nsmall')
        z.writestr('Annual Report.pdf',b'%PDF-1.4\n'+b'A'*100)
    async def handler(req): return httpx.Response(200,content=bio.getvalue(),headers={'content-type':'application/zip'})
    c=httpx.AsyncClient(transport=httpx.MockTransport(handler)); d=ArtifactDownloader(client=c,retries=1)
    p,_,_,parts=await d.fetch('https://x/a.zip',tmp_path/'main.pdf','ZIP'); assert parts==2 and p.read_bytes().endswith(b'A'*100); assert not (tmp_path.parent/'evil.pdf').exists(); await c.aclose()

@pytest.mark.asyncio
async def test_html_rejected(tmp_path):
    async def handler(req): return httpx.Response(200,content=b'<html>x</html>',headers={'content-type':'text/html'})
    c=httpx.AsyncClient(transport=httpx.MockTransport(handler)); d=ArtifactDownloader(client=c,retries=1)
    with pytest.raises(RuntimeError): await d.fetch('https://x/a.pdf',tmp_path/'a.pdf','PDF')
    await c.aclose()
