"""
Meldunek z szablonu (bez LLM): każda informacja pochodzi z obiektów wymienionych w polu "zrodla".
Struktura według docs/FORMAT.md v2: fakty → ocena → rekomendacja → termin decyzji (zgłoszenia mieszkańców
są poza zakresem AeroPass, więc "zgloszenia" = null).
"""
from datetime import datetime, timedelta

POZIOM_TEKST = {"pilne": "PILNE", "wazne": "WAŻNE", "informacyjne": "INFO"}
NIEPRZEJEZDNE = {"zalany", "zerwany", "zablokowany"}
OPIS_STANU = {"zalany": "zalany", "zerwany": "zerwany most", "zablokowany": "zablokowany (np. powalone drzewo)"}


def _min_temu(teraz, czas_iso):
    if not czas_iso:
        return None
    return max(0, round((teraz - datetime.fromisoformat(czas_iso)).total_seconds() / 60))


def temu(m):
    return "przed chwilą" if not m else f"{m} min temu"


def opis_trasy(odcinki_trasy, po_id):
    drogi = list(dict.fromkeys(po_id[o]["droga"] for o in odcinki_trasy))  # kolejność przejazdu, bez powtórzeń
    km = sum(po_id[o]["dlugosc_m"] for o in odcinki_trasy) / 1000
    nazwy = [d for d in drogi if d.startswith("DW") or d[0].isupper()]
    return (" → ".join(nazwy[:4]) or "drogi lokalne"), round(km, 1)


def zbuduj(wies, status, trasy, przyczyny, po_id, teraz, nr):
    """status: {"ciezarowy": ..., "terenowy": ...}; trasy: {klasa: [id odcinków] | None};
    przyczyny: id odcinków nieprzejezdnych na normalnym dojeździe do wsi."""
    ciez, ter = status["ciezarowy"], status["terenowy"]
    fakty = [{"id": o, "droga": po_id[o]["droga"], "stan": po_id[o]["stan"],
              "czas_obserwacji": po_id[o]["czas_obserwacji"], "obraz": (po_id[o].get("zrodlo") or {}).get("obraz")}
             for o in przyczyny]
    zrodla = list(przyczyny)
    uzasadnienie = []
    wiek = [_min_temu(teraz, f["czas_obserwacji"]) for f in fakty if f["czas_obserwacji"]]

    if ciez == "dostepna":
        poziom, srodek = "informacyjne", "droga"
        opis, km = opis_trasy(trasy["ciezarowy"], po_id)
        wiek_trasy = [_min_temu(teraz, po_id[o]["czas_obserwacji"]) for o in trasy["ciezarowy"] if po_id[o]["czas_obserwacji"]]
        dzialanie = f"Dojazd wozem ciężkim: {opis}, ok. {km} km."
        if wiek_trasy:
            dzialanie += f" Najstarsza obserwacja na trasie: {temu(max(wiek_trasy))}."
        zrodla += trasy["ciezarowy"]
        uzasadnienie.append("trasa po odcinkach przyjętych jako przejezdne w scenariuszu")
    elif ter == "dostepna":
        poziom, srodek = "wazne", "droga_terenowa"
        opis, km = opis_trasy(trasy["terenowy"], po_id)
        lesne = [o for o in trasy["terenowy"] if po_id[o]["lesny"]]
        zrodla += trasy["terenowy"]
        dzialanie = (f"Wóz ciężki nie dojedzie. Dojazd tylko pojazdem terenowym: {opis}, ok. {km} km"
                     + (f", w tym droga leśna sprawdzona {temu(min(_min_temu(teraz, po_id[o]['czas_obserwacji']) or 0 for o in lesne))}." if lesne else "."))
        uzasadnienie += ["brak dojazdu drogą utwardzoną", "objazd leśny zweryfikowany z drona"]
    else:
        poziom, srodek = "pilne", "potwierdzic_najpierw"
        objazd = "brak objazdu dla pojazdów terenowych" if ter == "odcieta" else "objazd leśny niezweryfikowany"
        dzialanie = ("Brak dojazdu drogą dla wozów PSP i OSP. Do decyzji: inny środek (łódź, śmigłowiec, dojście pieszo) "
                     f"po potwierdzeniu dostępności sił; lądowisko niepotwierdzone; {objazd}.")
        uzasadnienie += ["brak dojazdu drogą utwardzoną", objazd]
    trasa = trasy["ciezarowy"] if ciez == "dostepna" else (trasy["terenowy"] if ter == "dostepna" else [])
    bez_obserwacji = sum(not po_id[o]["czas_obserwacji"] for o in trasa)
    if bez_obserwacji:
        dzialanie += f" Odcinki przyjęte jako przejezdne bez obserwacji: {bez_obserwacji} (założenie symulacji)."
        uzasadnienie.append(f"odcinki trasy bez obserwacji: {bez_obserwacji}")
    if wiek:
        uzasadnienie.append(f"wiek informacji: {min(wiek)}–{max(wiek)} min")

    if wies.get("mieszkancy_rejestr"):
        uzasadnienie.append(f"mieszkańców w rejestrze: {wies['mieszkancy_rejestr']} (nie liczba osób obecnych)")
    termin = {"pilne": 10, "wazne": 20}.get(poziom)
    przyczyny_txt = "; ".join(f"{f['droga']}: {OPIS_STANU.get(f['stan'], f['stan'])}" for f in fakty[:3]) or "—"
    ocena_txt = {"dostepna": "dostępna", "odcieta": "odcięta", "nieznany": "nieustalony"}
    tekst = (f"{POZIOM_TEKST[poziom]} – {wies['nazwa']}, {teraz:%H:%M}\n"
             f"Status dla wozu ciężkiego: {ocena_txt[ciez]}; dla terenowego: {ocena_txt[ter]}.\n"
             f"Nieprzejezdne na zwykłym dojeździe: {przyczyny_txt}"
             + (f" (obraz z drona: {temu(min(wiek))})" if wiek else "") + ".\n"
             f"Rekomendacja: {dzialanie}"
             + (f"\nWymagana decyzja do {teraz + timedelta(minutes=termin):%H:%M}." if termin else ""))
    return {
        "id": f"mel-{nr:04d}",
        "czas": teraz.isoformat(timespec="seconds"),
        "wies": wies["id"],
        "poziom": poziom,
        "priorytet": {"pilne": 1, "wazne": 2, "informacyjne": 3}[poziom],
        "fakty": {"odcinki": fakty},
        "zgloszenia": None,
        "ocena": {"status": ciez, "status_terenowy": ter, "pewnosc": None},
        "rekomendacja": {"dzialanie": dzialanie, "srodek": srodek, "uzasadnienie": uzasadnienie},
        "wymagana_decyzja_do": (teraz + timedelta(minutes=termin)).isoformat(timespec="seconds") if termin else None,
        "tekst": tekst,
        "zrodla": sorted(set(zrodla)),
        "symulowane": True,
    }


