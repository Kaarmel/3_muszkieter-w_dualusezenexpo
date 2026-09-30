"""
Most do ATAK-CIV (wersja cywilna Android Team Awareness Kit) i serwera TAK: co 2 s wysyła komunikaty CoT
z pozycjami dronów, statusem wsi, nieprzejezdnymi odcinkami i punktami zatwierdzonymi przez operatora.

    python -m komunikacja.tak.most                                # UDP 127.0.0.1:6969 (test lokalny)
    python -m komunikacja.tak.most --udp 239.2.3.1:6969           # ATAK-CIV na telefonach w tej samej sieci (multicast SA)
    python -m komunikacja.tak.most --udp 192.168.1.23:4242        # jeden telefon (domyślne wejście ATAK)
    python -m komunikacja.tak.most --tcp takserver.psp.local:8087  # serwer TAK (strumień CoT bez TLS; TLS: port 8089 + certyfikaty)

Drony z API (/v1/telemetria), wsie i odcinki z planera (katalog stanu). Wsie i odcinki idą tylko po zmianie,
a raz na minutę wszystko, żeby telefon, który dołączył później, dostał pełny obraz.
"""
import argparse
import hashlib
import json
import os
import socket
import sys
import time
from datetime import datetime, timezone
from pathlib import Path

from komunikacja.klient import Klient
from komunikacja.tak import cot

STAN = Path(os.environ.get("AEROPASS_STAN", Path(__file__).resolve().parents[2] / "stan"))
NIEPRZEJEZDNE = {"zalany", "zerwany", "zablokowany"}


def czytaj(nazwa, domyslnie):
    try:
        return json.loads((STAN / nazwa).read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return domyslnie


class Cele:
    def __init__(self, udp, tcp):
        self.udp, self.tcp, self.sock_tcp = [], tcp, None
        self.u = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
        self.u.setsockopt(socket.IPPROTO_IP, socket.IP_MULTICAST_TTL, 1)  # multicast tylko w sieci lokalnej
        for a in filter(None, (udp or "").split(",")):
            h, p = a.rsplit(":", 1)
            self.udp.append((h, int(p)))

    def wyslij(self, xml):
        for cel in self.udp:
            self.u.sendto(xml, cel)
        if self.tcp:
            try:
                if not self.sock_tcp:
                    h, p = self.tcp.rsplit(":", 1)
                    self.sock_tcp = socket.create_connection((h, int(p)), timeout=3)
                self.sock_tcp.sendall(xml)
            except OSError as e:
                print(f"[tak] serwer TAK {self.tcp} niedostępny: {e}", file=sys.stderr)
                self.sock_tcp = None


def komunikaty(klient, pamiec, wszystko):
    out = []
    teraz = datetime.now(timezone.utc)
    tel = {k: t for k, t in (klient.pozycje() or {}).items()   # tylko drony, które odezwały się w ostatnich 2 min
           if (teraz - datetime.fromisoformat(t["odebrano"])).total_seconds() < 120}
    if not tel:  # API bez świeżej telemetrii: pozycje prosto z symulatora
        tel = {str(i + 1): {"dron": i + 1, **d} for i, d in enumerate(czytaj("misja.json", {}).get("drony", []))}
    for t in tel.values():
        out.append(cot.dron(t["dron"], t["polozenie"], t.get("kurs") or 0, 12.0, t.get("bateria_proc"), t.get("lacze")))
    meldunki = {m["wies"]: m["tekst"] for m in czytaj("meldunki.json", [])}
    obiekty = [(w["id"], w.get("status"), lambda w=w: cot.wies(w, meldunki.get(w["id"]))) for w in czytaj("wsie.json", [])]
    po_id = {o["id"]: o for o in czytaj("odcinki.json", [])}
    for oid, z in czytaj("zmiany.json", {}).items():
        if z.get("stan") in NIEPRZEJEZDNE and oid in po_id:
            obiekty.append((oid, z["stan"], lambda o=po_id[oid], s=z["stan"]: cot.odcinek(o, s)))
    for o in czytaj("obserwacje_operatora.json", []):  # punkty zatwierdzone w ai/kamera.py
        obiekty.append((f"obs-{o['id']}", o["typ"], lambda o=o: cot.obserwacja(o)))
    for uid, stan_, buduj in obiekty:
        podpis = hashlib.sha1(f"{stan_}|{meldunki.get(uid, '')}".encode()).hexdigest()
        if wszystko or pamiec.get(uid) != podpis:
            pamiec[uid] = podpis
            out.append(buduj())
    return out


if __name__ == "__main__":
    import signal
    signal.signal(signal.SIGTERM, lambda *_: sys.exit(0))
    ap = argparse.ArgumentParser()
    ap.add_argument("--udp", default=os.environ.get("AEROPASS_TAK_UDP", "127.0.0.1:6969"), help="host:port[,host:port]")
    ap.add_argument("--tcp", default=os.environ.get("AEROPASS_TAK_TCP"), help="serwer TAK host:port")
    ap.add_argument("--co", type=float, default=2.0, help="okres wysyłki w sekundach")
    a = ap.parse_args()
    klient, cele, pamiec, ostatnio_wszystko, puls, wyslane = Klient(), Cele(a.udp, a.tcp), {}, 0.0, 0.0, 0
    print(f"[tak] most CoT → UDP {a.udp or '-'}, TCP {a.tcp or '-'}", flush=True)
    try:
        while True:
            wszystko = time.time() - ostatnio_wszystko > 60
            for xml in komunikaty(klient, pamiec, wszystko):
                cele.wyslij(xml)
                wyslane += 1
            if wszystko:
                ostatnio_wszystko = time.time()
            if time.time() - puls > 10:
                klient.puls("tak", udp=a.udp, tcp=a.tcp, wyslane=wyslane)
                puls = time.time()
            time.sleep(a.co)
    except KeyboardInterrupt:
        pass
