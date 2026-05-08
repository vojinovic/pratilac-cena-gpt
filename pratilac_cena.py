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

# Email pragovi za sniženja
PRAG_PROCENT = 1.0
PRAG_APSOLUT = 200

RESEND_API_KEY = os.environ.get("RESEND_API_KEY", "")
EMAIL_PRIMALAC = os.environ.get("EMAIL_PRIMALAC", "")

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


def izvuci_specs(soup):
    """
    Parsira sve label/value parove iz "Opšte informacije" sekcije.
    
    Struktura na polovniautomobili je:
    <div class="divider">
        <div class="uk-grid">
            <div class="uk-width-1-2">Godište</div>
            <div class="uk-width-1-2 uk-text-bold">2022.</div>
        </div>
    </div>
    
    Vraća rečnik: {"godiste": 2022, "kilometraza": 158216, "karoserija": "Džip/SUV", ...}
    """
    specs = {}

    # Sve uk-grid divove koji sadrže labele i vrednosti
    grids = soup.find_all("div", class_="uk-grid")

    for grid in grids:
        cells = grid.find_all("div", class_="uk-width-1-2")

        if len(cells) >= 2:
            label = cells[0].get_text(" ", strip=True).lower()
            value = cells[1].get_text(" ", strip=True)

            if not label or not value:
                continue

            # Mapiranje labela na ključeve
            if "godište" in label or "godiste" in label:
                godina = re.sub(r"[^\d]", "", value)
                if godina and len(godina) == 4:
                    specs["godiste"] = int(godina)

            elif "kilometraža" in label or "kilometraza" in label:
                km = re.sub(r"[^\d]", "", value)
                if km:
                    specs["kilometraza"] = int(km)

            elif "karoserija" in label:
                specs["karoserija"] = value

            elif "gorivo" in label:
                specs["gorivo"] = value

            elif "snaga" in label:
                specs["snaga"] = value

            elif "kubikaža" in label or "kubikaza" in label:
                specs["kubikaza"] = value

            elif "marka" in label and "modela" not in label:
                specs["marka"] = value

            elif label == "model":
                specs["model_naziv"] = value

    return specs


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


def market_average_cena(model, baza):
    cene = []
    for _, data in baza.items():
        if data.get("model") == model and data.get("cena"):
            cene.append(data["cena"])
    if not cene:
        return None
    return sum(cene) / len(cene)


def market_average_km(model, baza):
    kms = []
    for _, data in baza.items():
        if data.get("model") == model and data.get("kilometraza"):
            kms.append(data["kilometraza"])
    if not kms:
        return None
    return sum(kms) / len(kms)


def market_average_godiste(model, baza):
    godine = []
    for _, data in baza.items():
        if data.get("model") == model and data.get("godiste"):
            godine.append(data["godiste"])
    if not godine:
        return None
    return sum(godine) / len(godine)


def calculate_score(
    label,
    html,
    cena,
    market_avg_cena,
    kilometraza,
    market_avg_km,
    godiste,
    market_avg_godiste,
    prva_cena,
    najmanja_cena,
    ukupno_snizenje,
    promena_tip,
):
    text = ((label or "") + " " + (html or "")).lower()

    score = 50

    # 1. CENA vs MARKET (±20)
    if market_avg_cena and cena:
        diff_percent = ((market_avg_cena - cena) / market_avg_cena) * 100

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

    # 2. KILOMETRAŽA vs MARKET (±15)
    if market_avg_km and kilometraza:
        # Manje km = bolje
        ratio = kilometraza / market_avg_km

        if ratio <= 0.5:
            score += 15
        elif ratio <= 0.75:
            score += 8
        elif ratio <= 0.9:
            score += 3
        elif ratio >= 1.5:
            score -= 10
        elif ratio >= 1.25:
            score -= 5

    # 3. GODIŠTE vs MARKET (±10)
    if market_avg_godiste and godiste:
        diff = godiste - market_avg_godiste

        if diff >= 2:
            score += 10
        elif diff >= 1:
            score += 5
        elif diff <= -2:
            score -= 8
        elif diff <= -1:
            score -= 3

    # 4. BONUS DEAL: niže km + mlađe + niža cena
    if (market_avg_cena and cena and cena < market_avg_cena and
        market_avg_km and kilometraza and kilometraza < market_avg_km and
        market_avg_godiste and godiste and godiste >= market_avg_godiste):
        score += 10
        print("BONUS DEAL: ispod proseka u sve tri kategorije!")

    # 5. OPREMA
    plus_keywords = {
        "awd": 5, "4x4": 5, "r-design": 5, "inscription": 5,
        "momentum": 3, "sport": 4, "pano": 5, "panorama": 5,
        "kamera": 3, "hud": 4, "webasto": 4, "led": 3,
        "matrix": 4, "harman": 3, "bowers": 4,
    }

    for keyword, points in plus_keywords.items():
        if keyword in text:
            score += points

    # 6. STANJE
    stanje_plus = {
        "prvi vlasnik": 10, "1 vlasnik": 10, "servisna": 6,
        "servisna knjiga": 8, "bez ulaganja": 8,
        "kupljen u srbiji": 6, "garaziran": 5,
    }

    for keyword, points in stanje_plus.items():
        if keyword in text:
            score += points

    stanje_minus = {
        "udaren": -25, "ostecen": -20, "oštećen": -20,
        "hitno": -5, "zamena": -5, "fiksno": -3,
        "potrebna ulaganja": -15,
    }

    for keyword, points in stanje_minus.items():
        if keyword in text:
            score += points

    # 7. TREND CENE
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
        response.encoding = "utf-8"

    except Exception as e:
        print("Greška:", e)
        return None, None, None, "", {}, False

    soup = BeautifulSoup(response.text, "html.parser")

    cena = izvuci_cenu(soup)
    slika = izvuci_sliku(soup)
    naziv = izvuci_naziv(soup)
    specs = izvuci_specs(soup)

    return cena, slika, naziv, response.text, specs, True


