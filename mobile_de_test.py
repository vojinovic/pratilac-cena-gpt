#!/usr/bin/env python3
"""
Faza 1 — Test da li mogu da skrejpujem mobile.de.
Pokreće se kao deo Dijagnostika workflow-a.
"""

import requests
import re
import json

# Volvo XC60 search, 2021-2023, 130-170K km
SEARCH_URL = "https://suchen.mobile.de/fahrzeuge/search.html?dam=false&isSearchRequest=true&ms=25100%3B22%3B%3B%3B&pageNumber=1&s=Car&sb=rel&vc=Car&yms=2021%3A2023&damageUnrepaired=NO_DAMAGE_UNREPAIRED&minFirstRegistrationDate=2021-01-01&maxFirstRegistrationDate=2023-12-31&maxMileage=170000&minMileage=130000"

# Pojedinačni oglas — testiraćemo i ovo, izvući ćemo prvi link sa search stranice
DETAIL_URL_FALLBACK = "https://suchen.mobile.de/fahrzeuge/details.html?id=405398642"

HEADERS = {
    "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/131.0.0.0 Safari/537.36",
    "Accept": "text/html,application/xhtml+xml,application/xml;q=0.9,image/avif,image/webp,image/apng,*/*;q=0.8",
    "Accept-Language": "de-DE,de;q=0.9,en;q=0.8",
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
    print(f"\n=== FETCH: {url[:100]}...")
    try:
        r = requests.get(url, headers=HEADERS, timeout=20)
        r.encoding = "utf-8"
        print(f"Status: {r.status_code}, content-length: {len(r.text)}")
        print(f"Content-Type: {r.headers.get('content-type')}")
        return r
    except Exception as e:
        print(f"GREŠKA: {e}")
        return None


def analyze_search_page(html):
    print("\n=== 1. CLOUDFLARE / BOT DETECTION ===")
    suspicious = ["just a moment", "checking your browser", "captcha", "verify you are human", "cloudflare"]
    for kw in suspicious:
        if kw in html.lower():
            print(f"⚠️  Detected: '{kw}' u HTML-u")
    
    title_match = re.search(r'<title>(.*?)</title>', html, re.IGNORECASE | re.DOTALL)
    if title_match:
        print(f"Title: {title_match.group(1).strip()[:200]}")
    
    print("\n=== 2. JSON-LD ===")
    ld_matches = re.findall(r'<script[^>]*type="application/ld\+json"[^>]*>(.*?)</script>', html, re.DOTALL)
    print(f"Pronadjeno {len(ld_matches)} JSON-LD blokova")
    for i, ld in enumerate(ld_matches[:3]):
        try:
            data = json.loads(ld.strip())
            data_type = data.get("@type", "?") if isinstance(data, dict) else "list"
            print(f"  {i+1}. type={data_type}")
            # Snippet ako sadrži ItemList ili Product
            if "ItemList" in str(data_type) or "Product" in str(data_type):
                print(f"     SNIPPET: {json.dumps(data, ensure_ascii=False)[:400]}")
        except:
            pass
    
    print("\n=== 3. dataLayer ili globalne JS varijable ===")
    if "dataLayer" in html:
        # Pokušaj da nadjemo dataLayer push-eve
        pushes = re.findall(r'dataLayer\.push\((\{[^;]+?\})\);', html)
        print(f"Pronadjeno {len(pushes)} dataLayer.push poziva")
        for p in pushes[:3]:
            print(f"  PUSH: {p[:300]}")
    
    # Mobile.de često ima window.__INITIAL_STATE__ ili sličan global
    initial_state_match = re.search(r'window\.__([A-Z_]+)__\s*=\s*(\{[^;]+);', html)
    if initial_state_match:
        print(f"Globalna var: window.__{initial_state_match.group(1)}__ ({len(initial_state_match.group(2))} chars)")
    
    print("\n=== 4. Search rezultati - linkovi na listinge ===")
    # Mobile.de listingi imaju URL formata /fahrzeuge/details.html?id=NUMBER
    listing_links = re.findall(r'href="(/fahrzeuge/details\.html\?id=\d+[^"]*)"', html)
    listing_links = list(set(listing_links))  # dedupe
    print(f"Pronadjeno {len(listing_links)} unique listing linkova")
    for link in listing_links[:5]:
        print(f"  {link[:150]}")
    
    print("\n=== 5. Cene u tekstu ===")
    cene = re.findall(r'(\d{1,3}(?:[.\s]\d{3})*)\s*€', html)
    cene_clean = list(set([c for c in cene if len(c.replace('.','').replace(' ','')) >= 4]))
    print(f"Pronadjeno {len(cene_clean)} unique cena")
    for c in cene_clean[:10]:
        print(f"  {c} €")
    
    print("\n=== 6. CSS klase sa 'price' u imenu ===")
    classes = set(re.findall(r'class="([^"]*[Pp]rice[^"]*)"', html))
    for c in list(classes)[:10]:
        print(f"  {c}")
    
    return listing_links


def analyze_detail_page(html):
    print("\n=== DETAIL: cena ===")
    # Mobile.de cena je obično u <span class="..price.."> ili u meta tagu
    price_match = re.search(r'<meta[^>]*property="product:price:amount"[^>]*content="([^"]+)"', html)
    if price_match:
        print(f"  meta product:price:amount: {price_match.group(1)}")
    
    # JSON-LD često ima offers/price
    ld_matches = re.findall(r'<script[^>]*type="application/ld\+json"[^>]*>(.*?)</script>', html, re.DOTALL)
    for ld in ld_matches[:5]:
        try:
            data = json.loads(ld.strip())
            if "offers" in str(data).lower() or "price" in str(data).lower():
                print(f"  JSON-LD sa cenom: {json.dumps(data, ensure_ascii=False)[:500]}")
                break
        except:
            pass
    
    print("\n=== DETAIL: km, godina, lokacija ===")
    # Mobile.de detail page često ima strukturisane "key-data"
    key_data = re.findall(r'data-testid="([^"]+)"[^>]*>([^<]+)<', html)
    for k, v in key_data[:20]:
        if any(x in k.lower() for x in ["price", "mileage", "year", "registration", "location", "fuel", "power"]):
            print(f"  [{k}] {v.strip()[:100]}")


# Pokretanje
print("=" * 80)
print("MOBILE.DE FAZA 1 - PROOF OF CONCEPT")
print("=" * 80)

# Test 1: search stranica
r1 = fetch(SEARCH_URL)
listing_urls = []
if r1 and r1.status_code == 200:
    listing_urls = analyze_search_page(r1.text)
    
    # Save HTML for inspection
    with open("mobile_de_search.html", "w", encoding="utf-8") as f:
        f.write(r1.text)
    print(f"\nHTML sačuvan u mobile_de_search.html")

# Test 2: detail stranica
print("\n" + "=" * 80)
print("DETAIL PAGE TEST")
print("=" * 80)

# Koristi prvi link iz search-a ili fallback
detail_url = None
if listing_urls:
    detail_url = "https://suchen.mobile.de" + listing_urls[0]
    print(f"Koristim prvi listing iz search-a: {detail_url}")
else:
    det
