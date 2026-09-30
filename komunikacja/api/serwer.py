"""
API AeroPass dla danych z drona i stacji dokującej (tylko biblioteka standardowa).

    python -m komunikacja.api.serwer          # http://127.0.0.1:8770/v1/zdrowie

Każde żądanie poza /v1/zdrowie wymaga nagłówka  Authorization: Bearer <AEROPASS_TOKEN>.
API jest jedynym zapisującym te pliki w katalogu stanu:
  telemetria.json (ostatnia pozycja każdego drona), obserwacje.jsonl (dziennik obserwacji),
  zdjecia/kolejka/ (zdjęcia czekające na model), uslugi.json (kto żyje w systemie).
Opis pól: komunikacja/api/openapi.yaml.
"""
import json
import os
import re
import sys
import threading
import time
from datetime import datetime, timezone
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from urllib.parse import parse_qs, urlparse

KATALOG = Path(__file__).resolve().parents[2]
STAN = Path(os.environ.get("AEROPASS_STAN", KATALOG / "stan"))
TOKEN = os.environ.get("AEROPASS_TOKEN", "aeropass-dev")
WERSJA = "1.0"
STANY = {"przejezdny", "zalany", "zerwany", "zablokowany", "nieznany"}
ZRODLA = {"dron", "model", "lora", "operator", "symulator"}
MAKS_JSON, MAKS_ZDJECIE = 64 * 1024, 20 * 1024 * 1024
ZDJECIA = {"image/jpeg": ".jpg", "image/png": ".png"}
blokada = threading.Lock()
uslugi = {}


def teraz():
    return datetime.now(timezone.utc).isoformat(timespec="seconds")


def zapisz_atomowo(plik, obj):
    tmp = plik.with_suffix(".tmp")
    tmp.write_text(json.dumps(obj, ensure_ascii=False), encoding="utf-8")
    tmp.replace(plik)


