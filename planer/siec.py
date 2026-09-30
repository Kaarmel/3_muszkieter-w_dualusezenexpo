"""
Sieć dróg doliny z OSM → odcinki (droga między skrzyżowaniami) + status wsi.

Status wsi dla danej klasy pojazdu (docs/FORMAT.md):
- "dostepna": istnieje dojazd z zewnątrz wyłącznie po odcinkach o znanym stanie "przejezdny",
- "odcieta": nie ma dojazdu nawet przy założeniu, że każdy odcinek o nieznanym stanie jest przejezdny,
- "nieznany": wszystko pomiędzy (brak dowodu to nie „bezpiecznie”).
"""
import json
import math
from collections import defaultdict

import networkx as nx

ZEW = "ZEW"  # wirtualny węzeł „świat zewnętrzny”: dojazd spoza doliny (np. JRG PSP Lesko)
DROGI = {"primary", "secondary", "tertiary", "unclassified", "residential", "living_street", "track"}  # bez „service” (podjazdy, parkingi)
MIEJSCOWOSCI = {"village", "hamlet", "town"}
PRZY_POTOKU_M = 60
KLASY = ("osobowy", "ciezarowy", "terenowy")


def hav(a, b):
    la1, lo1, la2, lo2 = map(math.radians, (*a, *b))
    h = math.sin((la2 - la1) / 2) ** 2 + math.cos(la1) * math.cos(la2) * math.sin((lo2 - lo1) / 2) ** 2
    return 12742000 * math.asin(math.sqrt(h))


def _slug(s):
    tr = str.maketrans("ąćęłńóśźż ", "acelnoszz-")
    return s.lower().translate(tr)


def zbuduj(osm_path, bbox):
    """Zwraca (odcinki, wsie, G, wezly_wsi). G: MultiGraph skrzyżowań, klucz krawędzi = id odcinka."""
    S, W, N, E = bbox
    el = json.load(open(osm_path, encoding="utf-8"))["elements"]
    key = lambda p: (round(p["lat"], 7), round(p["lon"], 7))

    # siatka punktów cieków do testu „przy potoku”
    siatka = defaultdict(list)
    for e in el:
        if e["type"] == "way" and e.get("tags", {}).get("waterway") in ("river", "stream"):
            for p in e["geometry"]:
                q = key(p)
                siatka[(int(q[0] * 500), int(q[1] * 500))].append(q)

    def blisko_wody(p):
        i, j = int(p[0] * 500), int(p[1] * 500)
        return any(hav(p, q) < PRZY_POTOKU_M for di in (-1, 0, 1) for dj in (-1, 0, 1) for q in siatka[(i + di, j + dj)])

    # graf mikrosegmentów
    M = nx.Graph()
    for e in el:
        t = e.get("tags", {})
        if e["type"] == "way" and t.get("highway") in DROGI:
            g = [key(p) for p in e["geometry"]]
            atr = {"lesny": t["highway"] == "track", "most": t.get("bridge") == "yes",
                   "droga": t.get("ref") and f"DW {t['ref']}" if t.get("ref", "").isdigit() else (t.get("ref") or t.get("name") or ("droga leśna" if t["highway"] == "track" else "droga lokalna"))}
            for a, b in zip(g, g[1:]):
                if a != b:
                    M.add_edge(a, b, **atr)

    # łańcuchy między węzłami podziału (skrzyżowania, końce, zmiana typu drogi/mostu)
    klucz = lambda u, v: (M.edges[u, v]["lesny"], M.edges[u, v]["most"], M.edges[u, v]["droga"])
    podzial = {n for n in M if M.degree(n) != 2 or len({klucz(n, m) for m in M[n]}) > 1}
    widziane, lancuchy = set(), []
    for start in sorted(podzial) + sorted(M):  # druga część łapie czyste pętle bez węzłów podziału
        for nb in sorted(M[start]):
            if (start, nb) in widziane:
                continue
            sciezka = [start, nb]
            widziane |= {(start, nb), (nb, start)}
            while sciezka[-1] not in podzial and sciezka[-1] != start:
                cur = sciezka[-1]
                nxt = next((m for m in M[cur] if m != sciezka[-2] and (cur, m) not in widziane), None)
                if nxt is None:
                    break
                widziane |= {(cur, nxt), (nxt, cur)}
                sciezka.append(nxt)
            lancuchy.append(sciezka)
        podzial.add(start)

    lancuchy.sort(key=lambda s: (min(s), max(s)))
    G = nx.MultiGraph()
    odcinki = []
    for i, s in enumerate(lancuchy, 1):
        d = M.edges[s[0], s[1]]
        oid = f"odc-{i:04d}"
        dl = sum(hav(a, b) for a, b in zip(s, s[1:]))
        most = any(M.edges[a, b]["most"] for a, b in zip(s, s[1:]))
        o = {"id": oid, "droga": d["droga"], "geometria": [[round(a, 6), round(b, 6)] for a, b in s],
             "dlugosc_m": round(dl), "most": most, "przy_potoku": most or any(blisko_wody(p) for p in s),
             "lesny": d["lesny"], "krytyczny_dla": []}
        odcinki.append(o)
        G.add_edge(s[0], s[-1], key=oid, dl=dl, lesny=o["lesny"])

    # świat zewnętrzny: węzły drogowe (nie leśne) poza obszarem albo tuż przy jego krawędzi
    for n in list(G):
        przy_krawedzi = min(n[0] - S, N - n[0]) < 0.0015 or min(n[1] - W, E - n[1]) < 0.002
        if przy_krawedzi and any(not d["lesny"] for _, _, d in G.edges(n, data=True)):
            G.add_edge(n, ZEW, key=f"ZEW-{n[0]}-{n[1]}", dl=0.0, lesny=False)

    # wsie → najbliższy węzeł drogi utwardzonej wewnątrz obszaru
    utwardzone = [n for n in G if n != ZEW and any(not d["lesny"] for _, _, d in G.edges(n, data=True))]
    wsie, wezly_wsi, uzyte = [], {}, set()
    for e in el:
        t = e.get("tags", {})
        if e["type"] == "node" and t.get("place") in MIEJSCOWOSCI and t.get("name"):
            p = (e["lat"], e["lon"])
            if not (S <= p[0] <= N and W <= p[1] <= E):
                continue
            wid = "wies-" + _slug(t["name"])
            while wid in uzyte:
                wid += "-2"
            uzyte.add(wid)
            pop = t.get("population")
            wsie.append({"id": wid, "nazwa": t["name"], "polozenie": [round(p[0], 6), round(p[1], 6)],
                         "mieszkancy_rejestr": int(pop) if pop and pop.isdigit() else None,
                         "mieszkancy_zrodlo": "OSM" if pop else None})
            wezly_wsi[wid] = min(utwardzone, key=lambda n: hav(p, n))

    # krytyczny_dla: odcinki (utwardzone), których samo przerwanie odcina wieś od świata zewnętrznego
    H = nx.Graph()
    krotnosc = defaultdict(list)
    for u, v, k, d in G.edges(keys=True, data=True):
        if not d["lesny"]:
            krotnosc[frozenset((u, v))].append(k)
            H.add_edge(u, v)
    po_id = {o["id"]: o for o in odcinki}
    for u, v in nx.bridges(H):
        ids = krotnosc[frozenset((u, v))]
        if len(ids) != 1 or ids[0].startswith("ZEW"):
            continue
        H2 = H.copy()
        H2.remove_edge(u, v)
        osiagalne = nx.node_connected_component(H2, ZEW)
        po_id[ids[0]]["krytyczny_dla"] = sorted(w for w, n in wezly_wsi.items() if n not in osiagalne)
    return odcinki, wsie, G, wezly_wsi


