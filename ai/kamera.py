"""Lokalne porównanie scen z kamerki modelem CLIP: python ai/kamera.py."""

from io import BytesIO
import json
import math
import os
from http.server import BaseHTTPRequestHandler, HTTPServer
from pathlib import Path
from datetime import datetime, timezone
from uuid import uuid4

import torch
from PIL import Image, UnidentifiedImageError
from transformers import pipeline


HTML = Path(__file__).with_suffix(".html")
STAN = Path(os.environ.get("AEROPASS_STAN", Path(__file__).resolve().parents[1] / "stan"))
MODEL = "openai/clip-vit-base-patch32"
REVISION = "3d74acf9a28c67741b2f4f2ea7635f0aaf6f0268"
OPISY = {
    "zalany": "a photo of a street flooded with water",
    "suchy": "a photo of a dry street with no flooding",
    "rzeka": "a photo of a river or lake",
    "wnetrze": "an indoor photo",
}


def decyzja(wyniki):
    """Wybór najbliższego opisu; pozostałe sceny są poza zakresem pokazu."""
    najlepszy = max(wyniki, key=lambda w: w["score"])["label"]
    return {OPISY["zalany"]: "zalany", OPISY["suchy"]: "suchy"}.get(najlepszy, "nieznany")


def analizuj(model, obraz):
    wyniki = model(obraz, candidate_labels=list(OPISY.values()))
    typy = {opis: typ for typ, opis in OPISY.items()}
    return {"stan": decyzja(wyniki),
            "wyniki": [{"typ": typy[w["label"]], "score": round(w["score"], 3)} for w in wyniki]}


def zapisz_kandydata(obraz, wynik, katalog=STAN):
    # ponytail: niezatwierdzone zdjęcia zostają na dysku; sprzątanie po czasie dodaj przy dłuższym użyciu.
    ident = uuid4().hex
    (katalog / "obrazy_operatora").mkdir(parents=True, exist_ok=True)
    (katalog / "kandydaci").mkdir(parents=True, exist_ok=True)
    obraz.save(katalog / "obrazy_operatora" / f"{ident}.jpg", format="JPEG", quality=90)
    kandydat = {"id": ident, "czas_analizy": datetime.now(timezone.utc).isoformat(timespec="seconds"),
                "model": MODEL, "wyniki": wynik["wyniki"], "sugestia": wynik["stan"]}
    (katalog / "kandydaci" / f"{ident}.json").write_text(json.dumps(kandydat, ensure_ascii=False), encoding="utf-8")
    return kandydat


def zatwierdz(dane, katalog=STAN):
    if not isinstance(dane, dict):
        raise ValueError("wyślij obiekt JSON")
    ident = str(dane.get("id", ""))
    if len(ident) != 32 or any(c not in "0123456789abcdef" for c in ident):
        raise ValueError("niepoprawny identyfikator zdjęcia")
    plik = katalog / "kandydaci" / f"{ident}.json"
    if not plik.is_file():
        raise ValueError("zdjęcie nie czeka na zatwierdzenie")
    typ = dane.get("typ")
    if typ not in {"zalanie", "brak_widocznego_zalania", "drzewa", "uszkodzony_most", "inne", "nie_ustalono"}:
        raise ValueError("wybierz rodzaj obserwacji")
    gps = [float(dane.get("lat")), float(dane.get("lon"))]
    if not all(map(math.isfinite, gps)) or not (-90 <= gps[0] <= 90 and -180 <= gps[1] <= 180):
        raise ValueError("niepoprawne współrzędne GPS")
    operator = str(dane.get("operator", "")).strip()[:80]
    zrodlo = str(dane.get("zrodlo", "")).strip()[:200]
    if not operator or not zrodlo:
        raise ValueError("podaj operatora i źródło zdjęcia")
    material = dane.get("material")
    if material not in {"demo", "lot"}:
        raise ValueError("oznacz materiał jako demo lub ujęcie z lotu")
    liczba = int(dane.get("liczba") or 0) if typ == "drzewa" else None
    if liczba is not None and not 1 <= liczba <= 999:
        raise ValueError("podaj liczbę drzew od 1 do 999")
    kandydat = json.loads(plik.read_text(encoding="utf-8"))
    wpis = {**kandydat, "czas_potwierdzenia": datetime.now(timezone.utc).isoformat(timespec="seconds"),
            "gps": gps, "typ": typ, "liczba": liczba, "operator": operator, "zrodlo": zrodlo,
            "material": material, "uwagi": str(dane.get("uwagi") or "").strip()[:300],
            "obraz": f"stan/obrazy_operatora/{ident}.jpg", "potwierdzone_przez_operatora": True}
    cel = katalog / "obserwacje_operatora.json"
    lista = json.loads(cel.read_text(encoding="utf-8")) if cel.exists() else []
    if any(o["id"] == ident for o in lista):
        raise ValueError("obserwacja została już zatwierdzona")
    lista.append(wpis)
    tmp = cel.with_suffix(".tmp")
    tmp.write_text(json.dumps(lista, ensure_ascii=False, indent=2), encoding="utf-8")
    tmp.replace(cel)
    plik.unlink()
    return wpis


