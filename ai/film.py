"""
Analiza filmu z drona po locie (offline): YOLO11n-seg (ai/model/best.pt, FloodNet) na każdej klatce,
poligony zalanych i suchych dróg, pasek oceny odcinka i kilka kadrów PNG do prezentacji.

    python ai/film.py film.mp4 --zrodlo "autor, link, licencja"   →   film/wyniki/<nazwa>/
    python ai/film.py --test                                       →   sprawdzenie logiki oceny

Offline, nie w czasie rzeczywistym: pełna rozdzielczość i każda klatka zamiast strumienia z drona;
szybkość przetwarzania zapisujemy w podsumowanie.json. Wynik modelu na tym nagraniu nie jest zweryfikowany.
Wymaga: pip install ultralytics (i ffmpeg w systemie).
"""
import argparse
import json
import subprocess
import sys
import time
from collections import Counter, deque
from pathlib import Path

KATALOG = Path(__file__).resolve().parent.parent
MODEL = KATALOG / "ai" / "model" / "best.pt"
PROG_ZALANY, PROG_SUCHY = 0.4, 0.5  # jak w notatniku treningu (metryka decyzji)
KLASY = {"flooded_road": ("zalana droga", (235, 99, 37)),      # BGR, kolory jak w panelu
         "road_non_flooded": ("sucha droga", (61, 128, 21)),
         "flooded_building": ("zalany budynek", (178, 145, 8))}
OCENA = {"zalany": ("ODCINEK ZALANY", (38, 40, 198)), "przejezdny": ("ODCINEK PRZEJEZDNY", (61, 128, 21)),
         "nieznany": ("NIE WIADOMO", (112, 98, 91))}
MAKS_SZER = 1920


def stan_klatki(wykrycia):
    """Brak dowodu = „nieznany”, nigdy „przejezdny” (ta sama logika co metryka w notatniku)."""
    if any(n == "flooded_road" and c >= PROG_ZALANY for n, c in wykrycia):
        return "zalany"
    if any(n == "road_non_flooded" and c >= PROG_SUCHY for n, c in wykrycia):
        return "przejezdny"
    return "nieznany"


def wygladz(okno, k):
    """Ocena z ostatniej sekundy: zalanie wygrywa już przy k klatkach (asymetrycznie, bo fałszywie
    przejezdna droga jest groźniejsza), przejezdny tylko przy większości, inaczej „nieznany”."""
    c = Counter(okno)
    if c["zalany"] >= k:
        return "zalany"
    if c["przejezdny"] > len(okno) / 2:
        return "przejezdny"
    return "nieznany"


def czcionka(rozmiar, gruba=False):
    from PIL import ImageFont
    for p in (f"/System/Library/Fonts/Supplemental/Arial{' Bold' if gruba else ''}.ttf",
              "/usr/share/fonts/truetype/dejavu/DejaVuSans.ttf"):
        if Path(p).exists():
            return ImageFont.truetype(p, rozmiar)
    return ImageFont.load_default()


def rysuj(klatka, poligony, ocena, zrodlo, t_s):
    import cv2
    import numpy as np
    from PIL import Image, ImageDraw
    h, w = klatka.shape[:2]
    s = w / 1280  # skala napisów
    warstwa = klatka.copy()
    for nazwa, _, pts in poligony:
        cv2.fillPoly(warstwa, [pts], KLASY[nazwa][1], cv2.LINE_AA)
    out = cv2.addWeighted(warstwa, 0.38, klatka, 0.62, 0)
    for nazwa, _, pts in poligony:
        cv2.polylines(out, [pts], True, KLASY[nazwa][1], max(2, round(2 * s)), cv2.LINE_AA)
    obraz = Image.fromarray(out[:, :, ::-1])
    d = ImageDraw.Draw(obraz, "RGBA")
    f_et, f_pas, f_male = czcionka(round(17 * s), True), czcionka(round(26 * s), True), czcionka(round(15 * s))
    for nazwa, pole, pts in poligony:  # etykiety tylko na większych obszarach, żeby nie zasłaniać obrazu
        if pole < 0.004 * w * h:
            continue
        x, y = pts[:, 0].mean(), pts[:, 1].mean()
        tekst = KLASY[nazwa][0]
        l, t, r, b = d.textbbox((x, y), tekst, font=f_et, anchor="mm")
        d.rounded_rectangle((l - 6 * s, t - 4 * s, r + 6 * s, b + 4 * s), radius=5 * s, fill=(17, 24, 39, 190))
        d.text((x, y), tekst, font=f_et, fill="white", anchor="mm")
    # górny pasek: ocena odcinka (wygładzona z ostatniej sekundy)
    tekst, kolor = OCENA[ocena]
    pas = round(52 * s)
    d.rectangle((0, 0, w, pas), fill=(17, 24, 39, 215))
    d.rectangle((0, 0, round(12 * s), pas), fill=kolor[::-1] + (255,))
    d.text((round(24 * s), pas / 2), "AeroPass · ocena odcinka:", font=f_pas, fill=(209, 213, 219), anchor="lm")
    x0 = d.textbbox((round(24 * s), pas / 2), "AeroPass · ocena odcinka: ", font=f_pas, anchor="lm")[2]
    d.text((x0, pas / 2), tekst, font=f_pas, fill=kolor[::-1], anchor="lm")
    d.text((w - round(18 * s), pas / 2), f"{int(t_s // 60):02d}:{t_s % 60:04.1f}", font=f_pas, fill=(209, 213, 219), anchor="rm")
    # legenda
    y = pas + round(12 * s)
    for nazwa, (opis, kol) in KLASY.items():
        d.rounded_rectangle((w - round(210 * s), y, w - round(12 * s), y + round(26 * s)), radius=5 * s, fill=(17, 24, 39, 170))
        d.rectangle((w - round(200 * s), y + round(7 * s), w - round(186 * s), y + round(19 * s)), fill=kol[::-1] + (255,))
        d.text((w - round(178 * s), y + round(13 * s)), opis, font=f_male, fill="white", anchor="lm")
        y += round(32 * s)
    # dolny pasek: uczciwe oznaczenie
    dol = round(30 * s)
    d.rectangle((0, h - dol, w, h), fill=(17, 24, 39, 200))
    d.text((round(14 * s), h - dol / 2), "Analiza offline po locie · YOLO11n-seg douczony na FloodNet (Teksas) · wynik niezweryfikowany na tym nagraniu"
           + (f" · Źródło filmu: {zrodlo}" if zrodlo else ""), font=f_male, fill=(209, 213, 219), anchor="lm")
    return np.asarray(obraz)[:, :, ::-1].copy()


