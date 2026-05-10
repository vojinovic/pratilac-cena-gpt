#!/usr/bin/env python3
import requests
import re
import json

URL = "https://www.polovniautomobili.com/auto-oglasi/28482744/volvo-xc60-20b4-mhev-r-design"

HEADERS = {
    "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/131.0.0.0 Safari/537.36",
    "Accept": "text/html,application/xhtml+xml,application/xml;q=0.9,image/avif,image/webp,image/apng,*/*;q=0.8",
    "Accept-Language": "sr-RS,sr;q=0.9",
    "Accept-Encoding": "gzip, deflate, br",
    "Connection": "keep-alive",
    "Upgrade-Insecure-Requests": "1",
}

print(f"Fetching: {URL}")
r = requests.get(URL, headers=HEADERS, timeout=20)
r.encoding = "utf-8"
print(f"Status: {r.status_code}, content length: {len(r.text)}")

html = r.text

# 1. dataLayer - sva price polja
print("\n=== dataLayer ===")
m = re.search(r'dataLayer\.push\((\{[^;]*?"object_uid"[^;]*?\})\);', html)
if m:
    try:
        d = json.loads(m.group(1))
        price_keys = {k: v for k, v in d.items() if 'price' in k.lower() or 'cena' in k.lower()}
        print(f"Price polja u dataLayer-u:")
        print(json.dumps(price_keys, indent=2, ensure_ascii=False))
    except Exception as e:
        print(f"JSON parse error: {e}")
else:
    print("dataLayer NIJE pronadjen!")

# 2. priceClassified
print("\n=== priceClassified klasa ===")
matches = re.findall(r'class="[^"]*priceClassified[^"]*"[^>]*>([^<]+)', html)
print(f"Pronadjeno {len(matches)} mesta")
for m_text in matches[:5]:
    print(f"  text: {m_text.strip()}")

# 3. Sve price klase
print("\n=== Sve klase sa 'price' u imenu ===")
classes = set(re.findall(r'class="([^"]*[Pp]rice[^"]*)"', html))
for c in list(classes)[:15]:
    print(f"  {c}")

# 4. Cene u tekstu blizu € znaka
print("\n=== Cene u tekstu (€) ===")
matches = re.findall(r'(\d[\d.,\s]{2,12})\s*€', html)
print(f"Pronadjeno {len(matches)} cena")
for m_text in matches[:10]:
    print(f"  {m_text.strip()}")

# 5. Meta tagovi
print("\n=== Meta price ===")
for p in [r'<meta[^>]*property="product:price:amount"[^>]*content="([^"]+)"', 
          r'<meta[^>]*itemprop="price"[^>]*content="([^"]+)"',
          r'<meta[^>]*content="([^"]+)"[^>]*property="product:price:amount"']:
    matches = re.findall(p, html)
    for m_text in matches:
        print(f"  Pronadjena cena u meta: {m_text}")

# 6. Title
title_match = re.search(r'<title>(.*?)</title>', html)
if title_match:
    print(f"\nTitle: {title_match.group(1)}")
