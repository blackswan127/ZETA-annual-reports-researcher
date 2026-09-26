import urllib.request
import re
import json

url = 'https://www.nzx.com/markets/NZSX'
req = urllib.request.Request(url, headers={'User-Agent': 'Mozilla/5.0 (Windows NT 10.0; Win64; x64)'})
resp = urllib.request.urlopen(req)
html = resp.read().decode('utf-8', errors='ignore')

data = json.loads(re.findall(r'<script[^>]*id=["\']__NEXT_DATA__["\'][^>]*>(.*?)</script>', html, re.DOTALL)[0])
queries = data['props']['pageProps']['dehydratedState']['queries']

active_inst = queries[0]['state']['data']
market_inst = queries[1]['state']['data']

print(f'Total active instruments: {len(active_inst)}')
print(f'Total market instruments (NZSX): {len(market_inst)}')

# Check categories/types
categories = {}
company_map = {} # companyId -> info
for inst in active_inst:
    cat = inst.get('category', '')
    subcat = inst.get('subCategory', '')
    mtype = inst.get('marketType', '')
    key = f'{mtype}:{cat}:{subcat}'
    categories[key] = categories.get(key, 0) + 1
    
    cid = inst.get('companyId')
    if cid and mtype == 'NZSX':
        if cid not in company_map:
            company_map[cid] = {
                'companyId': cid,
                'code': inst.get('code'),
                'name': inst.get('name'),
                'isin': inst.get('isin'),
                'category': cat,
                'subCategory': subcat,
                'instruments': []
            }
        company_map[cid]['instruments'].append(inst)

print('\nCategories breakdown in activeInstruments:')
for k, v in sorted(categories.items()):
    print(f'  {k}: {v}')

print(f'\nUnique NZSX companies with companyId: {len(company_map)}')
sample_keys = list(company_map.keys())[:10]
for k in sample_keys:
    print(f"  {k}: {company_map[k]['code']} - {company_map[k]['name']} (ISIN: {company_map[k]['isin']})")