def urzadzenie():
    import torch
    return "mps" if torch.backends.mps.is_available() else ("cuda" if torch.cuda.is_available() else "cpu")


def wykryj(model, klatka, urz):
    """YOLO na jednej klatce: [(klasa, pewność)] do oceny i [(klasa, pole, punkty)] do rysowania."""
    import cv2
    r = model.predict(klatka, imgsz=640, conf=0.25, retina_masks=True, device=urz, verbose=False)[0]
    wykrycia, poligony = [], []
    if r.masks is not None:
        for c, p, xy in zip(r.boxes.cls.tolist(), r.boxes.conf.tolist(), r.masks.xy):
            nazwa = model.names[int(c)]
            wykrycia.append((nazwa, p))
            if nazwa in KLASY and len(xy) >= 3:
                pts = xy.astype("int32")
                poligony.append((nazwa, cv2.contourArea(pts), pts))
    return wykrycia, poligony


def analizuj(wejscie, wyjscie, zrodlo=""):
    import cv2
    from ultralytics import YOLO
    wyjscie.mkdir(parents=True, exist_ok=True)
    postep = wyjscie / "postep.json"

    def zapisz_postep(**kw):
        postep.write_text(json.dumps({"plik": wejscie.name, "zrodlo": zrodlo, **kw}, ensure_ascii=False), encoding="utf-8")

    cap = cv2.VideoCapture(str(wejscie))
    if not cap.isOpened():
        raise SystemExit(f"Nie mogę otworzyć filmu: {wejscie}")
    fps = cap.get(cv2.CAP_PROP_FPS) or 25.0
    n = int(cap.get(cv2.CAP_PROP_FRAME_COUNT)) or 0
    w0, h0 = int(cap.get(cv2.CAP_PROP_FRAME_WIDTH)), int(cap.get(cv2.CAP_PROP_FRAME_HEIGHT))
    skala = min(1.0, MAKS_SZER / w0)
    w, h = int(w0 * skala) // 2 * 2, int(h0 * skala) // 2 * 2  # H.264 + yuv420p wymaga parzystych wymiarów
    urz = urzadzenie()
    model = YOLO(str(MODEL))
    film = wyjscie / f"{wejscie.stem}_aeropass.mp4"
    ff = subprocess.Popen(["ffmpeg", "-loglevel", "error", "-y", "-f", "rawvideo", "-pix_fmt", "bgr24", "-s", f"{w}x{h}",
                           "-r", f"{fps:.3f}", "-i", "-", "-an", "-c:v", "libx264", "-preset", "veryfast", "-crf", "20",
                           "-pix_fmt", "yuv420p", "-movflags", "+faststart", str(film)], stdin=subprocess.PIPE)
    okno, k = deque(maxlen=max(1, round(fps))), max(2, round(fps / 4))
    oceny, na_sekunde, kadry = Counter(), [], {}
    t0, i = time.time(), 0
    zapisz_postep(etap="analiza", klatka=0, klatek=n)
    while True:
        ok, klatka = cap.read()
        if not ok:
            break
        if (klatka.shape[1], klatka.shape[0]) != (w, h):
            klatka = cv2.resize(klatka, (w, h), interpolation=cv2.INTER_AREA)
        wykrycia, poligony = wykryj(model, klatka, urz)
        okno.append(stan_klatki(wykrycia))
        ocena = wygladz(okno, k)
        oceny[ocena] += 1
        t_s = i / fps
        if int(t_s) >= len(na_sekunde):
            na_sekunde.append(ocena)
        gotowa = rysuj(klatka, poligony, ocena, zrodlo, t_s)
        ff.stdin.write(gotowa.tobytes())
        # kadry do slajdów: w każdej ćwiartce filmu klatka z największym obszarem zalanej (albo suchej) drogi
        pole = sum(p for nz, p, _ in poligony if nz == "flooded_road") * 10 + sum(p for nz, p, _ in poligony if nz == "road_non_flooded")
        cw = min(3, int(4 * i / n)) if n else 0
        if pole > kadry.get(cw, (-1,))[0]:
            kadry[cw] = (pole, i, gotowa)
        i += 1
        if i % 15 == 0:
            zapisz_postep(etap="analiza", klatka=i, klatek=n, fps_przetwarzania=round(i / (time.time() - t0), 1))
    cap.release()
    ff.stdin.close()
    if ff.wait() != 0:
        raise SystemExit("ffmpeg nie zapisał filmu")
    czas = time.time() - t0
    pliki_kadrow = []
    for cw, (_, nr, obraz) in sorted(kadry.items()):
        p = wyjscie / f"kadr_{cw + 1}_{nr / fps:05.1f}s.png"
        cv2.imwrite(str(p), obraz)
        pliki_kadrow.append(p.name)
    podsumowanie = {
        "plik": wejscie.name, "zrodlo": zrodlo, "film": film.name, "kadry": pliki_kadrow,
        "klatek": i, "fps_filmu": round(fps, 2), "rozdzielczosc": [w, h], "urzadzenie": urz,
        "czas_przetwarzania_s": round(czas, 1), "fps_przetwarzania": round(i / czas, 1) if czas else None,
        "udzial_klatek": {s: round(oceny[s] / i, 3) if i else 0 for s in OCENA},
        "ocena_na_sekunde": na_sekunde,
        "model": "YOLO11n-seg douczony na FloodNet (ai/model/best.pt), imgsz 640, conf 0.25",
        "progi": {"zalany": PROG_ZALANY, "suchy": PROG_SUCHY, "okno_klatek": okno.maxlen, "zalanie_od_klatek": k},
        "uwaga": "analiza offline; wynik niezweryfikowany na tym nagraniu; ocena odcinka to wygładzona ocena klatek z ostatniej sekundy",
    }
    (wyjscie / "podsumowanie.json").write_text(json.dumps(podsumowanie, ensure_ascii=False, indent=1), encoding="utf-8")
    zapisz_postep(etap="gotowe", klatka=i, klatek=i, fps_przetwarzania=podsumowanie["fps_przetwarzania"])
    return podsumowanie


