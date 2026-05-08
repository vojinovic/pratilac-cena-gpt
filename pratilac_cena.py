#!/usr/bin/env python3

import json
import re

import requests
from bs4 import BeautifulSoup

OGLASI_FAJL = "oglasi.json"

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


def ucitaj_oglase():
    with open(OGLASI_FAJL, "r", encoding="utf-8") as f:
        return json.load(f)


def main():
    """DEBUG: Proveri samo PRVI oglas i ispiši šta je server vratio."""
    oglasi = ucitaj_oglase()

    if not oglasi:
        print("Nema oglasa")
        return

    url = oglasi[0]["url"]
    print(f"\n=== DEBUG: {url} ===\n")

    try:
        response = requests.get(url, headers=HEADERS, timeout=20)
        print(f"Status code: {response.status_code}")
        print(f"Response length: {len(response.text)} chars")
        print(f"Content-Type: {response.headers.get('Content-Type')}")
        print(f"Server: {response.headers.get('Server')}")

        html = response.text

        # Da li je generalno cena u HTML-u?
        print(f"\n--- Pretrage u sirovom HTML ---")
        print(f"'EUR' u HTML: {'EUR' in html}")
        print(f"Euro znak u HTML: {'\u20AC' in html}")
        print(f"'priceClassified' u HTML: {'priceClassified' in html}")
        print(f"'regularPriceColor' u HTML: {'regularPriceColor' in html}")
        print(f"'discountedPriceColor' u HTML: {'discountedPriceColor' in html}")
        print(f"Broj euro znakova: {html.count(chr(0x20AC))}")

        # Vidimo sve € pozicije
        print(f"\n--- Sve pozicije sa euro znakom (prvih 10) ---")
        positions = list(re.finditer(r".{60}\u20AC.{20}", html))
        for i, match in enumerate(positions[:10]):
            snippet = match.group(0).replace("\n", " ")
            print(f"  [{i+1}]: ...{snippet}...")

        # Proveri da li smo na captcha/blokiran stranici
        print(f"\n--- Captcha/blok provere ---")
        print(f"'captcha' u HTML (case-ins): {'captcha' in html.lower()}")
        print(f"'cloudflare' u HTML (case-ins): {'cloudflare' in html.lower()}")
        print(f"'access denied' u HTML (case-ins): {'access denied' in html.lower()}")
        print(f"'forbidden' u HTML (case-ins): {'forbidden' in html.lower()}")
        print(f"'just a moment' u HTML (case-ins): {'just a moment' in html.lower()}")

        # Title
        soup = BeautifulSoup(html, "html.parser")
        title = soup.find("title")
        if title:
            print(f"\nTitle tag: {title.get_text(strip=True)}")

        # H1
        h1 = soup.find("h1")
        if h1:
            print(f"H1 tag: {h1.get_text(strip=True)}")

        # Prvih 2000 karaktera HTML-a
        print(f"\n--- Prvih 2000 karaktera HTML-a ---")
        print(html[:2000])

        # Poslednjih 2000 karaktera
        print(f"\n--- Poslednjih 2000 karaktera HTML-a ---")
        print(html[-2000:])

    except Exception as e:
        print(f"Greška: {e}")


if __name__ == "__main__":
    main()