def dozwolony(d, klasa):
    return klasa == "terenowy" or not d["lesny"]


def _podgraf(G, stany, klasa, optymistyczny):
    ok = {"przejezdny", "nieznany"} if optymistyczny else {"przejezdny"}
    H = nx.Graph()
    H.add_node(ZEW)
    for u, v, k, d in G.edges(keys=True, data=True):
        if not dozwolony(d, klasa):
            continue
        if k.startswith("ZEW") or stany.get(k, "nieznany") in ok:
            if not H.has_edge(u, v) or H[u][v]["dl"] > d["dl"]:
                H.add_edge(u, v, dl=d["dl"], id=k)
    return H


def status_wsi(G, wezly_wsi, stany, klasa="ciezarowy"):
    P = _podgraf(G, stany, klasa, optymistyczny=False)
    O = _podgraf(G, stany, klasa, optymistyczny=True)
    cp = nx.node_connected_component(P, ZEW)
    co = nx.node_connected_component(O, ZEW)
    return {w: "dostepna" if n in cp else ("odcieta" if n not in co else "nieznany") for w, n in wezly_wsi.items()}


def trasa(G, wezel, stany, klasa="ciezarowy"):
    """Najkrótszy dojazd z zewnątrz po odcinkach o znanym stanie „przejezdny” (lista id) albo None."""
    P = _podgraf(G, stany, klasa, optymistyczny=False)
    try:
        sciezka = nx.shortest_path(P, ZEW, wezel, weight="dl")
    except (nx.NetworkXNoPath, nx.NodeNotFound):
        return None
    return [P[a][b]["id"] for a, b in zip(sciezka, sciezka[1:]) if not P[a][b]["id"].startswith("ZEW")]


if __name__ == "__main__":
    # test logiki statusu na małym grafie: ZEW —a— X —b— Y, oraz objazd leśny ZEW —c(leśny)— Y
    G = nx.MultiGraph()
    G.add_edge(ZEW, "X", key="ZEW-1", dl=0, lesny=False)
    G.add_edge("X", "A", key="a", dl=100, lesny=False)
    G.add_edge("A", "Y", key="b", dl=100, lesny=False)
    G.add_edge("X", "Y", key="c", dl=300, lesny=True)
    wz = {"wies-a": "A", "wies-y": "Y"}
    assert status_wsi(G, wz, {}) == {"wies-a": "nieznany", "wies-y": "nieznany"}
    assert status_wsi(G, wz, {"a": "przejezdny"}) == {"wies-a": "dostepna", "wies-y": "nieznany"}
    assert status_wsi(G, wz, {"a": "zerwany"}) == {"wies-a": "odcieta", "wies-y": "odcieta"}
    assert status_wsi(G, wz, {"a": "zerwany"}, "terenowy") == {"wies-a": "nieznany", "wies-y": "nieznany"}
    assert status_wsi(G, wz, {"a": "zerwany", "c": "przejezdny", "b": "przejezdny"}, "terenowy") == {"wies-a": "dostepna", "wies-y": "dostepna"}
    assert trasa(G, "Y", {"a": "przejezdny", "b": "przejezdny"}) == ["a", "b"]
    assert trasa(G, "Y", {"a": "zerwany"}) is None
    print("OK: status wsi i trasy (brak dowodu = nieznany, drogi leśne tylko dla terenowych)")
