import hashlib,re
from pathlib import Path

def safe_component(v,max_len=120):
 v=re.sub(r'[<>:"/\\|?*\x00-\x1f]','_',v or '').strip(' .')
 v=re.sub(r'\s+',' ',v)
 return (v[:max_len] or 'UNKNOWN').strip()
def stable_id(*parts): return hashlib.sha256('|'.join(parts).encode()).hexdigest()[:24]
def sha256_file(path,chunk=1024*1024):
 h=hashlib.sha256()
 with Path(path).open('rb') as f:
  for b in iter(lambda:f.read(chunk),b''): h.update(b)
 return h.hexdigest()
def base_ticker(symbol): return (symbol or '').split('.',1)[0].upper()
def prefer_symbol(symbols):
 n=[s for s in symbols if s.upper().endswith('.N0000')]
 return sorted(n or symbols)[0] if symbols else ''
