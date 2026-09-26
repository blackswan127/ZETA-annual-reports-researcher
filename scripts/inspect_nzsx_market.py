import urllib.request
import re
import json

url = 'https://www.nzx.com/markets/NZSX'
req = urllib.request.Request(url, headers={'User-Agent': 'Mozilla/5.0 (Windows NT 10.0; Win64; x64)'})
resp = urllib.request.urlopen(req)
html = resp.read().decode('utf-8', errors='ignore')

json_blobs = re.findall(r'<script[^>]*id=["\']__NEXT_DATA__["\'][^>]*>(.*?)</script>', html, re.DOTALL)
if json_blobs:
    data = json.loads(json_blobs[0])
    queries = data.get('props', {}).get('pageProps', {}).get('dehydratedState', {}).get('queries', [])
    print('Queries count:', len(queries))
    for q in queries:
        print('QueryKey:', q.get('queryKey'))
        state = q.get('state', {})
        q_data = state.get('data')
        if isinstance(q_data, list):
            print('  List len:', len(q_data))
            if q_data:
                print('  Sample item:', q_data[0])
        elif isinstance(q_data, dict):
            print('  Dict keys:', list(q_data.keys()))
            if 'data' in q_data:
                print('  subdata len:', len(q_data['data']))
                if q_data['data']:
                    print('  Sample subdata item:', q_data['data'][0])
