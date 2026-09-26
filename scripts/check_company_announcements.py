import urllib.request
import re
import json

urls = [
    'https://www.nzx.com/companies/AIR/announcements',
    'https://www.nzx.com/companies/AIR',
    'https://www.nzx.com/companies/AIA/announcements',
    'https://www.nzx.com/companies/BRW/announcements'
]

headers = {'User-Agent': 'Mozilla/5.0 (Windows NT 10.0; Win64; x64)'}

for url in urls:
    req = urllib.request.Request(url, headers=headers)
    try:
        resp = urllib.request.urlopen(req)
        html = resp.read().decode('utf-8', errors='ignore')
        json_blobs = re.findall(r'<script[^>]*id=["\']__NEXT_DATA__["\'][^>]*>(.*?)</script>', html, re.DOTALL)
        if json_blobs:
            data = json.loads(json_blobs[0])
            queries = data.get('props', {}).get('pageProps', {}).get('dehydratedState', {}).get('queries', [])
            print(f'URL: {url}')
            print('Queries count:', len(queries))
            for q in queries:
                print('  QueryKey:', q.get('queryKey'))
                q_data = q.get('state', {}).get('data')
                if isinstance(q_data, list):
                    print(f'  List len {len(q_data)}')
                elif isinstance(q_data, dict):
                    print(f'  Dict keys {list(q_data.keys())}')
                    if 'data' in q_data and isinstance(q_data['data'], list):
                        print(f'    subdata list len: {len(q_data["data"])}')
        else:
            print(f'URL: {url} - No NEXT_DATA found')
    except Exception as e:
        print(f'Error for {url}: {e}')
