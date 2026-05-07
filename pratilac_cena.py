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
    "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/135.0.0.0 Safari/537.36",
    "Accept-Language": "sr-RS,sr;q=0.9,en-US;q=0.8,en;q=0.7",
    "Accept": "text/html,application/xhtml+xml,application/xml;q=0.9,image/webp,*/*;q=0.8",
    "Connection": "keep-alive",
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

                if 1000 <= cena <= 300000:
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


def proveri_oglas(url):
    try:
        resp = requests.get(url, headers=HEADERS, timeout=20)
        resp.raise_for_status()

    except Exception as e:
        print(f"Greška pri otvaranju oglasa: {e}")
        return None, False

    soup = BeautifulSoup(resp.text, "html.parser")
    cena = izvuci_cenu(soup, resp.text)

    print(f"Pronađena cena: {cena}")

    return cena, True


def format_cena(cena):
    if cena is None:
        return "N/A"
    return f"{cena:,}".replace(",", ".") + " €"


def posalji_email(snizenja):
    if not snizenja:
        return

    html = "<h2>🚗 Sniženje cene!</h2>"

    for s in snizenja:
        html += f"""
        <p>
        <a href="{s['url']}">{s['label']}</a><br>
        Prethodna cena: <s>{format_cena(s['stara'])}</s><br>
        Nova cena: <strong>{format_cena(s['nova'])}</strong><br>
        Sniženje: <strong>{format_cena(s['razlika'])}</strong>
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
            "subject": f"🚗 Sniženje cene oglasa ({len(snizenja)})",
            "html": html,
        },
    )


def main():
    oglasi = ucitaj_oglase()
    baza = ucitaj_bazu()

    snizenja = []
    sada = datetime.now().strftime("%d.%m.%Y %H:%M")

    for oglas in oglasi:
        url = oglas["url"]
        label = oglas["label"]

        print(f"Proveravam: {label}")

        cena, aktivan = proveri_oglas(url)

        if not aktivan:
            print("Oglas nedostupan")
            continue

        stara_baza = baza.get(url, {})
        stara_cena = stara_baza.get("cena")

        prethodna_cena = stara_baza.get("prethodna_cena")
        promena = 0
        promena_tip = "bez_promene"
        datum_promene = stara_baza.get("datum_promene")

        if stara_cena and cena:
            if cena < stara_cena:
                prethodna_cena = stara_cena
                promena = stara_cena - cena
                promena_tip = "snizenje"
                datum_promene = sada

                snizenja.append({
                    "url": url,
                    "label": label,
                    "stara": stara_cena,
                    "nova": cena,
                    "razlika": promena,
                })

            elif cena > stara_cena:
                prethodna_cena = stara_cena
                promena = cena - stara_cena
                promena_tip = "povecanje"
                datum_promene = sada

        baza[url] = {
            "label": label,
            "cena": cena,
            "prethodna_cena": prethodna_cena,
            "promena": promena,
            "promena_tip": promena_tip,
            "datum_promene": datum_promene,
            "aktivan": aktivan,
            "poslednja_provera": sada
        }

        time.sleep(PAUZA)

    sacuvaj_bazu(baza)
    posalji_email(snizenja)

    print("Gotovo.")


if __name__ == "__main__":
    main()