def czytaj(plik, domyslnie):
    try:
        return json.loads(plik.read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return domyslnie


def odcinki():
    """Znane identyfikatory odcinków (z pliku stanu); pusty zbiór = nie sprawdzamy."""
    return {o["id"] for o in czytaj(STAN / "odcinki.json", [])}


def polozenie(p):
    if not (isinstance(p, list) and len(p) == 2 and -90 <= float(p[0]) <= 90 and -180 <= float(p[1]) <= 180):
        raise ValueError("polozenie: [szerokość, długość] w stopniach")
    return [round(float(p[0]), 6), round(float(p[1]), 6)]


def telemetria(d):
    wpis = {"dron": int(d["dron"]), "polozenie": polozenie(d["polozenie"]), "czas": str(d.get("czas") or teraz()),
            "kurs": float(d.get("kurs") or 0) % 360, "bateria_proc": d.get("bateria_proc"),
            "wysokosc_m": d.get("wysokosc_m"), "lacze": d.get("lacze"), "odebrano": teraz()}
    if not 0 <= wpis["dron"] <= 255:
        raise ValueError("dron: 0–255")
    with blokada:
        wszystkie = czytaj(STAN / "telemetria.json", {})
        wszystkie[str(wpis["dron"])] = wpis
        zapisz_atomowo(STAN / "telemetria.json", wszystkie)
    return wpis


def obserwacja(d):
    ids = odcinki()
    if not re.fullmatch(r"odc-\d{4}", str(d.get("odcinek"))) or (ids and d["odcinek"] not in ids):
        raise ValueError("odcinek: nieznany identyfikator (np. odc-0493)")
    if d.get("stan") not in STANY or d.get("zrodlo") not in ZRODLA:
        raise ValueError(f"stan: {sorted(STANY)}; zrodlo: {sorted(ZRODLA)}")
    wpis = {"odcinek": d["odcinek"], "stan": d["stan"], "zrodlo": d["zrodlo"], "czas": str(d.get("czas") or teraz()),
            "dron": d.get("dron"), "pewnosc": d.get("pewnosc"), "obraz": d.get("obraz"), "lacze": d.get("lacze"),
            "uwagi": str(d.get("uwagi") or "")[:300], "odebrano": teraz()}
    with blokada:
        plik = STAN / "obserwacje.jsonl"
        wpis["nr"] = sum(1 for _ in open(plik, encoding="utf-8")) if plik.exists() else 0
        with open(plik, "a", encoding="utf-8") as f:
            f.write(json.dumps(wpis, ensure_ascii=False) + "\n")
    return wpis


def obserwacje_od(od):
    plik = STAN / "obserwacje.jsonl"
    lista = [json.loads(w) for w in open(plik, encoding="utf-8")] if plik.exists() else []
    return {"od": od, "nastepny": len(lista), "obserwacje": lista[od:]}


class Obsluga(BaseHTTPRequestHandler):
    server_version = "AeroPassAPI/" + WERSJA

    def log_message(self, fmt, *a):
        if not self.path.startswith("/v1/zdrowie"):
            sys.stderr.write(f"[api] {self.address_string()} {fmt % a}\n")

    def odpowiedz(self, obj, kod=200):
        body = json.dumps(obj, ensure_ascii=False).encode()
        self.send_response(kod)
        self.send_header("Content-Type", "application/json; charset=utf-8")
        self.send_header("Content-Length", str(len(body)))
        self.end_headers()
        self.wfile.write(body)

    def autoryzacja(self):
        if self.headers.get("Authorization") == f"Bearer {TOKEN}":
            return True
        self.odpowiedz({"blad": "brak albo zły token (nagłówek Authorization: Bearer …)"}, 401)
        return False

    def tresc(self, maks):
        n = int(self.headers.get("Content-Length") or 0)
        if not 0 < n <= maks:
            raise ValueError(f"pusta albo za duża treść (maks. {maks // 1024} kB)")
        return self.rfile.read(n)

    def do_GET(self):
        u = urlparse(self.path)
        if u.path == "/v1/zdrowie":
            return self.odpowiedz({"usluga": "api", "ok": True, "wersja": WERSJA, "czas": teraz()})
        if not self.autoryzacja():
            return
        if u.path == "/v1/telemetria":
            return self.odpowiedz(czytaj(STAN / "telemetria.json", {}))
        if u.path == "/v1/obserwacje":
            return self.odpowiedz(obserwacje_od(int(parse_qs(u.query).get("od", ["0"])[0])))
        if u.path == "/v1/uslugi":
            t = time.time()
            return self.odpowiedz({n: {**u_, "wiek_s": round(t - u_["t"], 1), "ok": t - u_["t"] < 30} for n, u_ in uslugi.items()})
        self.odpowiedz({"blad": "nie ma takiego zasobu"}, 404)

    def do_POST(self):
        u = urlparse(self.path)
        if not self.autoryzacja():
            return
        try:
            if u.path == "/v1/telemetria":
                return self.odpowiedz(telemetria(json.loads(self.tresc(MAKS_JSON))), 201)
            if u.path == "/v1/obserwacje":
                return self.odpowiedz(obserwacja(json.loads(self.tresc(MAKS_JSON))), 201)
            if u.path == "/v1/zdjecia":
                return self.zdjecie(parse_qs(u.query))
            m = re.fullmatch(r"/v1/uslugi/([a-z0-9_-]{1,32})/puls", u.path)
            if m:
                info = json.loads(self.tresc(MAKS_JSON) if int(self.headers.get("Content-Length") or 0) else b"{}")
                uslugi[m.group(1)] = {"t": time.time(), "ostatni_puls": teraz(), "info": info}
                with blokada:
                    zapisz_atomowo(STAN / "uslugi.json", uslugi)
                return self.odpowiedz({"ok": True})
            self.odpowiedz({"blad": "nie ma takiego zasobu"}, 404)
        except (ValueError, KeyError, TypeError) as e:
            self.odpowiedz({"blad": str(e)}, 400)

    def zdjecie(self, q):
        """Zdjęcie odcinka z drona trafia do kolejki; model (ai/zdjecia.py) zamienia je w obserwację."""
        odcinek, typ = q.get("odcinek", [""])[0], self.headers.get("Content-Type", "").split(";")[0]
        ids = odcinki()
        if not re.fullmatch(r"odc-\d{4}", odcinek) or (ids and odcinek not in ids):
            raise ValueError("odcinek: nieznany identyfikator")
        if typ not in ZDJECIA:
            raise ValueError("Content-Type: image/jpeg albo image/png")
        dane = self.tresc(MAKS_ZDJECIE)
        nr = f"{datetime.now(timezone.utc):%Y%m%dT%H%M%S%f}-{odcinek}"
        kolejka = STAN / "zdjecia" / "kolejka"
        kolejka.mkdir(parents=True, exist_ok=True)
        (kolejka / (nr + ZDJECIA[typ])).write_bytes(dane)
        zapisz_atomowo(kolejka / (nr + ".json"), {"odcinek": odcinek, "dron": q.get("dron", [None])[0], "plik": nr + ZDJECIA[typ], "odebrano": teraz()})
        self.odpowiedz({"ok": True, "zdjecie": nr, "status": "w kolejce do analizy"}, 202)


def uruchom(host=None, port=None):
    STAN.mkdir(parents=True, exist_ok=True)
    host = host or os.environ.get("AEROPASS_API_HOST", "127.0.0.1")
    port = int(port or os.environ.get("AEROPASS_API_PORT", 8770))
    if TOKEN == "aeropass-dev":
        print("[api] UWAGA: domyślny token deweloperski; ustaw AEROPASS_TOKEN przed wdrożeniem", file=sys.stderr)
    serwer = ThreadingHTTPServer((host, port), Obsluga)
    print(f"[api] AeroPass API {WERSJA}: http://{host}:{port}/v1/zdrowie", flush=True)
    return serwer


if __name__ == "__main__":
    import signal
    signal.signal(signal.SIGTERM, lambda *_: sys.exit(0))
    try:
        uruchom().serve_forever()
    except KeyboardInterrupt:
        pass
