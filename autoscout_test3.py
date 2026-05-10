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

print("AUTOSCOUT24 - DETALJNA STRUKTURA LISTINGA")

r = requests.get(SEARCH_URL, headers=HEADERS, timeout=20)
r.encoding = "utf-8"
print(f"Status: {r.status_code}")

if r.status_code != 200:
    raise SystemExit(1)

next_match = re.search(r'<script id="__NEXT_DATA__" type="application/json">(.*?)</script>', r.text, re.DOTALL)
data = json.loads(next_match.group(1))
listings = data["props"]["pageProps"]["listings"]

# Uzmi prvi listing i izlistaj SVE pod-objekte
first = listings[0]

print("\n" + "=" * 80)
print("VEHICLE objekt - ceo")
print("=" * 80)
print(json.dumps(first.get("vehicle"), indent=2, ensure_ascii=False))

print("\n" + "=" * 80)
print("VEHICLE_DETAILS objekt - ceo")
print("=" * 80)
print(json.dumps(first.get("vehicleDetails"), indent=2, ensure_ascii=False))

print("\n" + "=" * 80)
print("LOCATION objekt - ceo")
print("=" * 80)
print(json.dumps(first.get("location"), indent=2, ensure_ascii=False))

print("\n" + "=" * 80)
print("SELLER objekt - ceo")
print("=" * 80)
print(json.dumps(first.get("seller"), indent=2, ensure_ascii=False))

print("\n" + "=" * 80)
print("STATISTICS / RATINGS / WLTP")
print("=" * 80)
for k in ["statistics", "ratings", "wltpValues"]:
    print(f"\n--- {k} ---")
    print(json.dumps(first.get(k), indent=2, ensure_ascii=False))

# Pogledaj još jedan listing iz različite zemlje da vidim varijacije
print("\n" + "=" * 80)
print("LOKACIJE PRVIH 10 LISTINGA")
print("=" * 80)
for i, l in enumerate(listings[:10]):
    loc = l.get("location", {})
    veh = l.get("vehicle", {})
    price = l.get("price", {}).get("priceFormatted", "?")
    print(f"  {i+1}. {price} | {veh.get('make')} {veh.get('model')} {veh.get('modelVersionInput', '')[:40]} | {loc.get('countryCode')} {loc.get('zip')} {loc.get('city')}")
