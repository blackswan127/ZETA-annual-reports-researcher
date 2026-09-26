import urllib.request
import re
import json

url = 'https://www.nzx.com/announcements/480615'
req = urllib.request.Request(url, headers={'User-Agent': 'Mozilla/5.0 (Windows NT 10.0; Win64; x64)'})
resp = urllib.request.urlopen(req)
html = resp.read().decode('utf-8', errors='ignore')

json_blobs = re.findall(r'<script[^>]*id=["\']__NEXT_DATA__["\'][^>]*>(.*?)</script>', html, re.DOTALL)
if json_blobs:
    data = json.loads(json_blobs[0])
    ann = data.get('props', {}).get('pageProps', {}).get('announcement', {})
    print('Attachments:', ann.get('attachments'))