if __name__ == "__main__":
    po_id = {"a": {"droga": "DW 897", "stan": "zerwany", "czas_obserwacji": "2026-09-30T08:00:00+02:00", "dlugosc_m": 500, "lesny": False},
             "l": {"droga": "track", "stan": "przejezdny", "czas_obserwacji": "2026-09-30T08:05:00+02:00", "dlugosc_m": 2000, "lesny": True}}
    teraz = datetime.fromisoformat("2026-09-30T08:10:00+02:00")
    w = {"id": "wies-x", "nazwa": "Wetlina", "mieszkancy_rejestr": 307}
    m = zbuduj(w, {"ciezarowy": "odcieta", "terenowy": "dostepna"}, {"ciezarowy": None, "terenowy": ["l"]}, ["a"], po_id, teraz, 1)
    assert m["poziom"] == "wazne" and "5 min temu" in m["rekomendacja"]["dzialanie"] and set(m["zrodla"]) == {"a", "l"}
    m = zbuduj(w, {"ciezarowy": "odcieta", "terenowy": "nieznany"}, {"ciezarowy": None, "terenowy": None}, ["a"], po_id, teraz, 2)
    assert m["poziom"] == "pilne" and "niezweryfikowany" in m["tekst"] and "08:20" in m["tekst"]
    assert "śmigłowiec" in m["rekomendacja"]["dzialanie"] and "po potwierdzeniu" in m["rekomendacja"]["dzialanie"]
    po_id["u"] = {"droga": "DW 897", "stan": "przejezdny", "czas_obserwacji": None, "dlugosc_m": 500, "lesny": False}
    m = zbuduj(w, {"ciezarowy": "dostepna", "terenowy": "dostepna"},
               {"ciezarowy": ["u"], "terenowy": ["u"]}, [], po_id, teraz, 3)
    assert "bez obserwacji" in m["rekomendacja"]["dzialanie"]
    assert "przed chwilą" not in m["rekomendacja"]["dzialanie"]
    assert m["ocena"]["pewnosc"] is None
    print(m["tekst"])
    print("OK: meldunki z szablonu")
