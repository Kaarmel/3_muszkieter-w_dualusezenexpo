"""
Serwer panelu AeroPass (tylko biblioteka standardowa, działa bez internetu).
Serwuje katalog repo (panel/, stan/, wyniki/) i przyjmuje decyzje: POST /api/decyzja → dopisanie do stan/decyzje.json.
Przyciski symulacji: POST /api/sterowanie {akcja: start|reset|pauza|wznow|tempo} uruchamia symulator/demo.py jako proces potomny.
Analiza filmu: POST /api/film?nazwa=…&zrodlo=… (plik w treści) → ai/film.py w tle → film/wyniki/<nazwa>/ (panel/film.html).

Uruchomienie z katalogu repo: python panel/serwer.py   →   http://localhost:8765/panel/
"""
import importlib.util
import json
import re
import signal
import subprocess
import sys
import threading
from datetime import datetime
from http.server import SimpleHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from urllib.parse import parse_qs, urlparse

KATALOG = Path(__file__).resolve().parent.parent
DECYZJE = KATALOG / "stan" / "decyzje.json"
TYPY = {"decyzja": {"zatwierdzona", "odrzucona", "zmieniona"},
        "potwierdzenie_wykonania": {"zadysponowano", "w_drodze", "dotarlo", "niewykonane"}}
blokada = threading.Lock()
demo = {"proc": None, "ziarno": 56, "strategia": "B", "przygotuj": False}
analiza = {"proc": None}
FILMY = {".mp4", ".mov", ".m4v", ".avi", ".mkv"}
MAKS_FILM = 4 * 1024**3


def wyniki_filmow():
    out = []
    for d in sorted((KATALOG / "film" / "wyniki").glob("*/"), key=lambda d: d.stat().st_mtime, reverse=True):
        wpis = {"katalog": f"film/wyniki/{d.name}/"}
        for nazwa in ("postep", "podsumowanie"):
            try:
                wpis[nazwa] = json.loads((d / f"{nazwa}.json").read_text(encoding="utf-8"))
            except (OSError, ValueError):
                pass
        out.append(wpis)
    p = analiza["proc"]
    return {"trwa": bool(p and p.poll() is None), "wyniki": out,
            "blad": (KATALOG / "film" / "analiza.log").read_text(encoding="utf-8", errors="replace")[-600:]
            if p and p.poll() not in (None, 0) else None}


def uruchom_demo(ziarno, strategia, tempo, reczne, przygotuj):
    """Jeden proces demo naraz: nowy start lub reset kończy poprzedni."""
    zatrzymaj_demo()
    cmd = [sys.executable, "symulator/demo.py", "--ziarno", str(ziarno), "--strategia", strategia, "--tempo", str(tempo),
           "--reczne", json.dumps(reczne)] + (["--przygotuj"] if przygotuj else [])
    log = open(KATALOG / "stan" / "demo.log", "w")
    demo.update(proc=subprocess.Popen(cmd, cwd=KATALOG, stdout=log, stderr=subprocess.STDOUT),
                ziarno=ziarno, strategia=strategia, przygotuj=przygotuj)


def zatrzymaj_demo():
    p = demo["proc"]
    if p and p.poll() is None:
        p.terminate()
        try:
            p.wait(timeout=3)
        except subprocess.TimeoutExpired:
            p.kill()


def sterowanie():
    try:
        s = json.loads((KATALOG / "stan" / "sterowanie.json").read_text(encoding="utf-8"))
    except (OSError, ValueError):
        s = {}
    p = demo["proc"]
    out = {"dziala": bool(p and p.poll() is None and not demo["przygotuj"]), "ziarno": demo["ziarno"],
           "strategia": demo["strategia"], "pauza": bool(s.get("pauza")), "tempo": s.get("tempo", 3)}
    if p and p.poll() not in (None, 0):  # np. brak networkx w środowisku, z którego uruchomiono serwer
        out["blad"] = (KATALOG / "stan" / "demo.log").read_text(encoding="utf-8", errors="replace")[-400:]
    return out


