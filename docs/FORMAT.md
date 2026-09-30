# Wspólny format danych

To umowa między modułami: planer (B), model AI (A), portal i panel (C), skrypt demo (D). **Zmiany w tym pliku uzgadniamy razem**, bo inaczej integracja o 20:00 się rozsypie.

Wersja 2 (29.09, 15:20). Zmiany względem wersji 1:
- meldunek podzielony na fakty, zgłoszenia, ocenę, rekomendację i termin decyzji,
- „można latać” i zatwierdzenie w obiekcie `lot`,
- weryfikacja zgłoszeń,
- potwierdzenie wykonania w dzienniku decyzji,
- `mieszkancy_rejestr` zamiast `mieszkancy`,
- `zweryfikowany` przy odcinku.

## Zasady

- **Wymiana przez pliki JSON w katalogu `stan/`:** `wsie.json`, `odcinki.json`, `loty.json`, `zgloszenia.json`, `meldunki.json`, `decyzje.json`. Każdy plik to lista obiektów. Skrypt demo i moduły zapisują do nich, a panel je czyta. Bez bazy danych i bez kolejek.
- **Współrzędne:** `[lat, lon]` (jak w Leaflet). **Uwaga:** GeoJSON używa `[lon, lat]`, więc przy eksporcie do GeoJSON trzeba je zamienić.
- **Czas:** ISO 8601 ze strefą czasową, np. `"2026-09-30T08:15:00+02:00"`.
- **Identyfikatory:** tekstowe z przedrostkiem: `wies-`, `odc-`, `lot-`, `zgl-`, `mel-`, `dec-`.
- **Każdy obiekt ma pole `"symulowane": true/false`.** Panel na jego podstawie oznacza, co jest prawdziwe, a co symulowane. To nasza uczciwość wobec jury zapisana w danych.
- Pewność jest w skali od 0 do 1 tylko wtedy, gdy została zmierzona i skalibrowana; w demo ma wartość `null` (nieoszacowana). Stany i statusy to wyłącznie wartości z list poniżej.
- **„Nie wiadomo” to osobny stan, nigdy domyślnie „bezpiecznie”.** Brak obserwacji oznacza `"nieznany"`.

## wies

```json
{
  "id": "wies-wetlina",
  "nazwa": "Wetlina",
  "polozenie": [49.1466, 22.4853],
  "mieszkancy_rejestr": 307,
  "mieszkancy_zrodlo": "OSM",
  "status": "odcieta",
  "status_pewnosc": null,
  "status_czas": "2026-09-30T08:15:00+02:00",
  "dojazd": {"osobowy": false, "ciezarowy": false, "terenowy": true},
  "ladowisko": {"polozenie": [49.1471, 22.4802], "wymiary_m": [40, 60], "czas_obserwacji": null},
  "symulowane": true
}
```

- `status`: `"dostepna"` | `"czesciowo"` (dojazd tylko dla części pojazdów) | `"odcieta"` | `"nieznany"`.
- `mieszkancy_rejestr` to **liczba z rejestru**, a nie liczba osób faktycznie we wsi. W meldunku nigdy nie podajemy jej jako „tylu ludzi czeka”.
- `ladowisko` może być `null`. Bez `czas_obserwacji` lądowisko to tylko kandydat i nie trafia do rekomendacji.
- Wiek informacji panel liczy z `status_czas`.

## odcinek

```json
{
  "id": "odc-0042",
  "droga": "DW 897",
  "geometria": [[49.1502, 22.4700], [49.1498, 22.4755]],
  "dlugosc_m": 850,
  "most": true,
  "przy_potoku": true,
  "lesny": false,
  "krytyczny_dla": ["wies-wetlina", "wies-smerek"],
  "stan": "zerwany",
  "przejezdny_dla": [],
  "zweryfikowany": true,
  "pewnosc": null,
  "czas_obserwacji": "2026-09-30T08:10:00+02:00",
  "zrodlo": {"typ": "dron", "lot": "lot-003", "obraz": "obrazy/lot-003/0042.jpg"},
  "symulowane": true
}
```

- `stan`: `"przejezdny"` | `"zalany"` | `"zablokowany"` | `"zerwany"` | `"nieznany"`.
- `przejezdny_dla`: podzbiór listy `["osobowy", "ciezarowy", "terenowy"]`.
- `zweryfikowany`: `true` tylko po obserwacji. **Droga leśna (`lesny: true`) jest objazdem dopiero, gdy `zweryfikowany: true`**, bo OSM pokazuje możliwość, a nie przejezdność.
- `krytyczny_dla`: wsie, które odcina samo przerwanie tego odcinka. Liczy to planer.
- `czas_obserwacji` i `zrodlo` są `null`, dopóki nikt odcinka nie sprawdził.

## lot