def posalji_email(snizenja, nestali):
    if not snizenja and not nestali:
        return

    if not RESEND_API_KEY or not EMAIL_PRIMALAC:
        print("UPOZORENJE: RESEND_API_KEY ili EMAIL_PRIMALAC nije postavljen, preskačem email")
        return

    delovi = []
    if snizenja:
        delovi.append(f"{len(snizenja)} sniženja")
    if nestali:
        delovi.append(f"{len(nestali)} nestao oglas" if len(nestali) == 1 else f"{len(nestali)} nestala oglasa")

    subject = "🚗 Auto Drukara: " + ", ".join(delovi)

    html = """
    <div style="font-family: Arial, sans-serif; max-width: 600px;">
        <h2 style="color: #5b4ce6;">🚗 Auto Drukara - Promene</h2>
    """

    if snizenja:
        html += '<h3 style="color: #28a745; margin-top: 30px;">🎉 Sniženja cene</h3>'
        for s in snizenja:
            slika_html = f'<img src="{s["slika"]}" style="max-width: 300px; border-radius: 8px; margin: 10px 0;">' if s.get("slika") else ""
            procenat = (s["razlika"] / s["stara"]) * 100
            html += f"""
            <div style="border: 1px solid #e0e0e0; border-radius: 10px; padding: 15px; margin-bottom: 15px; background: #f8fff8;">
                <h4 style="margin: 0 0 10px 0;">{s["label"]}</h4>
                {slika_html}
                <p style="font-size: 18px; margin: 8px 0;">
                    <span style="text-decoration: line-through; color: #999;">{s["stara"]:,} €</span>
                    →
                    <strong style="color: #28a745; font-size: 22px;">{s["nova"]:,} €</strong>
                </p>
                <p style="color: #28a745; margin: 4px 0;">
                    Pad: <strong>{s["razlika"]:,} €</strong> ({procenat:.1f}%)
                </p>
                <a href="{s["url"]}" style="color: #5b4ce6;">Otvori oglas</a>
            </div>
            """

    if nestali:
        html += '<h3 style="color: #d10000; margin-top: 30px;">❌ Nestali oglasi</h3>'
        for n in nestali:
            html += f"""
            <div style="border: 1px solid #e0e0e0; border-radius: 10px; padding: 15px; margin-bottom: 15px; background: #fff8f8;">
                <h4 style="margin: 0 0 10px 0;">{n["label"]}</h4>
                <p style="color: #666; margin: 4px 0;">
                    Poslednja cena: <strong>{n["poslednja_cena"]:,} €</strong>
                </p>
                <a href="{n["url"]}" style="color: #5b4ce6;">Otvori oglas (možda 404)</a>
            </div>
            """

    html += """
        <hr style="border: none; border-top: 1px solid #eee; margin: 30px 0;">
        <p style="color: #999; font-size: 13px;">
            Obaveštenje od Auto Drukara aplikacije.
        </p>
    </div>
    """

    try:
        resp = requests.post(
            "https://api.resend.com/emails",
            headers={
                "Authorization": f"Bearer {RESEND_API_KEY}",
                "Content-Type": "application/json",
            },
            json={
                "from": "Auto Drukara <onboarding@resend.dev>",
                "to": [EMAIL_PRIMALAC],
                "subject": subject,
                "html": html,
            },
            timeout=10,
        )

        if resp.status_code == 200:
            print(f"EMAIL POSLAT: {subject}")
        else:
            print(f"EMAIL GREŠKA: {resp.status_code} - {resp.text[:200]}")

    except Exception as e:
        print(f"EMAIL EXCEPTION: {e}")


