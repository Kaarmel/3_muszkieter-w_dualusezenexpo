# Materiały do projektu 1 (odcięte miejscowości)

Spis wszystkiego, co zebraliśmy: źródło, licencja, do czego służy, kto używa. **Rola D przepisuje to potem do sekcji „Użycie AI i zasobów zewnętrznych” w README repo zgłoszeniowego (wymóg reg. IX).**

Role: **A** = AI (FloodNet), **B** = mapa i logika, **C** = portal i panel, **D** = prezentacja i README. Szczegóły w [../projekt.md](../projekt.md#podział-ról-i-czas-wewnętrzny-deadline-1100).

## Co już jest w tym folderze

| Plik | Co zawiera | Źródło i licencja | Do czego | Rola |
|---|---|---|---|---|
| [imgw/hydro_podkarpackie.json](imgw/hydro_podkarpackie.json) | 50 wodowskazów z woj. podkarpackiego: stan wody, **stan ostrzegawczy i alarmowy**, przepływ; pobrane 29.09 o 13:45 | API IMGW-PIB ([opis API](https://danepubliczne.imgw.pl/apiinfo)); wymagane podanie źródła *(dokładne warunki do weryfikacji)* | Krok 1 przepływu: wyzwalacz misji (stan ≥ alarmowy); dane testowe | B |
| [imgw/synop_podkarpackie.json](imgw/synop_podkarpackie.json) | Rzeszów, Krosno, **Lesko** (najbliżej doliny), Przemyśl: wiatr, opad, temperatura | jw. | Decyzja „można latać” (limit wiatru drona *do weryfikacji*) | B |
| [osm/dolina_solinki.json](osm/dolina_solinki.json) | **Kandydat na dolinę demo** (zespół decyduje). Obszar 49,12–49,32°N, 22,28–22,52°E: drogi (w tym **DW 897**, DW 893, DW 894), **96 mostów**, drogi leśne, potoki, 32 miejscowości | OpenStreetMap przez Overpass API; licencja **ODbL**, atrybucja „© OpenStreetMap contributors” | Graf przejezdności, mapa w panelu | B, C |
| [biblioteki/leaflet-1.9.4/](biblioteki/leaflet-1.9.4/) | Leaflet (JS, CSS, ikony) do użycia **bez internetu** | BSD-2-Clause ([LICENSE](biblioteki/leaflet-1.9.4/LICENSE)) | Mapa w panelu sztabu i w portalu | C |
| [prototypy/krytyczne_odcinki.py](prototypy/krytyczne_odcinki.py) | **Prototyp dla roli B**: odcinki dróg, których przerwanie odcina wieś, i przybliżona trasa lotu ([wynik](prototypy/wynik_bez_drog_lesnych.txt)): 15 z 31 wsi odcina jedno przerwanie. Liczy 31 miejscowości, bez pojedynczego zabudowania (stąd różnica z 32) | nasz kod; networkx (BSD) | Punkt wyjścia planera lotu i symulacji Monte Carlo | B |
| [floodnet_colab.md](floodnet_colab.md) | Instrukcja: FloodNet w Colabie (pobranie, zmniejszenie do 512 px, liczność klas) | FloodNet: **CDLA-Permissive 1.0**, wymagane cytowanie | Trening i metryka segmentacji | A |

### Dlaczego dolina Solinki i Wetlinki jako kandydat

- Karta projektu już używa DW 897 w przykładowym meldunku, więc demo będzie spójne.
- W dolinie są **trzy prawdziwe wodowskazy IMGW** ze stanami alarmowymi:

  | Wodowskaz | Rzeka | ID stacji | Stan ostrzegawczy | Stan alarmowy | Stan 29.09 |
  |---|---|---|---|---|---|
  | Cisna | Solinka | 149220080 | 190 cm | 240 cm | 73 cm |
  | Terka | Solinka | 149220100 | 200 cm | 260 cm | 72 cm |
  | Kalnica | Wetlina | 149220110 | 370 cm | 420 cm | 258 cm |

  Wyzwalacz w demo używa więc prawdziwych progów, a symulowany jest tylko poziom wody.
- Wsie leżą wzdłuż jednej drogi przy potoku (Cisna, Wetlina, Smerek, Kalnica, Dołżyca, Przysłup, Terka i inne), a mostów jest dużo. To dokładnie scenariusz „zerwany most = odcięta wieś”.

**Braki w danych OSM** (dla roli B):
- Liczba mieszkańców jest tylko dla kilku wsi, np. Cisna 457, Wetlina 307, Terka 204. Reszta: GUS albo liczba punktów adresowych PRG *(do uzupełnienia)*.
- W grafie dróg bez dróg leśnych jest 15 osobnych kawałków. Część to pojedyncze drogi dojazdowe, które przy budowie grafu trzeba odfiltrować albo podpiąć.
- **Krawędź obszaru:** DW 897 biegnie dalej na wschód (za Wetlinę, w stronę Ustrzyk Górnych), a DW 893 na północny zachód (w stronę Baligrodu). Siedziba sztabu w Lesku też leży poza obszarem. Jeśli za bazę przyjmiemy punkt w środku doliny, algorytm uzna za odciętą wieś, do której da się dojechać drogą spoza obszaru, a jury z Podkarpacia to wyłapie. **Rozwiązanie:** każdą drogę przecinającą krawędź obszaru podłączyć do jednego wirtualnego węzła „świat zewnętrzny” i traktować go jako bazę. Druga możliwość: powiększyć obszar.

## Do pobrania, gdy dolina będzie wybrana (rola B)

| Co | Gdzie | Uwagi |
|---|---|---|
| Mapy zagrożenia powodziowego (obszary zalewowe, np. Q1%) | ISOK / Wody Polskie: [isok.gov.pl](https://isok.gov.pl/) | Podstawa „które drogi zaleje”. **Sprawdzić, czy mapy obejmują Solinkę i Wetlinę**, oraz format i licencję. Rezerwa: NMT |
| Numeryczny Model Terenu (NMT, 1 m) | GUGiK: [geoportal.gov.pl](https://www.geoportal.gov.pl/) (pobieranie danych) | Pobrać **tylko pas wzdłuż potoku**, bo cała dolina w 1 m to duży plik. Zastosowania: zalanie „rezerwowe”, lądowiska |
| Punkty adresowe (PRG) | GUGiK: geoportal.gov.pl / dane.gov.pl | Liczba budynków we wsi jako przybliżenie liczby mieszkańców |
| Format planu misji QGroundControl (`.plan`) | [dokumentacja QGC](https://docs.qgroundcontrol.com/master/en/qgc-dev-guide/file_formats/plan.html) | Eksport planu lotu (pozycja „powinno być”) |
| osmnx | [osmnx.readthedocs.io](https://osmnx.readthedocs.io/) | Może sam pobrać drogi z OSM. Nasz plik JSON to kopia offline |

**Podkład mapy offline:** kafelków z tile.openstreetmap.org nie wolno pobierać hurtowo ([zasady](https://operations.osmfoundation.org/policies/tiles/)). W panelu rysujemy drogi, potoki i wsie z `osm/dolina_solinki.json` jako wektory. To działa bez internetu i zgodnie z licencją.

## Tylko jeśli będzie potrzebne

- **Raspberry Pi jako „ładunek drona” z portalem:** [nodogsplash](https://github.com/nodogsplash/nodogsplash) (portal, który otwiera się sam po połączeniu z siecią). Klonować dopiero wtedy, gdy Raspberry Pi jest pod ręką: `git clone --depth 1 … repo/nodogsplash` (folder `repo/` jest ignorowany przez git).
- **Znaki ziemia–powietrze ICAO (V, X):** źródło do znalezienia (ICAO Annex 12 *do weryfikacji*). Tylko na slajd „co dalej”.

## Środowisko Python (sprawdzone 29.09)

Na tym Macu jest Python 3.14.7. Sprawdzony w venv:
- **instalują się i działają:** osmnx 2.1.1, networkx, geopandas, shapely, pyproj, fastapi, uvicorn, pillow, opencv-python-headless;
- **PyTorch i torchvision** mają gotowe paczki dla 3.14 na Maca z Apple Silicon (niezainstalowane).

Nie trzeba instalować starszego Pythona.

```bash
# venv POZA Google Drive (tysiące plików nie mogą się synchronizować z chmurą)
python3 -m venv ~/.venvs/dualuse && source ~/.venvs/dualuse/bin/activate
pip install osmnx fastapi uvicorn pillow opencv-python-headless
```

## Zasady porządku

- **Duże dane (zbiory, NMT, obrazy) trzymamy poza Google Drive,** w `~/dualuse_dane/`. Folder projektu jest synchronizowany z chmurą, a na dysku Maca zostało ok. 33 GB.
- Foldery `dane/` i `repo/` w tym katalogu są w `.gitignore`.
- Każdy nowy materiał dopisujemy do tabeli wyżej: źródło, licencja, rola. Bez tego nie powstanie sekcja o zasobach zewnętrznych (reg. IX).
- **Nie latamy dronem na miejscu:** strefa lotniska Rzeszów-Jasionka.
