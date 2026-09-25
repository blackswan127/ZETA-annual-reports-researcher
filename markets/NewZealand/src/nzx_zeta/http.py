import time, random, requests
from .config import USER_AGENT

class Http:
    def __init__(self, delay=0.35, timeout=45, retries=5):
        self.s=requests.Session(); self.s.headers.update({"User-Agent":USER_AGENT,"Accept":"*/*"})
        self.delay=delay; self.timeout=timeout; self.retries=retries
    def request(self, method,url,**kw):
        last=None
        for i in range(self.retries):
            try:
                if self.delay: time.sleep(self.delay)
                r=self.s.request(method,url,timeout=self.timeout,**kw)
                if r.status_code==429 or 500<=r.status_code<600:
                    wait=float(r.headers.get("Retry-After") or min(30,2**i+random.random()))
                    time.sleep(wait); continue
                r.raise_for_status(); return r
            except Exception as e:
                last=e; time.sleep(min(15,2**i))
        raise RuntimeError(f"HTTP failed after {self.retries} attempts: {url}: {last}")
    def get(self,url,**kw): return self.request("GET",url,**kw)
