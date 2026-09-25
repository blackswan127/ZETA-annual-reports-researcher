import hashlib, os, shutil
from pathlib import Path
from pypdf import PdfReader
from .naming import final_path, identity_complete

def validate_pdf(path:Path,min_bytes=8000):
    if not path.exists() or path.stat().st_size<min_bytes: return False,"too-small"
    with path.open("rb") as f:
        if f.read(5)!=b"%PDF-": return False,"bad-signature"
    try:
        r=PdfReader(str(path)); n=len(r.pages)
        if n<2: return False,"too-few-pages"
    except Exception as e: return False,f"pdf-parse:{e}"
    return True,"ok"

def sha256(path:Path):
    h=hashlib.sha256()
    with path.open("rb") as f:
        for b in iter(lambda:f.read(1024*1024),b""): h.update(b)
    return h.hexdigest()

def _copy_local(src:Path,dst_part:Path):
    with src.open("rb") as s, dst_part.open("wb") as d: shutil.copyfileobj(s,d,1024*1024)

def fetch_candidate(http,row,zeta_root:Path,staging_root:Path,min_bytes=8000):
    ticker=row["ticker"]; fy=row["fiscal_year"]; url=row["url"]
    complete=identity_complete(row["lei"],row["isin"],ticker)
    if complete:
        target=final_path(Path(zeta_root),row["lei"],row["isin"],ticker,fy)
    else:
        target=Path(staging_root)/"unresolved_identity"/ticker/f"FY{fy}"/f"{ticker}_FY{fy}_AR_EN.pdf"
    target.parent.mkdir(parents=True,exist_ok=True); part=target.with_suffix(target.suffix+".part")
    if target.exists():
        ok,_=validate_pdf(target,min_bytes)
        if ok:return target,sha256(target),target.stat().st_size,complete
    if os.path.exists(url):
        _copy_local(Path(url),part)
    else:
        offset=part.stat().st_size if part.exists() else 0
        headers={"Range":f"bytes={offset}-"} if offset else {}
        r=http.get(url,headers=headers,stream=True)
        if offset and r.status_code!=206:
            part.unlink(missing_ok=True); offset=0
            r=http.get(url,stream=True)
        mode="ab" if offset and r.status_code==206 else "wb"
        with part.open(mode) as f:
            for chunk in r.iter_content(1024*1024):
                if chunk:f.write(chunk)
    ok,why=validate_pdf(part,min_bytes)
    if not ok: raise RuntimeError(why)
    os.replace(part,target)
    return target,sha256(target),target.stat().st_size,complete
