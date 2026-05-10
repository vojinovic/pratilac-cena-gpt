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
}

print("=" * 80)
print("AUTOSCOUT24 - LISTINGI EXTRACT TEST")
print("=" * 80)

r = requests.get(SEARCH_URL, headers=HEADERS, timeout=20)
r.encoding = "utf-8"
print(f"Status: {r.status_code}, content: {len(r.text)} chars")

if r.status_code != 200:
    print("FAIL")
    raise SystemExit(1)

html = r.text

# Izvuci __NEXT_DATA__
next_match = re.search(r'<script id="__NEXT_DATA__" type="application/json">(.*?)</script>', html, re.DOTALL)
if not next_match:
    print("__NEXT_DATA__ nije pronadjen!")
    raise SystemExit(1)

data = json.loads(next_match.group(1))
page_props = data.get("props", {}).get("pageProps", {})

print(f"\nUkupno rezultata: {page_props.get('numberOfResults')}")
print(f"Broj stranica: {page_props.get('numberOfPages')}")

listings = page_props.get("listings", [])
print(f"Listinga na ovoj stranici: {len(listings)}")

if listings:
    print("\n" + "=" * 80)
    print("PRVI LISTING - sva polja")
    print("=" * 80)
    first = listings[0]
    print(json.dumps(first, indent=2, ensure_ascii=False)[:4000])
    
    print("\n" + "=" * 80)
    print("KLJUCNI PODACI ZA PRVIH 5 LISTINGA")
    print("=" * 80)
    for i, listing in enumerate(listings[:5]):
        print(f"\n--- Listing {i+1} ---")
        # Pokušaj da nadjemo ključne podatke (struktura može varirati)
        for key in ["id", "make", "model", "modelVersion", "price", "priceFormatted", 
                    "mileage", "firstRegistration", "fuel", "power", "powerKw", "powerHp",
                    "city", "country", "url", "vehicleId", "imageUrls", "images",
                    "lifecycleState", "vat"]:
            if key in listing:
                val = listing[key]
                if isinstance(val, (dict, list)):
                    val_str = json.dumps(val, ensure_ascii=False)[:200]
                else:
                    val_str = str(val)[:200]
                print(f"  {key}: {val_str}")

print("\n" + "=" * 80)
print("STRUKTURNI KLJUCEVI svih listinga")
print("=" * 80)
if listings:
    all_keys = set()
    for l in listings:
        all_keys.update(l.keys())
    print(f"Sve dostupne ključeve: {sorted(all_keys)}")
