import time, random, requests, threading
from .config import USER_AGENT
class Http:
    def __init__(self,delay=.35,timeout=45,retries=5):
        self.s=requests.Session(); self.s.headers.update({"User-Agent":USER_AGENT,"Accept":"*/*"}); self.delay=delay; self.timeout=timeout; self.retries=retries
        self._rate_lock=threading.Lock(); self._next_allowed=0.0
    def _throttle(self):
        if not self.delay:return
        with self._rate_lock:
            now=time.monotonic(); wait=max(0.0,self._next_allowed-now)
            if wait:time.sleep(wait)
            self._next_allowed=max(now,self._next_allowed)+self.delay
    def request(self,method,url,**kw):
        last=None
        for i in range(self.retries):
            try:
                self._throttle(); r=self.s.request(method,url,timeout=self.timeout,**kw)
                if r.status_code==429 or 500<=r.status_code<600:
                    time.sleep(float(r.headers.get("Retry-After") or min(30,2**i+random.random()))); continue
                r.raise_for_status(); return r
            except Exception as e:
                last=e; time.sleep(min(15,2**i))
        raise RuntimeError(f"HTTP failed after {self.retries} attempts: {url}: {last}")
    def get(self,url,**kw):return self.request("GET",url,**kw)
