import os,re,hashlib
from concurrent.futures import ThreadPoolExecutor,as_completed
from urllib.parse import urljoin,urlparse
from bs4 import BeautifulSoup
from ..models import Issuer,Candidate
from ..classify import annual_report_score,infer_fiscal_year
BASE="https://dse.ternary.com.bd"

def require_terms_ack():
    if os.environ.get("DSE_ACKNOWLEDGE_TERMS")!="1":raise RuntimeError("DSE public-site access is disabled until DSE_ACKNOWLEDGE_TERMS=1 is explicitly set after reviewing DSE terms/permissions for your use.")
def shard_accept(ticker,count,index):
    if count<=1:return True
    return int(hashlib.sha256(ticker.upper().encode()).hexdigest()[:16],16)%count==index
def parse_companies_page(html):
    soup=BeautifulSoup(html,"html.parser");out=[];seen=set()
    for a in soup.find_all("a",href=True):
        m=re.search(r"/company/([A-Z0-9]+)(?:$|[?#])",a["href"],re.I)
        if not m:continue
        t=m.group(1).upper()
        if t in seen:continue
        seen.add(t);out.append((t,a.get_text(" ",strip=True)))
    return out
def obvious_non_equity(ticker,label):
    low=(f"{ticker} {label}").lower()
    return ticker.upper().startswith(("TB2Y","TB5Y","TB10Y","TB15Y","TB20Y")) or any(x in low for x in ["bgtb","treasury bond","perpetual bond","mutual fund"])

def parse_company_page(html,ticker,fallback_name=""):
    soup=BeautifulSoup(html,"html.parser");text=soup.get_text(" ",strip=True);h1=soup.find("h1");name=h1.get_text(" ",strip=True) if h1 else fallback_name
    inst="";board="";status="";fye="";website="";fin="";sector=""
    m=re.search(r"Instrument\s*[\u00b7·:Â\s-]+\s*([A-Za-z ]+?)(?:\s+Debut|\s+Financial|\s+Market|$)",text,re.I);inst=m.group(1).strip() if m else ""
    m=re.search(r"\bIn DSE\s+([A-Z]+)\b",text);board=m.group(1).strip() if m else ""
    m=re.search(r"Present Operational Status\s+([A-Za-z -]+?)(?:Head Office|Registered Office|Factory Address|Contact Phone)",text,re.I);status=m.group(1).strip() if m else ""
    m=re.search(r"Year-end\s+([A-Za-z]+)",text,re.I);fye=m.group(1).strip() if m else ""
    # sector appears just before 'In DSE' on the profile header
    m=re.search(r"Instrument\s*[·:].{0,80}?\b([A-Za-z& ]{3,40})\s+In DSE\s+[A-Z]+",text,re.I);sector=m.group(1).strip() if m else ""
    external=[]
    for a in soup.find_all("a",href=True):
        href=urljoin(BASE,a["href"]);label=a.get_text(" ",strip=True);low=(href+" "+label).lower()
        if urlparse(href).scheme in {"http","https"} and "dse.ternary.com.bd" not in urlparse(href).netloc:
            external.append((href,label));
            if not fin and any(k in low for k in ["financialreport","financial-report","financial_reports","financialreports","financial statement","financial statement"]):fin=href
    for href,label in external:
        if not website and not any(x in urlparse(href).netloc.lower() for x in ["facebook.com","linkedin.com","youtube.com"]):website=f"{urlparse(href).scheme}://{urlparse(href).netloc}/"
    return Issuer(ticker=ticker,name=name,website=website,financials_url=fin,instrument_type=inst,board=board,sector=sector,fiscal_year_end=fye,operational_status=status)
def is_equity_issuer(i):
    t=i.instrument_type.lower();name=i.name.lower()
    if any(x in t for x in ["bond","debt","mutual fund","fund","treasury","g-sec"]):return False
    if any(x in name for x in ["perpetual bond","mutual fund","bgtb ","treasury bond"]):return False
    return "equity" in t or (not t and not any(x in name for x in ["bond","fund"]))
def parse_financial_page(html,ticker,base_url,start=2017,end=2025):
    soup=BeautifulSoup(html,"html.parser");out=[]
    for a in soup.find_all("a",href=True):
        href=urljoin(base_url,a["href"]);label=a.get_text(" ",strip=True);blob=f"{label} {href.rsplit('/',1)[-1]}";score=annual_report_score(blob)
        if score<5:continue
        fy,_=infer_fiscal_year(blob)
        if fy and start<=fy<=end:out.append(Candidate(ticker=ticker,fiscal_year=fy,title=label or href.rsplit('/',1)[-1],url=href,source="DSE_FINANCIAL_LINK",confidence=score+3))
    uniq={}
    for c in out:uniq[(c.fiscal_year,c.url)]=c
    return list(uniq.values())
class DSEPublic:
    def __init__(self,http):self.http=http
    def current_universe(self,shard_count=1,shard_index=0,enrich_cdbl=True,workers=6):
        require_terms_ack();raw=[x for x in parse_companies_page(self.http.get(f"{BASE}/companies").text) if not obvious_non_equity(*x) and shard_accept(x[0],shard_count,shard_index)];issuers=[]
        def one(x):
            ticker,label=x; i=parse_company_page(self.http.get(f"{BASE}/company/{ticker}").text,ticker,label); return i if is_equity_issuer(i) else None
        with ThreadPoolExecutor(max_workers=max(1,workers)) as ex:
            fut=[ex.submit(one,x) for x in raw]
            for f in as_completed(fut):
                try:
                    i=f.result()
                    if i:issuers.append(i)
                except Exception:pass
        issuers.sort(key=lambda x:x.ticker)
        if enrich_cdbl:
            try:
                from .cdbl import fetch_cdbl
                from ..identity import apply_cdbl_isin
                apply_cdbl_isin(issuers,fetch_cdbl(self.http))
            except Exception:pass
        return issuers
    def financial_documents(self,issuer,start,end,max_pages=12):
        require_terms_ack()
        if not issuer["financials_url"]:return []
        root=issuer["financials_url"];host=urlparse(root).netloc;queue=[root];seen=set();out=[]
        while queue and len(seen)<max_pages:
            u=queue.pop(0)
            if u in seen:continue
            seen.add(u)
            try:html=self.http.get(u).text
            except Exception:continue
            out.extend(parse_financial_page(html,issuer["ticker"],u,start,end))
            soup=BeautifulSoup(html,"html.parser")
            for a in soup.find_all("a",href=True):
                href=urljoin(u,a["href"]);label=a.get_text(" ",strip=True);low=(label+" "+href).lower()
                if urlparse(href).netloc!=host or href in seen:continue
                if not href.lower().split("?")[0].endswith(".pdf") and any(k in low for k in ["annual","report","financial","download","archive","previous"]):queue.append(href)
        uniq={}
        for c in out:uniq[(c.fiscal_year,c.url)]=c
        return list(uniq.values())
