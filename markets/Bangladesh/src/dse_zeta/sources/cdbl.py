from bs4 import BeautifulSoup
BASE="https://www.cdbl.com.bd/list-of-isin"
def parse_cdbl_list(html):
    soup=BeautifulSoup(html,"html.parser");out=[]
    for tr in soup.find_all("tr"):
        c=[x.get_text(" ",strip=True) for x in tr.find_all(["td","th"])]
        if len(c)>=6 and len(c[1])==12 and c[1][:2].upper()=="BD":out.append((c[1].upper(),c[2],c[5]))
    return out
def fetch_cdbl(http):return parse_cdbl_list(http.get(BASE).text)
