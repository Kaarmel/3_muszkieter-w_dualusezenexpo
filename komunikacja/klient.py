"""
Klient API AeroPass: używają go symulator, bramka LoRa, model zdjęć i most TAK. Oprogramowanie stacji
dokującej może wołać te same metody albo po prostu wysyłać JSON zgodny z komunikacja/api/openapi.yaml.

Adresy usług ze zmiennych środowiskowych (w kontenerach to nazwy usług z docker-compose):
  AEROPASS_API_URL   domyślnie http://127.0.0.1:8770
  AEROPASS_TOKEN     domyślnie aeropass-dev
  AEROPASS_LORA_UDP  domyślnie 127.0.0.1:1700 (bramka LoRa, surowe ramki 20 B)

Z terminala:
  python -m komunikacja.klient zdrowie
  python -m komunikacja.klient uslugi
  python -m komunikacja.klient obserwacja --odcinek odc-0493 --stan zalany
  python -m komunikacja.klient zdjecie foto.jpg --odcinek odc-0493
"""
import argparse
import json
import os
import socket
import sys
from urllib.error import HTTPError, URLError
from urllib.request import Request, urlopen


class Klient:
    def __init__(self, url=None, token=None, timeout=2.0):
        self.url = (url or os.environ.get("AEROPASS_API_URL", "http://127.0.0.1:8770")).rstrip("/")
        self.token = token or os.environ.get("AEROPASS_TOKEN", "aeropass-dev")
        self.timeout, self.blad = timeout, None

    def _zadanie(self, metoda, sciezka, dane=None, typ="application/json"):
        if dane is not None and typ == "application/json":
            dane = json.dumps(dane, ensure_ascii=False).encode()
        r = Request(self.url + sciezka, data=dane, method=metoda,
                    headers={"Authorization": f"Bearer {self.token}", "Content-Type": typ})
        try:
            with urlopen(r, timeout=self.timeout) as odp:
                self.blad = None
                return json.loads(odp.read() or b"null")
        except HTTPError as e:
            self.blad = f"{e.code}: {e.read().decode(errors='replace')[:200]}"
        except (URLError, OSError, ValueError) as e:
            self.blad = f"brak połączenia z {self.url}: {e}"
        return None

    def zdrowie(self):
        return self._zadanie("GET", "/v1/zdrowie")

    def telemetria(self, dron, polozenie, **pola):
        return self._zadanie("POST", "/v1/telemetria", {"dron": dron, "polozenie": list(polozenie), **pola})

    def obserwacja(self, odcinek, stan, zrodlo="dron", **pola):
        return self._zadanie("POST", "/v1/obserwacje", {"odcinek": odcinek, "stan": stan, "zrodlo": zrodlo, **pola})

    def pozycje(self):
        """Ostatnia telemetria każdego drona: {"1": {...}, "2": {...}}."""
        return self._zadanie("GET", "/v1/telemetria")

    def obserwacje(self, od=0):
        return self._zadanie("GET", f"/v1/obserwacje?od={int(od)}")

    def zdjecie(self, dane, odcinek, dron=None, typ="image/jpeg"):
        return self._zadanie("POST", f"/v1/zdjecia?odcinek={odcinek}" + (f"&dron={dron}" if dron is not None else ""), dane, typ)

    def puls(self, usluga, **info):
        return self._zadanie("POST", f"/v1/uslugi/{usluga}/puls", info)

    def uslugi(self):
        return self._zadanie("GET", "/v1/uslugi")


def wyslij_lora(ramka, adres=None):
    """Ramka LoRa do bramki (UDP). W terenie ten krok robi radio: moduł LoRa drona → bramka na stacji."""
    host, port = (adres or os.environ.get("AEROPASS_LORA_UDP", "127.0.0.1:1700")).rsplit(":", 1)
    with socket.socket(socket.AF_INET, socket.SOCK_DGRAM) as s:
        s.sendto(ramka, (host, int(port)))


if __name__ == "__main__":
    ap = argparse.ArgumentParser(description="Klient API AeroPass")
    ap.add_argument("polecenie", choices=["zdrowie", "uslugi", "obserwacja", "zdjecie"])
    ap.add_argument("plik", nargs="?", help="zdjęcie (dla polecenia zdjecie)")
    ap.add_argument("--odcinek"), ap.add_argument("--stan", default="zalany"), ap.add_argument("--dron", type=int)
    a = ap.parse_args()
    k = Klient()
    if a.polecenie == "zdjecie":
        typ = "image/png" if a.plik.lower().endswith(".png") else "image/jpeg"
        wynik = k.zdjecie(open(a.plik, "rb").read(), a.odcinek, a.dron, typ)
    elif a.polecenie == "obserwacja":
        wynik = k.obserwacja(a.odcinek, a.stan, zrodlo="operator", dron=a.dron)
    else:
        wynik = getattr(k, a.polecenie)()
    print(json.dumps(wynik, ensure_ascii=False, indent=1) if wynik is not None else f"BŁĄD: {k.blad}")
    sys.exit(0 if wynik is not None else 1)