def main():
    oglasi = ucitaj_oglase()
    baza = ucitaj_bazu()

    now = datetime.now().strftime("%d.%m.%Y %H:%M")

    snizenja_za_email = []
    nestali_za_email = []

    for oglas in oglasi:
        url = oglas["url"]

        print("\nPROVERA:", url)

        cena, slika, naziv, html, specs, aktivan = proveri_oglas(url)

        stara = baza.get(url, {})

        label = (
            oglas.get("label")
            or naziv
            or stara.get("label")
            or "Oglas"
        )

        model = extract_model(url)

        if not aktivan:
            bio_aktivan = stara.get("aktivan", True)
            poslednja_cena = stara.get("cena")

            if bio_aktivan and poslednja_cena:
                nestali_za_email.append({
                    "url": url,
                    "label": label,
                    "poslednja_cena": poslednja_cena,
                })
                print(f"NESTAO OGLAS: {label}")

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

        # Sad imamo cenu i specs
        godiste = specs.get("godiste") or stara.get("godiste")
        kilometraza = specs.get("kilometraza") or stara.get("kilometraza")
        karoserija = specs.get("karoserija") or stara.get("karoserija")
        gorivo = specs.get("gorivo") or stara.get("gorivo")

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
                    razlika = abs(promena)
                    ukupno_snizenje += razlika

                    procenat = (razlika / prethodna_cena) * 100
                    if procenat >= PRAG_PROCENT or razlika >= PRAG_APSOLUT:
                        snizenja_za_email.append({
                            "url": url,
                            "label": label,
                            "stara": prethodna_cena,
                            "nova": cena,
                            "razlika": razlika,
                            "slika": slika or stara.get("slika"),
                        })
                        print(f"SNIŽENJE ZA EMAIL: {label} -{razlika}€ ({procenat:.1f}%)")
                    else:
                        print(f"sniženje ispod praga, preskačem email: {label} -{razlika}€ ({procenat:.1f}%)")
                else:
                    promena_tip = "poskupljenje"

        najmanja_cena = min(cena, najmanja_cena)

        # Privremeno upiši nove podatke u baza pre nego što izračunamo prosek
        # (da bi prosek uključio i ovaj auto)
        baza[url] = {
            **stara,
            "model": model,
            "cena": cena,
            "kilometraza": kilometraza,
            "godiste": godiste,
        }

        market_cena = market_average_cena(model, baza)
        market_km = market_average_km(model, baza)
        market_god = market_average_godiste(model, baza)

        score = calculate_score(
            label=label,
            html=html,
            cena=cena,
            market_avg_cena=market_cena,
            kilometraza=kilometraza,
            market_avg_km=market_km,
            godiste=godiste,
            market_avg_godiste=market_god,
            prva_cena=prva_cena,
            najmanja_cena=najmanja_cena,
            ukupno_snizenje=ukupno_snizenje,
            promena_tip=promena_tip,
        )

        print(f"MODEL: {model}")
        print(f"CENA: {cena}€ | MARKET AVG: {market_cena:.0f}€" if market_cena else f"CENA: {cena}€")
        print(f"KM: {kilometraza} | MARKET AVG: {market_km:.0f}" if (kilometraza and market_km) else f"KM: {kilometraza}")
        print(f"GODIŠTE: {godiste} | MARKET AVG: {market_god:.1f}" if (godiste and market_god) else f"GODIŠTE: {godiste}")
        print(f"SCORE: {score}")
        print(f"LABEL: {label}")

        baza[url] = {
            "label": label,
            "model": model,
            "cena": cena,
            "godiste": godiste,
            "kilometraza": kilometraza,
            "karoserija": karoserija,
            "gorivo": gorivo,
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

    if snizenja_za_email or nestali_za_email:
        print(f"\nŠaljem email: {len(snizenja_za_email)} sniženja, {len(nestali_za_email)} nestala oglasa")
        posalji_email(snizenja_za_email, nestali_za_email)
    else:
        print("\nNema promena za email")

    print("\nGOTOVO")


if __name__ == "__main__":
    main()
