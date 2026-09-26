import urllib.request
import re

url = 'https://www.nzx.com/companies/AIR/announcements'
req = urllib.request.Request(url, headers={'User-Agent': 'Mozilla/5.0 (Windows NT 10.0; Win64; x64)'})
resp = urllib.request.urlopen(req)
html = resp.read().decode('utf-8', errors='ignore')

scripts = re.findall(r'src=["\'](/_next/static/chunks/[^"\']+)["\']', html)
print('Found scripts:', len(scripts))

for s in scripts:
    s_url = 'https://www.nzx.com' + s
    s_req = urllib.request.Request(s_url, headers={'User-Agent': 'Mozilla/5.0'})
    try:
        s_resp = urllib.request.urlopen(s_req)
        s_js = s_resp.read().decode('utf-8', errors='ignore')
        if 'announcements' in s_js:
            print(f'Found "announcements" in {s}')
            # Look for api endpoints or fetch calls
            matches = re.findall(r'["\'](https?://api\.nzx\.com/[^"\']+|/api/[^"\']+|/public/[^"\']+)["\']', s_js)
            if matches:
                print('  Endpoints in script:', set(matches))
            # Also look for query function / fetch template strings
            urls = re.findall(r'[`\'"]([^`\'"]*announcement[^`\'"]*)[`\'"]', s_js, re.IGNORECASE)
            print('  Announcement patterns:', set([u for u in urls if len(u) < 100][:10]))
    except Exception as e:
        print(f'Error fetching {s}: {e}')
