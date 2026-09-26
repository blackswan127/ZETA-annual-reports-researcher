import urllib.request
import re
import json

test_urls = [
    'https://www.nzx.com/companies/AIR/announcements?year=2024',
    'https://www.nzx.com/companies/AIR/announcements?year=2023',
    'https://www.nzx.com/companies/AIR/announcements?page=2',
    'https://www.nzx.com/companies/AIR/announcements/2024',
]

headers = {'User-Agent': 'Mozilla/5.0 (Windows NT 10.0; Win64; x64)'}

for url in test_urls:
    req = urllib.request.Request(url, headers=headers)
    try:
        resp = urllib.request.urlopen(req)
        html = resp.read().decode('utf-8', errors='ignore')
        json_blobs = re.findall(r'<script[^>]*id=["\']__NEXT_DATA__["\'][^>]*>(.*?)</script>', html, re.DOTALL)
        if json_blobs:
            data = json.loads(json_blobs[0])
            queries = data.get('props', {}).get('pageProps', {}).get('dehydratedState', {}).get('queries', [])
            ann_q = [q for q in queries if 'announcements' in q.get('queryKey', [])]
            if ann_q:
                print(f'URL {url} -> queryKey: {ann_q[0].get("queryKey")}, announcements count: {len(ann_q[0].get("state", {}).get("data", {}).get("data", []))}')
            else:
                print(f'URL {url} -> No ann query, queries: {[q.get("queryKey") for q in queries]}')
    except Exception as e:
        print(f'Error {url}: {e}')
