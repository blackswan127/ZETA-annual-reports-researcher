import urllib.request

test_urls = [
    'https://www.nzx.com/company/AIR000000/announcements/2024/all.json',
    'https://www.nzx.com/company/AIR000000/announcements/2023/all.json',
    'https://www.nzx.com/company/AIR000000/announcements/2020/all.json',
    'https://api.nzx.com/public/company/AIR000000/announcements/2024/all.json',
]

headers = {'User-Agent': 'Mozilla/5.0 (Windows NT 10.0; Win64; x64)', 'Referer': 'https://www.nzx.com/'}

for url in test_urls:
    req = urllib.request.Request(url, headers=headers)
    try:
        with urllib.request.urlopen(req) as resp:
            data = resp.read()
            print(f'SUCCESS: {url} (status {resp.status}, bytes {len(data)})')
            # Print sample
            print(data[:300].decode('utf-8', errors='ignore'))
    except Exception as e:
        print(f'FAIL: {url} -> {e}')
