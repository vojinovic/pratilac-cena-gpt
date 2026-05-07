# pratilac_cena.py

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
    "User-Agent": "Mozilla/5.0"
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


def izvuci_cenu(text):

    patterns = [
        r'([\d\.]+)\s*€',
        r'([\d\.]+)\s*EUR',
    ]

    for pattern in patterns:

        match = re.search(pattern, text)

        if match:

            cena = match.group(1)

            cena = cena.replace(".", "")
            cena = cena.replace(",", "")

            try:
                return int(cena)
            except:
                pass

    return None


def izvuci_sliku(soup):

    # og:image
    meta = soup.find("meta", property="og:image")

    if meta and meta.get("content"):

        url = meta.get("content").strip()

        if url.startswith("http"):
            return url

    # twitter:image
    meta2 = soup.find("meta", attrs={"name": "twitter:image"})

    if meta2 and meta2.get("content"):

        url = meta2.get("content").strip()

        if url.startswith("http"):
            return url

    # fallback
    imgs = soup.find_all("img")

    for img in imgs:

        src = img.get("src")

        if not src:
            continue

        src = src.strip()

        if "gcdn.polovniautomobili.com" in src:
            return src

    return None


def izvuci_naziv(soup):

    title = soup.find("title")

    if title:

        text = title.get_text(strip=True)

        text = text.replace("| Polovni Automobili", "")
        text = text.strip()

        return text

    return "Oglas"


def calculate_score(
    label,
    html,
    cena,
    prva_cena,
    najmanja_cena,
    broj_promena,
    ukupno_snizenje,
    promena_tip
):

    text = ((label or "") + " " + (html or "")).lower()

    score = 50

    # cena
    if cena:

        if cena < 25000:
            score += 20

        elif cena < 30000:
            score += 15

        elif cena < 35000:
            score += 10

        elif cena > 45000:
            score -= 10

    # snizenje
    if prva_cena and cena and prva_cena > cena:

        pad_proc = ((prva_cena - cena) / prva_cena) * 100

        if pad_proc > 15:
            score += 25

        elif pad_proc > 10:
            score += 20

        elif pad_proc > 5:
            score += 10

    # oprema
    bonus_keywords = [
        "r-design",
        "inscription",
        "momentum",
        "awd",
        "4x4",
        "pano",
        "panorama",
        "matrix",
        "hud",
        "360",
        "massage",
        "memorija",
        "acc",
        "full",
        "ful"
    ]

    for kw in bonus_keywords:

        if kw in text:
            score += 3

    # dobri signali
    good_signals = [
        "prvi vlasnik",
        "1 vlasnik",
        "servisna",
        "garaza",
        "garažiran",
        "bez ulaganja",
        "kao nov"
    ]

    for kw in good_signals:

        if kw in text:
            score += 5

    # losi signali
    bad_signals = [
        "hitno",
        "fiksno",
        "zamena",
        "ostecen",
        "oštećen"
    ]

    for kw in bad_signals:

        if kw in text:
            score -= 5

    score = max(0, min(score, 100))

    return round(score)


def proveri_oglas(url):

    try:

        resp = requests.get(
            url,
            headers=HEADERS,
            timeout=20
        )

        html = resp.text

        soup = BeautifulSoup(html, "html.parser")

        cena = izvuci_cenu(html)

        slika = izvuci_sliku(soup)

        naziv = izvuci_naziv(soup)

        return cena, slika, naziv, html, True

    except Exception as e:

        print("GRESKA:", e)

        return None, None, None, "", False


def main():

    oglasi = ucitaj_oglase()

    baza = ucitaj_bazu()

    now = datetime.now().strftime("%d.%m.%Y %H:%M")

    for oglas in oglasi:

        url = oglas["url"]

        print("\nPROVERA:", url)

        cena, slika, naziv, html, aktivan = proveri_oglas(url)

        if url not in baza:

            baza[url] = {
                "label": oglas.get("label") or naziv,
                "cena": cena,
                "prva_cena": cena,
                "najmanja_cena": cena,
                "broj_promena": 0,
                "ukupno_snizenje": 0,
                "slika": slika,
                "prethodna_cena": None,
                "promena": 0,
                "promena_tip": "bez_promene",
                "datum_promene": None,
                "aktivan": aktivan,
                "problem_cena": False,
                "poslednja_provera": now,
                "score": 0
            }

        else:

            stara = baza[url]

            prethodna_cena = stara.get("cena")

            promena = 0

            promena_tip = "bez_promene"

            if cena and prethodna_cena:

                promena = cena - prethodna_cena

                if promena < 0:
                    promena_tip = "snizenje"

                elif promena > 0:
                    promena_tip = "poskupljenje"

            if cena and (
                stara.get("najmanja_cena") is None
                or cena < stara.get("najmanja_cena")
            ):
                stara["najmanja_cena"] = cena

            if promena != 0:
                stara["broj_promena"] += 1

            if promena < 0:
                stara["ukupno_snizenje"] += abs(promena)

            stara["prethodna_cena"] = prethodna_cena
            stara["cena"] = cena or prethodna_cena
            stara["promena"] = promena
            stara["promena_tip"] = promena_tip
            stara["datum_promene"] = now if promena != 0 else stara.get("datum_promene")
            stara["slika"] = slika or stara.get("slika")
            stara["aktivan"] = aktivan
            stara["problem_cena"] = cena is None
            stara["poslednja_provera"] = now

        baza[url]["score"] = calculate_score(
            baza[url].get("label"),
            html,
            baza[url].get("cena"),
            baza[url].get("prva_cena"),
            baza[url].get("najmanja_cena"),
            baza[url].get("broj_promena"),
            baza[url].get("ukupno_snizenje"),
            baza[url].get("promena_tip")
        )

        print("SCORE:", baza[url]["score"])

        time.sleep(PAUZA)

    sacuvaj_bazu(baza)

    print("\nGOTOVO")


if __name__ == "__main__":
    main()
