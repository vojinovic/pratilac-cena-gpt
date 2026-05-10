#!/usr/bin/env python3
"""
AutoScout24 dijagnostika - Faza 1
"""

import requests
import re
import json

# Volvo XC60 search, 2021-2023, do 170K km, EU
SEARCH_URL = "https://www.autoscout24.com/lst/volvo/xc60?atype=C&damaged_listing=exclude&desc=0&fregfrom=2021&fregto=2023&kmto=170000&powertype=kw&search_id=&sort=standard&source=detailpage_back-to-search-link&ustate=N%2CU"

DETAIL_URL_FALLBACK = "https://www.autoscout24.com/offers/volvo-xc60-test"  # fallback, koristi rezultat iz search-a

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


def fetch(url):
    print(f"\nFETCH: {url[:120]}")
    try:
        r = requests.get(url, headers=HEADERS, timeout=20)
        r.encoding = "utf-8"
        print(f"Status: {r.status_code}")
        print(f"Content length: {len(r.text)}")
        print(f"Content-Type: {r.headers.get('content-type')}")
        return r
    except Exception as e:
        print(f"GREŠKA: {e}")
        return None


def detect_blockers(html):
    print("\n=== DETEKCIJA BLOKADE ===")
    text_lower = html.lower()
    
    detected = []
    if "cloudflare" in text_lower or "cf-ray" in text_lower:
        detected.append("Cloudflare")
    if "akamai" in text_lower:
        detected.append("Akamai")
    if "datadome" in text_lower:
        detected.append("DataDome")
    if "perimeterx" in text_lower or "px-captcha" in text_lower:
        detected.append("PerimeterX")
    if "captcha" in text_lower:
        detected.append("Captcha keyword")
    if "access denied" in text_lower or "zugriff verweigert" in text_lower:
        detected.append("Access denied")
    if "blocked" in text_lower:
        detected.append("Blocked keyword")
    
    if detected:
        print(f"Detektovano: {', '.join(detected)}")
    else:
        print("Nista direktno detektovano - dobar znak")
    
    title_match = re.search(r'<title>(.*?)</title>', html, re.IGNORECASE | re.DOTALL)
    if title_match:
        print(f"Title: {title_match.group(1).strip()[:200]}")


def analyze_search(html):
    print("\n=== JSON-LD ===")
    ld_matches = re.findall(r'<script[^>]*type="application/ld\+json"[^>]*>(.*?)</script>', html, re.DOTALL)
    print(f"Pronadjeno {len(ld_matches)} JSON-LD blokova")
    for i, ld in enumerate(ld_matches[:5]):
        try:
            data = json.loads(ld.strip())
            data_type = data.get("@type", "?") if isinstance(data, dict) else "list"
            print(f"  {i+1}. type={data_type}")
            if "ItemList" in str(data_type) or "Product" in str(data_type) or "Vehicle" in str(data_type):
                print(f"     SNIPPET: {json.dumps(data, ensure_ascii=False)[:600]}")
        except Exception as e:
            print(f"  {i+1}. Parse error: {e}")
    
    print("\n=== INITIAL STATE / NEXT_DATA ===")
    # AutoScout24 koristi Next.js, što znači __NEXT_DATA__ JSON je verovatno tu
    next_data_match = re.search(r'<script id="__NEXT_DATA__" type="application/json">(.*?)</script>', html, re.DOTALL)
    if next_data_match:
        print(f"Pronadjen __NEXT_DATA__ ({len(next_data_match.group(1))} chars)")
        try:
            data = json.loads(next_data_match.group(1))
            # Pokušaj da nadjem listinge
            data_str = json.dumps(data)
            if '"price"' in data_str.lower() and '"id"' in data_str.lower():
                print("✓ Sadrzi price i id polja - listingi su verovatno ovde")
                # Nadji prvi listing
                if "props" in data and "pageProps" in data["props"]:
                    page_props_keys = list(data["props"]["pageProps"].keys())
                    print(f"pageProps ključevi: {page_props_keys[:20]}")
        except Exception as e:
            print(f"JSON parse greška: {e
