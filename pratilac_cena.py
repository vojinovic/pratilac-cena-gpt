#!/usr/bin/env python3

import json
import re

import requests
from bs4 import BeautifulSoup

OGLASI_FAJL = "oglasi.json"

EURO = "\u20AC"

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
    print("=== DEBUG ===")
    print("URL:", url)
    print()

    try:
        response = requests.get(url, headers=HEADERS, timeout=20)
        print("Status code:", response.status_code)
        print("Response length:", len(response.text), "chars")
        print("Content-Type:", response.headers.get("Content-Type"))
        print("Server:", response.headers.get("Server"))

        html = response.text

        # Da li je generalno cena u HTML-u?
        print()
        print("--- Pretrage u sirovom HTML ---")
        print("'EUR' u HTML:", "EUR" in html)
        print("Euro znak u HTML:", EURO in html)
        print("'priceClassified' u HTML:", "priceClassified" in html)
        print("'regularPriceColor' u HTML:", "regularPriceColor" in html)
        print("'discountedPriceColor' u HTML:", "discountedPriceColor" in html)
        print("Broj euro znakova:", html.count(EURO))

        # Vidimo sve € pozicije
        print()
        print("--- Sve pozicije sa euro znakom (prvih 10) ---")
        pattern = ".{60}" + EURO + ".{20}"
        positions = list(re.finditer(pattern, html))
        for i, match in enumerate(positions[:10]):
            snippet = match.group(0).replace("\n", " ")
            print("  [" + str(i + 1) + "]: ..." + snippet + "...")

        # Proveri da li smo na captcha/blokiran stranici
        print()
        print("--- Captcha/blok provere ---")
        print("'captcha' u HTML (case-ins):", "captcha" in html.lower())
        print("'cloudflare' u HTML (case-ins):", "cloudflare" in html.lower())
        print("'access denied' u HTML (case-ins):", "access denied" in html.lower())
        print("'forbidden' u HTML (case-ins):", "forbidden" in html.lower())
        print("'just a moment' u HTML (case-ins):", "just a moment" in html.lower())

        # Title
        soup = BeautifulSoup(html, "html.parser")
        title = soup.find("title")
        if title:
            print()
            print("Title tag:", title.get_text(strip=True))

        # H1
        h1 = soup.find("h1")
        if h1:
            print("H1 tag:", h1.get_text(strip=True))

        # Prvih 2000 karaktera HTML-a
        print()
        print("--- Prvih 2000 karaktera HTML-a ---")
        print(html[:2000])

        # Poslednjih 2000 karaktera
        print()
        print("--- Poslednjih 2000 karaktera HTML-a ---")
        print(html[-2000:])

    except Exception as e:
        print("Greška:", e)


if __name__ == "__main__":
    main()
