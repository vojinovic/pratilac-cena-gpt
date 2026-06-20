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


def izvuci_iz_meta(soup):
    """
    Glavni izvor podataka posle PA redizajna (jun 2026): meta description i
    keywords su serverski renderovani (PA ih mora dati zbog Google/FB share-a),
    za razliku od dataLayer-a i priceClassified koji se sad učitavaju JS-om
    pa ih curl_cffi ne vidi.

    Primer meta-description:
    "Škoda Kodiaq 2.0tdi dsg 4x4, 2021. godište, Džip/SUV, Dizel, 1968 cm3,
     vozilo prešlo 191850 km, Voganj. Cena 21.950 €, Putnička vozila..."

    Vraća dict: cena, godiste, kilometraza, gorivo, karoserija, kubikaza, mesto.
    Sva polja su opciona (None ako se ne nađu).
    """
    result = {
        "cena": None, "godiste": None, "kilometraza": None,
        "gorivo": None, "karoserija": None, "kubikaza": None, "mesto": None,
    }

    desc = None
    meta = soup.find("meta", attrs={"name": "description"})
    if meta and meta.get("content"):
        desc = meta.get("content")
    if not desc:
        meta = soup.find("meta", attrs={"property": "og:description"})
        if meta and meta.get("content"):
            desc = meta.get("content")

    if not desc:
        return result

    # Normalizuj non-breaking space (&nbsp; -> obican razmak)
    desc = desc.replace("\xa0", " ").replace("&nbsp;", " ")

    # CENA: "Cena 21.950 €" ili "Cena 21950 €"
    m = re.search(r"Cena\s+([\d.\s]+)\s*€", desc)
    if m:
        result["cena"] = parsiraj_broj(m.group(1))

    # GODIŠTE: "2021. godište"
    m = re.search(r"(\d{4})\.\s*godi", desc)
    if m:
        try:
            g = int(m.group(1))
            if 1950 <= g <= datetime.now().year + 1:
                result["godiste"] = g
        except (ValueError, TypeError):
            pass

    # KILOMETRAŽA: "vozilo prešlo 191850 km" ili "prešlo 191.850 km"
    m = re.search(r"prešlo\s+([\d.\s]+)\s*km", desc)
    if not m:
        m = re.search(r"([\d.\s]+)\s*km\b", desc)
    if m:
        cifre = re.sub(r"[^\d]", "", m.group(1))
        if cifre:
            km = int(cifre)
            if 0 <= km <= 2000000:
                result["kilometraza"] = km

    # KUBIKAŽA: "1968 cm3"
    m = re.search(r"(\d{3,5})\s*cm3", desc)
    if m:
        try:
            result["kubikaza"] = int(m.group(1))
        except (ValueError, TypeError):
            pass

    # GORIVO: poznate vrednosti iz opisa
    for fuel in ["Dizel", "Benzin + metan (CNG)", "Benzin + gas (TNG)", "Benzin", "Hibrid", "Električni pogon", "Elektro"]:
        if fuel in desc:
            result["gorivo"] = fuel
            break

    # KAROSERIJA: poznate vrednosti
    for chassis in ["Džip/SUV", "Limuzina", "Karavan", "Hečbek", "Kupe", "Kabriolet", "Monovolumen (MiniVan)", "Pickup", "Kombi"]:
        if chassis in desc:
            result["karoserija"] = chassis
            break

    # MESTO: izmedju "km, " i ". Cena" -> "Voganj"
    m = re.search(r"km,\s*([^.]+?)\.\s*Cena", desc)
    if m:
        result["mesto"] = m.group(1).strip()

    return result


