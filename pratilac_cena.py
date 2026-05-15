#!/usr/bin/env python3
"""
Pratilac cena - multi-user verzija.

Workflow:
1. GET /admin/all-oglasi?key=SCRAPER_SECRET → dobija oglase svih korisnika
2. Za svakog korisnika, scrape-uje sve oglase
3. POST /admin/save-cene?key=SCRAPER_SECRET → upisuje cene nazad u worker (KV)
"""

import json
import os
import re
import time
from datetime import datetime

from curl_cffi import requests
from bs4 import BeautifulSoup

API_URL = os.environ.get("API_URL", "https://pratilac-cena-api.vojinovic82.workers.dev")
SCRAPER_SECRET = os.environ.get("SCRAPER_SECRET", "")
PAUZA = 4


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


def izvuci_data_layer(html):
    """Izvlači dataLayer JSON sa strukturiranim podacima."""
    pattern = r'dataLayer\.push\((\{[^;]*?"object_uid"[^;]*?\})\);'
    match = re.search(pattern, html)
    if not match:
        return {}
    try:
        return json.loads(match.group(1))
    except (json.JSONDecodeError, ValueError):
        return {}


def izvuci_cenu(soup, data_layer=None):
    if data_layer and data_layer.get("object_price"):
        cena = parsiraj_broj(data_layer.get("object_price"))
        if cena:
            return cena

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

    el = soup.find(attrs={"data-title": True})
    if el:
        title = el.get("data-title", "")
        match = re.search(r"-\s*([\d.,]+)\s*€", title)
        if match:
            cena = parsiraj_broj(match.group(1))
            if cena:
                return cena

    return None


def izvuci_sliku(soup):
    meta = soup.find("meta", property="og:image")
    if meta and meta.get("content"):
        return meta.get("content")
    return None


def izvuci_naziv(soup, data_layer=None):
    if data_layer and data_layer.get("name"):
        return data_layer.get("name")

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
    cene = [d["cena"] for _, d in baza.items() if d.get("model") == model and d.get("cena")]
    if not cene:
        return None
    return sum(cene) / len(cene)


def calculate_score(label, html, cena, market_avg, ukupno_snizenje, promena_tip, data_layer=None):
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
        "awd": 5, "4x4": 5, "r-design": 5, "inscription": 5,
        "momentum": 3, "sport": 4, "pano": 5, "panorama": 5,
        "kamera": 3, "hud": 4, "webasto": 4, "led": 3,
        "matrix": 4, "harman": 3, "bowers": 4,
    }
    for keyword, points in plus_keywords.items():
        if keyword in text:
            score += points

    if data_layer:
        if data_layer.get("object_prvi_vlasnik") == "yes":
            score += 10
        if data_layer.get("object_servisna_knjizica") == "yes":
            score += 8
        if data_layer.get("object_garancija") == "yes":
            score += 8
        if data_layer.get("object_kupljen_nov_u_srbiji") == "yes":
            score += 6

        damage = (data_layer.get("object_damage") or "").lower()
        if "udaren" in damage:
            score -= 25
        elif "oštećen" in damage and "nije" not in damage:
            score -= 20

        if data_layer.get("object_taxi") == "yes":
            score -= 15

    if "hitno" in text:
        score -= 5
    if "zamena" in text:
        score -= 5
    if "fiksno" in text:
        score -= 3
    if "potrebna ulaganja" in text:
        score -= 15

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

    return max(0, min(100, round(score)))


def proveri_oglas(url):
    try:
        response = requests.get(url, impersonate="chrome", timeout=20)
        response.raise_for_status()
        response.encoding = "utf-8"
    except Exception as e:
        print("Greška:", e)
        return None, None, None, "", {}, False

    final_url = response.url
    if "redirect_message" in final_url or "/auto-oglasi/pretraga" in final_url:
        print(f"  OGLAS OBRISAN (redirect na: {final_url})")
        return None, None, None, "", {}, False

    soup = BeautifulSoup(response.text, "html.parser")
    data_layer = izvuci_data_layer(response.text)

    cena = izvuci_cenu(soup, data_layer)
    slika = izvuci_sliku(soup)
    naziv = izvuci_naziv(soup, data_layer)

    return cena, slika, naziv, response.text, data_layer, True


def fetch_all_oglasi():
    """Vraca {email: [oglasi]} mapu iz worker-a."""
    url = f"{API_URL}/admin/all-oglasi?key={SCRAPER_SECRET}"
    print(f"GET {url[:60]}...")
    res = requests.get(url, timeout=30)
    res.raise_for_status()
    data = res.json()
    return data.get("users", {})


def save_cene_for_user(email, cene):
    """Salje cene za jednog korisnika u worker."""
    url = f"{API_URL}/admin/save-cene?key={SCRAPER_SECRET}"
    res = requests.post(
        url,
        json={"user_email": email, "cene": cene},
        timeout=30
    )
    res.raise_for_status()
    return res.json()