class Obsluga(BaseHTTPRequestHandler):
    model = None

    def log_message(self, *args):
        pass

    def odpowiedz(self, kod, dane):
        body = json.dumps(dane, ensure_ascii=False).encode("utf-8")
        self.send_response(kod)
        self.send_header("Content-Type", "application/json; charset=utf-8")
        self.send_header("Content-Length", str(len(body)))
        self.send_header("Cache-Control", "no-store")
        self.end_headers()
        self.wfile.write(body)

    def do_GET(self):
        if self.path != "/":
            return self.send_error(404)
        body = HTML.read_bytes()
        self.send_response(200)
        self.send_header("Content-Type", "text/html; charset=utf-8")
        self.send_header("Content-Length", str(len(body)))
        self.send_header("Cache-Control", "no-store")
        self.end_headers()
        self.wfile.write(body)

    def do_POST(self):
        if self.path == "/api/potwierdz":
            try:
                rozmiar = int(self.headers.get("Content-Length", "0"))
                if self.headers.get("Content-Type") != "application/json" or not 0 < rozmiar <= 4096:
                    raise ValueError("wyślij JSON do 4 KB")
                self.odpowiedz(200, zatwierdz(json.loads(self.rfile.read(rozmiar))))
            except (ValueError, TypeError, OSError, json.JSONDecodeError) as e:
                self.odpowiedz(400, {"blad": str(e)})
            return
        if self.path not in ("/api/analiza", "/api/analiza?zapisz=1"):
            return self.send_error(404)
        try:
            rozmiar = int(self.headers.get("Content-Length", "0"))
            if self.headers.get("Content-Type") != "image/jpeg" or not 0 < rozmiar <= 5_000_000:
                raise ValueError("wyślij klatkę JPEG do 5 MB")
            with Image.open(BytesIO(self.rfile.read(rozmiar))) as plik:
                if max(plik.size) > 2048:
                    raise ValueError("obraz większy niż 2048 px")
                obraz = plik.convert("RGB")
        except (ValueError, UnidentifiedImageError, OSError) as e:
            self.odpowiedz(400, {"blad": str(e)})
            return
        try:
            wynik = analizuj(self.model, obraz)
            if self.path.endswith("zapisz=1"):
                wynik["kandydat"] = zapisz_kandydata(obraz, wynik)["id"]
            self.odpowiedz(200, wynik)
        except Exception as e:
            self.odpowiedz(500, {"blad": f"błąd modelu: {e}"})


if __name__ == "__main__":
    urzadzenie = "mps" if torch.backends.mps.is_available() else ("cuda" if torch.cuda.is_available() else "cpu")
    print(f"Ładuję CLIP na {urzadzenie} (przy pierwszym uruchomieniu pobiera wagi)…", flush=True)
    Obsluga.model = pipeline("zero-shot-image-classification", model=MODEL, revision=REVISION, device=urzadzenie)
    print("AeroPass kamera: http://localhost:8767/  (Ctrl+C kończy)", flush=True)
    HTTPServer(("127.0.0.1", 8767), Obsluga).serve_forever()
