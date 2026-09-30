"""
Eksperymentalna usługa: zdjęcia z kolejki API → YOLO11n-seg → sugestia „model” w dzienniku API.

    python -m ai.zdjecia          # pętla; zdjęcia wysyła dron/stacja: POST /v1/zdjecia?odcinek=odc-0493

Ta sama logika oceny co w analizie filmu (ai/film.py): zalana droga ≥ 0,4 → zalany, sucha droga ≥ 0,5 → przejezdny,
inaczej „nieznany”. Zdjęcie z naniesionymi poligonami trafia do stan/zdjecia/gotowe/ i jest podpięte pod obserwację.
Wynik modelu na nowych zdjęciach jest niezweryfikowany i nie trafia do planera.
Osobny, zatwierdzony wpis operatora jest wymagany do zmiany stanu odcinka.
"""
import json
import os
import sys
import time
from pathlib import Path

from ai.film import MODEL, rysuj, stan_klatki, urzadzenie, wykryj
from komunikacja.klient import Klient

KATALOG = Path(__file__).resolve().parents[1]
STAN = Path(os.environ.get("AEROPASS_STAN", KATALOG / "stan"))


def przetworz(model, urz, klient, meta_plik):
    import cv2
    meta = json.loads(meta_plik.read_text(encoding="utf-8"))
    zdjecie = meta_plik.with_name(meta["plik"])
    obraz = cv2.imread(str(zdjecie))
    gotowe = STAN / "zdjecia" / "gotowe"
    gotowe.mkdir(parents=True, exist_ok=True)
    if obraz is None:
        stan, uwagi, wynik = "nieznany", "nie udało się odczytać zdjęcia", None
    else:
        wykrycia, poligony = wykryj(model, obraz, urz)
        stan = stan_klatki(wykrycia)
        wynik = gotowe / (meta_plik.stem + ".jpg")
        cv2.imwrite(str(wynik), rysuj(obraz, poligony, stan, f"zdjęcie odcinka {meta['odcinek']}", 0.0))
        uwagi = f"YOLO11n-seg: {len(wykrycia)} wykryć; wynik niezweryfikowany"
    odp = klient.obserwacja(meta["odcinek"], stan, zrodlo="model", dron=meta.get("dron"), uwagi=uwagi,
                            obraz=str(wynik.relative_to(STAN.parent)) if wynik else None)
    if odp is None:
        print(f"[analiza] API nie przyjęło obserwacji ({klient.blad}); spróbuję ponownie", file=sys.stderr)
        return False
    for p in (meta_plik, zdjecie):
        p.replace(gotowe / p.name)
    print(f"[analiza] {meta['odcinek']}: {stan} ({uwagi})", flush=True)
    return True


if __name__ == "__main__":
    import signal
    signal.signal(signal.SIGTERM, lambda *_: sys.exit(0))
    from ultralytics import YOLO
    model, urz, klient = YOLO(str(MODEL)), urzadzenie(), Klient(timeout=5)
    kolejka = STAN / "zdjecia" / "kolejka"
    kolejka.mkdir(parents=True, exist_ok=True)
    print(f"[analiza] model {MODEL.name} na {urz}; kolejka {kolejka}", flush=True)
    puls, zrobione = 0.0, 0
    try:
        while True:
            for meta_plik in sorted(kolejka.glob("*.json")):
                zrobione += przetworz(model, urz, klient, meta_plik)
            if time.time() - puls > 10:
                klient.puls("analiza", urzadzenie=urz, zdjec=zrobione, w_kolejce=len(list(kolejka.glob("*.json"))))
                puls = time.time()
            time.sleep(1)
    except KeyboardInterrupt:
        pass
