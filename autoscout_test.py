#!/usr/bin/env python3
import requests
import re
import json

SEARCH_URL = "https://www.autoscout24.com/lst/volvo/xc60?atype=C&damaged_listing=exclude&fregfrom=2021&fregto=2023&kmto=170000&sort=standard&ustate=N%2CU"

HEADERS = {
    "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/131.0.0.0 Safari/537.36",
    "Accept": "text/html,application/xhtml+xml,application/xml;q=0.9,image/avif,image/webp,image/apng,*/*;q=0.8",
    "Accept-Language": "en-US,en;q=0.9,de;q=0.8",
    "Accept-Encoding": "gzip, deflate",
    "Connection": "keep-alive",
    "Upgrade-Insecure-Requests": "1",
    "Sec-Fetch-Dest": "document",
    "Sec-Fetch-Mode": "navigate",
    "Sec-Fetch-Site": "none",
    "Sec-Fetch-User": "?1",
    "Cache-Control": "max-age=0",
}

print("=" * 80)
print("AUTOSCOUT24 DIJAGNOSTIKA")
print("=" * 80)
print(f"\nFETCH: {SEARCH_URL[:120]}")

r = requests.get(SEARCH_URL, headers=HEADERS, timeout=20)
r.encoding = "utf-8"

print(f"Status: {r.status_code}")
print(f"Content length: {len(r.text)}")
print(f"Content-Type: {r.headers.get('content-type')}")

print("\n=== RESPONSE HEADERS ===")
for k, v in r.headers.items():
    print(f"  {k}: {v}")

if r.status_code != 200:
    print("\n=== PRVIH 2000 KARAKTERA TELA (jer status nije 200) ===")
    print(r.text[:2000])

html = r.text
text_lower = html.lower()

print("\n=== DETEKCIJA BLOKADE ===")
detected = []
if "cloudflare" in text_lower or "cf-ray" in text_lower:
    detected.append("Cloudflare")
if "akamai" in text_lower:
    detected.append("Akamai")
if "datadome" in text_lower:
    detected.append("DataDome")
if "perimeterx" in text_lower:
    detected.append("PerimeterX")
if "captcha" in text_lower:
    detected.append("Captcha keyword")
if "access denied" in text_lower:
    detected.append("Access denied")
if "blocked" in text_lower:
    detected.append("Blocked keyword")

if detected:
    print(f"Detektovano: {', '.join(detected)}")
else:
    print("Nista direktno detektovano - dobar znak")

title_match = re.search(r"<title>(.*?)</title>", html, re.IGNORECASE | re.DOTALL)
if title_match:
    print(f"Title: {title_match.group(1).strip()[:200]}")

if r.status_code == 200:
    print("\n=== JSON-LD ===")
    ld_matches = re.findall(r'<script[^>]*type="application/ld\+json"[^>]*>(.*?)</script>', html, re.DOTALL)
    print(f"Pronadjeno {len(ld_matches)} JSON-LD blokova")
    for i, ld in enumerate(ld_matches[:5]):
        try:
            data = json.loads(ld.strip())
            data_type = data.get("@type", "?") if isinstance(data, dict) else "list"
            print(f"  {i+1}. type={data_type}")
        except Exception as parse_err:
            print(f"  {i+1}. parse error")

    print("\n=== __NEXT_DATA__ (Next.js prerendered podaci) ===")
    next_match = re.search(r'<script id="__NEXT_DATA__" type="application/json">(.*?)</script>', html, re.DOTALL)
    if next_match:
        print(f"Pronadjen, duzina: {len(next_match.group(1))} chars")
        try:
            data = json.loads(next_match.group(1))
            page_props = data.get("props", {}).get("pageProps", {})
            print(f"pageProps keys: {list(page_props.keys())[:20]}")
        except Exception as e:
            print(f"Parse error")
    else:
        print("NIJE pronadjen")

    print("\n=== Listing linkovi ===")
    listing_links = re.findall(r'href="(/offers/[^"]+)"', html)
    listing_links = list(set(listing_links))
    print(f"Pronadjeno {len(listing_links)} unique linkova")
    for link in listing_links[:5]:
        print(f"  {link[:150]}")

    print("\n=== Cene u tekstu (€) ===")
    cene = re.findall(r"€\s*([\d,.]+)", html)
    cene_unique = list(set(cene))[:15]
    for c in cene_unique[:10]:
        print(f"  €{c}")

print("\n" + "=" * 80)
print("GOTOVO")
print("=" * 80)
