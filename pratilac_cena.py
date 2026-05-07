#!/usr/bin/env python3

import json
import os
import re
import time
from datetime import datetime

import requests
from bs4 import BeautifulSoup

RESEND_API_KEY = os.environ.get("RESEND_API_KEY", "")
EMAIL_PRIMALAC = os.environ.get("EMAIL_PRIMALAC", "")

OGLASI_FAJL = "oglasi.json"
BAZA_FAJL = "cene_oglasa.json"

PAUZA = 4

HEADERS = {
    "User-Agent": (
        "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
        "AppleWebKit/537.36 (KHTML, like Gecko) "
        "Chrome/120.0.0.0 Safari/537.36"
    )
}


def ucitaj_oglase():
    with open(OGLASI_FAJL, "r", encoding="utf-8") as f:
        return json.load(f)


def ucitaj_bazu():
    if os.path.exists(BAZA_FAJL):
        with open(BAZA_FAJL, "r", encoding="utf-8") as f:
            return json.load(f)
    return {}


def sacuvaj_bazu(baza):
    with open(BAZA_FAJL, "w", encoding="utf-8") as f:
        json.dump(baza, f, ensure_ascii=False, indent=2)


def izvuci_cenu(soup):
    selektori = [
        {"class": "price-box__price"},
        {"itemprop": "price"},
        {"class": "price"},
    ]

    for sel in selektori:
        el = soup.find(attrs=sel)

        if el:
            cifre = re.sub(r"[^\d]", "", el.get_text(strip=True))

            if cifre:
                return int(cifre)

    return None


def proveri_oglas(url):
    try:
        resp = requests.get(url, headers=HEADERS, timeout=15)
        resp.raise_for_status()

    except Exception:
        return None, False

    soup = BeautifulSoup(resp.text, "html.parser")

    cena = izvuci_cenu(soup)

    return cena, True


def posalji_email(snizenja):
    if not snizenja:
        return

    html = "<h2>🚗 Sniženje cene!</h2>"

    for s in snizenja:
        html += f"""
        <p>
        <a href="{s['url']}">{s['label']}</a><br>
        {s['stara']} € → <strong>{s['nova']} €</strong>
        </p>
        """

    requests.post(
        "https://api.resend.com/emails",
        headers={
            "Authorization": f"Bearer {RESEND_API_KEY}",
            "Content-Type": "application/json",
        },
        json={
            "from": "Pratilac Cena <onboarding@resend.dev>",
            "to": [EMAIL_PRIMALAC],
            "subject": "🚗 Sniženje cene oglasa",
            "html": html,
        },
    )


def main():
    oglasi = ucitaj_oglase()
    baza = ucitaj_bazu()

    snizenja = []

    for oglas in oglasi:
        url = oglas["url"]
        label = oglas["label"]

        print(f"Proveravam: {label}")

        cena, aktivan = proveri_oglas(url)

        if not aktivan:
            print("Oglas nedostupan")
            continue

        stara_cena = baza.get(url, {}).get("cena")

        if stara_cena and cena and cena < stara_cena:
            snizenja.append({
                "url": url,
                "label": label,
                "stara": stara_cena,
                "nova": cena,
            })

        baza[url] = {
            "label": label,
            "cena": cena,
            "aktivan": aktivan,
            "poslednja_provera": datetime.now().strftime("%d.%m.%Y %H:%M")
        }

        time.sleep(PAUZA)

    sacuvaj_bazu(baza)

    posalji_email(snizenja)

    print("Gotovo.")


if __name__ == "__main__":
    main()
