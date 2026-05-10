#!/usr/bin/env python3
import requests
import re

URL = "https://suchen.mobile.de/fahrzeuge/search.html?vc=Car&makeModelVariant1.makeId=25100&makeModelVariant1.modelId=22&pageNumber=1"

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

print(f"FETCH: {URL}")
r = requests.get(URL, headers=HEADERS, timeout=20)
r.encoding = "utf-8"

print(f"Status: {r.status_code}")
print(f"Content length: {len(r.text)}")
print(f"Content-Type: {r.headers.get('content-type')}")

print("\n=== RESPONSE HEADERS ===")
for k, v in r.headers.items():
    print(f"  {k}: {v}")

print("\n=== PRVIH 3000 KARAKTERA TELA ===")
print(r.text[:3000])

print("\n=== POSLEDNJIH 1000 KARAKTERA ===")
print(r.text[-1000:])

# Detect challenge
text_lower = r.text.lower()
print("\n=== DETEKCIJA TIPA BLOKADE ===")
if "cloudflare" in text_lower:
    print("✓ Cloudflare detektovan")
if "ray id" in text_lower:
    print("✓ Cloudflare Ray ID prisutan (čist Cloudflare block)")
if "captcha" in text_lower:
    print("✓ Captcha detektovan")
if "akamai" in text_lower:
    print("✓ Akamai detektovan")
if "datadome" in text_lower:
    print("✓ DataDome detektovan (popularan anti-bot)")
if "perimeterx" in text_lower or "px-captcha" in text_lower:
    print("✓ PerimeterX detektovan")
if "you have been blocked" in text_lower or "access denied" in text_lower:
    print("✓ Eksplicitan block")
