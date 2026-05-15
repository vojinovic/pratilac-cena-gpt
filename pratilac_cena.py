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
PAUZA = 4

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


def ucitaj_bazu():
    if os.path.exists(BAZA_FAJL):
        with open(BAZA_FAJL, "r", encoding="utf-8") as f:
            return json.load(f)
    return {}


def sacuvaj_bazu(baza):
    with open(BAZA_FAJL, "w", encoding="utf-8") as f:
        json.dump(baza, f, ensure_ascii=False, indent=2)


def parsiraj_broj(text):
    if not text:
        return None

    cifre = re.sub(r"[^\d]", "", str(text))

    if not cifre:
        return None

    cena = int(cifre)

    if 1000 <= cena <= 500000:
        return cena

    return None


def izvuci_cenu(soup):
    el = soup.find("span", class_="priceClassified")

    if el:
        cena = parsiraj_broj(el.get_text(" ", strip=True))
        if cena:
            return cena

    el = soup.find(class_=re.compile(r"priceClassified"))

    if el:
        cena = parsiraj_broj(el.get_text(" ", strip=True))
        if cena:
            return cena

    meta = soup.find("meta", attrs={"property": "product:price:amount"})
    if meta and meta.get("content"):
        cena = parsiraj_broj(meta.get("content"))
        if cena:
            return cena

    return None


def izvuci_sliku(soup):
    meta = soup.find("meta", property="og:image")

    if meta and meta.get("content"):
        return meta.get("content")

    return None


def izvuci_naziv(soup):
    h1 = soup.find("h1")

    if h1:
        return h1.get_text(" ", strip=True)

    title = soup.find("title")

    if title:
        text = title.get_text(" ", strip=True)
        text = text.replace("| Polovni Automobili", "").replace("- Polovni automobili", "").replace("Polovni Automobili", "").strip()
        return text

    return "Oglas"


def extract_model(url):
    if not url:
        return "unknown"

    match = re.search(r"/auto-oglasi/\d+/([^/?#]+)", url)

    if not match:
        return "unknown"

    slug = match.group(1).lower()

    delovi = slug.split("-")

    if len(delovi) >= 2:
        return delovi[0] + "-" + delovi[1]

    if len(delovi) == 1:
        return delovi[0]

    return "unknown"


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

    if score > 100:
        score = 100

    if score < 0:
        score = 0

    return round(score)


def proveri_oglas(url):
    try:
        response = requests.get(url, headers=HEADERS, timeout=20)
        response.raise_for_status()

        # FIX: prisilno postavi UTF-8 jer requests pogađa Latin-1 i to lomi naše š/č/ć/ž
        response.encoding = "utf-8"

    except Exception as e:
        print("Greška:", e)
        return None, None, None, "", False

    # Detekcija obrisanog oglasa: polovniautomobili redirektuje na search stranicu
    # sa ?redirect_message=1 parametrom
    final_url = response.url
    if "redirect_message" in final_url or "/auto-oglasi/pretraga" in final_url:
        print(f"  OGLAS OBRISAN (redirect na: {final_url})")
        return None, None, None, "", False

    soup = BeautifulSoup(response.text, "html.parser")

    cena = izvuci_cenu(soup)
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

        # Custom label korisnika -> ako nema, sveži naziv iz HTML -> tek onda stari
        # (sveži pre starog jer je možda ranije bio polomljen UTF-8)
        label = (
            oglas.get("label")
            or naziv
            or stara.get("label")
            or "Oglas"
        )

        model = extract_model(url)

        if not aktivan:
            baza[url] = {
                **stara,
                "label": label,
                "model": model,
                "aktivan": False,
                "problem_cena": True,
                "poslednja_provera": now,
            }

            continue

        if cena is None:
            print("UPOZORENJE: Stranica učitana ali cena nije pronađena")

            baza[url] = {
                **stara,
                "label": label,
                "model": model,
                "slika": slika or stara.get("slika"),
                "problem_cena": True,
                "aktivan": True,
                "poslednja_provera": now,
            }

            time.sleep(PAUZA)
            continue

        prethodna_cena = stara.get("cena")

        prva_cena = stara.get("prva_cena") or cena
        najmanja_cena = stara.get("najmanja_cena") or cena

        promena = 0
        promena_tip = "bez_promene"

        ukupno_snizenje = stara.get("ukupno_snizenje", 0)
        broj_promena = stara.get("broj_promena", 0)

        if prethodna_cena:
            if cena != prethodna_cena:
                promena = cena - prethodna_cena
                broj_promena += 1

                if promena < 0:
                    promena_tip = "snizenje"
                    ukupno_snizenje += abs(promena)
                else:
                    promena_tip = "poskupljenje"

        najmanja_cena = min(cena, najmanja_cena)

        market_avg = market_average(model, baza)

        score = calculate_score(
            label=label,
            html=html,
            cena=cena,
            market_avg=market_avg,
            prva_cena=prva_cena,
            najmanja_cena=najmanja_cena,
            ukupno_snizenje=ukupno_snizenje,
            promena_tip=promena_tip,
        )

        print("MODEL:", model)
        print("MARKET AVG:", market_avg)
        print("CENA:", cena)
        print("SCORE:", score)
        print("LABEL:", label)

        baza[url] = {
            "label": label,
            "model": model,
            "cena": cena,
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
            "problem_cena": False,
            "poslednja_provera": now,
            "score": score,
        }

        time.sleep(PAUZA)

    sacuvaj_bazu(baza)

    print("\nGOTOVO")


if __name__ == "__main__":
    main()
