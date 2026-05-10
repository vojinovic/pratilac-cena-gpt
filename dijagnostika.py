#!/usr/bin/env python3
import requests
import re
import json

URL = "https://www.polovniautomobili.com/auto-oglasi/28482744/volvo-xc60-20b4-mhev-r-design"

HEADERS = {
    "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/131.0.0.0 Safari/537.36",
    "Accept": "text/html,application/xhtml+xml,application/xml;q=0.9,image/avif,image/webp,image/apng,*/*;q=0.8",
    "Accept-Language": "sr-RS,sr;q=0.9,en-US;q=0.8,en;q=0.7",
    "Accept-Encoding": "gzip, deflate, br",
    "Connection": "keep-alive",
    "Upgrade-Insecure-Requests": "1",
    "Sec-Fetch-Dest": "document",
    "Sec-Fetch-Mode": "navigate",
    "Sec-Fetch-Site": "none",
    "Sec-Fetch-User": "?1",
    "Cache-Control": "max-age=0",
}

print(f"Fetching: {URL}")
r = requests.get(URL, headers=HEADERS, timeout=20)
r.encoding = "utf-8"
print(f"Status: {r.status_code}, content length: {len(r.text)}")
print(f"Content-Type: {r.headers.get('content-type')}")

if r.status_code != 200:
    print("\nHEADERI:")
    for k, v in r.headers.items():
        print(f"  {k}: {v}")
    print("\nPRVIH 500 BYTES:")
    print(r.text[:500])
    raise SystemExit(1)

html = r.text

print("\n" + "=" * 60)
print("1. dataLayer pretraga")
print("=" * 60)
m = re.search(r'dataLayer\.push\((\{[^;]*?"object_uid"[^;]*?\})\);', html)
if m:
    print("dataLayer PRONADJEN")
    try:
        d = json.loads(m.group(1))
        # Sva price polja
        price_keys = {k: v for k, v in d.items() if 'price' in k.lower() or 'cena' in k.lower()}
        print(f"\nPolja sa 'price' ili 'cena':")
        print(json.dumps(price_keys, indent=2, ensure_ascii=False))
    except Exception as e:
        print(f"JSON parse error: {e}")
else:
    print("dataLayer NIJE PRONADJEN!")

print("\n" + "=" * 60)
print("2. priceClassified klasa")
print("=" * 60)
matches = re.findall(r'class="[^"]*priceClassified[^"]*"[^>]*>([^<]+)', html)
print(f"Pronadjeno {len(matches)} mesta")
for m_text in matches[:5]:
    print(f"  text: {m_text.strip()}")

print("\n" + "=" * 60)
print("3. Sve klase sa 'price' u imenu")
print("=" * 60)
classes = set(re.findall(r'class="([^"]*[Pp]rice[^"]*)"', html))
print(f"Razlicitih klasa: {len(classes)}")
for c in list(classes)[:15]:
    print(f"  {c}")

print("\n" + "=" * 60)
print("4. Cene u tekstu (€)")
print("=" * 60)
matches = re.findall(r'(\d[\d.,\s]{2,12})\s*€', html)
print(f"Pronadjeno {len(matches)} cena")
for m_text in matches[:10]:
    print(f"  {m_text.strip()}")

print("\n" + "=" * 60)
print("5. Meta tagovi sa cenom")
print("=" * 60)
for p in [
    r'<meta[^>]*property="product:price:amount"[^>]*content="([^"]+)"',
    r'<meta[^>]*itemprop="price"[^>]*content="([^"]+)"',
    r'<meta[^>]*content="([^"]+)"[^>]*property="product:price:amount"',
]:
    matches = re.findall(p, html)
    for m_text in matches:
        print(f"  Cena u meta: {m_text}")

print("\n" + "=" * 60)
print("6. Title")
print("=" * 60)
title_match = re.search(r'<title>(.*?)</title>', html)
if title_match:
    print(f"Title: {title_match.group(1)}")

print("\n" + "=" * 60)
print("7. Provera blokiranja")
print("=" * 60)
if "cloudflare" in html.lower():
    print("UPOZORENJE: 'cloudflare' u HTML-u!")
if "challenge" in html.lower():
    print("UPOZORENJE: 'challenge' u HTML-u!")
if "captcha" in html.lower():
    print("UPOZORENJE: 'captcha' u HTML-u!")
if len(html) < 5000:
    print(f"UPOZORENJE: HTML je samo {len(html)} chars - mozda blok")

print("\nGOTOVO")
