"""
Wybór łącza dla wiadomości z drona zależnie od warunków, oraz czas nadawania LoRa.

Kolejność (od najbogatszego łącza):
  1. RF  – łącze drona do stacji dokującej (2,4 / 5,8 GHz): pełne dane i zdjęcia, gdy dron widzi stację.
  2. LTE – modem w dronie albo w stacji, jeśli jest zasięg: zdjęcia w niższej rozdzielczości.
  3. LoRa 868 MHz – tylko krótkie ramki stanu (odcinek, stan, pozycja); działa daleko i bez sieci komórkowej.
  4. Zapisz i prześlij po powrocie do stacji – gdy nic nie działa albo wiadomość jest za duża na LoRa.

Zasięgi to założenia do sprawdzenia w terenie (Bieszczady: doliny zasłaniają widoczność).
Czas nadawania LoRa: wzór z noty Semtech SX1276/77/78/79 (rozdz. 4.1.1.7).
"""
import math

# założenia do pomiaru w terenie (km)
RF_ZASIEG_KM = {"los": 8.0, "nlos": 2.0}      # łącze drona do stacji, z widocznością / bez
LORA_ZASIEG_KM = {"los": 15.0, "nlos": 8.0}   # 868 MHz, antena na maszcie stacji; 868 MHz lepiej obchodzi zbocza niż 2,4 GHz
LORA_MAKS_BAJTOW = {7: 222, 8: 222, 9: 115, 10: 51, 11: 51, 12: 51}  # EU868, LoRaWAN RP002 (do weryfikacji)
LORA_CYKL_PRACY = 0.01   # 1% w podpaśmie 868,0–868,6 MHz (ERC Rec 70-03, ETSI EN 300 220), do weryfikacji


def czas_nadawania_ms(bajty, sf=7, bw_khz=125, cr=1, preambula=8, naglowek=True, crc=True):
    """Time on air ramki LoRa w ms (cr=1 oznacza kodowanie 4/5)."""
    t_sym = (2 ** sf) / (bw_khz * 1000) * 1000
    de = 1 if sf >= 11 and bw_khz == 125 else 0   # low data rate optimize
    ih = 0 if naglowek else 1
    liczba = 8 + max(math.ceil((8 * bajty - 4 * sf + 28 + 16 * crc - 20 * ih) / (4 * (sf - 2 * de))) * (cr + 4), 0)
    return (preambula + 4.25) * t_sym + liczba * t_sym


def sf_dla_odleglosci(km, widocznosc):
    """Im dalej, tym wolniejszy (dłuższy) SF; założenie liniowe do skalibrowania pomiarem RSSI/SNR."""
    zasieg = LORA_ZASIEG_KM["los" if widocznosc else "nlos"]
    return min(12, max(7, 7 + math.ceil(5 * km / zasieg)))


def wiadomosci_na_godzine(bajty, sf):
    """Ile ramek zmieści się w limicie cyklu pracy (np. 36 s nadawania na godzinę przy 1%)."""
    return int(3600 * 1000 * LORA_CYKL_PRACY // czas_nadawania_ms(bajty, sf))


def wybierz(odleglosc_km, widocznosc=True, lte=False, bajty=20):
    """Zwraca (łącze, szczegóły). bajty: rozmiar wiadomości (ramka stanu ok. 20 B, zdjęcie setki kB)."""
    wid = "los" if widocznosc else "nlos"
    if odleglosc_km <= RF_ZASIEG_KM[wid]:
        return "rf", {"powod": f"stacja w zasięgu RF ({odleglosc_km:.1f} km ≤ {RF_ZASIEG_KM[wid]} km, {wid})"}
    if lte:
        return "lte", {"powod": "brak RF, jest zasięg LTE"}
    if odleglosc_km <= LORA_ZASIEG_KM[wid]:
        sf = sf_dla_odleglosci(odleglosc_km, widocznosc)
        if bajty <= LORA_MAKS_BAJTOW[sf]:
            return "lora", {"sf": sf, "czas_ms": round(czas_nadawania_ms(bajty, sf), 1),
                            "ramek_na_h": wiadomosci_na_godzine(bajty, sf), "powod": f"tylko LoRa, SF{sf}"}
        return "zapisz", {"powod": f"{bajty} B nie mieści się w ramce LoRa SF{sf}; wyślemy po powrocie do stacji"}
    return "zapisz", {"powod": "brak łącza; zapis na pokładzie i wysyłka po powrocie do stacji"}


def tabela(bajty=20):
    """Tabela do dokumentacji: czas nadawania i limit ramek dla ramki stanu AeroPass."""
    return [{"sf": sf, "czas_ms": round(czas_nadawania_ms(bajty, sf), 1), "ramek_na_h": wiadomosci_na_godzine(bajty, sf)}
            for sf in range(7, 13)]


if __name__ == "__main__":
    # wartości kontrolne: kalkulator TTN dla 13 B przy 125 kHz: SF7 46,3 ms, SF12 1155,1 ms
    assert round(czas_nadawania_ms(13, 7), 1) == 46.3 and round(czas_nadawania_ms(13, 12), 1) == 1155.1
    assert wybierz(3)[0] == "rf" and wybierz(3, widocznosc=False)[0] == "lora"
    assert wybierz(12, lte=True)[0] == "lte" and wybierz(12)[0] == "lora" and wybierz(40)[0] == "zapisz"
    assert wybierz(12, bajty=300_000)[0] == "zapisz"  # zdjęcie nie pójdzie przez LoRa
    for w in tabela():
        print(f"SF{w['sf']}: {w['czas_ms']} ms na ramkę 20 B, maks. {w['ramek_na_h']} ramek/h przy 1%")
    print("OK: wybór łącza i czas nadawania LoRa")
