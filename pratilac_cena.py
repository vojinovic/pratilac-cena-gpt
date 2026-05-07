def main():
    oglasi = ucitaj_oglase()
    baza = ucitaj_bazu()

    snizenja = []

    sada = datetime.now().strftime("%d.%m.%Y %H:%M")

    for oglas in oglasi:
        url = oglas["url"]

        print(f"Proveravam: {url}")

        cena, slika, naziv, aktivan = proveri_oglas(url)

        stara_baza = baza.get(url, {})

        if not aktivan:
            print("Oglas nedostupan")

            baza[url] = {
                "label": stara_baza.get("label", "Oglas"),
                "cena": stara_baza.get("cena"),
                "slika": stara_baza.get("slika"),
                "prethodna_cena": stara_baza.get("prethodna_cena"),
                "promena": stara_baza.get("promena", 0),
                "promena_tip": "nestao",
                "datum_promene": sada,
                "aktivan": False,
                "poslednja_provera": sada
            }

            continue

        label = oglas.get("label") or naziv

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
            "slika": slika,
            "prethodna_cena": prethodna_cena,
            "promena": promena,
            "promena_tip": promena_tip,
            "datum_promene": datum_promene,
            "aktivan": True,
            "poslednja_provera": sada
        }

        time.sleep(PAUZA)

    sacuvaj_bazu(baza)

    posalji_email(snizenja)

    print("Gotovo.")
