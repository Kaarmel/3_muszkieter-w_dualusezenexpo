"""
AeroPass — demo całego przepływu jedną komendą:
alarm IMGW → „można latać” → propozycja lotu → zgoda operatora (w panelu) → autonomiczny zwiad
(najpierw odcinki rozstrzygające) → status wsi dla wozu ciężkiego i terenowego → meldunki →
sprawdzenie objazdów leśnych dla odciętych wsi → decyzje w panelu.

Prawdziwe: sieć dróg i wsie (OSM), progi alarmowe wodowskazów i wiatr (IMGW), logika planera i meldunków.
Symulowane: poziom wody ponad progiem, porywy wiatru, przelot drona, stan odcinków (stan/prawda.json),
obrazy z drona (zastępcze zdjęcia z FloodNet, jeśli są wyniki modelu).

Uruchomienie z katalogu repo:
    python panel/serwer.py            # w osobnym terminalu, panel: http://localhost:8765/panel/
    python symulator/demo.py [--tempo 3] [--auto] [--ziarno 56] [--strategia B]
--tempo: ile minut symulacji na sekundę; --auto: start drona zatwierdzany automatycznie po 3 s;
--ziarno: losowanie powodzi; --strategia: B = najpierw odcinki rozstrzygające, A = przegląd wszystkich dróg przy ciekach;
--reczne: JSON {id_odcinka: stan} nadpisujący wylosowaną prawdę; --przygotuj: tylko zapisz stan początkowy.
Panel uruchamia to samo przyciskami (panel/serwer.py); pauza i tempo są w stan/sterowanie.json.
"""
import argparse
import itertools
import json
import math
import random
import sys
import time
from datetime import datetime, timedelta
from pathlib import Path

KATALOG = Path(__file__).resolve().parent.parent
sys.path[:0] = [str(KATALOG / "planer"), str(KATALOG)]
import meldunek  # noqa: E402
from komunikacja import lacze  # noqa: E402
from komunikacja.klient import Klient, wyslij_lora  # noqa: E402
from komunikacja.lora import ramka  # noqa: E402
import monte_carlo as mc  # noqa: E402
import scenariusz as sc  # noqa: E402
import siec  # noqa: E402

START = datetime.fromisoformat("2026-09-30T06:00:00+02:00")
ZIARNO = 56  # scenariusz demo: 6 wsi odciętych dla wozu ciężkiego (w tym Wetlina), 2 z objazdem leśnym
DRONY = 4    # po jednym na stację dokującą
STAN = Path("stan")
STRATEGIE = {"B": "najpierw odcinki rozstrzygające", "A": "przegląd wszystkich dróg przy ciekach"}
NIEPRZEJEZDNE = meldunek.NIEPRZEJEZDNE


def zapisz(nazwa, obj):
    tmp = STAN / (nazwa + ".tmp")
    tmp.write_text(json.dumps(obj, ensure_ascii=False), encoding="utf-8")
    tmp.replace(STAN / nazwa)  # zapis atomowy: panel nigdy nie czyta połowy pliku


def alarm():
    hydro = {h["stacja"]: h for h in json.load(open("dane/imgw/hydro_podkarpackie.json", encoding="utf-8"))}
    k = hydro["Kalnica"]
    prog = int(k["stan_alarmowy"])
    return {"zrodlo": f"IMGW hydro {k['id_stacji']} ({k['stacja']}, rzeka {k['rzeka']})",
            "stan_cm": prog + 11, "prog_alarmowy_cm": prog, "prog_ostrzegawczy_cm": int(k["stan_ostrzegawczy"]),
            "stan_rzeczywisty_cm": int(k["stan_wody"]), "pomiar_rzeczywisty": k["stan_wody_data_pomiaru"],
            "zweryfikowany": False, "uwaga": "progi prawdziwe (IMGW), poziom wody symulowany; alarm nie jest prawdziwy"}


def mozna_latac(czas):
    syn = {s["stacja"]: s for s in json.load(open("dane/imgw/synop_podkarpackie.json", encoding="utf-8"))}
    w = float(syn["Lesko"]["predkosc_wiatru"])
    porywy = w + 3  # IMGW synop nie podaje porywów: wartość symulowana (docelowo czujnik na stacji)
    poziom = "zielone" if w <= 7 and porywy <= 10 else ("zolte" if w <= 9 and porywy <= 12 else "czerwone")
    return {"poziom": poziom, "wiatr_ms": w, "porywy_ms": porywy, "opad": None, "przestrzen": "niezweryfikowana",
            "powod": f"wiatr {w:g} m/s (IMGW Lesko, pomiar {syn['Lesko']['data_pomiaru']} godz. {syn['Lesko']['godzina_pomiaru']}:00), porywy {porywy:g} m/s (symulowane); opad i przestrzeń niezweryfikowane",
            "czas": czas.isoformat(timespec="seconds")}


