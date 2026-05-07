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
    "User-Agent": "Mozilla/5.0",
    "Accept-Language": "sr-RS,sr;q=0.9,en-US;q=0.8",
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


def normalizuj_cenu(text):
    if not text:
        return None

    patterns = [
        r"([\d\.\s]{4,})\s*€",
        r"([\d\.\s]{4,})\s*EUR",
    ]

    for pattern in patterns:
        match = re.search(pattern, str(text))

        if match:
            cifre = re.sub(r"[^\d]", "", match.group(1))
            if cifre:
                cena = int(cifre)
                if 1000 <= cena <= 500000:
                    return cena

    return None


def izvuci_cenu(soup, html):
    for el in soup.find_all():
        if el.string:
            cena = normalizuj_cenu(el.string)
            if cena:
                return cena

    return normalizuj_cenu(html)


def izvuci_sliku(soup):
    img = soup.find("meta", property="og:image")
    if img and img.get("content"):
        return img.get("content")

    img = soup.find("img")
    if img and img.get("src"):
        return img.get("src")

    return None


def izvuci_naziv(soup):
    if soup.title:
        return soup.title.text.strip()
    h1 = soup.find("h1")
    if h1:
        return h1.text.strip()
    return "Oglas"


def proveri_oglas(url):
    try:
        r = requests.get(url, headers=HEADERS, timeout=20)
        r.raise_for_status()
    except:
        return None, None, None, False

    soup = BeautifulSoup(r.text, "html.parser")

    return (
        izvuci_cenu(soup, r.text),
        izvuci_sliku(soup),
        izvuci_naziv(soup),
        True
    )


# 🧠 SCORE ENGINE (AKTIVAN)
def calculate_score(title, text, price):

    text = (title or "").lower() + " " + (text or "").lower()

    score = 50

    # positive
    if "prvi vlasnik" in text:
        score += 10
    if "servisna knjiga" in text:
        score += 10
    if "garaziran" in text:
        score += 5
    if "bez ulaganja" in text:
        score += 10
    if "full oprema" in text:
        score += 8

    # negative
    if "udaren" in text:
        score -= 30
    if "farban" in text:
        score -= 20
    if "ostecen" in text:
        score -= 25
    if "uvoz" in text:
        score -= 5

    # price bias
    if price:
        if price < 20000:
            score += 5
        if price > 40000:
            score -= 5

    return max(0, min(100, score))


def format_cena(cena):
    if cena is None:
        return "N/A"
    return f"{cena:,}".replace(",", ".") + " €"


def main():

    oglasi = ucitaj_oglase()
    baza = ucitaj_bazu()

    snizenja = []
    upozorenja = []

    sada = datetime.now().strftime("%d.%m.%Y %H:%M")

    for oglas in oglasi:

        url = oglas["url"]
        print("Proveravam:", url)

        cena, slika, naziv, aktivan = proveri_oglas(url)

        stara = baza.get(url, {})

        label = oglas.get("label") or naziv

        # 🔥 SCORE (OVDE SE AKTIVIRA)
        score = calculate_score(naziv, "", cena)

        if not aktivan:
            baza[url] = {
                **stara,
                "aktivan": False,
                "poslednja_provera": sada,
                "score": score
            }
            continue

        stara_cena = stara.get("cena")

        promena = 0
        tip = "bez_promene"

        if stara_cena and cena:
            if cena < stara_cena:
                promena = stara_cena - cena
                tip = "snizenje"

                snizenja.append({
                    "url": url,
                    "label": label,
                    "stara": stara_cena,
                    "nova": cena,
                    "razlika": promena
                })

            elif cena > stara_cena:
                promena = cena - stara_cena
                tip = "povecanje"

        baza[url] = {
            "label": label,
            "cena": cena,
            "slika": slika,
            "aktivan": True,
            "prethodna_cena": stara_cena,
            "promena": promena,
            "promena_tip": tip,
            "poslednja_provera": sada,
            "score": score   # ⭐ AKTIVNO
        }

        time.sleep(PAUZA)

    sacuvaj_bazu(baza)

    print("Gotovo.")


if __name__ == "__main__":
    main()