def fetch_user_cene(email):
    """Trenutne cene za usera (da bismo imali prethodno stanje za diff)."""
    # Worker nema endpoint za ovo (samo /data zahteva auth)
    # Workaround: koristimo cene koje smo upravo skrejpovali i merge na worker strani
    return {}


def scrape_for_user(email, oglasi):
    """Scrape sve oglase jednog korisnika i vrati cene mapu."""
    print(f"\n{'=' * 70}")
    print(f"USER: {email} | {len(oglasi)} oglasa")
    print(f"{'=' * 70}")

    now = datetime.now().strftime("%d.%m.%Y %H:%M")
    now_iso = datetime.now().strftime("%Y-%m-%d %H:%M:%S")

    # Trenutne cene iz worker-a (ne mozemo direktno - workflow nema user JWT)
    # Resenje: worker /admin/save-cene merge-uje sa postojecima, pa nije problem
    baza_nova = {}

    for oglas in oglasi:
        url = oglas["url"]
        print(f"\nPROVERA: {url}")

        cena, slika, naziv, html, data_layer, aktivan = proveri_oglas(url)

        label = oglas.get("label") or naziv or "Oglas"
        model = extract_model(url)

        if not aktivan:
            baza_nova[url] = {
                "label": label,
                "model": model,
                "aktivan": False,
                "problem_cena": True,
                "poslednja_provera": now,
            }
            continue

        if cena is None:
            print("UPOZORENJE: cena nije pronađena")
            baza_nova[url] = {
                "label": label,
                "model": model,
                "slika": slika,
                "problem_cena": True,
                "aktivan": True,
                "poslednja_provera": now,
            }
            time.sleep(PAUZA)
            continue

        # Strukturisani podaci iz dataLayer
        godiste = None
        kilometraza = None
        gorivo = None
        karoserija = None
        last_renewed_date = None

        if data_layer:
            try:
                if data_layer.get("object_production_year"):
                    godiste = int(data_layer.get("object_production_year"))
            except (ValueError, TypeError):
                pass
            try:
                if data_layer.get("object_mileage"):
                    kilometraza = int(data_layer.get("object_mileage"))
            except (ValueError, TypeError):
                pass
            gorivo = data_layer.get("object_fuel")
            karoserija = data_layer.get("object_chassis")
            last_renewed_date = data_layer.get("object_last_renewed_date")

        market_avg = market_average(model, baza_nova)
        score = calculate_score(
            label=label,
            html=html,
            cena=cena,
            market_avg=market_avg,
            ukupno_snizenje=0,
            promena_tip="bez_promene",
            data_layer=data_layer,
        )

        print(f"MODEL: {model} | CENA: {cena} | GODIŠTE: {godiste} | KM: {kilometraza} | SCORE: {score}")

        baza_nova[url] = {
            "label": label,
            "model": model,
            "cena": cena,
            "godiste": godiste,
            "kilometraza": kilometraza,
            "gorivo": gorivo,
            "karoserija": karoserija,
            "prva_cena": cena,
            "najmanja_cena": cena,
            "broj_promena": 0,
            "ukupno_snizenje": 0,
            "slika": slika,
            "prethodna_cena": cena,
            "promena": 0,
            "promena_tip": "bez_promene",
            "aktivan": True,
            "problem_cena": False,
            "poslednja_provera": now,
            "score": score,
            "last_renewed_date": last_renewed_date,
            "prvi_vlasnik": data_layer.get("object_prvi_vlasnik") == "yes" if data_layer else False,
            "servisna_knjizica": data_layer.get("object_servisna_knjizica") == "yes" if data_layer else False,
            "garancija": data_layer.get("object_garancija") == "yes" if data_layer else False,
            "kupljen_nov_u_srbiji": data_layer.get("object_kupljen_nov_u_srbiji") == "yes" if data_layer else False,
            "damage": data_layer.get("object_damage") if data_layer else None,
            "owner_name": data_layer.get("companyName") if data_layer else None,
        }

        time.sleep(PAUZA)

    return baza_nova


def main():
    if not SCRAPER_SECRET:
        print("GREŠKA: SCRAPER_SECRET nije postavljen")
        return

    print(f"API: {API_URL}")
    users_oglasi = fetch_all_oglasi()
    print(f"\nPronađeno {len(users_oglasi)} korisnika sa oglasima")

    for email, oglasi in users_oglasi.items():
        if not oglasi:
            print(f"\n{email}: nema oglasa, preskačem")
            continue

        try:
            cene = scrape_for_user(email, oglasi)
            print(f"\n>>> Šaljem {len(cene)} cena za {email}...")
            result = save_cene_for_user(email, cene)
            print(f">>> Uspešno: {result}")
        except Exception as e:
            print(f"GREŠKA za {email}: {e}")
            continue

    print("\nGOTOVO")


if __name__ == "__main__":
    main()