class Demo:
    def __init__(self, tempo, auto, ziarno=ZIARNO, strategia="B", reczne=None):
        self.tempo, self.auto, self.ziarno, self.strategia = tempo, auto, ziarno, strategia
        self.przebieg, self.alarm = f"{ziarno}-{strategia}-{time.time():.0f}", None
        STAN.mkdir(exist_ok=True)
        zapisz("sterowanie.json", {"pauza": False, "tempo": tempo})
        sc.zapisz(ziarno, STAN / "prawda.json")  # statyczne stan/odcinki.json i stan/wsie.json
        self.sw = mc.Swiat()
        self.prawda = sc.losuj_prawde(self.sw.odc, random.Random(ziarno))
        # ręczne zmiany z panelu (klik na odcinku); system ich nie zna, dopóki dron nie sprawdzi
        reczne = {k: v for k, v in (reczne or {}).items() if k in self.prawda and v in NIEPRZEJEZDNE | {"przejezdny"}}
        self.prawda.update(reczne)
        self.statyczne = {o["id"]: o for o in json.load(open(STAN / "odcinki.json", encoding="utf-8"))}
        # droga z dala od cieków: system zakłada przejezdność, więc przeszkoda tam to zgłoszenie (np. 112),
        # które dopisuje odcinek do zwiadu; stacje zostają tam, gdzie były
        self.zgloszone = [k for k in reczne if not self.sw.po_id[k]["lesny"] and not sc.zagrozony(self.sw.po_id[k])]
        for k in self.zgloszone:
            self.sw.po_id[k]["przy_potoku"] = True  # tylko w pamięci tego przebiegu: „nie zakładaj, sprawdź”
            self.sw.zagrozone.append(k)
            self.sw.sektor[k] = min(range(len(self.sw.doki)), key=lambda i: siec.hav(self.sw._srodek(k), self.sw.doki[i]))
            self.statyczne[k].update(stan="nieznany", przejezdny_dla=[], zrodlo=None, zgloszenie=True)
        if self.zgloszone:
            zapisz("odcinki.json", list(self.statyczne.values()))
        self.wsie = {w["id"]: w for w in json.load(open(STAN / "wsie.json", encoding="utf-8"))}
        self.stany = sc.stan_poczatkowy(self.sw.odc)  # wiedza systemu (wszystkie klasy, także leśne)
        self.dyn, self.meldunki, self.zdarzenia = {}, {}, []
        self.drony = [list(p) for _, p in self.sw.stacje][:DRONY]
        self.kursy, self.lacza, self.bufory = [0.0] * DRONY, ["rf"] * DRONY, [[] for _ in range(DRONY)]
        # komunikacja z API: symulowane drony wysyłają telemetrię i obserwacje tak jak prawdziwe (RF/LoRa/zapis)
        self.api = Klient(timeout=0.5)
        start_api = self.api.obserwacje(0)
        self.api_ok, self.obs_od, self.obs_t = start_api is not None, (start_api or {}).get("nastepny", 0), 0.0
        self.status = {w: {"ciezarowy": "nieznany", "terenowy": "nieznany"} for w in self.wsie}
        st0 = siec.status_wsi(self.sw.G, self.sw.wz, self.stany, "ciezarowy")
        self.nieznane0, self.progi = [w for w, s in st0.items() if s == "nieznany"], {}  # do porównania strategii
        self.nr_mel, self.t0, self.ostatni_t = itertools.count(1), 0.0, 0.0
        wszystkie_przejezdne = {o["id"]: "przejezdny" for o in self.sw.odc if not o["lesny"]}
        self.normalnie = {w: siec.trasa(self.sw.G, self.sw.wz[w], wszystkie_przejezdne) or [] for w in self.wsie}
        obrazy = self._obrazy()
        self.obrazy = {k: itertools.cycle(v) if v else None for k, v in obrazy.items()}
        for f in ("meldunki.json", "zmiany.json", "loty.json", "zdarzenia.json"):
            zapisz(f, [] if f != "zmiany.json" else {})
        zapisz("decyzje.json", [])
        self.lot = {"id": "lot-001", "dron": "dok-" + siec._slug(self.sw.stacje[0][0]), "typ": "zwiad_drog",
                    "status": "propozycja", "symulowane": True}

    def _obrazy(self):
        p = Path("wyniki/predykcje_demo.json")
        if not p.exists():
            return {"zalany": [], "przejezdny": []}
        d = json.load(open(p, encoding="utf-8"))
        # tylko zdjęcia, na których model trafił (zastępcze ilustracje stanu symulowanego; metryka błędów jest osobno)
        return {"zalany": [x for x in d if x["prawda"] == "zalany" and x["stan"] == "zalany"],
                "przejezdny": [x for x in d if x["prawda"] == "przejezdny" and x["stan"] == "przejezdny"]}

    def zegar(self, t_min):
        return START + timedelta(minutes=self.t0 + t_min)

    def zdarzenie(self, t_min, typ, tekst):
        self.zdarzenia.append({"czas": self.zegar(t_min).isoformat(timespec="seconds"), "typ": typ, "tekst": tekst})
        zapisz("zdarzenia.json", self.zdarzenia[-60:])
        print(f"[{self.zegar(t_min):%H:%M}] {tekst}")

    def misja(self, t_min, etap, poz=None, dron=0):
        if poz:
            a, b = self.drony[dron], list(poz)
            if a != b:  # kurs w stopniach od północy, do strzałki drona w panelu
                self.kursy[dron] = round(math.degrees(math.atan2((b[1] - a[1]) * math.cos(math.radians(a[0])), b[0] - a[0])) % 360)
            self.drony[dron] = b
            self.nadaj(dron, t_min)
        ust = sum(s["ciezarowy"] != "nieznany" for s in self.status.values())
        znane = sum(self.status[w]["ciezarowy"] != "nieznany" for w in self.nieznane0) / max(len(self.nieznane0), 1)
        for p in (50, 90, 100):
            if znane * 100 >= p and etap == "zwiad":
                self.progi.setdefault(str(p), round(t_min))
        km = sum(self.statyczne[o]["dlugosc_m"] for o, d in self.dyn.items()) / 1000
        zapisz("misja.json", {"czas": self.zegar(t_min).isoformat(timespec="seconds"), "minuta_lotu": round(t_min, 1),
                              "etap": etap, "przebieg": self.przebieg, "ziarno": self.ziarno, "strategia": self.strategia, "drony": [{"polozenie": p, "stacja": self.sw.stacje[i][0], "kurs": self.kursy[i], "lacze": self.lacza[i]} for i, p in enumerate(self.drony)], "lot": self.lot["id"],
                              "stacje": [{"nazwa": n, "polozenie": list(p)} for n, p in self.sw.stacje],
                              "alarm": self.alarm, "mozna_latac": self.lot.get("mozna_latac"),
                              "postep": {"wsie_ustalone": ust, "wsie_razem": len(self.wsie), "km_sprawdzone": round(km, 1),
                                          "min_do_proc_nieznanych": self.progi, "nieznane_na_starcie": len(self.nieznane0)},
                              "symulowane": True})

    def nadaj(self, dron, t_min, odcinek=None, stan=None):
        """Wiadomość drona łączem wybranym jak w terenie: RF → HTTP do API, LoRa → ramka 20 B przez bramkę,
        brak łącza → bufor na pokładzie, wysłany po powrocie w zasięg RF."""
        if not self.api_ok:
            return
        poz = self.drony[dron]
        km = siec.hav(poz, self.sw.doki[dron % len(self.sw.doki)]) / 1000
        l, _ = lacze.wybierz(km, widocznosc=km <= 3, lte=False)  # założenia: widoczność stacji do 3 km, brak LTE w dolinie
        self.lacza[dron] = l
        czas = self.zegar(t_min)
        wiad = {"dron": dron + 1, "polozenie": poz, "czas": czas.isoformat(timespec="seconds"), "kurs": self.kursy[dron],
                "bateria_proc": None, "odcinek": odcinek, "stan": stan}
        if l == "zapisz":
            self.bufory[dron].append(wiad)
            return
        if l == "lora":
            wyslij_lora(ramka.koduj("obserwacja" if odcinek else "telemetria", dron + 1, czas.timestamp(), poz,
                                    odcinek, stan or "nieznany", 0))
            return
        for w in self.bufory[dron] + [wiad]:  # RF: najpierw zaległe z bufora
            opoznione = w is not wiad
            self.api.telemetria(w["dron"], w["polozenie"], czas=w["czas"], kurs=w["kurs"], lacze="zapisz" if opoznione else l)
            if w["odcinek"]:
                self.api.obserwacja(w["odcinek"], w["stan"], zrodlo="dron", dron=w["dron"], czas=w["czas"],
                                    lacze="zapisz" if opoznione else l, uwagi="symulacja")
        self.bufory[dron] = []

    def zewnetrzne(self):
        """Tylko obserwacje operatora z API mogą wpłynąć na planer; wynik modelu czeka na człowieka."""
        if not self.api_ok or time.time() - self.obs_t < 1:
            return {}
        self.obs_t = time.time()
        odp = self.api.obserwacje(self.obs_od) or {}
        self.obs_od = odp.get("nastepny", self.obs_od)
        nowe = {}
        for o in odp.get("obserwacje", []):
            if o["zrodlo"] != "operator" or o["odcinek"] not in self.statyczne:
                continue
            nowe[o["odcinek"]] = s = o["stan"]
            self.stany[o["odcinek"]] = s
            self.dyn[o["odcinek"]] = {"stan": s, "przejezdny_dla": ["osobowy", "ciezarowy", "terenowy"] if s == "przejezdny" else [],
                                      "zweryfikowany": o["zrodlo"] == "operator", "pewnosc": None,
                                      "czas_obserwacji": self.zegar(self.ostatni_t).isoformat(timespec="seconds"),
                                      "zrodlo": {"typ": o["zrodlo"], "obraz": o.get("obraz"), "uwaga": o.get("uwagi") or None},
                                      "symulowane": False}
            kto = "operator"
            self.zdarzenie(self.ostatni_t, "odcinek", f"{self.statyczne[o['odcinek']]['droga']} ({o['odcinek']}): {meldunek.OPIS_STANU.get(s, s)} — {kto} (przez API)")
        if nowe:
            zapisz("zmiany.json", self.dyn)
            self.odswiez(self.ostatni_t)
        return nowe

    def obserwuj(self, oid):
        s = self.prawda[oid]
        pula = self.obrazy.get("przejezdny" if s == "przejezdny" else "zalany")
        foto = next(pula) if pula else None
        self._foto = foto
        return s

    def widok(self, ids):
        return {o: {**self.statyczne[o], **self.dyn.get(o, {"stan": self.stany[o], "czas_obserwacji": None, "zrodlo": None})} for o in ids}

    def po_kroku(self, t_min, oid, poz, stany_ciez, st_ciez, dron=0):
        teraz = self.zegar(t_min)
        s = self.stany[oid] = stany_ciez[oid]
        foto = getattr(self, "_foto", None)
        self.dyn[oid] = {"stan": s, "przejezdny_dla": ["osobowy", "ciezarowy", "terenowy"] if s == "przejezdny" else [],
                         "zweryfikowany": True, "pewnosc": None, "czas_obserwacji": teraz.isoformat(timespec="seconds"),
                         "zrodlo": {"typ": "dron", "lot": self.lot["id"],
                                    "obraz": f"wyniki/{foto['plik']}" if foto else None,
                                    "model": {"stan": foto["stan"], "pewnosc": foto["pewnosc"]} if foto else None,
                                    "uwaga": "stan ze scenariusza; obraz FloodNet i jego predykcja są osobną ilustracją" if foto else "stan ze scenariusza; obserwacja symulowana"},
                         "symulowane": True}
        self.nadaj(dron, t_min, oid, s)
        if s in NIEPRZEJEZDNE and not self.statyczne[oid]["lesny"]:
            self.zdarzenie(t_min, "odcinek", f"{self.statyczne[oid]['droga']} ({oid}): {meldunek.OPIS_STANU[s]}")
        self.odswiez(t_min, st_ciez)
        self.misja(t_min, "zwiad", poz, dron)
        zapisz("zmiany.json", self.dyn)
        self.spij(t_min - self.ostatni_t)
        self.ostatni_t = t_min

    def spij(self, dt_min):
        """Tempo i pauza z panelu (stan/sterowanie.json); tempo = minuty symulacji na sekundę."""
        s = self.sterowanie()
        while s.get("pauza"):
            time.sleep(0.3)
            s = self.sterowanie()
        time.sleep(min(dt_min / max(float(s.get("tempo") or self.tempo), 0.1), 2.0))

    def sterowanie(self):
        try:
            return json.loads((STAN / "sterowanie.json").read_text(encoding="utf-8"))
        except (OSError, ValueError):
            return {}

    def odswiez(self, t_min, st_ciez=None):
        teraz = self.zegar(t_min)
        st_ciez = st_ciez or siec.status_wsi(self.sw.G, self.sw.wz, self.stany, "ciezarowy")
        st_ter = siec.status_wsi(self.sw.G, self.sw.wz, self.stany, "terenowy")
        for w in self.wsie:
            nowy = {"ciezarowy": st_ciez[w], "terenowy": st_ter[w]}
            if nowy == self.status[w]:
                continue
            self.status[w] = nowy
            wies = self.wsie[w]
            wies.update({"status": nowy["ciezarowy"], "status_pewnosc": None,
                         "status_czas": teraz.isoformat(timespec="seconds"),
                         "dojazd": {"osobowy": nowy["ciezarowy"] == "dostepna", "ciezarowy": nowy["ciezarowy"] == "dostepna",
                                    "terenowy": nowy["terenowy"] == "dostepna"}, "symulowane": True})
            if nowy["ciezarowy"] == "nieznany" and nowy["terenowy"] == "nieznany":
                continue
            trasy = {k: siec.trasa(self.sw.G, self.sw.wz[w], self.stany, k) for k in ("ciezarowy", "terenowy")}
            przyczyny = [o for o in self.normalnie[w] if self.stany.get(o) in NIEPRZEJEZDNE]
            ids = przyczyny + (trasy["ciezarowy"] or []) + (trasy["terenowy"] or [])
            m = meldunek.zbuduj(wies, nowy, trasy, przyczyny, self.widok(ids), teraz, next(self.nr_mel))
            self.meldunki[w] = m
            self.zdarzenie(t_min, "meldunek", m["tekst"].split("\n")[0] + " — " + m["rekomendacja"]["dzialanie"][:90])
        zapisz("wsie.json", list(self.wsie.values()))
        zapisz("meldunki.json", sorted(self.meldunki.values(), key=lambda m: (m["priorytet"], -(self.wsie[m["wies"]].get("mieszkancy_rejestr") or 0))))

    def czekaj_na_zgode(self):
        self.lot["status"] = "propozycja"
        zapisz("loty.json", [self.lot])
        self.zdarzenie(0, "lot", f"Propozycja lotu lot-001: {DRONY} drony, zwiad dróg przy ciekach, {STRATEGIE[self.strategia]}. Czeka na zgodę operatora.")
        self.misja(0, "czeka_na_zgode")
        t = time.time()
        while True:
            dec = [d for d in json.load(open(STAN / "decyzje.json", encoding="utf-8")) if d.get("dotyczy") == "lot-001"]
            if dec:
                break
            if self.auto and time.time() - t > 3:
                dec = [{"id": "dec-0001", "typ": "decyzja", "dotyczy": "lot-001", "czas": self.zegar(0).isoformat(timespec="seconds"),
                        "kto": "operator (demo, automatycznie)", "wynik": "zatwierdzona", "zmiana": None, "uwagi": "", "symulowane": True}]
                zapisz("decyzje.json", dec)
                break
            time.sleep(0.5)
        if dec[-1]["wynik"] != "zatwierdzona":
            self.zdarzenie(0, "lot", f"Lot odrzucony przez: {dec[-1]['kto']}. Koniec demo.")
            sys.exit(0)
        self.lot.update({"status": "w_locie", "zatwierdzil": {"kto": dec[-1]["kto"], "czas": dec[-1]["czas"]}})
        zapisz("loty.json", [self.lot])
        self.zdarzenie(0, "lot", f"Start zatwierdzony ({dec[-1]['kto']}). Startuje {DRONY} dronów ze stacji: {', '.join(n for n, _ in self.sw.stacje[:DRONY])}.")

    def objazdy_lesne(self, t_min, poz):
        """Dla wsi odciętych dla wozu ciężkiego: sprawdź najkrótszy możliwy objazd dla terenowego."""
        self.lot = {**self.lot, "id": "lot-002", "typ": "zwiad_drog", "status": "w_locie", "powod": "objazdy leśne do wsi odciętych"}
        zapisz("loty.json", [self.lot])
        for w in [w for w, s in self.status.items() if s["ciezarowy"] == "odcieta"]:
            for _ in range(20):
                if self.status[w]["terenowy"] != "nieznany":
                    break
                O = siec._podgraf(self.sw.G, self.stany, "terenowy", optymistyczny=True)
                try:
                    sciezka = siec.nx.shortest_path(O, siec.ZEW, self.sw.wz[w], weight="dl")
                except siec.nx.NetworkXNoPath:
                    break
                nieznane = [O[a][b]["id"] for a, b in zip(sciezka, sciezka[1:]) if self.stany.get(O[a][b]["id"]) == "nieznany"]
                if not nieznane:
                    break
                for oid in nieznane:
                    d_dolot, wyj = mc.dolot(self.sw, poz, oid)
                    t_min += (d_dolot + self.statyczne[oid]["dlugosc_m"]) / mc.V / 60
                    poz = wyj
                    stany = dict(self.stany)
                    stany[oid] = self.obserwuj(oid)
                    self.po_kroku(t_min, oid, poz, stany, None)
                    if stany[oid] in NIEPRZEJEZDNE:
                        break
        return t_min

    def uruchom(self):
        self.alarm = alarm()
        self.zdarzenie(0, "alarm", f"SCENARIUSZ ALARMU: {self.alarm['zrodlo']} — {self.alarm['stan_cm']} cm przy progu alarmowym {self.alarm['prog_alarmowy_cm']} cm (poziom symulowany; rzeczywisty zapisany pomiar: {self.alarm['stan_rzeczywisty_cm']} cm).")
        self.lot["mozna_latac"] = mozna_latac(self.zegar(0))
        for k in self.zgloszone:
            self.zdarzenie(0, "zgloszenie", f"Zgłoszenie (symulowane, np. 112): przeszkoda na drodze {self.statyczne[k]['droga']} ({k}). Odcinek dopisany do zwiadu, bez założenia przejezdności.")
        self.zdarzenie(0, "pogoda", f"Ocena pogody w scenariuszu: {self.lot['mozna_latac']['poziom'].upper()} — {self.lot['mozna_latac']['powod']}. To nie jest zgoda na lot.")
        self.czekaj_na_zgode()
        if not self.api_ok:
            self.zdarzenie(0, "lot", f"API niedostępne ({self.api.blad}); demo działa bez komunikacji z dronami.")
        krzywa, _ = mc.symuluj(self.sw, self.prawda, self.strategia, obserwuj=self.obserwuj, po_kroku=self.po_kroku,
                               drony=DRONY, zewnetrzne=self.zewnetrzne)
        t_min, poz = krzywa[-1][0], None
        poz = self.sw.doki[0]
        self.zdarzenie(t_min, "lot", "Zwiad dróg zakończony. Sprawdzam objazdy leśne dla wsi odciętych.")
        t_min = self.objazdy_lesne(t_min, poz)
        self.lot["status"] = "zakonczony"
        zapisz("loty.json", [self.lot])
        ciez = [s["ciezarowy"] for s in self.status.values()]
        self.zdarzenie(t_min, "koniec", f"Koniec misji po {t_min:.0f} min lotu: {ciez.count('dostepna')} wsi dostępnych, {ciez.count('odcieta')} odciętych dla wozu ciężkiego, {ciez.count('nieznany')} nieustalonych.")
        self.misja(t_min, "koniec", poz)
        # pełny plik w formacie docs/FORMAT.md na koniec
        zapisz("odcinki.json", [{**o, **self.dyn.get(o["id"], {})} for o in self.statyczne.values()])


if __name__ == "__main__":
    ap = argparse.ArgumentParser()
    ap.add_argument("--tempo", type=float, default=3.0, help="minuty symulacji na sekundę")
    ap.add_argument("--auto", action="store_true", help="start drona zatwierdzany automatycznie")
    ap.add_argument("--ziarno", type=int, default=ZIARNO, help="losowanie powodzi (56 = scenariusz z prezentacji)")
    ap.add_argument("--strategia", choices=STRATEGIE, default="B")
    ap.add_argument("--reczne", type=json.loads, default={}, help='np. \'{"odc-0042": "zalany"}\'')
    ap.add_argument("--przygotuj", action="store_true", help="tylko stan początkowy (reset panelu)")
    a = ap.parse_args()
    d = Demo(a.tempo, a.auto, a.ziarno, a.strategia, a.reczne)
    if a.przygotuj:
        d.misja(0, "gotowy")
    else:
        d.uruchom()
