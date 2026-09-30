"""
Generator scenariusza demo: stan/wsie.json, stan/odcinki.json (FORMAT.md) + symulator/scenariusz/prawda.json.

Prawdziwe: sieć dróg, mosty, cieki i wsie doliny Solinki i Wetlinki (OSM), progi IMGW.
SYMULOWANE: które odcinki są zalane lub zerwane (prawda.json) — losowane z prawdopodobieństw niżej.
ponytail: prawdopodobieństwa to założenie; zamiast nich można użyć map zagrożenia powodziowego ISOK, gdy będą dostępne.

Uruchomienie z katalogu repo: python planer/scenariusz.py [ziarno]
"""
import json
import random
import sys
from pathlib import Path

import siec

BBOX = (49.12, 22.28, 49.32, 22.52)
OSM = "dane/osm/dolina_solinki.json"
P_ZERWANY_MOST = 0.10      # most na cieku: zerwany
P_ZALANY_PRZY_POTOKU = 0.03  # odcinek utwardzony przy cieku: zalany
P_LESNY_PRZY_POTOKU = 0.30   # droga leśna przy cieku: rozmyta (nieprzejezdna nawet dla terenowych)


def wczytaj():
    """Sieć + wsie osiągalne drogą utwardzoną w warunkach normalnych (pozostałe pomijamy)."""
    odcinki, wsie, G, wz = siec.zbuduj(OSM, BBOX)
    normalnie = siec.status_wsi(G, wz, {o["id"]: "przejezdny" for o in odcinki if not o["lesny"]})
    wsie = [w for w in wsie if normalnie[w["id"]] == "dostepna"]
    wz = {w["id"]: wz[w["id"]] for w in wsie}
    return odcinki, wsie, G, wz


def zagrozony(o):
    return o["przy_potoku"]


def losuj_prawde(odcinki, rng):
    prawda = {}
    for o in odcinki:
        if not zagrozony(o):
            prawda[o["id"]] = "przejezdny"
        elif o["lesny"]:
            prawda[o["id"]] = "zablokowany" if rng.random() < P_LESNY_PRZY_POTOKU else "przejezdny"
        elif o["most"]:
            prawda[o["id"]] = "zerwany" if rng.random() < P_ZERWANY_MOST else "przejezdny"
        else:
            prawda[o["id"]] = "zalany" if rng.random() < P_ZALANY_PRZY_POTOKU else "przejezdny"
    return prawda


def cieki():
    """Rzeki i potoki z OSM w obszarze doliny (do mapy w panelu)."""
    S, W, N, E = BBOX
    out = []
    for e in json.load(open(OSM, encoding="utf-8"))["elements"]:
        typ = e.get("tags", {}).get("waterway")
        if e["type"] == "way" and typ in ("river", "stream"):
            g = [[round(p["lat"], 5), round(p["lon"], 5)] for p in e["geometry"]]
            if any(S <= a <= N and W <= b <= E for a, b in g):
                out.append({"nazwa": e["tags"].get("name"), "typ": typ, "geometria": g})
    return out


def stan_poczatkowy(odcinki):
    """Przed lotem: utwardzone z dala od cieków = przejezdne z założenia; reszta nieznana."""
    return {o["id"]: "przejezdny" if (not zagrozony(o) and not o["lesny"]) else "nieznany" for o in odcinki}


def zapisz(ziarno=7, plik_prawdy="symulator/scenariusz/prawda.json"):
    odcinki, wsie, G, wz = wczytaj()
    prawda = losuj_prawde(odcinki, random.Random(ziarno))
    stany = stan_poczatkowy(odcinki)
    status = siec.status_wsi(G, wz, stany)
    Path("stan").mkdir(exist_ok=True)
    Path("scenariusz").mkdir(exist_ok=True)
    out_o = []
    for o in odcinki:
        s = stany[o["id"]]
        out_o.append({**o, "stan": s,
                      "przejezdny_dla": (["osobowy", "ciezarowy", "terenowy"] if s == "przejezdny" else []),
                      "zweryfikowany": False, "pewnosc": None,
                      "czas_obserwacji": None,
                      "zrodlo": {"typ": "zalozenie", "opis": "droga utwardzona z dala od cieków"} if s == "przejezdny" else None,
                      "symulowane": False})
    out_w = [{**w, "status": status[w["id"]], "status_pewnosc": None, "status_czas": None,
              "dojazd": {k: False for k in siec.KLASY}, "ladowisko": None, "symulowane": False}
             for w in wsie]
    json.dump(out_o, open("stan/odcinki.json", "w"), ensure_ascii=False)
    json.dump(cieki(), open("stan/cieki.json", "w"), ensure_ascii=False)
    json.dump(out_w, open("stan/wsie.json", "w"), ensure_ascii=False, indent=1)
    json.dump({"ziarno": ziarno, "symulowane": True,
               "zalozenia": {"P_ZERWANY_MOST": P_ZERWANY_MOST, "P_ZALANY_PRZY_POTOKU": P_ZALANY_PRZY_POTOKU,
                             "P_LESNY_PRZY_POTOKU": P_LESNY_PRZY_POTOKU},
               "stany": prawda}, open(plik_prawdy, "w"), ensure_ascii=False)
    zle = sum(v != "przejezdny" for v in prawda.values())
    print(f"odcinki: {len(out_o)}, wsie: {len(out_w)}, nieprzejezdnych w prawdzie (symulowane): {zle}")
    print("status przed lotem:", {k: sum(v == k for v in status.values()) for k in ("dostepna", "nieznany", "odcieta")})
    prawdziwy = siec.status_wsi(G, wz, prawda)
    print("status gdyby wszystko było wiadomo:", {k: sum(v == k for v in prawdziwy.values()) for k in ("dostepna", "nieznany", "odcieta")})


if __name__ == "__main__":
    zapisz(int(sys.argv[1]) if len(sys.argv) > 1 else 7)
