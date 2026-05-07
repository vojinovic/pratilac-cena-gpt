import json
from datetime import datetime

FILES_OGLASI = "oglasi.json"
FILES_CENE = "cene_oglasa.json"


def izracunaj_score(p):
    score = 50  # base score

    cena = p.get("cena", 0)
    prva = p.get("prva_cena", cena)
    najmanja = p.get("najmanja_cena", cena)

    ukupno_snizenje = p.get("ukupno_snizenje", 0)
    broj_promena = p.get("broj_promena", 0)
    tip = p.get("promena_tip", "bez_promene")

    # 1. cena level
    if cena < 30000:
        score += 20
    elif cena < 35000:
        score += 10
    else:
        score -= 5

    # 2. discount bonus
    if ukupno_snizenje > 1000:
        score += 15
    elif ukupno_snizenje > 0:
        score += 5

    # 3. trend
    if tip == "pad":
        score += 15
    elif tip == "rast":
        score -= 10

    # 4. activity bonus (pregovori / promene)
    if broj_promena > 2:
        score += 5
    elif broj_promena == 0:
        score -= 5

    # clamp
    if score > 100:
        score = 100
    if score < 0:
        score = 0

    return score


def main():

    # load oglasi
    with open(FILES_OGLASI, "r", encoding="utf-8") as f:
        oglasi = json.load(f)

    try:
        with open(FILES_CENE, "r", encoding="utf-8") as f:
            cene = json.load(f)
    except:
        cene = {}

    novi_output = {}

    for oglas in oglasi:

        url = oglas["url"]

        # već postojeći podaci
        stari = cene.get(url, {})

        cena = oglas.get("cena", stari.get("cena"))

        prva_cena = stari.get("prva_cena", cena)
        prethodna_cena = stari.get("cena")

        # promena logika
        if prethodna_cena and prethodna_cena != cena:
            broj_promena = stari.get("broj_promena", 0) + 1
        else:
            broj_promena = stari.get("broj_promena", 0)

        ukupno_snizenje = prva_cena - cena

        if cena < prethodna_cena if prethodna_cena else cena:
            promena_tip = "pad"
        elif cena > prethodna_cena if prethodna_cena else cena:
            promena_tip = "rast"
        else:
            promena_tip = "bez_promene"

        obj = {
            "label": oglas.get("label"),
            "cena": cena,
            "prva_cena": prva_cena,
            "najmanja_cena": min(stari.get("najmanja_cena", cena), cena),
            "broj_promena": broj_promena,
            "ukupno_snizenje": ukupno_snizenje,
            "slika": oglas.get("slika"),
            "prethodna_cena": prethodna_cena,
            "promena": (prethodna_cena - cena) if prethodna_cena else 0,
            "promena_tip": promena_tip,
            "datum_promene": datetime.now().strftime("%d.%m.%Y %H:%M"),
            "aktivan": True,
            "problem_cena": False,
            "poslednja_provera": datetime.now().strftime("%d.%m.%Y %H:%M"),

            # 🔥 KLJUČNO
            "score": izracunaj_score({
                "cena": cena,
                "prva_cena": prva_cena,
                "najmanja_cena": stari.get("najmanja_cena", cena),
                "ukupno_snizenje": ukupno_snizenje,
                "broj_promena": broj_promena,
                "promena_tip": promena_tip
            })
        }

        novi_output[url] = obj

    # save
    with open(FILES_CENE, "w", encoding="utf-8") as f:
        json.dump(novi_output, f, indent=2, ensure_ascii=False)


if __name__ == "__main__":
    main()
