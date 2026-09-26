import urllib.request
import json

headers = {'User-Agent': 'Mozilla/5.0 (Windows NT 10.0; Win64; x64)', 'Referer': 'https://www.nzx.com/'}

company_id = 'AIR000000'
for year in range(2017, 2026):
    url = f'https://api.nzx.com/public/company/{company_id}/announcements/{year}/all.json'
    req = urllib.request.Request(url, headers=headers)
    try:
        with urllib.request.urlopen(req) as resp:
            data = json.loads(resp.read().decode('utf-8'))
            print(f'Year {year}: {len(data)} announcements')
            for item in data:
                title = item.get('title', '')
                ann_type = item.get('type', '')
                if ann_type == 'ANNREP' or any(k in title.lower() for k in ['annual report', 'sustainability', 'esg', 'integrated report', 'climate']):
                    print(f'   -> [{item["id"]}] {ann_type} | {title}')
    except Exception as e:
        print(f'Year {year} error: {e}')