```json
{
  "id": "lot-003",
  "dron": "dok-cisna-1",
  "typ": "zwiad_drog",
  "status": "zatwierdzony",
  "alarm": {"zrodlo": "IMGW hydro 149220110 (Kalnica, Wetlina)", "stan_cm": 431, "prog_alarmowy_cm": 420, "zweryfikowany": false},
  "mozna_latac": {"poziom": "zielone", "wiatr_ms": 5, "porywy_ms": 8, "opad": null, "przestrzen": "niezweryfikowana", "powod": "ocena pogody w scenariuszu; opad i przestrzeń niezweryfikowane", "czas": "2026-09-30T07:55:00+02:00"},
  "zatwierdzil": {"kto": "operator (demo)", "czas": "2026-09-30T07:58:00+02:00"},
  "plan_odcinki": ["odc-0042", "odc-0043"],
  "plan_zawis": [],
  "czas_planowany_min": 17,
  "czas_uzyteczny_min": 18,
  "powod": "stan alarmowy na wodowskazie Kalnica; odcinki krytyczne dla 3 wsi",
  "symulowane": true
}
```

- `typ`: `"zwiad_drog"` | `"zawis_portal"`. **Zwiad dróg i zawis z portalem nad wsią to osobne loty**, bo zawis zjada większość baterii.
- `status`: `"propozycja"` → `"zatwierdzony"` (decyduje człowiek) → `"w_locie"` → `"zakonczony"`, albo `"odrzucony"` / `"przerwany"`.
- `mozna_latac.poziom`:
  - `"zielone"`: średni wiatr ≤ 7 m/s, porywy ≤ 10 m/s, brak burzy,
  - `"zolte"`: 7–9 m/s albo porywy 10–12 m/s; lot tylko po analizie,
  - `"czerwone"`: powyżej tych progów, burza, marznący opad albo warunki poza instrukcją drona.
  - Lot `"czerwone"` nie może mieć statusu `"zatwierdzony"`.
- `mozna_latac.przestrzen`: `"niezweryfikowana"` w demo; docelowo `"ok"` | `"strefa_R"` | `"konflikt"` po rzeczywistej weryfikacji.
- `czas_uzyteczny_min`: czas na przelot i zawis po odjęciu rezerwy (18 z 25 min). `czas_planowany_min` nie może go przekroczyć.
- **Portal w locie `zawis_portal` zamyka przyjmowanie zgłoszeń, gdy dron osiąga próg bezpiecznego powrotu.**

## zgloszenie (z portalu Wi-Fi albo ze znaku na ziemi)

```json
{
  "id": "zgl-7f3a",
  "wies": "wies-wetlina",
  "czas": "2026-09-30T08:31:00+02:00",
  "kanal": "wifi",
  "liczba_osob": 4,
  "pilne_medyczne": ["insulina"],
  "potrzeby": ["woda", "leki"],
  "osoby_szczegolnie_narazone": ["senior"],
  "uwagi": "Babcia leżąca, parter zalany",
  "telefon": null,
  "weryfikacja": "niezweryfikowane",
  "przekazane_do_sztabu": "2026-09-30T08:52:00+02:00",
  "symulowane": false
}
```

- `kanal`: `"wifi"` | `"znak_ziemia"`.
- `pilne_medyczne`: podzbiór listy `["insulina", "dializa", "tlen", "osoba_lezaca", "uraz", "porod", "inne"]`.
- `potrzeby`: podzbiór listy `["woda", "zywnosc", "leki", "prad_sprzet_medyczny", "ogrzewanie", "higiena", "ewakuacja"]`.
- `osoby_szczegolnie_narazone`: podzbiór listy `["dziecko", "senior", "niepelnosprawnosc"]`.
- `weryfikacja`: `"niezweryfikowane"` | `"potwierdzone_obrazem"` | `"potwierdzone_kontaktem"` | `"duplikat"` | `"odrzucone"`.
- **Ochrona danych (RODO):**
  - **nie ma pola na imię i nazwisko**,
  - `uwagi` mają maks. 200 znaków, a formularz prosi, żeby nie wpisywać nazwisk,
  - `telefon` jest opcjonalny,
  - zgłoszenia usuwamy po zakończeniu akcji.
- `przekazane_do_sztabu` to moment, w którym dron wrócił do zasięgu i przekazał zgłoszenia (przechowaj i przekaż dalej).

## meldunek (generuje go szablon, bez LLM)

Pięć części: **fakty → zgłoszenia → ocena systemu → rekomendacja → termin decyzji**. Samą decyzję zapisuje obiekt `decyzja`.

