import os, re, hashlib
from urllib.parse import urljoin
from bs4 import BeautifulSoup
from ..models import Issuer, Candidate
from ..classify import annual_report_score, infer_fiscal_year

BASE="https://www.nzx.com"

def require_terms_ack():
    if os.environ.get("NZX_ACKNOWLEDGE_TERMS") != "1":
        raise RuntimeError("NZX public-site access is disabled until NZX_ACKNOWLEDGE_TERMS=1 is explicitly set after reviewing NZX terms/licensing for your use.")

def parse_market_page(html:str):
    soup=BeautifulSoup(html,"html.parser")
    out=[]
    for tr in soup.find_all("tr"):
        cells=[c.get_text(" ",strip=True) for c in tr.find_all(["td","th"])]
        if len(cells)>=2:
            code=cells[0].strip().upper()
            if re.fullmatch(r"[A-Z0-9]{2,8}",code) and code not in {"CODE"}:
                out.append((code,cells[1].strip()))
    if not out:
        # fallback for rendered/text-ish markup
        for a in soup.find_all("a",href=re.compile(r"/companies/[A-Z0-9]+$")):
            code=a.get("href","").rstrip("/").split("/")[-1].upper()
            name=a.get_text(" ",strip=True)
            if code and name: out.append((code,name))
    seen=set(); ded=[]
    for x in out:
        if x[0] not in seen: seen.add(x[0]); ded.append(x)
    return ded

def parse_company_page(html:str, ticker:str, fallback_name="") -> Issuer:
    soup=BeautifulSoup(html,"html.parser")
    text=soup.get_text(" ",strip=True)
    h1=soup.find("h1")
    name=h1.get_text(" ",strip=True) if h1 else fallback_name
    isin=""; typ=""; venue=""; fye=""; website=""
    m=re.search(r"ISIN:\s*([A-Z0-9]{12})",text,re.I); isin=m.group(1).upper() if m else ""
    m=re.search(r"Type:\s*([^|]{2,80}?)(?:52 Week|Price|Maturity|About Company)",text,re.I); typ=m.group(1).strip() if m else ""
    m=re.search(r"Primary Listing Venue\s*[:|]?\s*([A-Za-z ]{2,20})",text,re.I); venue=m.group(1).strip() if m else ""
    m=re.search(r"End of Financial Year\s*[:|]?\s*([A-Za-z]+)",text,re.I); fye=m.group(1).strip() if m else ""
    for a in soup.find_all("a",href=True):
        href=a["href"]
        if href.startswith("http") and "nzx.com" not in href and not website: website=href
    return Issuer(ticker=ticker,name=name,isin=isin,website=website,instrument_type=typ,primary_listing_venue=venue,fiscal_year_end=fye)

def is_equity_issuer(i:Issuer) -> bool:
    t=i.instrument_type.lower()
    if any(x in t for x in ["bond","note","fund","etf","warrant","option","debt"]): return False
    return ("ordinary" in t or "share" in t or not t)

def parse_documents_page(html:str,ticker:str,start=2017,end=2025):
    soup=BeautifulSoup(html,"html.parser"); out=[]
    for a in soup.find_all("a",href=True):
        title=a.get_text(" ",strip=True)
        score=annual_report_score(title)
        if score < 5: continue
        fy,why=infer_fiscal_year(title)
        if fy and start<=fy<=end:
            out.append(Candidate(ticker=ticker,fiscal_year=fy,title=title,url=urljoin(BASE,a["href"]),source="NZX_DOCUMENTS",confidence=score+2))
    return out

def parse_announcement_page(html:str,ticker:str,source="NZX_ANNREP"):
    soup=BeautifulSoup(html,"html.parser"); text=soup.get_text(" ",strip=True)
    title=""
    h=soup.find(["h1","h2","h3"]); title=h.get_text(" ",strip=True) if h else ""
    typ="ANNREP" if re.search(r"\bANNREP\b",text) else ""
    score=annual_report_score(title,typ,text)
    if score < 5: return []
    fy,why=infer_fiscal_year(title,text)
    urls=[]
    for a in soup.find_all("a",href=True):
        href=urljoin(BASE,a["href"])
        label=a.get_text(" ",strip=True)
        if href.lower().endswith(".pdf") or "api.nzx.com/public/announcement/" in href or "annual report" in label.lower():
            urls.append((href,label))
    out=[]
    for href,label in urls:
        if fy:
            out.append(Candidate(ticker=ticker,fiscal_year=fy,title=label or title,url=href,source=source,confidence=score+1))
    return out

def shard_accept(ticker:str,count:int,index:int)->bool:
    if count <= 1: return True
    n=int(hashlib.sha256(ticker.upper().encode()).hexdigest()[:16],16)
    return n % count == index

class NZXPublic:
    def __init__(self,http): self.http=http
    def current_universe(self, shard_count=1, shard_index=0):
        require_terms_ack()
        page=self.http.get(f"{BASE}/markets/NZSX").text
        raw=parse_market_page(page); issuers=[]
        for ticker,name in raw:
            if not shard_accept(ticker,shard_count,shard_index): continue
            try:
                p=self.http.get(f"{BASE}/companies/{ticker}").text
                i=parse_company_page(p,ticker,name)
                if is_equity_issuer(i): issuers.append(i)
            except Exception:
                continue
        return issuers
    def documents(self,ticker,start,end):
        require_terms_ack(); html=self.http.get(f"{BASE}/companies/{ticker}/documents").text
        return parse_documents_page(html,ticker,start,end)
