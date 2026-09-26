import urllib.request
import json
import re

url = 'https://www.nzx.com/markets/NZSX'
req = urllib.request.Request(url, headers={'User-Agent': 'Mozilla/5.0'})
html = urllib.request.urlopen(req).read().decode('utf-8', errors='ignore')
data = json.loads(re.findall(r'<script[^>]*id=["\']__NEXT_DATA__["\'][^>]*>(.*?)</script>', html, re.DOTALL)[0])
active_inst = data['props']['pageProps']['dehydratedState']['queries'][0]['state']['data']

mapping = {}
for inst in active_inst:
    code = inst.get('code')
    if code:
        mapping[code] = (inst.get('companyId'), inst.get('name'), inst.get('isin'))

for t in ['AIA', 'AIR', 'SPK', 'MEL', 'FPH', 'MCY', 'CNU', 'POT', 'RYM', 'EBO']:
    print(t, '->', mapping.get(t))