def izvuci_cenu(soup, data_layer=None, meta_data=None):
    # 1) Meta description (glavni izvor posle PA redizajna)
    if meta_data and meta_data.get("cena"):
        return meta_data["cena"]

    # 2) dataLayer (radi ako PA vrati server-side render)
    if data_layer and data_layer.get("object_price"):
        cena = parsiraj_broj(data_layer.get("object_price"))
        if cena:
            return cena

    # 3) Stari DOM fallback-ovi
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

    # og:title je pouzdaniji od h1 posle redizajna
    meta = soup.find("meta", property="og:title")
    if meta and meta.get("content"):
        text = meta.get("content")
        text = text.replace("| Polovni Automobili", "").replace("- Polovni automobili", "").replace("Polovni Automobili", "").strip()
        if text:
            return text

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
    raw = None

    el = soup.find("div", class_="description-wrapper")
    if el:
        raw = el.get_text("\n", strip=True)

    # Schema.org Car description
    if not raw:
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
                            raw = desc
                            break
                if raw:
                    break
            except (json.JSONDecodeError, AttributeError, TypeError):
                continue

    return sanitize_opis(raw)


def sanitize_opis(text):
    """
    Uklanja lične podatke iz opisa (telefoni, emailovi) i skracuje na 500 karaktera.
    GDPR-friendly: ne čuvamo PII u našoj bazi.
    """
    if not text:
        return None

    # Email
    text = re.sub(r"\S+@\S+\.\S+", "[email]", text)

    # Telefoni (razne forme srpskih brojeva)
    # +381 64 1234567, 064/1234-567, 064 12 34 567, 0641234567 itd
    text = re.sub(r"\+?\d{1,3}[\s/-]?\d{2,3}[\s/-]?\d{2,4}[\s/-]?\d{2,4}", "[telefon]", text)
    # Krace forme tipa 064 123 456 ili 06412345
    text = re.sub(r"\b0\d{2}[\s/-]?\d{2,4}[\s/-]?\d{2,4}\b", "[telefon]", text)

    # URL-ovi (mogu otkriti druge sajtove, kontakt)
    text = re.sub(r"https?://\S+", "[link]", text)
    text = re.sub(r"www\.\S+", "[link]", text)

    # Skrati na 500 chars
    if len(text) > 500:
        text = text[:497] + "..."

    return text.strip()


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


def linear_regression(samples):
    """
    Linearna regresija: cena = a + b*godiste + c*km

    samples: list of dicts sa kljucevima 'cena', 'godiste', 'kilometraza'

    Vraca dict sa:
        - coefs: (a, b, c) ili None ako matematicki nije moguce
        - r_squared: kvalitet fit-a (0-1)
        - predict(godiste, km): funkcija
    Vraca None ako nedovoljno podataka.
    """
    # Filtriraj samples - mora imati sve 3 vrednosti
    pts = [
        (s["cena"], s["godiste"], s["kilometraza"])
        for s in samples
        if s.get("cena") and s.get("godiste") and s.get("kilometraza")
    ]

    n = len(pts)
    if n < 5:
        return None

    # OLS regresija sa 2 prediktora (godiste, km)
    # Sistem: y = a + b*x1 + c*x2
    # Resava se: [n   sum(x1)  sum(x2)  ] [a]   [sum(y)]
    #            [sum(x1) sum(x1^2) sum(x1*x2)] [b] = [sum(y*x1)]
    #            [sum(x2) sum(x1*x2) sum(x2^2)] [c]   [sum(y*x2)]

    y = [p[0] for p in pts]
    x1 = [p[1] for p in pts]
    x2 = [p[2] for p in pts]

    sum_y = sum(y)
    sum_x1 = sum(x1)
    sum_x2 = sum(x2)
    sum_x1x1 = sum(v * v for v in x1)
    sum_x2x2 = sum(v * v for v in x2)
    sum_x1x2 = sum(x1[i] * x2[i] for i in range(n))
    sum_yx1 = sum(y[i] * x1[i] for i in range(n))
    sum_yx2 = sum(y[i] * x2[i] for i in range(n))

    # 3x3 matrica
    A = [
        [n,      sum_x1,   sum_x2],
        [sum_x1, sum_x1x1, sum_x1x2],
        [sum_x2, sum_x1x2, sum_x2x2],
    ]
    B = [sum_y, sum_yx1, sum_yx2]

    # Resi Ax = B Gaussovom eliminacijom
    try:
        coefs = _solve_3x3(A, B)
    except (ValueError, ZeroDivisionError):
        return None

    a, b, c = coefs

    # R-squared
    mean_y = sum_y / n
    ss_tot = sum((yi - mean_y) ** 2 for yi in y)
    ss_res = sum((y[i] - (a + b * x1[i] + c * x2[i])) ** 2 for i in range(n))
    r_squared = 1 - (ss_res / ss_tot) if ss_tot > 0 else 0

    def predict(godiste, km):
        return a + b * godiste + c * km

    return {
        "coefs": (a, b, c),
        "r_squared": r_squared,
        "predict": predict,
        "n_samples": n,
    }


