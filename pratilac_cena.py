#!/usr/bin/env python3
"""
Pratilac cena - multi-user verzija sa proširenim podacima.

Izvlači iz oglasa: opis, zemlju uvoza, boju, VIN, pogon, opremu, rating prodavca,
emisionu klasu - i koristi te podatke u scoring sistemu.
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


# ========================================================================
# PARSIRANJE OGLASA
# ========================================================================

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


def izvuci_opis(soup):
    """Izvuče slobodan tekstualni opis oglasa."""
    el = soup.find("div", class_="description-wrapper")
    if el:
        return el.get_text("\n", strip=True)

    # Schema.org Car description
    for script in soup.find_all("script", type="application/ld+json"):
        try:
            data = json.loads(script.string or "{}")
            items = data if isinstance(data, list) else [data]
            for item in items:
                if isinstance(item, dict):
                    offer = item.get("makesOffer") or {}
                    car = offer.get("itemOffered") or {}
                    desc = car.get("description")
                    if desc:
                        return desc
        except (json.JSONDecodeError, AttributeError, TypeError):
            continue

    return None


def izvuci_dodatne_info(soup):
    """
    Izvuče polja iz "Dodatne informacije" sekcije:
    Boja, Materijal enterijera, Boja enterijera, Zemlja uvoza, Poreklo vozila,
    Pogon, Emisiona klasa, Broj sedišta, Plivajući zamajac.
    """
    result = {}

    # Svi divovi sa labelima u "Dodatne informacije"
    for divider in soup.find_all("div", class_="divider"):
        cells = divider.find_all("div", recursive=True)
        # Tipično: <div class="divider"><div class="uk-grid"><div>Label</div><div class="uk-text-bold">Value</div></div></div>
        text_cells = []
        for c in cells:
            text = c.get_text(" ", strip=True)
            if text and not c.find("div"):  # samo leaf divovi
                text_cells.append(text)

        if len(text_cells) >= 2:
            label = text_cells[0].lower().rstrip(":")
            value = text_cells[1].strip()

            if "zemlja uvoza" in label:
                result["zemlja_uvoza"] = value
            elif label == "boja":
                result["boja"] = value
            elif "materijal enterijera" in label:
                result["enterijer_materijal"] = value
            elif "boja enterijera" in label:
                result["boja_enterijera"] = value
            elif "poreklo vozila" in label:
                result["poreklo"] = value
            elif label == "pogon":
                result["pogon"] = value
            elif "emisiona klasa" in label:
                result["emisiona_klasa"] = value
            elif "broj sedi" in label:
                result["broj_sedista"] = value
            elif "broj vrata" in label:
                result["broj_vrata"] = value
            elif "broj šasije" in label or "broj sasije" in label:
                result["vin"] = value

    return result


def izvuci_opremu(soup):
    """
    Izvuče listu opreme/sigurnosti iz odgovarajućih sekcija (Sigurnost, Oprema, Stanje).
    Svaka stavka je u <div class="uk-width-medium-1-4 uk-width-1-2 uk-margin-small-bottom">.
    """
    oprema = []

    for section in soup.find_all("section"):
        h2 = section.find("h2", class_="classified-title")
        if not h2:
            continue
        h2_text = h2.get_text(" ", strip=True).lower()

        if "sigurnost" in h2_text or "oprema" in h2_text or "stanje" in h2_text:
            for div in section.find_all("div", class_=re.compile(r"uk-width-medium-1-4")):
                text = div.get_text(" ", strip=True)
                if text and text not in oprema and len(text) < 50:
                    oprema.append(text)

    return oprema


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


def extract_brand(model):
    if not model or model == "unknown":
        return None
    return model.split("-")[0]


# ========================================================================
# MARKET STATISTIKE
# ========================================================================

def _avg(arr):
    return sum(arr) / len(arr) if arr else None


def market_stats(model, karoserija, baza, min_sample=3):
    same_model = [d for d in baza.values() if d.get("model") == model and d.get("cena")]

    if len(same_model) >= min_sample:
        scope = "model"
        items = same_model
    else:
        brand = extract_brand(model)
        if brand and karoserija:
            wider = [
                d for d in baza.values()
                if extract_brand(d.get("model") or "") == brand
                and d.get("karoserija") == karoserija
                and d.get("cena")
            ]
            if len(wider) >= min_sample:
                scope = "brand+chassis"
                items = wider
            else:
                scope = "model"
                items = same_model
        else:
            scope = "model"
            items = same_model

    cene = [d["cena"] for d in items if d.get("cena")]
    kms = [d["kilometraza"] for d in items if d.get("kilometraza")]
    godine = [d["godiste"] for d in items if d.get("godiste")]

    return {
        "scope": scope,
        "sample_size": len(items),
        "avg_cena": _avg(cene),
        "avg_km": _avg(kms),
        "avg_godiste": _avg(godine),
    }


def days_since(date_str):
    if not date_str:
        return None
    try:
        date = datetime.strptime(date_str, "%Y-%m-%d %H:%M:%S")
        delta = datetime.now() - date
        return delta.days
    except (ValueError, TypeError):
        return None


# ========================================================================
# BRAND-SPECIFIC PAKETI
# ========================================================================

PACKAGE_KEYWORDS = {
    "volvo": {
        "top": ["r-design", "r design", "polestar", "inscription"],
        "mid": ["momentum", "summum", "ocean race"],
    },
    "bmw": {
        "top": ["m sport", "m-sport", "m pack", "m paket", "m performance"],
        "mid": ["luxury line", "sport line", "modern line"],
    },
    "audi": {
        "top": ["s line", "s-line", "rs ", "quattro"],
        "mid": ["design", "advanced"],
    },
    "mercedes-benz": {
        "top": ["amg", "amg line"],
        "mid": ["avantgarde", "exclusive"],
    },
    "skoda": {
        "top": ["rs ", "sportline", "monte carlo"],
        "mid": ["style", "ambition"],
    },
    "volkswagen": {
        "top": ["r-line", "r line", "gti", "gtd"],
        "mid": ["highline", "comfortline"],
    },
    "porsche": {
        "top": [" s ", "gts", "turbo", "4s"],
        "mid": [],
    },
}

# Zemlje uvoza - na osnovu reputacije održavanja
GOOD_IMPORT_COUNTRIES = {"italija", "nemačka", "nemacka", "austrija", "švajcarska", "svajcarska", "francuska", "holandija", "belgija", "luksemburg", "danska", "švedska", "svedska"}
BAD_IMPORT_COUNTRIES = {"bugarska", "rumunija", "albanija", "ukrajina", "moldavija"}

NEGATIVE_TITLE_KEYWORDS = {
    "havarisan": -20,
    "udaren": -15,
    "oštećen": -10,
    "ostecen": -10,
    "hitno": -3,
    "zamena": -3,
}


# ========================================================================
# SCORING V3
# ========================================================================

def calculate_score_v3(
    cena, naslov, kilometraza, godiste,
    market_stats_data, structured_data, extra_info,
    last_renewed_date, promena_tip, ukupno_snizenje, model,
):
    breakdown = []
    market_cena = market_stats_data.get("avg_cena") if market_stats_data else None
    market_km = market_stats_data.get("avg_km") if market_stats_data else None
    market_god = market_stats_data.get("avg_godiste") if market_stats_data else None

    naslov_lower = (naslov or "").lower()
    brand = extract_brand(model) if model else None

    # CENA (max ~30)
    if market_cena and cena:
        diff = ((market_cena - cena) / market_cena) * 100
        if diff >= 20:
            breakdown.append({"label": f"Cena {diff:.0f}% niža od proseka", "value": 30, "category": "cena"})
        elif diff >= 15:
            breakdown.append({"label": f"Cena {diff:.0f}% niža od proseka", "value": 25, "category": "cena"})
        elif diff >= 10:
            breakdown.append({"label": f"Cena {diff:.0f}% niža od proseka", "value": 20, "category": "cena"})
        elif diff >= 5:
            breakdown.append({"label": f"Cena {diff:.0f}% niža od proseka", "value": 12, "category": "cena"})
        elif diff <= -10:
            breakdown.append({"label": f"Cena {abs(diff):.0f}% viša od proseka", "value": -15, "category": "cena"})
        elif diff <= -5:
            breakdown.append({"label": f"Cena {abs(diff):.0f}% viša od proseka", "value": -5, "category": "cena"})

    if ukupno_snizenje and ukupno_snizenje >= 2000:
        breakdown.append({"label": f"Pad cene ukupno {ukupno_snizenje}€", "value": 5, "category": "cena"})
    elif ukupno_snizenje and ukupno_snizenje >= 1000:
        breakdown.append({"label": f"Pad cene ukupno {ukupno_snizenje}€", "value": 3, "category": "cena"})

    if promena_tip == "snizenje":
        breakdown.append({"label": "Skorašnje sniženje", "value": 3, "category": "cena"})
    elif promena_tip == "poskupljenje":
        breakdown.append({"label": "Skorašnje poskupljenje", "value": -5, "category": "cena"})

    # STANJE (max ~30)
    has_damage = False
    if structured_data:
        if structured_data.get("object_prvi_vlasnik") == "yes":
            breakdown.append({"label": "Prvi vlasnik", "value": 6, "category": "stanje"})
        if structured_data.get("object_servisna_knjizica") == "yes":
            breakdown.append({"label": "Servisna knjižica", "value": 5, "category": "stanje"})
        if structured_data.get("object_garancija") == "yes":
            breakdown.append({"label": "Garancija", "value": 4, "category": "stanje"})
        if structured_data.get("object_kupljen_nov_u_srbiji") == "yes":
            breakdown.append({"label": "Kupljen nov u Srbiji", "value": 5, "category": "stanje"})

        damage = (structured_data.get("object_damage") or "").lower()
        if "udaren" in damage:
            breakdown.append({"label": "Auto je udaran", "value": -25, "category": "stanje"})
            has_damage = True
        elif "oštećen" in damage and "nije" not in damage:
            breakdown.append({"label": "Auto je oštećen", "value": -20, "category": "stanje"})
            has_damage = True
        elif "nije" in damage:
            breakdown.append({"label": "Bez oštećenja", "value": 5, "category": "stanje"})

        if structured_data.get("object_taxi") == "yes":
            breakdown.append({"label": "Taksi vozilo", "value": -15, "category": "stanje"})
        if structured_data.get("object_test_vozilo") == "yes":
            breakdown.append({"label": "Test vozilo", "value": -5, "category": "stanje"})

    # Negativni keywords u naslovu
    if not has_damage:
        for kw, val in NEGATIVE_TITLE_KEYWORDS.items():
            if val < 0 and kw in naslov_lower:
                if (kw == "ostecen" or kw == "oštećen") and "nije" in naslov_lower:
                    continue
                breakdown.append({"label": f"Naslov: '{kw}'", "value": val, "category": "stanje"})
                has_damage = True
                break

    # KILOMETRAZA (max ~18)
    if kilometraza and godiste:
        current_year = datetime.now().year
        years_old = max(current_year - godiste, 1)
        km_per_year = kilometraza / years_old

        if km_per_year <= 8000:
            breakdown.append({"label": f"Vrlo malo vožen ({km_per_year:.0f} km/god)", "value": 18, "category": "kilometraza"})
        elif km_per_year <= 12000:
            breakdown.append({"label": f"Manje vožen ({km_per_year:.0f} km/god)", "value": 10, "category": "kilometraza"})
        elif km_per_year <= 18000:
            pass  # neutralna zona
        elif km_per_year <= 25000:
            breakdown.append({"label": f"Iznad proseka ({km_per_year:.0f} km/god)", "value": -3, "category": "kilometraza"})
        elif km_per_year <= 35000:
            breakdown.append({"label": f"Mnogo vožen ({km_per_year:.0f} km/god)", "value": -8, "category": "kilometraza"})
        else:
            breakdown.append({"label": f"Ekstremno vožen ({km_per_year:.0f} km/god)", "value": -12, "category": "kilometraza"})

    # GODISTE + PAKET (max ~15)
    if market_god and godiste:
        diff = godiste - market_god
        if diff >= 2:
            breakdown.append({"label": f"Mlađi od proseka ({godiste}.)", "value": 8, "category": "godiste"})
        elif diff >= 1:
            breakdown.append({"label": f"Mlađi od proseka ({godiste}.)", "value": 4, "category": "godiste"})
        elif diff <= -2:
            breakdown.append({"label": f"Stariji od proseka ({godiste}.)", "value": -8, "category": "godiste"})
        elif diff <= -1:
            breakdown.append({"label": f"Stariji od proseka ({godiste}.)", "value": -3, "category": "godiste"})

    if brand and brand in PACKAGE_KEYWORDS:
        pkg = PACKAGE_KEYWORDS[brand]
        package_added = False
        for kw in pkg.get("top", []):
            if kw in naslov_lower:
                breakdown.append({"label": f"Top paket ({kw.strip().upper()})", "value": 5, "category": "paket"})
                package_added = True
                break
        if not package_added:
            for kw in pkg.get("mid", []):
                if kw in naslov_lower:
                    breakdown.append({"label": f"Srednji paket ({kw})", "value": 3, "category": "paket"})
                    break

    # NOVO: POREKLO/UVOZ (max ~6)
    if extra_info:
        zemlja = (extra_info.get("zemlja_uvoza") or "").lower().strip()
        if zemlja:
            if any(c in zemlja for c in GOOD_IMPORT_COUNTRIES):
                breakdown.append({"label": f"Uvoz: {extra_info['zemlja_uvoza']}", "value": 5, "category": "poreklo"})
            elif any(c in zemlja for c in BAD_IMPORT_COUNTRIES):
                breakdown.append({"label": f"Uvoz: {extra_info['zemlja_uvoza']}", "value": -3, "category": "poreklo"})

        # Pogon 4x4/AWD
        pogon = (extra_info.get("pogon") or "").lower()
        if "4x4" in pogon or "awd" in pogon or "4motion" in pogon or "quattro" in pogon:
            breakdown.append({"label": "Pogon 4x4 / AWD", "value": 4, "category": "paket"})

        # Emisiona klasa
        emisiona = (extra_info.get("emisiona_klasa") or "").lower()
        if "euro 6" in emisiona:
            breakdown.append({"label": "Euro 6", "value": 2, "category": "stanje"})
        elif "euro 5" in emisiona:
            breakdown.append({"label": "Euro 5", "value": 0, "category": "stanje"})
        elif "euro 4" in emisiona:
            breakdown.append({"label": "Euro 4", "value": -3, "category": "stanje"})
        elif "euro 3" in emisiona or "euro 2" in emisiona:
            breakdown.append({"label": f"{extra_info.get('emisiona_klasa')}", "value": -5, "category": "stanje"})

    # Rating prodavca (max ~4)
    if structured_data:
        rating = structured_data.get("object_owner_rating")
        if rating:
            try:
                r = float(rating)
                if r >= 4.5:
                    breakdown.append({"label": f"Prodavac {r}⭐", "value": 3, "category": "prodavac"})
                elif r < 3:
                    breakdown.append({"label": f"Slab prodavac {r}⭐", "value": -3, "category": "prodavac"})
            except (ValueError, TypeError):
                pass

    # SVEZINA (max ~10)
    days_renewed = days_since(last_renewed_date)
    if days_renewed is not None:
        if days_renewed <= 3:
            breakdown.append({"label": f"Svež oglas ({days_renewed}d)", "value": 10, "category": "svezina"})
        elif days_renewed <= 7:
            breakdown.append({"label": f"Svež oglas ({days_renewed}d)", "value": 7, "category": "svezina"})
        elif days_renewed <= 14:
            breakdown.append({"label": f"Skoro objavljen ({days_renewed}d)", "value": 4, "category": "svezina"})
        elif days_renewed > 60:
            breakdown.append({"label": f"Stoji predugo ({days_renewed}d)", "value": -8, "category": "svezina"})
        elif days_renewed > 30:
            breakdown.append({"label": f"Stoji {days_renewed} dana", "value": -3, "category": "svezina"})

    # OUTLIER
    outlier = False
    if market_cena and cena:
        diff = ((market_cena - cena) / market_cena) * 100
        if diff >= 25:
            neg_signals = 0
            if has_damage:
                neg_signals += 1
            if market_km and kilometraza and (kilometraza / market_km) > 1.4:
                neg_signals += 1
            if structured_data and structured_data.get("object_taxi") == "yes":
                neg_signals += 1
            for kw in ["hitno", "zamena"]:
                if kw in naslov_lower:
                    neg_signals += 1
                    break

            if neg_signals >= 2:
                outlier = True
                breakdown.append({"label": "⚠️ Sumnjivo niska cena", "value": 0, "category": "outlier"})

    raw_score = 50 + sum(item["value"] for item in breakdown)
    if outlier:
        raw_score = min(raw_score, 40)
    raw_score = max(0, min(100, raw_score))

    return {
        "score": int(round(raw_score)),
        "outlier": outlier,
        "scope": market_stats_data.get("scope") if market_stats_data else None,
        "sample_size": market_stats_data.get("sample_size") if market_stats_data else 0,
        "breakdown": breakdown,
    }


# ========================================================================
# SCRAPE
# ========================================================================

def proveri_oglas(url):
    try:
        response = requests.get(url, impersonate="chrome", timeout=20)
        response.raise_for_status()
        response.encoding = "utf-8"
    except Exception as e:
        print("Greška:", e)
        return None, None, None, "", {}, {}, "", [], False

    final_url = response.url
    if "redirect_message" in final_url or "/auto-oglasi/pretraga" in final_url:
        print(f"  OGLAS OBRISAN")
        return None, None, None, "", {}, {}, "", [], False

    soup = BeautifulSoup(response.text, "html.parser")
    data_layer = izvuci_data_layer(response.text)
    extra_info = izvuci_dodatne_info(soup)
    opis = izvuci_opis(soup)
    oprema = izvuci_opremu(soup)

    cena = izvuci_cenu(soup, data_layer)
    slika = izvuci_sliku(soup)
    naziv = izvuci_naziv(soup, data_layer)

    return cena, slika, naziv, response.text, data_layer, extra_info, opis, oprema, True


# ========================================================================
# WORKER API
# ========================================================================

def fetch_all_oglasi():
    url = f"{API_URL}/admin/all-oglasi?key={SCRAPER_SECRET}"
    res = requests.get(url, timeout=30)
    res.raise_for_status()
    data = res.json()
    return data.get("users", {})


def save_cene_for_user(email, cene):
    url = f"{API_URL}/admin/save-cene?key={SCRAPER_SECRET}"
    res = requests.post(url, json={"user_email": email, "cene": cene}, timeout=30)
    res.raise_for_status()
    return res.json()


# ========================================================================
# MAIN
# ========================================================================

def scrape_for_user(email, oglasi):
    print(f"\n{'=' * 70}")
    print(f"USER: {email} | {len(oglasi)} oglasa")
    print(f"{'=' * 70}")

    now = datetime.now().strftime("%d.%m.%Y %H:%M")
    baza_nova = {}

    # PROLAZ 1: scrape svih
    for oglas in oglasi:
        url = oglas["url"]
        print(f"\nPROVERA: {url}")

        cena, slika, naziv, html, data_layer, extra_info, opis, oprema, aktivan = proveri_oglas(url)

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
            print("  UPOZORENJE: cena nije pronađena")
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

        godiste = None
        kilometraza = None
        gorivo = None
        karoserija = None
        last_renewed_date = None
        snaga = None
        kubikaza = None

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
            try:
                if data_layer.get("object_engine_horsepower"):
                    snaga = int(data_layer.get("object_engine_horsepower"))
            except (ValueError, TypeError):
                pass
            try:
                if data_layer.get("object_engine_volume"):
                    kubikaza = int(data_layer.get("object_engine_volume"))
            except (ValueError, TypeError):
                pass

            gorivo = data_layer.get("object_fuel")
            karoserija = data_layer.get("object_chassis")
            last_renewed_date = data_layer.get("object_last_renewed_date")

        print(f"  MODEL: {model} | CENA: {cena} | {godiste}, {kilometraza}km")
        if extra_info.get("zemlja_uvoza"):
            print(f"  UVOZ: {extra_info['zemlja_uvoza']} | POGON: {extra_info.get('pogon', '')}")

        baza_nova[url] = {
            "label": label,
            "model": model,
            "cena": cena,
            "godiste": godiste,
            "kilometraza": kilometraza,
            "gorivo": gorivo,
            "karoserija": karoserija,
            "snaga": snaga,
            "kubikaza": kubikaza,
            "menjac": data_layer.get("object_gear_box") if data_layer else None,
            "klima": data_layer.get("object_air_conditioner") if data_layer else None,
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
            "last_renewed_date": last_renewed_date,
            "prvi_vlasnik": data_layer.get("object_prvi_vlasnik") == "yes" if data_layer else False,
            "servisna_knjizica": data_layer.get("object_servisna_knjizica") == "yes" if data_layer else False,
            "garancija": data_layer.get("object_garancija") == "yes" if data_layer else False,
            "kupljen_nov_u_srbiji": data_layer.get("object_kupljen_nov_u_srbiji") == "yes" if data_layer else False,
            "damage": data_layer.get("object_damage") if data_layer else None,
            "owner_name": data_layer.get("companyName") if data_layer else None,
            "owner_rating": data_layer.get("object_owner_rating") if data_layer else None,
            # NOVI PODACI
            "opis": opis,
            "oprema": oprema,
            "zemlja_uvoza": extra_info.get("zemlja_uvoza"),
            "boja": extra_info.get("boja"),
            "enterijer_materijal": extra_info.get("enterijer_materijal"),
            "boja_enterijera": extra_info.get("boja_enterijera"),
            "poreklo": extra_info.get("poreklo"),
            "pogon": extra_info.get("pogon"),
            "emisiona_klasa": extra_info.get("emisiona_klasa"),
            "broj_sedista": extra_info.get("broj_sedista"),
            "broj_vrata": extra_info.get("broj_vrata"),
            "vin": extra_info.get("vin"),
            # privremena za pass 2
            "_data_layer": data_layer,
            "_naslov": naziv,
            "_extra_info": extra_info,
        }

        time.sleep(PAUZA)

    # PROLAZ 2: scoring
    print(f"\n--- Izračunavam score ---")
    for url, c in list(baza_nova.items()):
        if c.get("problem_cena") or not c.get("cena"):
            continue

        stats = market_stats(c["model"], c.get("karoserija"), baza_nova, min_sample=3)

        score_result = calculate_score_v3(
            cena=c["cena"],
            naslov=c.get("_naslov") or c.get("label"),
            kilometraza=c.get("kilometraza"),
            godiste=c.get("godiste"),
            market_stats_data=stats,
            structured_data=c.get("_data_layer"),
            extra_info=c.get("_extra_info"),
            last_renewed_date=c.get("last_renewed_date"),
            promena_tip="bez_promene",
            ukupno_snizenje=0,
            model=c["model"],
        )

        c["score"] = score_result["score"]
        c["outlier"] = score_result["outlier"]
        c["score_breakdown"] = score_result["breakdown"]
        c["score_scope"] = score_result["scope"]
        c["score_sample_size"] = score_result["sample_size"]

        # Cleanup privremenih polja
        c.pop("_data_layer", None)
        c.pop("_naslov", None)
        c.pop("_extra_info", None)

        sign = "🔥" if c["score"] >= 80 else ("🟢" if c["score"] >= 60 else ("🟡" if c["score"] >= 40 else "🔴"))
        print(f"  {sign} {c['score']:>3} | {c['label'][:50]:<50}")

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
