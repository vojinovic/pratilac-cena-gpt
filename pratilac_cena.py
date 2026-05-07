#!/usr/bin/env python3

import json
import os
import re
import time
from datetime import datetime

import requests
from bs4 import BeautifulSoup

OGLASI_FAJL = "oglasi.json"
BAZA_FAJL = "cene_oglasa.json"
PAUZA = 3

HEADERS = {
    "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/135.0.0.0 Safari/537.36",
    "Accept-Language": "sr-RS,sr;q=0.9,en-US;q=0.8,en;q=0.7",
    "Accept": "text/html,application/xhtml+xml,application/xml;q=0.9,image/webp,*/*;q=0.8",
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

    text = str(text)
    patterns = [
        r"([\d\.\s]{4,})\s*€",
        r"([\d\.\s]{4,})\s*EUR",
        r'"price"\s*:\s*"?([\d\.]+)"?',
        r'"amount"\s*:\s*"?([\d\.]+)"?',
        r'"priceAmount"\s*:\s*"?([\d\.]+)"?',
    ]

    for pattern in patterns:
        match = re.search(pattern, text, re.IGNORECASE)
        if match:
            cifre = re.sub(r"[^\d]", "", match.group(1))
            if cifre:
                cena = int(cifre)
                if 1000 <= cena <= 500000:
                    return cena

    return None


def izvuci_cenu(soup, html):
    selektori = [
        {"class": "price-box__price"},
        {"class": "priceBox"},
        {"class": "price"},
        {"itemprop": "price"},
        {"property": "product:price:amount"},
        {"property": "og:price:amount"},
        {"name": "price"},
    ]

    for sel in selektori:
        el = soup.find(attrs=sel)
        if el:
            cena = normalizuj_cenu(el.get("content") or el.get_text(" ", strip=True))
            if cena:
                return cena

    for meta in soup.find_all("meta"):
        cena = normalizuj_cenu(meta.get("content"))
        if cena:
            return cena

    for script in soup.find_all("script"):
        text = script.string or script.get_text(" ", strip=True)
        cena = normalizuj_cenu(text)
        if cena:
            return cena

    return normalizuj_cenu(html)


def izvuci_sliku(soup, html):
    meta_selectors = [
        ("property", "og:image"),
        ("name", "og:image"),
        ("name", "twitter:image"),
        ("property", "twitter:image"),
    ]

    for attr, value in meta_selectors:
        el = soup.find("meta", attrs={attr: value})
        if el and el.get("content"):
            src = el.get("content").strip()
            if src.startswith("http"):
                return src

    image_patterns = [
        r'https://gcdn\.polovniautomobili\.com/[^"\']+\.(?:jpg|jpeg|png|webp)',
        r'https:\\/\\/gcdn\.polovniautomobili\.com\\/[^"\']+\.(?:jpg|jpeg|png|webp)',
    ]

    for pattern in image_patterns:
        match = re.search(pattern, html, re.IGNORECASE)
        if match:
            src = match.group(0).replace("\\/", "/")
            return src

    for img in soup.find_all("img"):
        for attr in ["src", "data-src", "data-original", "data-lazy"]:
            src = img.get(attr)
            if src and "gcdn.polovniautomobili.com" in src:
                return src.strip()

    return None


def izvuci_naziv(soup):
    h1 = soup.find("h1")
    if h1:
        text = h1.get_text(" ", strip=True)
        if text:
            return text

    title = soup.find("title")
    if title:
        text = title.get_text(" ", strip=True)
        text = text.replace("| Polovni Automobili", "")
        text = text.replace("- Polovni automobili", "")
        text = text.replace("Polovni Automobili", "")
        text = text.strip()
        if text:
            return text

    return "Oglas"


def proveri_oglas(url):
    try:
        resp = requests.get(url, headers=HEADERS, timeout=20)
        resp.raise_for_status()
    except Exception as e:
        print(f"Greška pri otvaranju oglasa: {e}")
        return None, None, None, "", False

    soup = BeautifulSoup(resp.text, "html.parser")

    cena = izvuci_cenu(soup, resp.text)
    slika = izvuci_sliku(soup, resp.text)
    naziv = izvuci_naziv(soup)

    print(f"Pronađena cena: {cena}")
    print(f"Pronađena slika: {slika}")

    return cena, slika, naziv, resp.text, True


def calculate_score(label, html, cena, prva_cena, najmanja_cena, broj_promena, ukupno_snizenje, promena_tip):
    text = ((label or "") + " " + (html or "")).lower()
    score = 50

    if cena:
        if cena < 25000:
            score += 20
        elif cena < 30000:
            score += 15
        elif cena < 35000:
            score += 10
        elif cena > 45000:
            score -= 10

    if prva_cena and cena and prva_cena > cena:
        pad_proc = ((prva_cena - cena) / prva_cena) * 100
        if pad_proc > 15:
            score += 25
        elif pad_proc > 10:
            score += 20
        elif pad_proc > 5:
            score += 10

    bonus_keywords = [
        "r-design", "inscription", "momentum", "awd", "4x4", "pano",
        "panorama", "matrix", "hud", "360", "massage", "memorija",
        "acc", "full", "ful"
    ]

    for kw in bonus_keywords:
        if kw in text:
            score += 3

    good_signals = [
        "prvi vlasnik", "1 vlasnik", "servisna", "garaza", "garažiran",
        "bez ulaganja", "kao nov", "kupljen nov"
    ]

    for kw in good_signals:
        if kw in text:
            score += 5

    bad_signals = ["hitno", "fiksno", "zamena", "ostecen", "oštećen"]

    for kw in bad_signals:
        if kw in text:
            score -= 5

    return max(0, min(round(score), 100))


def main():
    oglasi = ucitaj_oglase()
    baza = ucitaj_bazu()
    now = datetime.now().strftime("%d.%m.%Y %H:%M")

    for oglas in oglasi:
        url = oglas["url"]
        print("\nPROVERA:", url)

        cena, slika, naziv, html, aktivan = proveri_oglas(url)
        stara = baza.get(url, {})

        label = oglas.get("label") or stara.get("label") or naziv or "Oglas"
        prethodna_cena = stara.get("cena")

        if not aktivan:
            baza[url] = {
                **stara,
                "label": label,
                "aktivan": False,
                "poslednja_provera": now,
                "slika": stara.get("slika"),
            }
            time.sleep(PAUZA)
            continue

        final_cena = cena if cena is not None else prethodna_cena

        prva_cena = stara.get("prva_cena") or final_cena
        najmanja_cena = stara.get("najmanja_cena") or final_cena

        promena = 0
        promena_tip = "bez_promene"
        broj_promena = stara.get("broj_promena", 0)
        ukupno_snizenje = stara.get("ukupno_snizenje", 0)
        datum_promene = stara.get("datum_promene")

        if prethodna_cena and final_cena and final_cena != prethodna_cena:
            promena = final_cena - prethodna_cena
            broj_promena += 1
            datum_promene = now

            if promena < 0:
                promena_tip = "snizenje"
                ukupno_snizenje += abs(promena)
            else:
                promena_tip = "poskupljenje"

        if final_cena and najmanja_cena:
            najmanja_cena = min(najmanja_cena, final_cena)

        final_slika = slika or stara.get("slika")

        score = calculate_score(
            label,
            html,
            final_cena,
            prva_cena,
            najmanja_cena,
            broj_promena,
            ukupno_snizenje,
            promena_tip,
        )

        baza[url] = {
            "label": label,
            "cena": final_cena,
            "prva_cena": prva_cena,
            "najmanja_cena": najmanja_cena,
            "broj_promena": broj_promena,
            "ukupno_snizenje": ukupno_snizenje,
            "slika": final_slika,
            "prethodna_cena": prethodna_cena,
            "promena": promena,
            "promena_tip": promena_tip,
            "datum_promene": datum_promene,
            "aktivan": True,
            "problem_cena": cena is None,
            "poslednja_provera": now,
            "score": score,
        }

        print("SCORE:", score)
        print("SLIKA FINAL:", final_slika)

        time.sleep(PAUZA)

    sacuvaj_bazu(baza)
    print("\nGOTOVO")


if __name__ == "__main__":
    main()