class Obsluga(SimpleHTTPRequestHandler):
    def __init__(self, *a, **k):
        super().__init__(*a, directory=str(KATALOG), **k)

    def end_headers(self):
        self.send_header("Cache-Control", "no-store")
        super().end_headers()

    def log_message(self, *a):  # cisza w terminalu (panel odpytuje co 1,5 s)
        pass

    def odpowiedz(self, obj, kod=200):
        body = json.dumps(obj, ensure_ascii=False).encode()
        self.send_response(kod)
        self.send_header("Content-Type", "application/json; charset=utf-8")
        self.send_header("Content-Length", str(len(body)))
        self.end_headers()
        self.wfile.write(body)

    def do_GET(self):
        if self.path.split("?")[0] == "/api/sterowanie":
            return self.odpowiedz(sterowanie())
        if self.path.split("?")[0] == "/api/film":
            return self.odpowiedz(wyniki_filmow())
        zakres = re.fullmatch(r"bytes=(\d*)-(\d*)", self.headers.get("Range", ""))
        plik = Path(self.translate_path(self.path))
        if zakres and any(zakres.groups()) and plik.is_file():
            return self.fragment(plik, *zakres.groups())
        super().do_GET()

    def fragment(self, plik, a, b):
        """Odpowiedź 206 na Range: bez tego Safari nie odtworzy filmu w <video>."""
        rozmiar = plik.stat().st_size
        start = int(a) if a else max(0, rozmiar - int(b))
        koniec = min(int(b), rozmiar - 1) if a and b else rozmiar - 1
        if start > koniec:
            return self.send_error(416)
        self.send_response(206)
        self.send_header("Content-Type", self.guess_type(str(plik)))
        self.send_header("Content-Range", f"bytes {start}-{koniec}/{rozmiar}")
        self.send_header("Content-Length", str(koniec - start + 1))
        self.send_header("Accept-Ranges", "bytes")
        self.end_headers()
        with open(plik, "rb") as f:
            f.seek(start)
            reszta = koniec - start + 1
            while reszta > 0:
                kawalek = f.read(min(reszta, 1 << 20))
                if not kawalek:
                    break
                self.wfile.write(kawalek)
                reszta -= len(kawalek)

    def film(self):
        """Wgranie filmu (surowa treść żądania, zapis kawałkami) i start analizy offline w tle."""
        q = parse_qs(urlparse(self.path).query)
        nazwa = re.sub(r"[^\w.-]", "_", Path(q.get("nazwa", [""])[0]).name)[:80].lstrip(".")
        zrodlo = q.get("zrodlo", [""])[0].strip()[:200]
        dlugosc = int(self.headers.get("Content-Length", 0))
        if Path(nazwa).suffix.lower() not in FILMY:
            return self.odpowiedz({"blad": f"obsługiwane pliki: {', '.join(sorted(FILMY))}"}, 400)
        if not zrodlo:
            return self.odpowiedz({"blad": "podaj źródło i licencję filmu (wymóg regulaminu)"}, 400)
        if not 0 < dlugosc <= MAKS_FILM:
            return self.odpowiedz({"blad": "pusty albo za duży plik (maks. 4 GB)"}, 400)
        if not importlib.util.find_spec("ultralytics"):
            return self.odpowiedz({"blad": f"brak ultralytics w {sys.executable}: pip install ultralytics "
                                           "albo uruchom serwer z venv, w którym jest model"}, 400)
        if analiza["proc"] and analiza["proc"].poll() is None:
            return self.odpowiedz({"blad": "trwa analiza innego filmu"}, 409)
        cel = KATALOG / "film" / "wejscie" / nazwa
        cel.parent.mkdir(parents=True, exist_ok=True)
        with open(cel, "wb") as f:
            reszta = dlugosc
            while reszta:
                kawalek = self.rfile.read(min(reszta, 1 << 20))
                if not kawalek:
                    return self.odpowiedz({"blad": "przerwane wysyłanie"}, 400)
                f.write(kawalek)
                reszta -= len(kawalek)
        log = open(KATALOG / "film" / "analiza.log", "w")
        analiza["proc"] = subprocess.Popen([sys.executable, "ai/film.py", str(cel), "--zrodlo", zrodlo],
                                           cwd=KATALOG, stdout=log, stderr=subprocess.STDOUT)
        self.odpowiedz({"ok": True, "plik": nazwa})

    def steruj(self):
        try:
            d = json.loads(self.rfile.read(int(self.headers.get("Content-Length", 0))) or b"{}")
            akcja = d.get("akcja")
            if akcja in ("start", "reset"):
                ziarno, strategia = int(d.get("ziarno", 56)), d.get("strategia", "B")
                tempo = min(max(float(d.get("tempo", 3)), 0.1), 120)
                reczne = {str(k): str(v) for k, v in (d.get("reczne") or {}).items()}
                if strategia not in ("A", "B") or not 0 <= ziarno < 10**6:
                    raise ValueError("niepoprawny scenariusz")
                uruchom_demo(ziarno, strategia, tempo, reczne, przygotuj=akcja == "reset")
            elif akcja in ("pauza", "wznow", "tempo"):
                s = sterowanie()
                plik = KATALOG / "stan" / "sterowanie.json"
                tmp = plik.with_suffix(".tmp")
                tmp.write_text(json.dumps({"pauza": akcja == "pauza" or (akcja == "tempo" and s["pauza"]),
                                           "tempo": min(max(float(d.get("tempo", s["tempo"])), 0.1), 120)}), encoding="utf-8")
                tmp.replace(plik)
            else:
                raise ValueError("nieznana akcja")
            self.odpowiedz(sterowanie())
        except Exception as e:
            self.odpowiedz({"blad": str(e)}, 400)

    def do_POST(self):
        if self.path == "/api/sterowanie":
            return self.steruj()
        if self.path.startswith("/api/film"):
            return self.film()
        if self.path != "/api/decyzja":
            return self.send_error(404)
        try:
            d = json.loads(self.rfile.read(int(self.headers.get("Content-Length", 0))) or b"{}")
            typ, wynik = d.get("typ", "decyzja"), d.get("wynik")
            if typ not in TYPY or wynik not in TYPY[typ] or not str(d.get("dotyczy", "")).startswith(("mel-", "lot-", "dec-")):
                raise ValueError("niepoprawna decyzja")
            with blokada:
                log = json.loads(DECYZJE.read_text(encoding="utf-8")) if DECYZJE.exists() else []
                try:  # czas z zegara misji (demo), a jeśli go brak, czas rzeczywisty
                    czas = json.loads((KATALOG / "stan" / "misja.json").read_text(encoding="utf-8"))["czas"]
                except Exception:
                    czas = datetime.now().astimezone().isoformat(timespec="seconds")
                wpis = {"id": f"dec-{len(log) + 1:04d}", "typ": typ, "dotyczy": d["dotyczy"], "czas": czas,
                        "kto": str(d.get("kto") or "dyżurny (demo)")[:80], "wynik": wynik,
                        "zmiana": (str(d["zmiana"])[:300] if d.get("zmiana") else None),
                        "uwagi": str(d.get("uwagi") or "")[:300], "symulowane": True}
                log.append(wpis)  # dziennik: tylko dopisujemy
                tmp = DECYZJE.with_suffix(".tmp")
                tmp.write_text(json.dumps(log, ensure_ascii=False), encoding="utf-8")
                tmp.replace(DECYZJE)
            body, kod = json.dumps(wpis, ensure_ascii=False).encode(), 200
        except Exception as e:
            body, kod = json.dumps({"blad": str(e)}, ensure_ascii=False).encode(), 400
        self.send_response(kod)
        self.send_header("Content-Type", "application/json; charset=utf-8")
        self.send_header("Content-Length", str(len(body)))
        self.end_headers()
        self.wfile.write(body)


if __name__ == "__main__":
    print("Panel AeroPass: http://localhost:8765/panel/  (Ctrl+C kończy)")
    (KATALOG / "stan").mkdir(exist_ok=True)
    signal.signal(signal.SIGTERM, lambda *_: sys.exit(0))  # zamknięcie terminala też sprząta proces demo
    if not (KATALOG / "stan" / "misja.json").exists():
        uruchom_demo(56, "B", 3, {}, przygotuj=True)  # pierwszy start: pusta mapa scenariusza z prezentacji
    try:
        ThreadingHTTPServer(("127.0.0.1", 8765), Obsluga).serve_forever()
    except KeyboardInterrupt:
        pass
    finally:
        zatrzymaj_demo()
        if analiza["proc"] and analiza["proc"].poll() is None:
            analiza["proc"].terminate()
