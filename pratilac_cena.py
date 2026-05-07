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
    "User-Agent": "Mozilla/5.0",
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
    selectors = [
        {"class": "price"},
        {"class": "priceBox"},
        {"itemprop": "price"},
    ]

    for sel in selectors:
        el = soup.find(attrs=sel)

        if el:
            cena = normalizuj_cenu(
                el.get("content") or el.get_text(" ", strip=True)
            )

            if cena:
                return cena

    return normalizuj_cenu(html)


def izvuci_sliku(soup):
    meta = soup.find("meta", property="og:image")

    if meta and meta.get("content"):
        return meta.get("content")

    img = soup.find("img")

    if img:
        return img.get("src")

    return None


def izvuci_naziv(soup):
    h1 = soup.find("h1")

    if h1:
        return h1.get_text(" ", strip=True)

    title = soup.find("title")

    if title:
        return title.get_text(" ", strip=True)

    return "Oglas"


def extract_model(label):
    if not label:
        return "unknown"

    text = label.lower()

    modeli = [
        "xc60",
        "xc90",
        "kodiaq",
        "tiguan",
        "x5",
        "gle",
        "q5",
        "q7",
        "glc",
        "x3",
    ]

    for model in modeli:
        if model in text:
            return model

    words = text.split()

    if len(words) >= 2:
        return words[1]

    return words[0]


def market_average(model, baza):
    cene = []

    for _, data in baza.items():
        if data.get("model") == model and data.get("cena"):
            cene.append(data["cena"])

    if not cene:
        return None

    return sum(cene) / len(cene)


def calculate_score(
    label,
    html,
    cena,
    market_avg,
    prva_cena,
    najmanja_cena,
    ukupno_snizenje,
    promena_tip,
):
    text = ((label or "") + " " + (html or "")).lower()

    score = 50

    # MARKET INTELLIGENCE
    if market_avg and cena:
        diff_percent = ((market_avg - cena) / market_avg) * 100

        if diff_percent >= 15:
            score += 20
        elif diff_percent >= 10:
            score += 15
        elif diff_percent >= 5:
            score += 8
        elif diff_percent <= -15:
            score -= 20
        elif diff_percent <= -10:
            score -= 10

    # OPREMA
    plus_keywords = {
        "awd": 5,
        "4x4": 5,
        "r-design": 5,
        "inscription": 5,
        "momentum": 3,
        "sport": 4,
        "pano": 5,
        "panorama": 5,
        "kamera": 3,
        "hud": 4,
        "webasto": 4,
        "led": 3,
        "matrix": 4,
        "harman": 3,
        "bowers": 4,
    }

    for keyword, points in plus_keywords.items():
        if keyword in text:
            score += points

    # STANJE
    stanje_plus = {
        "prvi vlasnik": 10,
        "1 vlasnik": 10,
        "servisna": 6,
        "servisna knjiga": 8,
        "bez ulaganja": 8,
        "kupljen u srbiji": 6,
        "garaziran": 5,
    }

    for keyword, points in stanje_plus.items():
        if keyword in text:
            score += points

    stanje_minus = {
        "udaren": -25,
        "ostecen": -20,
        "oštećen": -20,
        "hitno": -5,
        "zamena": -5,
        "fiksno": -3,
        "potrebna ulaganja": -15,
    }

    for keyword, points in stanje_minus.items():
        if keyword in text:
            score += points

    # TREND CENE
    if ukupno_snizenje >= 2000:
        score += 12
    elif ukupno_snizenje >= 1000:
        score += 8
    elif ukupno_snizenje > 0:
        score += 4

    if promena_tip == "snizenje":
        score += 5

    if promena_tip == "poskupljenje":
        score -= 8

    # LIMIT
    if score > 100:
        score = 100

    if score < 0:
        score = 0

    return round(score)


def proveri_oglas(url):
    try:
        response = requests.get(url, headers=HEADERS, timeout=20)
        response.raise_for_status()

    except Exception as e:
        print("Greška:", e)
        return None, None, None, "", False

    soup = BeautifulSoup(response.text, "html.parser")

    cena = izvuci_cenu(soup, response.text)
    slika = izvuci_sliku(soup)
    naziv = izvuci_naziv(soup)

    return cena, slika, naziv, response.text, True


def main():
    oglasi = ucitaj_oglase()
    baza = ucitaj_bazu()

    now = datetime.now().strftime("%d.%m.%Y %H:%M")

    for oglas in oglasi:
        url = oglas["url"]

        print("\nPROVERA:", url)

        cena, slika, naziv, html, aktivan = proveri_oglas(url)

        stara = baza.get(url, {})

        label = (
            oglas.get("label")
            or stara.get("label")
            or naziv
            or "Oglas"
        )

        model = extract_model(label)

        prethodna_cena = stara.get("cena")

        if not aktivan:
            baza[url] = {
                **stara,
                "aktivan": False,
                "poslednja_provera": now,
            }

            continue

        final_cena = cena if cena else prethodna_cena

        prva_cena = stara.get("prva_cena") or final_cena
        najmanja_cena = stara.get("najmanja_cena") or final_cena

        promena = 0
        promena_tip = "bez_promene"

        ukupno_snizenje = stara.get("ukupno_snizenje", 0)
        broj_promena = stara.get("broj_promena", 0)

        if prethodna_cena and final_cena:
            if final_cena != prethodna_cena:
                promena = final_cena - prethodna_cena
                broj_promena += 1

                if promena < 0:
                    promena_tip = "snizenje"
                    ukupno_snizenje += abs(promena)
                else:
                    promena_tip = "poskupljenje"

        if final_cena and najmanja_cena:
            najmanja_cena = min(final_cena, najmanja_cena)

        market_avg = market_average(model, baza)

        score = calculate_score(
            label=label,
            html=html,
            cena=final_cena,
            market_avg=market_avg,
            prva_cena=prva_cena,
            najmanja_cena=najmanja_cena,
            ukupno_snizenje=ukupno_snizenje,
            promena_tip=promena_tip,
        )

        print("MODEL:", model)
        print("MARKET AVG:", market_avg)
        print("SCORE:", score)

        baza[url] = {
            "label": label,
            "model": model,
            "cena": final_cena,
            "prva_cena": prva_cena,
            "najmanja_cena": najmanja_cena,
            "broj_promena": broj_promena,
            "ukupno_snizenje": ukupno_snizenje,
            "slika": slika or stara.get("slika"),
            "prethodna_cena": prethodna_cena,
            "promena": promena,
            "promena_tip": promena_tip,
            "datum_promene": now if promena != 0 else stara.get("datum_promene"),
            "aktivan": True,
            "problem_cena": cena is None,
            "poslednja_provera": now,
            "score": score,
        }

        time.sleep(PAUZA)

    sacuvaj_bazu(baza)

    print("\nGOTOVO")


if __name__ == "__main__":
    main()
