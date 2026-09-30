"""
Ramka LoRa AeroPass: 20 bajtów, mieści się nawet przy SF12 (limit 51 B w EU868).

 bajt  pole
 0     wersja (4 bity) | typ (4 bity): 1 = obserwacja odcinka, 2 = telemetria
 1     numer drona (0–255)
 2–3   numer odcinka (odc-0493 → 493), 0 = brak
 4     stan: 0 nieznany, 1 przejezdny, 2 zalany, 3 zerwany, 4 zablokowany
 5     bateria w %
 6–9   czas UNIX (s)
 10–13 szerokość geogr. × 1e5 (int32)
 14–17 długość geogr. × 1e5 (int32)
 18–19 CRC-16/CCITT z bajtów 0–17
"""
import binascii
import struct

WERSJA = 1
TYPY = {"obserwacja": 1, "telemetria": 2}
STANY = ["nieznany", "przejezdny", "zalany", "zerwany", "zablokowany"]
UKLAD = ">BBHBBIii"
ROZMIAR = struct.calcsize(UKLAD) + 2


def koduj(typ, dron, czas, polozenie, odcinek=None, stan="nieznany", bateria=0):
    numer = int(odcinek.split("-")[1]) if odcinek else 0
    tresc = struct.pack(UKLAD, (WERSJA << 4) | TYPY[typ], dron, numer, STANY.index(stan), max(0, min(100, int(bateria))),
                        int(czas), round(polozenie[0] * 1e5), round(polozenie[1] * 1e5))
    return tresc + struct.pack(">H", binascii.crc_hqx(tresc, 0xFFFF))


def dekoduj(ramka):
    if len(ramka) != ROZMIAR:
        raise ValueError(f"zła długość ramki: {len(ramka)} B zamiast {ROZMIAR} B")
    tresc, (crc,) = ramka[:-2], struct.unpack(">H", ramka[-2:])
    if binascii.crc_hqx(tresc, 0xFFFF) != crc:
        raise ValueError("błąd CRC (uszkodzona ramka)")
    wt, dron, numer, stan, bateria, czas, lat, lon = struct.unpack(UKLAD, tresc)
    if wt >> 4 != WERSJA:
        raise ValueError(f"nieznana wersja ramki: {wt >> 4}")
    typ = {v: k for k, v in TYPY.items()}[wt & 0x0F]
    return {"typ": typ, "dron": dron, "odcinek": f"odc-{numer:04d}" if numer else None, "stan": STANY[stan],
            "bateria_proc": bateria, "czas": czas, "polozenie": [lat / 1e5, lon / 1e5]}


if __name__ == "__main__":
    r = koduj("obserwacja", 3, 1790740800, (49.27012, 22.41234), "odc-0493", "zalany", 64)
    assert len(r) == ROZMIAR == 20
    d = dekoduj(r)
    assert d == {"typ": "obserwacja", "dron": 3, "odcinek": "odc-0493", "stan": "zalany", "bateria_proc": 64,
                 "czas": 1790740800, "polozenie": [49.27012, 22.41234]}, d
    zepsuta = bytes([r[0] ^ 0x01]) + r[1:]
    try:
        dekoduj(zepsuta)
        raise AssertionError("uszkodzona ramka przeszła")
    except ValueError:
        pass
    print("OK: ramka LoRa 20 B, kodowanie, dekodowanie i CRC")