def _solve_3x3(A, B):
    """Resi 3x3 linearni sistem Gaussovom eliminacijom."""
    # Kopiraj da ne menjamo original
    M = [row[:] + [B[i]] for i, row in enumerate(A)]

    # Forward elimination sa partial pivoting
    for i in range(3):
        # Nadji najveci pivot u koloni
        max_row = i
        for k in range(i + 1, 3):
            if abs(M[k][i]) > abs(M[max_row][i]):
                max_row = k
        M[i], M[max_row] = M[max_row], M[i]

        if abs(M[i][i]) < 1e-10:
            raise ValueError("Singular matrix")

        # Eliminisi
        for k in range(i + 1, 3):
            factor = M[k][i] / M[i][i]
            for j in range(i, 4):
                M[k][j] -= factor * M[i][j]

    # Back substitution
    x = [0, 0, 0]
    for i in range(2, -1, -1):
        x[i] = M[i][3]
        for j in range(i + 1, 3):
            x[i] -= M[i][j] * x[j]
        x[i] /= M[i][i]

    return x


def expected_price(model, karoserija, godiste, km, baza, reference_data=None, min_sample=5):
    """
    Vraca ocekivanu cenu za auto. Pokusava redom:
    1. Linearna regresija na model (sopstveni oglasi + reference set)
    2. Prosek za model
    3. Prosek za brand+karoserija
    """
    # Sopstveni oglasi istog modela
    same_model = [d for d in baza.values() if d.get("model") == model]
    same_model_full = [
        {"cena": d["cena"], "godiste": d["godiste"], "kilometraza": d["kilometraza"]}
        for d in same_model
        if d.get("cena") and d.get("godiste") and d.get("kilometraza")
    ]

    # Augmentacija sa reference set-om
    augmented = list(same_model_full)
    used_reference = False
    if reference_data and len(same_model_full) < min_sample:
        brand = extract_brand(model)
        model_part = "-".join(model.split("-")[1:]) if "-" in model else None
        if brand and model_part:
            key = (brand, model_part, karoserija)
            refs = reference_data.get(key, [])
            augmented.extend(refs)
            if refs:
                used_reference = True

    # Pokusaj 1: linearna regresija
    reg = linear_regression(augmented) if len(augmented) >= min_sample else None

    if reg and godiste and km:
        scope = "regression+ref" if used_reference else "regression"
        return {
            "expected": reg["predict"](godiste, km),
            "scope": scope,
            "sample_size": reg["n_samples"],
            "user_samples": len(same_model_full),
            "confidence": reg["r_squared"],
            "avg_cena": _avg([d["cena"] for d in augmented]),
            "avg_km": _avg([d["kilometraza"] for d in augmented]),
            "avg_godiste": _avg([d["godiste"] for d in augmented]),
        }

    # Pokusaj 2: prosek istog modela
    if len(augmented) >= 3:
        return {
            "expected": _avg([d["cena"] for d in augmented]),
            "scope": "model_avg+ref" if used_reference else "model_avg",
            "sample_size": len(augmented),
            "user_samples": len(same_model_full),
            "confidence": 0.4,
            "avg_cena": _avg([d["cena"] for d in augmented]),
            "avg_km": _avg([d["kilometraza"] for d in augmented]),
            "avg_godiste": _avg([d["godiste"] for d in augmented]),
        }

    # Pokusaj 3: brand+karoserija prosek
    brand = extract_brand(model)
    if brand and karoserija:
        wider = [
            d for d in baza.values()
            if extract_brand(d.get("model") or "") == brand
            and d.get("karoserija") == karoserija
            and d.get("cena")
        ]
        if len(wider) >= 3:
            return {
                "expected": _avg([d["cena"] for d in wider]),
                "scope": "brand+chassis_avg",
                "sample_size": len(wider),
                "user_samples": len(same_model_full),
                "confidence": 0.3,
                "avg_cena": _avg([d["cena"] for d in wider]),
                "avg_km": _avg([d["kilometraza"] for d in wider if d.get("kilometraza")]),
                "avg_godiste": _avg([d["godiste"] for d in wider if d.get("godiste")]),
            }

    return None


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
    expected = market_stats_data.get("expected") if market_stats_data else None
    scope = market_stats_data.get("scope") if market_stats_data else None
    market_km = market_stats_data.get("avg_km") if market_stats_data else None
    market_god = market_stats_data.get("avg_godiste") if market_stats_data else None

    naslov_lower = (naslov or "").lower()
    brand = extract_brand(model) if model else None

    # CENA - porediti sa OCEKIVANOM cenom (linearna regresija) umesto sa avg
    if expected and cena:
        diff = ((expected - cena) / expected) * 100

        # Label menja se zavisno od scope-a
        if scope == "regression":
            label_prefix = "Cena"  # ocekivana - prilagodjena godistu i km
        else:
            label_prefix = "Cena vs prosek"  # samo prosek (fallback)

        if diff >= 20:
            breakdown.append({"label": f"{label_prefix} {diff:.0f}% niža od očekivane", "value": 30, "category": "cena"})
        elif diff >= 15:
            breakdown.append({"label": f"{label_prefix} {diff:.0f}% niža od očekivane", "value": 25, "category": "cena"})
        elif diff >= 10:
            breakdown.append({"label": f"{label_prefix} {diff:.0f}% niža od očekivane", "value": 20, "category": "cena"})
        elif diff >= 5:
            breakdown.append({"label": f"{label_prefix} {diff:.0f}% niža od očekivane", "value": 12, "category": "cena"})
        elif diff <= -10:
            breakdown.append({"label": f"{label_prefix} {abs(diff):.0f}% viša od očekivane", "value": -15, "category": "cena"})
        elif diff <= -5:
            breakdown.append({"label": f"{label_prefix} {abs(diff):.0f}% viša od očekivane", "value": -5, "category": "cena"})

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
        je_prvi_vlasnik = structured_data.get("object_prvi_vlasnik") == "yes"
        je_kupljen_nov = structured_data.get("object_kupljen_nov_u_srbiji") == "yes"

        if je_prvi_vlasnik:
            breakdown.append({"label": "Prvi vlasnik", "value": 6, "category": "stanje"})
        if structured_data.get("object_servisna_knjizica") == "yes":
            breakdown.append({"label": "Servisna knjižica", "value": 5, "category": "stanje"})
        if structured_data.get("object_garancija") == "yes":
            breakdown.append({"label": "Garancija", "value": 4, "category": "stanje"})
        if je_kupljen_nov:
            breakdown.append({"label": "Kupljen nov u Srbiji", "value": 5, "category": "stanje"})

        # KOMBINOVANI BONUS: prvi vlasnik + kupljen nov u Srbiji.
        # Najjači signal poverenja na tržištu - eliminiše rizik uvoza
        # (manipulacija km, skriveni udesi, lažna istorija koju ni CarVertical
        # ne uhvati). Važi za sve, ali skaliran: što je auto noviji, signal jači.
        if je_prvi_vlasnik and je_kupljen_nov:
            if godiste:
                starost = datetime.now().year - godiste
                if starost <= 3:
                    bonus, label = 14, "Nov, domaći, prvi vlasnik"
                elif starost <= 6:
                    bonus, label = 11, "Mlad, domaći, prvi vlasnik"
                elif starost <= 10:
                    bonus, label = 8, "Domaći od prvog vlasnika"
                else:
                    bonus, label = 6, "Domaći od prvog vlasnika"
            else:
                bonus, label = 8, "Domaći od prvog vlasnika"
            breakdown.append({"label": label, "value": bonus, "category": "stanje"})

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
    if expected and cena:
        diff = ((expected - cena) / expected) * 100
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
        # Mrežna/HTTP greška (403, 502, timeout...) NIJE dokaz da je oglas
        # obrisan. Vrati aktivan=None (nepoznato), pa pozivalac zadrži stare
        # podatke umesto da oglas proglasi mrtvim ili obriše cenu.
        print("Greška:", e)
        return None, None, None, "", {}, {}, "", [], None, {}

    final_url = response.url
    # Obrisan oglas: PA redirektuje na pretragu slicnih. Stari format je sadrzao
    # 'redirect_message' ili '/pretraga', novi (jun 2026) vodi na kategorijski
    # URL bez broja oglasa, npr /auto-oglasi/volvo/xc60/dzipsuv/dizel.
    # Pravi oglas UVEK ima numericki ID: /auto-oglasi/29352833/...
    obrisan = False
    if "redirect_message" in final_url or "/auto-oglasi/pretraga" in final_url:
        obrisan = True
    elif "/auto-oglasi/" in final_url and not re.search(r"/auto-oglasi/\d+/", final_url):
        obrisan = True
    else:
        # Dodatna provera: canonical koji ne sadrzi broj oglasa = redirekt na kategoriju
        soup_check = BeautifulSoup(response.text, "html.parser")
        canon = soup_check.find("link", attrs={"rel": "canonical"})
        if canon and canon.get("href") and not re.search(r"/auto-oglasi/\d+/", canon.get("href")):
            obrisan = True

    if obrisan:
        print(f"  OGLAS OBRISAN")
        return None, None, None, "", {}, {}, "", [], False, {}

    soup = BeautifulSoup(response.text, "html.parser")
    data_layer = izvuci_data_layer(response.text)
    meta_data = izvuci_iz_meta(soup)
    extra_info = izvuci_dodatne_info(soup)
    opis = izvuci_opis(soup)
    oprema = izvuci_opremu(soup)

    cena = izvuci_cenu(soup, data_layer, meta_data)
    slika = izvuci_sliku(soup)
    naziv = izvuci_naziv(soup, data_layer)

    return cena, slika, naziv, response.text, data_layer, extra_info, opis, oprema, True, meta_data


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


