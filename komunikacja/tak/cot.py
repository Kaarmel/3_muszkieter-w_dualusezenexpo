"""
Komunikaty Cursor on Target (CoT 2.0) dla ATAK-CIV / WinTAK / iTAK i serwera TAK.

 - dron        → punkt  "a-f-A-C-H" (swój, powietrze, cywilny, wiropłat), co kilka sekund
 - wieś        → znacznik "b-m-p-s-m" w kolorze statusu, w opisie ostatni meldunek
 - odcinek     → linia "u-d-f" (rysunek) dla odcinków zalanych, zerwanych i zablokowanych

Typy CoT i kolory to propozycja do uzgodnienia z administratorem serwera TAK w komendzie PSP.
"""
import xml.etree.ElementTree as ET
from datetime import datetime, timedelta, timezone

KOLOR = {"dostepna": -16744448, "odcieta": -65536, "nieznany": -8355712,          # ARGB jako int32, jak w ATAK
         "zalany": -16776961, "zerwany": -65536, "zablokowany": -65536}
NIEZNANE = "9999999.0"


def _czas(t):
    return t.astimezone(timezone.utc).strftime("%Y-%m-%dT%H:%M:%S.%fZ")[:-4] + "Z"


def _zdarzenie(uid, typ, lat, lon, teraz, waznosc_s, how="m-g"):
    e = ET.Element("event", version="2.0", uid=uid, type=typ, how=how,
                   time=_czas(teraz), start=_czas(teraz), stale=_czas(teraz + timedelta(seconds=waznosc_s)))
    ET.SubElement(e, "point", lat=f"{lat:.6f}", lon=f"{lon:.6f}", hae=NIEZNANE, ce=NIEZNANE, le=NIEZNANE)
    return e, ET.SubElement(e, "detail")


def dron(nr, polozenie, kurs=0, predkosc_ms=0.0, bateria=None, lacze=None, teraz=None):
    teraz = teraz or datetime.now(timezone.utc)
    e, d = _zdarzenie(f"aeropass-dron-{nr}", "a-f-A-C-H", polozenie[0], polozenie[1], teraz, 30)
    ET.SubElement(d, "contact", callsign=f"AeroPass Dron {nr}")
    ET.SubElement(d, "track", course=f"{kurs:.1f}", speed=f"{predkosc_ms:.1f}")
    ET.SubElement(d, "remarks").text = " · ".join(x for x in (f"bateria {bateria}%" if bateria is not None else "",
                                                             f"łącze {lacze}" if lacze else "", "zwiad dróg (symulacja)") if x)
    return ET.tostring(e, encoding="utf-8")


def wies(w, meldunek=None, teraz=None):
    teraz = teraz or datetime.now(timezone.utc)
    e, d = _zdarzenie(f"aeropass-{w['id']}", "b-m-p-s-m", w["polozenie"][0], w["polozenie"][1], teraz, 600, how="h-g-i-g-o")
    status = {"dostepna": "dojazd jest", "odcieta": "ODCIĘTA", "nieznany": "nie wiadomo"}[w.get("status", "nieznany")]
    ET.SubElement(d, "contact", callsign=f"{w['nazwa']}: {status}")
    ET.SubElement(d, "color", argb=str(KOLOR[w.get("status", "nieznany")]))
    ET.SubElement(d, "remarks").text = meldunek or f"Status dojazdu wozem ciężkim: {status}."
    return ET.tostring(e, encoding="utf-8")


OBSERWACJA = {  # typ z ai/kamera.py → (nazwa na mapie, kolor ARGB)
    "zalanie": ("Zalanie", -16776961), "drzewa": ("Blokada drogi: powalone drzewa", -65536),
    "uszkodzony_most": ("Uszkodzony most", -65536), "inne": ("Przeszkoda", -23296),
    "brak_widocznego_zalania": ("Brak widocznego zalania", -16744448), "nie_ustalono": ("Nie ustalono", -8355712),
}


def obserwacja(o, teraz=None):
    """Punkt zatwierdzony przez operatora w ai/kamera.py: miejsce zdarzenia, nie pozycja drona."""
    teraz = teraz or datetime.now(timezone.utc)
    nazwa, kolor = OBSERWACJA.get(o["typ"], OBSERWACJA["inne"])
    if o.get("liczba"):
        nazwa += f" ({o['liczba']})"
    e, d = _zdarzenie(f"aeropass-obs-{o['id']}", "b-m-p-s-m", o["gps"][0], o["gps"][1], teraz, 6 * 3600, how="h-g-i-g-o")
    ET.SubElement(d, "contact", callsign=f"{nazwa} · AeroPass")
    ET.SubElement(d, "color", argb=str(kolor))
    material = "materiał demonstracyjny" if o.get("material") == "demo" else "ujęcie z lotu"
    ET.SubElement(d, "remarks").text = " · ".join(x for x in (
        f"Potwierdził: {o['operator']}, {o['czas_potwierdzenia']}", f"sugestia AI: {o.get('sugestia', '—')}",
        f"źródło: {o['zrodlo']}", material, o.get("uwagi", "")) if x)
    return ET.tostring(e, encoding="utf-8")


def odcinek(o, stan, teraz=None):
    teraz = teraz or datetime.now(timezone.utc)
    g = o["geometria"]
    srodek = g[len(g) // 2]
    e, d = _zdarzenie(f"aeropass-{o['id']}", "u-d-f", srodek[0], srodek[1], teraz, 1800, how="h-e")
    for lat, lon in g[:: max(1, len(g) // 40)] + [g[-1]]:   # do ~40 punktów, żeby ramka była mała
        ET.SubElement(d, "link", point=f"{lat:.6f},{lon:.6f}")
    ET.SubElement(d, "contact", callsign=f"{o['droga']}: {stan}")
    ET.SubElement(d, "strokeColor", value=str(KOLOR[stan]))
    ET.SubElement(d, "strokeWeight", value="4.0")
    ET.SubElement(d, "remarks").text = f"AeroPass: {o['droga']} ({o['id']}) {stan}, obserwacja z drona."
    return ET.tostring(e, encoding="utf-8")


if __name__ == "__main__":
    t = datetime(2026, 9, 30, 4, 10, tzinfo=timezone.utc)
    x = ET.fromstring(dron(2, (49.27, 22.41), kurs=135, bateria=71, lacze="lora", teraz=t))
    assert x.get("type") == "a-f-A-C-H" and x.get("uid") == "aeropass-dron-2" and x.get("stale") == "2026-09-30T04:10:30.000Z"
    assert x.find("detail/track").get("course") == "135.0" and "lora" in x.find("detail/remarks").text
    w = ET.fromstring(wies({"id": "wies-wetlina", "nazwa": "Wetlina", "polozenie": [49.26, 22.47], "status": "odcieta"}, "PILNE – Wetlina", t))
    assert w.find("detail/color").get("argb") == "-65536" and w.find("detail/contact").get("callsign") == "Wetlina: ODCIĘTA"
    o = ET.fromstring(odcinek({"id": "odc-0493", "droga": "DW 897", "geometria": [[49.1, 22.3], [49.2, 22.4], [49.3, 22.5]]}, "zalany", t))
    assert o.get("type") == "u-d-f" and len(o.findall("detail/link")) >= 3
    print("OK: komunikaty CoT dla ATAK-CIV (dron, wieś, odcinek)")
