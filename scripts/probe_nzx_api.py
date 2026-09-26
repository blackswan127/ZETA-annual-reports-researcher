import urllib.request
import json

endpoints = [
    'https://api.nzx.com/public/announcement/480615',
    'https://api.nzx.com/public/announcements?market=NZSX',
    'https://api.nzx.com/public/announcements?code=BRW',
    'https://api.nzx.com/public/companies/BRW/announcements',
    'https://api.nzx.com/public/instruments',
    'https://api.nzx.com/public/companies',
]

headers = {'User-Agent': 'Mozilla/5.0 (Windows NT 10.0; Win64; x64)', 'Accept': 'application/json'}

for ep in endpoints:
    req = urllib.request.Request(ep, headers=headers)
    try:
        with urllib.request.urlopen(req) as resp:
            data = resp.read()
            print(f'SUCCESS {ep}: status {resp.status}, bytes {len(data)}')
            try:
                js = json.loads(data.decode('utf-8'))
                if isinstance(js, list):
                    print(f'  List len {len(js)}')
                elif isinstance(js, dict):
                    print(f'  Dict keys: {list(js.keys())}')
            except:
                pass
    except Exception as e:
        print(f'FAILED {ep}: {e}')