```json
{
  "id": "mel-0012",
  "czas": "2026-09-30T14:35:00+02:00",
  "wies": "wies-wetlina",
  "poziom": "pilne",
  "priorytet": 1,
  "fakty": {
    "odcinki": [{"id": "odc-0042", "droga": "DW 897", "stan": "zerwany", "czas_obserwacji": "2026-09-30T14:23:00+02:00", "obraz": "obrazy/lot-003/0042.jpg"}]
  },
  "zgloszenia": {
    "liczba": 2,
    "pilne_medyczne": ["insulina"],
    "osoby_do_ewakuacji": null,
    "kanal": ["wifi"],
    "ostatnie": "2026-09-30T14:20:00+02:00",
    "zweryfikowane": 0
  },
  "ocena": {
    "status": "odcieta",
    "pewnosc": null,
    "objazdy": [{"odcinki": ["odc-0107"], "dla": ["terenowy"], "zweryfikowany": false}]
  },
  "rekomendacja": {
    "dzialanie": "Potwierdzić stan pacjentów i skierować zespół z lekami. Śmigłowca nie wskazywać, dopóki nie potwierdzono dostępności i lądowiska.",
    "srodek": "droga_terenowa",
    "uzasadnienie": [
      "zagrożenie życia: insulina (zgłoszenie niezweryfikowane)",
      "izolacja od ok. 6 h",
      "objazd leśny niezweryfikowany",
      "wiek informacji: 12 min"
    ]
  },
  "wymagana_decyzja_do": "2026-09-30T14:45:00+02:00",
  "tekst": "PILNE – Wetlina, 14:35\nStatus: odcięta; pewność wysoka.\nDW 897, odcinek X–Y: nieprzejezdny, obraz z drona sprzed 12 min.\nPotrzeby: 2 zgłoszenia medyczne, w tym insulina; liczba osób do ewakuacji: niepotwierdzona.\nAlternatywny dojazd: droga leśna, niezweryfikowana.\nRekomendacja: potwierdzić stan pacjentów i skierować zespół z lekami; śmigłowca nie wskazywać, dopóki nie potwierdzono dostępności i lądowiska.\nWymagana decyzja do 14:45.",
  "zrodla": ["odc-0042", "odc-0107", "zgl-7f3a", "zgl-8b21"],
  "symulowane": true
}
```

- `poziom`: `"pilne"` | `"wazne"` | `"informacyjne"`. Panel pokazuje go **tekstem i ikoną**, nie samym kolorem.
- `rekomendacja.srodek`: `"droga"` | `"droga_terenowa"` | `"lodz"` | `"smiglowiec"` | `"potwierdzic_najpierw"`.
- **Kolejność kryteriów w `uzasadnienie`** (wagi w konfiguracji):
  1. zagrożenie życia i maksymalny czas oczekiwania,
  2. liczba osób i osoby szczególnie narażone,
  3. czas izolacji,
  4. dostępność alternatywnego transportu,
  5. wiek i wiarygodność informacji.
- **Zakazy (pozorna dokładność):**
  - nie podawać `mieszkancy_rejestr` jako liczby osób we wsi,
  - nie proponować lądowiska bez `czas_obserwacji`,
  - nie proponować śmigłowca bez potwierdzonej dostępności.
- **Każda informacja w `tekst` musi pochodzić z obiektów wymienionych w `zrodla`.**

## decyzja (dziennik: tylko dopisujemy)

```json
{
  "id": "dec-0005",
  "typ": "decyzja",
  "dotyczy": "mel-0012",
  "czas": "2026-09-30T14:41:00+02:00",
  "kto": "starosta / upoważniony kierujący (demo)",
  "wynik": "zmieniona",
  "zmiana": "zespół z lekami łodzią zamiast drogą terenową",
  "uwagi": "",
  "symulowane": true
}
```

```json
{
  "id": "dec-0006",
  "typ": "potwierdzenie_wykonania",
  "dotyczy": "dec-0005",
  "czas": "2026-09-30T15:20:00+02:00",
  "kto": "dyżurny PCZK (demo)",
  "wynik": "dotarlo",
  "zmiana": null,
  "uwagi": "leki przekazane, 1 osoba do ewakuacji jutro",
  "symulowane": true
}
```

- `typ`: `"decyzja"` | `"potwierdzenie_wykonania"`.
- `dotyczy`: meldunek (`mel-`) albo lot (`lot-`) przy `"decyzja"`; decyzja (`dec-`) przy `"potwierdzenie_wykonania"`.
- `wynik`:
  - dla `"decyzja"`: `"zatwierdzona"` | `"odrzucona"` | `"zmieniona"`,
  - dla `"potwierdzenie_wykonania"`: `"zadysponowano"` | `"w_drodze"` | `"dotarlo"` | `"niewykonane"`.
- **Role:** użytkownikiem systemu jest dyżurny PCZK i sztab powiatowy, a decyzję zatwierdza starosta albo upoważniony kierujący działaniami. Start drona (`dotyczy: lot-…`) zatwierdza operator.
- Pętla domyka się dopiero po potwierdzeniu wykonania. Panel pokazuje decyzje bez potwierdzenia jako **„niepotwierdzone wykonanie”**.