def test():
    assert stan_klatki([]) == "nieznany"
    assert stan_klatki([("road_non_flooded", 0.9), ("flooded_road", 0.45)]) == "zalany"
    assert stan_klatki([("flooded_road", 0.3), ("road_non_flooded", 0.6)]) == "przejezdny"
    assert stan_klatki([("flooded_building", 0.9)]) == "nieznany"
    assert wygladz(["przejezdny"] * 20 + ["zalany"] * 5, 5) == "zalany"      # zalanie wygrywa już przy k klatkach
    assert wygladz(["przejezdny"] * 13 + ["nieznany"] * 12, 5) == "przejezdny"
    assert wygladz(["przejezdny"] * 12 + ["nieznany"] * 13, 5) == "nieznany"  # bez większości nie zgadujemy
    print("OK: ocena klatek i wygładzanie (brak dowodu = nie wiadomo, zalanie ma pierwszeństwo)")


if __name__ == "__main__":
    ap = argparse.ArgumentParser()
    ap.add_argument("film", nargs="?", type=Path)
    ap.add_argument("--zrodlo", default="", help="autor, link i licencja filmu (widoczne na nagraniu)")
    ap.add_argument("--wyjscie", type=Path, help="domyślnie film/wyniki/<nazwa filmu>")
    ap.add_argument("--test", action="store_true")
    a = ap.parse_args()
    if a.test or not a.film:
        test()
        sys.exit(0)
    wynik = analizuj(a.film, a.wyjscie or KATALOG / "film" / "wyniki" / a.film.stem, a.zrodlo)
    print(json.dumps({k: wynik[k] for k in ("film", "kadry", "klatek", "fps_filmu", "fps_przetwarzania", "udzial_klatek")}, ensure_ascii=False))
