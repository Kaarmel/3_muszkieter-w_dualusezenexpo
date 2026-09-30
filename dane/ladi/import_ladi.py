"""Pobierz 1500 zdjęć referencyjnych LADI v2 (bez treningu modelu).

    pip install pyarrow pillow
    python dane/ladi/import_ladi.py
    python dane/ladi/import_ladi.py --check
"""

import argparse
import csv
import hashlib
import io
import shutil
import tempfile
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path
from urllib.request import urlopen


ROOT = Path(__file__).resolve().parents[2]
DEST = ROOT / "dane" / "ladi"
REVISION = "5f2dbfe8c466d32edafd1bab847ec5252309acdb"
BASE = f"https://huggingface.co/datasets/MITLL/LADI-v2-dataset/resolve/{REVISION}/data"
LIMIT = 1500


def sprawdz():
    with (DEST / "manifest.csv").open(newline="", encoding="utf-8") as plik:
        rows = list(csv.DictReader(plik))
    assert len(rows) == LIMIT, f"jest {len(rows)} zamiast {LIMIT} zdjęć"
    assert len({r["plik"] for r in rows}) == LIMIT, "powtórzone nazwy"
    assert len({r["source_sha256"] for r in rows}) == LIMIT, "powtórzone obrazy źródłowe"
    assert len(list((DEST / "obrazy").glob("*.jpg"))) == LIMIT, "liczba plików nie zgadza się z manifestem"
    for r in rows:
        obraz = (DEST / "obrazy" / r["plik"]).read_bytes()
        assert hashlib.sha256(obraz).hexdigest() == r["sha256"], r["plik"]
    print(f"OK: {LIMIT} różnych plików, {sum(int(r['roads_any']) for r in rows)} z etykietą drogi, "
          f"{sum(int(r['flooding_any']) for r in rows)} z etykietą zalania")


def pobierz(split, nr, folder):
    nazwa = f"data-{nr:05d}-of-00040.arrow"
    url = f"{BASE}/{split}/{nazwa}"
    plik = folder / f"{split}-{nr:02d}.arrow"
    for proba in range(3):
        try:
            with urlopen(url, timeout=120) as odpowiedz, plik.open("wb") as cel:
                shutil.copyfileobj(odpowiedz, cel)
            return plik
        except Exception:
            plik.unlink(missing_ok=True)
            if proba == 2:
                raise


def importuj():
    import pyarrow as pa
    from PIL import Image, ImageOps

    if (DEST / "obrazy").exists() or (DEST / "manifest.csv").exists():
        raise SystemExit("Dane już istnieją; sprawdź je przez --check")

    widziane = set()
    rows = []
    with tempfile.TemporaryDirectory(prefix="aeropass-ladi-") as tymczasowy:
        folder = Path(tymczasowy)
        obrazy = folder / "obrazy"
        obrazy.mkdir()

        for split in ("test", "validation"):
            with ThreadPoolExecutor(max_workers=4) as pool:
                zadania = {}
                nastepny = 0
                for nr in range(40):
                    while nastepny < min(nr + 4, 40):
                        zadania[nastepny] = pool.submit(pobierz, split, nastepny, folder)
                        nastepny += 1
                    plik = zadania.pop(nr).result()
                    czytnik = pa.ipc.open_stream(pa.memory_map(str(plik)))
                    indeks = 0
                    for partia in czytnik:
                        for pozycja in range(partia.num_rows):
                            surowe = partia.column("image")[pozycja].as_py()["bytes"]
                            zrodlo_sha = hashlib.sha256(surowe).hexdigest()
                            if zrodlo_sha in widziane:
                                indeks += 1
                                continue
                            with Image.open(io.BytesIO(surowe)) as wejscie:
                                obraz = ImageOps.exif_transpose(wejscie).convert("RGB")
                                obraz.thumbnail((640, 640), Image.Resampling.LANCZOS)
                            wynik = io.BytesIO()
                            obraz.save(wynik, "JPEG", quality=80)
                            bajty = wynik.getvalue()
                            nazwa = f"{split}-{nr:02d}-{indeks:03d}.jpg"
                            (obrazy / nazwa).write_bytes(bajty)
                            etykiety = {k: int(partia.column(k)[pozycja].as_py()) for k in partia.schema.names if k != "image"}
                            rows.append({"plik": nazwa, "source_row": f"data/{split}/data-{nr:05d}-of-00040.arrow#{indeks}",
                                         "source_sha256": zrodlo_sha, "sha256": hashlib.sha256(bajty).hexdigest(),
                                         **etykiety})
                            widziane.add(zrodlo_sha)
                            indeks += 1
                            if len(rows) == LIMIT:
                                break
                        if len(rows) == LIMIT:
                            break
                    plik.unlink()
                    print(f"{split} {nr + 1}/40: {len(rows)} zdjęć", flush=True)
                    if len(rows) == LIMIT:
                        break
            if len(rows) == LIMIT:
                break

        if len(rows) != LIMIT:
            raise RuntimeError(f"zebrano tylko {len(rows)} zdjęć")
        manifest = folder / "manifest.csv"
        with manifest.open("w", newline="", encoding="utf-8") as plik:
            pisz = csv.DictWriter(plik, fieldnames=list(rows[0]), lineterminator="\n")
            pisz.writeheader()
            pisz.writerows(rows)
        DEST.mkdir(parents=True, exist_ok=True)
        shutil.move(str(obrazy), DEST / "obrazy")
        shutil.move(str(manifest), DEST / "manifest.csv")
    sprawdz()


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--check", action="store_true", help="sprawdź pliki i sumy SHA-256")
    args = parser.parse_args()
    sprawdz() if args.check else importuj()