def fetch_reference_set(brand, model, chassis=None):
    """
    Dohvata oglase istog brand+model (i opcionalno karoserija) sa worker
    /admin/reference-search endpoint-a. Vraca listu sa cena/godiste/kilometraza
    za augmentaciju regresije.
    """
    try:
        params = {"key": SCRAPER_SECRET, "brand": brand, "model": model}
        if chassis:
            params["chassis"] = chassis

        # Build query string
        qs = "&".join(f"{k}={v}" for k, v in params.items())
        url = f"{API_URL}/admin/reference-search?{qs}"
        res = requests.get(url, timeout=60, impersonate="chrome")
        res.raise_for_status()
        data = res.json()
        results = data.get("results", [])
        cached = data.get("cached")
        return results, cached
    except Exception as e:
        print(f"  Reference fetch greška za {brand}/{model}: {e}")
        return [], False


def build_augmented_baza(baza_nova):
    """
    Za svaki model+karoserija koji ima <5 oglasa u user bazi, dohvati
    reference set sa polovniautomobili search-a i dodaj u memoriji.
    Vraca {(brand, model_part, karoserija): [reference dicts]}.
    """
    # Grupisi user oglase po (brand, model_part, karoserija)
    grupe = {}
    for url, c in baza_nova.items():
        if not c.get("cena") or not c.get("godiste") or not c.get("kilometraza"):
            continue
        model = c.get("model") or ""
        if not model or model == "unknown":
            continue
        delovi = model.split("-")
        if len(delovi) < 2:
            continue
        brand = delovi[0]
        model_part = "-".join(delovi[1:])
        karoserija = c.get("karoserija")
        key = (brand, model_part, karoserija)
        grupe.setdefault(key, []).append(c)

    reference_data = {}
    for key, oglasi in grupe.items():
        brand, model_part, karoserija = key

        if len(oglasi) >= 5:
            continue  # imamo dovoljno user podataka

        print(f"\n  Dohvaćam reference za {brand}/{model_part} ({len(oglasi)} user oglasa)...")
        chassis_id = _chassis_to_id(karoserija)
        refs, cached = fetch_reference_set(brand, model_part, chassis=chassis_id)
        cache_tag = "(cache)" if cached else "(fresh)"
        print(f"    Dobio {len(refs)} referentnih oglasa {cache_tag}")
        reference_data[key] = refs

    return reference_data


