# FloodNet w Google Colab: pobranie i przygotowanie (rola A)

**Dlaczego Colab, a nie laptop:** zip ma 13 GB (sprawdzone 29.09), a Mac ma ok. 33 GB wolnego miejsca. Pobieranie zajęłoby Wi-Fi całego zespołu, a folder projektu leży na Google Drive, który wysłałby wszystko do chmury. Colab pobiera z prędkością centrum danych i ma darmowe GPU.

**Co wraca do repo:** tylko małe pliki: `wyniki/metryki.json` i 5–10 obrazów z predykcjami. Zbiór zostaje w Colabie.

Colab: *Runtime → Change runtime type → T4 GPU*. Każdy blok poniżej to jedna komórka.

## 1. Pobranie i rozpakowanie (~10–20 min)

```bash
!wget -q --show-progress -O FloodNet.zip "https://www.dropbox.com/scl/fo/k33qdif15ns2qv2jdxvhx/ANGaa8iPRhvlrvcKXjnmNRc?rlkey=ao2493wzl1cltonowjdbrnp7f&dl=1"
!unzip -q FloodNet.zip -d FloodNet && rm FloodNet.zip
!find FloodNet -maxdepth 4 -type d
```

Jeśli `unzip` zgłosi błąd (bywa przy dużych zipach z Dropboxa), użyjcie `!7z x FloodNet.zip -oFloodNet`.

**Sprawdźcie wynik `find`:** komórka 2 zakłada, że zdjęcia są w `.jpg`, a maski w `.png`. Jeśli jest inaczej, popraw rozszerzenia.

## 2. Zmniejszenie do 512 px i liczność klas

Zmniejszony zbiór to kilkaset MB zamiast 13 GB. Da się go trenować w Colabie albo lokalnie na Macu (M2 Pro, PyTorch z MPS).

```python
from pathlib import Path
from collections import Counter
from PIL import Image
import numpy as np

SRC, DST, SZER = Path("FloodNet"), Path("floodnet512"), 512
# Kolejność klas wg README FloodNet (etykiety 0–9); sprawdzić na kilku maskach.
KLASY = ["tło", "budynek zalany", "budynek niezalany", "droga zalana", "droga niezalana",
         "woda", "drzewo", "pojazd", "basen", "trawa"]

piksele = Counter()
for p in SRC.rglob("*"):
    ext = p.suffix.lower()
    if ext not in (".jpg", ".png"):
        continue
    maska = ext == ".png"
    out = DST / p.relative_to(SRC)
    out.parent.mkdir(parents=True, exist_ok=True)
    im = Image.open(p)
    # maski: NEAREST, żeby nie powstały nieistniejące numery klas
    im = im.resize((SZER, SZER * im.height // im.width), Image.NEAREST if maska else Image.BILINEAR)
    im.save(out)
    if maska:
        piksele.update(dict(enumerate(np.bincount(np.asarray(im).ravel(), minlength=len(KLASY)))))

suma = sum(piksele.values())
for k, n in sorted(piksele.items()):
    print(f"{k:2} {KLASY[k] if k < len(KLASY) else '???':18} {100 * n / suma:5.1f}%")
```

Kontrola sensu: „droga zalana” powinna mieć kilka procent pikseli. Jeśli jest 0% albo pojawiają się klasy `???`, to maski mają inną kolejność albo format.

## 3. Zapis zmniejszonego zbioru, żeby nie przepadł po restarcie Colaba

```python
from google.colab import drive
drive.mount("/content/drive")
!cd /content && zip -qr floodnet512.zip floodnet512 && cp floodnet512.zip /content/drive/MyDrive/
```

## Dalej (decyzje roli A)

- Model segmentacji douczony na `floodnet512`, na podziale trening, walidacja i test z FloodNet. Licencję kodu i wag modelu sprawdzić przed użyciem (Ultralytics = AGPL, patrz [kontekst.md §7](../../kontekst.md)).
- **Metryka decyzji:** dla każdego zdjęcia ze zbioru testowego „czy jest zalana droga: tak/nie” (np. ≥ 1% pikseli klasy 3 w masce), potem precyzja i czułość. **Pominięte zalane drogi** (fałszywie „przejezdne”) podać osobno. Do tego IoU dla klas 3 i 4.
- Wynik do `wyniki/metryki.json` w repo zgłoszeniowym + 5–10 obrazów z predykcjami, w tym błędne.
- Cytowanie FloodNet (wymagane): Rahnemoonfar i in., „FloodNet: A High Resolution Aerial Imagery Dataset for Post Flood Scene Understanding”, IEEE Access 9, 2021, doi:10.1109/ACCESS.2021.3090981.
