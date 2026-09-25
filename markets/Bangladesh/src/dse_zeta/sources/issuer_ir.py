from urllib.parse import urljoin,urlparse
from bs4 import BeautifulSoup
from ..models import Candidate
from ..classify import annual_report_score,infer_fiscal_year
KEYS=("annual","report","investor","financial","results","disclosure","download","shareholder")
def discover_ir(http,ticker,website,start,end,max_pages=25):
    if not website:return []
    root=website if website.startswith("http") else "https://"+website;host=urlparse(root).netloc;queue=[root];seen=set();out=[]
    while queue and len(seen)<max_pages:
        u=queue.pop(0)
        if u in seen:continue
        seen.add(u)
        try:html=http.get(u).text
        except Exception:continue
        soup=BeautifulSoup(html,"html.parser")
        for a in soup.find_all("a",href=True):
            href=urljoin(u,a["href"]);label=a.get_text(" ",strip=True);low=(label+" "+href).lower()
            if urlparse(href).netloc!=host:continue
            if href.lower().split("?")[0].endswith(".pdf"):
                score=annual_report_score(label+" "+href);fy,_=infer_fiscal_year(label+" "+href)
                if score>=5 and fy and start<=fy<=end:out.append(Candidate(ticker,fy,label or href.rsplit('/',1)[-1],href,"ISSUER_IR",confidence=score))
            elif any(k in low for k in KEYS) and href not in seen and len(queue)<70:queue.append(href)
    uniq={}
    for c in out:uniq[(c.fiscal_year,c.url)]=c
    return list(uniq.values())
