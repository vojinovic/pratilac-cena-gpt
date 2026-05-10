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

PRAG_PROCENT = 1.0
PRAG_APSOLUT = 200

RESEND_API_KEY = os.environ.get("RESEND_API_KEY", "")
EMAIL_PRIMALAC = os.environ.get("EMAIL_PRIMALAC", "")

HEADERS = {
    "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/131.0.0.0 Safari/537.36",
    "Accept": "text/html,application/xhtml+xml,application/xml;q=0.9,image/avif,image/webp,image/apng,*/*;q=0.8",
    "Accept-Language": "sr-RS,sr;q=0.9,en-US;q=0.8,en;q=0.7",
    "Accept-Encoding": "gzip, deflate",
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


def izvuci_data_layer(html):
    """
    Izvlači podatke iz dataLayer.push({...}) na pojedinačnoj stranici oglasa.
    
    Polovniautomobili u JS-u ima:
        dataLayer.push({"fair_offer":"false","rubrika":"...","object_uid":"28482744",...})
    
    Vraća dict sa svim object_* poljima + ostalim korisnim.
    """
    # Pronadji prvi dataLayer.push sa "object_uid" u sebi
    pattern = r'dataLayer\.push\((\{[^;]*?"object_uid"[^;]*?\})\);'
    match = re.search(pattern, html)
    
    if not match:
        return {}
    
    json_str = match.group(1)
    
    try:
        data = json.loads(json_str)
        return data
    except json.JSONDecodeError as e:
        print(f"  Ne mogu da parsiram dataLayer JSON: {e}")
        return {}


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


def days_since(date_str):
    """Vraća broj dana od datog datuma do danas. Format: '2026-04-27 02:17:55'"""
    if not date_str:
        return None
    try:
        date = datetime.strptime(date_str, "%Y-%m-%d %H:%M:%S")
        delta = datetime.now() - date
        return delta.days
    except (ValueError, TypeError):
        return None


def calculate_score(
    cena, market_avg_cena,
    kilometraza, market_avg_km,
    godiste, market_avg_godiste,
    structured_data,
    last_renewed_date,
    promena_tip,
    ukupno_snizenje,
):
    """
    Score na osnovu strukturisanih polja iz polovniautomobili dataLayer-a,
    umesto keyword pretrage HTML-a.
    """
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

    # 5. STRUKTURISANA POLJA (mnogo pouzdanije od keyword pretrage!)
    if structured_data:
        if structured_data.get("object_prvi_vlasnik") == "yes":
            score += 10
        if structured_data.get("object_servisna_knjizica") == "yes":
            score += 8
        if structured_data.get("object_garancija") == "yes":
            score += 8
        if structured_data.get("object_kupljen_nov_u_srbiji") == "yes":
            score += 6
        
        # Damage status
        damage = structured_data.get("object_damage", "")
        if "udaren" in damage.lower():
            score -= 25
        elif "oštećen" in damage.lower() and "nije" not in damage.lower():
            score -= 20

        # Negativni signali
        if structured_data.get("object_taxi") == "yes":
            score -= 15  # taxi vozilo = puno km, intenzivna eksploatacija
        if structured_data.get("object_test_vozilo") == "yes":
            score -= 5

        # Pozitivni signali (ali manji bonus)
        if structured_data.get("object_old_timer") == "yes":
            score += 3  # oldtajmer može biti vredan
        
        # Rating prodavca (0-5, gde je 0 = nema rating)
        try:
            rating = float(structured_data.get("object_owner_rating", 0))
            if rating >= 4.5:
                score += 5
            elif rating >= 4.0:
                score += 3
            elif rating > 0 and rating < 3:
                score -= 5
        except (ValueError, TypeError):
            pass

    # 6. VREMENSKI TREND (last_renewed_date)
    days_renewed = days_since(last_renewed_date)
    if days_renewed is not None:
        if days_renewed <= 7:
            score += 5  # svež oglas
        elif days_renewed <= 30:
            pass  # normalno
        elif days_renewed <= 60:
            score -= 3  # stoji
        else:
            score -= 8  # stari oglas

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
    structured = izvuci_data_layer(response.text)

    return cena, slika, naziv, response.text, structured, True


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
        <p style="color: #999; font-size: 13px;">Obaveštenje od Auto Drukara aplikacije.</p>
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
    now_iso = datetime.now().strftime("%Y-%m-%d %H:%M:%S")

    snizenja_za_email = []
    nestali_za_email = []

    for oglas in oglasi:
        url = oglas["url"]

        print("\nPROVERA:", url)

        cena, slika, naziv, html, structured, aktivan = proveri_oglas(url)

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

        # Iz strukturisanih podataka
        godiste = None
        kilometraza = None
        gorivo = None
        karoserija = None
        last_renewed_date = None
        
        if structured:
            try:
                godiste = int(structured.get("object_production_year")) if structured.get("object_production_year") else None
            except (ValueError, TypeError):
                pass
            try:
                kilometraza = int(structured.get("object_mileage")) if structured.get("object_mileage") else None
            except (ValueError, TypeError):
                pass
            gorivo = structured.get("object_fuel")
            karoserija = structured.get("object_chassis")
            last_renewed_date = structured.get("object_last_renewed_date")

        # Fallback na stare vrednosti ako structured fail-uje
        godiste = godiste or stara.get("godiste")
        kilometraza = kilometraza or stara.get("kilometraza")
        gorivo = gorivo or stara.get("gorivo")
        karoserija = karoserija or stara.get("karoserija")

        # Prvi put videno - postavlja se samo prvi put
        prvi_put_videno = stara.get("prvi_put_videno") or now_iso

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
                        print(f"sniženje ispod praga: {label} -{razlika}€ ({procenat:.1f}%)")
                else:
                    promena_tip = "poskupljenje"

        najmanja_cena = min(cena, najmanja_cena)

        # Privremeno upiši pre score-a
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
            cena=cena,
            market_avg_cena=market_cena,
            kilometraza=kilometraza,
            market_avg_km=market_km,
            godiste=godiste,
            market_avg_godiste=market_god,
            structured_data=structured,
            last_renewed_date=last_renewed_date,
            promena_tip=promena_tip,
            ukupno_snizenje=ukupno_snizenje,
        )

        days_renewed = days_since(last_renewed_date)
        days_tracked = days_since(prvi_put_videno)

        print(f"MODEL: {model}")
        print(f"CENA: {cena}€" + (f" | MARKET AVG: {market_cena:.0f}€" if market_cena else ""))
        print(f"KM: {kilometraza}" + (f" | AVG: {market_km:.0f}" if market_km else ""))
        print(f"GODIŠTE: {godiste}" + (f" | AVG: {market_god:.1f}" if market_god else ""))
        if days_renewed is not None:
            print(f"OBNOVLJEN PRE: {days_renewed} dana")
        if days_tracked is not None:
            print(f"PRATIMO: {days_tracked} dana")
        if structured:
            indicators = []
            if structured.get("object_prvi_vlasnik") == "yes": indicators.append("prvi vlasnik")
            if structured.get("object_servisna_knjizica") == "yes": indicators.append("servisna")
            if structured.get("object_garancija") == "yes": indicators.append("garancija")
            if structured.get("object_kupljen_nov_u_srbiji") == "yes": indicators.append("kupljen u SRB")
            if indicators:
                print(f"INDIKATORI: {', '.join(indicators)}")
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
            
            # NOVO
            "prvi_put_videno": prvi_put_videno,
            "last_renewed_date": last_renewed_date,
            "prvi_vlasnik": structured.get("object_prvi_vlasnik") == "yes" if structured else False,
            "servisna_knjizica": structured.get("object_servisna_knjizica") == "yes" if structured else False,
            "garancija": structured.get("object_garancija") == "yes" if structured else False,
            "kupljen_nov_u_srbiji": structured.get("object_kupljen_nov_u_srbiji") == "yes" if structured else False,
            "damage": structured.get("object_damage") if structured else None,
            "owner_rating": structured.get("object_owner_rating") if structured else None,
            "owner_name": structured.get("companyName") if structured else None,
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
