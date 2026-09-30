"""
Bramka LoRa na stacji dokującej: odbiera ramki 20 B (komunikacja/lora/ramka.py) i przekazuje je do API.

    python -m komunikacja.lora.bramka                      # UDP 127.0.0.1:1700 (symulator, testy)
    python -m komunikacja.lora.bramka --serial /dev/ttyUSB0 # moduł LoRa (np. RAK/Heltec) wysyłający ramki jako HEX, jedna na linię

W terenie: moduł LoRa w dronie → radio 868 MHz → moduł na maszcie stacji → port szeregowy → ta bramka → API.
"""
import argparse
import os
import socket
import sys
import time

from komunikacja.klient import Klient
from komunikacja.lora.ramka import dekoduj


def przekaz(klient, ramka, licznik):
    try:
        d = dekoduj(ramka)
    except ValueError as e:
        licznik["bledy"] += 1
        print(f"[lora] odrzucona ramka: {e}", file=sys.stderr)
        return
    czas = time.strftime("%Y-%m-%dT%H:%M:%S+00:00", time.gmtime(d["czas"]))
    klient.telemetria(d["dron"], d["polozenie"], czas=czas, bateria_proc=d["bateria_proc"], lacze="lora")
    if d["typ"] == "obserwacja" and d["odcinek"]:
        klient.obserwacja(d["odcinek"], d["stan"], zrodlo="lora", dron=d["dron"], czas=czas, lacze="lora")
    licznik["odebrane"] += 1


def ramki_udp(adres):
    host, port = adres.rsplit(":", 1)
    s = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
    s.bind((host, int(port)))
    s.settimeout(5)
    print(f"[lora] bramka nasłuchuje UDP {adres}", flush=True)
    while True:
        try:
            yield s.recvfrom(256)[0]
        except socket.timeout:
            yield None


def ramki_serial(port):
    import serial  # pip install pyserial (tylko na stacji z modułem LoRa)
    with serial.Serial(port, 115200, timeout=5) as s:
        print(f"[lora] bramka czyta port {port}", flush=True)
        while True:
            linia = s.readline().strip()
            yield bytes.fromhex(linia.decode()) if linia else None


if __name__ == "__main__":
    import signal
    signal.signal(signal.SIGTERM, lambda *_: sys.exit(0))
    ap = argparse.ArgumentParser()
    ap.add_argument("--udp", default=os.environ.get("AEROPASS_LORA_UDP", "127.0.0.1:1700"))
    ap.add_argument("--serial", help="port modułu LoRa, np. /dev/ttyUSB0")
    a = ap.parse_args()
    klient, licznik, puls = Klient(), {"odebrane": 0, "bledy": 0}, 0.0
    try:
        for ramka in (ramki_serial(a.serial) if a.serial else ramki_udp(a.udp)):
            if ramka:
                przekaz(klient, ramka, licznik)
            if time.time() - puls > 10:
                klient.puls("lora", zrodlo=a.serial or f"udp {a.udp}", **licznik)
                puls = time.time()
    except KeyboardInterrupt:
        pass