# Mapa karoserija label -> ID koji search endpoint ocekuje
CHASSIS_MAP = {
    "Džip/SUV": "2632",
    "Limuzina": "2631",
    "Karavan": "2633",
    "Hečbek": "2630",
    "Hatchback": "2630",
    "Kupe": "2634",
    "Kabriolet": "2635",
    "Monovolumen (MiniVan)": "2636",
    "Pickup": "2637",
}


def _chassis_to_id(karoserija):
    if not karoserija:
        return None
    return CHASSIS_MAP.get(karoserija)


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

        cena, slika, naziv, html, data_layer, extra_info, opis, oprema, aktivan, meta_data = proveri_oglas(url)

        label = oglas.get("label") or naziv or "Oglas"
        model = extract_model(url)

        # aktivan=None znači mrežna/HTTP greška (403, 502, timeout). Oglas NIJE
        # obrisan, samo ga sad ne možemo pročitati. Šaljemo minimalan zapis bez
        # 'aktivan' polja; merge na Worker strani čuva sve stare podatke.
        if aktivan is None:
            baza_nova[url] = {
                "label": label,
                "model": model,
                "problem_cena": True,
                "poslednja_provera": now,
            }
            time.sleep(PAUZA)
            continue

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

        # Primarni izvor: dataLayer (kad PA vrati server-side render).
        # Fallback: meta description (radi i posle JS redizajna).
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

        # Dopuna iz meta description-a za sve što dataLayer nije dao
        if meta_data:
            if godiste is None:
                godiste = meta_data.get("godiste")
            if kilometraza is None:
                kilometraza = meta_data.get("kilometraza")
            if not gorivo:
                gorivo = meta_data.get("gorivo")
            if not karoserija:
                karoserija = meta_data.get("karoserija")
            if kubikaza is None:
                kubikaza = meta_data.get("kubikaza")

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
            "mesto": meta_data.get("mesto") if meta_data else None,
            # privremena za pass 2
            "_data_layer": data_layer,
            "_naslov": naziv,
            "_extra_info": extra_info,
        }

        time.sleep(PAUZA)

    # PROLAZ 2: scoring sa augmentacijom
    print(f"\n--- Pripremam reference podatke ---")
    reference_data = build_augmented_baza(baza_nova)

    print(f"\n--- Izračunavam score ---")
    for url, c in list(baza_nova.items()):
        if c.get("problem_cena") or not c.get("cena"):
            continue

        stats = expected_price(
            model=c["model"],
            karoserija=c.get("karoserija"),
            godiste=c.get("godiste"),
            km=c.get("kilometraza"),
            baza=baza_nova,
            reference_data=reference_data,
            min_sample=5,
        )

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
        c["expected_cena"] = round(stats["expected"]) if stats and stats.get("expected") else None
        c["expected_confidence"] = round(stats["confidence"] * 100) if stats and stats.get("confidence") is not None else None

        # Cleanup privremenih polja
        c.pop("_data_layer", None)
        c.pop("_naslov", None)
        c.pop("_extra_info", None)

        sign = "🔥" if c["score"] >= 80 else ("🟢" if c["score"] >= 60 else ("🟡" if c["score"] >= 40 else "🔴"))
        scope_label = score_result["scope"] or "no-stats"
        sample_info = f"n={score_result['sample_size']}"
        print(f"  {sign} {c['score']:>3} | {c['label'][:45]:<45} | {scope_label} ({sample_info})")

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
