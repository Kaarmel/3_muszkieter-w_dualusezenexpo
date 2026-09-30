# PROTOTYP (29.09, 14:15) dla roli B: które odcinki dróg w dolinie odcinają wsie, jeśli zostaną przerwane.
# Uruchomienie (z katalogu głównego repo): python planer/krytyczne_odcinki.py [plik.json] [tracks]  (wymaga: pip install networkx)
# Ograniczenia: tylko pojedyncze przerwania (mosty grafu); wieś = najbliższy węzeł drogi; trasa lotu to przybliżenie
# (najbliższy sąsiad, lot po prostej, bez powrotów na wymianę baterii); baza w Cisnej to założenie.
import json, math, sys, collections
import networkx as nx
OSM = next((a for a in sys.argv[1:] if a.endswith(".json")), "dane/osm/dolina_solinki.json")
Z_TRACKAMI = "tracks" in sys.argv[1:]
S, W, N, E = 49.12, 22.28, 49.32, 22.52
d = json.load(open(OSM))["elements"]
def hav(a, b):
    la1, lo1, la2, lo2 = map(math.radians, (*a, *b))
    h = math.sin((la2-la1)/2)**2 + math.cos(la1)*math.cos(la2)*math.sin((lo2-lo1)/2)**2
    return 12742000 * math.asin(math.sqrt(h))
key = lambda p: (round(p["lat"], 7), round(p["lon"], 7))
drogi = {"primary","secondary","tertiary","unclassified","residential","living_street","service"} | ({"track"} if Z_TRACKAMI else set())
G = nx.Graph(); woda = []
for e in d:
    t = e.get("tags", {})
    if e["type"] == "way" and t.get("highway") in drogi:
        g = [key(p) for p in e["geometry"]]
        for a, b in zip(g, g[1:]):
            if a != b: G.add_edge(a, b, dl=hav(a, b), most=t.get("bridge") == "yes", ref=t.get("ref"))
    if e["type"] == "way" and t.get("waterway") in ("river", "stream"):
        woda += [key(p) for p in e["geometry"]]
# siatka do szybkiego sprawdzania "czy blisko potoku"
siatka = collections.defaultdict(list)
for p in woda: siatka[(int(p[0]*500), int(p[1]*500))].append(p)
def blisko_wody(p, r=60):
    i, j = int(p[0]*500), int(p[1]*500)
    return any(hav(p, q) < r for di in (-1,0,1) for dj in (-1,0,1) for q in siatka[(i+di, j+dj)])
# świat zewnętrzny: węzły przy krawędzi obszaru
for n in list(G):
    if min(n[0]-S, N-n[0]) < 0.0015 or min(n[1]-W, E-n[1]) < 0.002: G.add_edge(n, "ZEW", dl=0, most=False, ref=None)
# wsie -> najbliższy węzeł drogi
wezly = [n for n in G if n != "ZEW"]
wsie = {}
for e in d:
    t = e.get("tags", {})
    if e["type"] == "node" and t.get("place") in ("village", "hamlet", "town"):
        p = (e["lat"], e["lon"]); wsie[t.get("name")] = min(wezly, key=lambda n: hav(p, n))
cc = nx.node_connected_component(G, "ZEW")
nieosiagalne = [w for w, n in wsie.items() if n not in cc]
mosty_grafu = list(nx.bridges(G))
H = G.copy(); H.remove_edges_from(mosty_grafu)
komp = {n: i for i, c in enumerate(nx.connected_components(H)) for n in c}
T = nx.Graph()
for a, b in mosty_grafu: T.add_edge(komp[a], komp[b], k=(a, b))
root = komp["ZEW"]; rodzic = {}
if root in T:
    for u, v in nx.bfs_edges(T, root): rodzic[v] = (u, T[u][v]["k"])
krytyczne = set(); per_wies = {}
for w, n in wsie.items():
    c = komp[n]; zb = set()
    while c in rodzic: u, k = rodzic[c]; zb.add(k); c = u
    per_wies[w] = zb; krytyczne |= zb
dl = lambda E: sum(G.edges[e]["dl"] for e in E) / 1000
wszystkie = [e for e in G.edges if "ZEW" not in e]
kryt_woda = {e for e in krytyczne if G.edges[e]["most"] or blisko_wody(e[0]) or blisko_wody(e[1])}
print(f"{'z drogami leśnymi' if Z_TRACKAMI else 'bez dróg leśnych'}: wsi {len(wsie)}, nieosiągalnych z zewnątrz już przed powodzią (błędy danych/obszaru): {len(nieosiagalne)} {nieosiagalne}")
print(f"  wszystkie drogi: {dl(wszystkie):.0f} km")
print(f"  odcinki, których przerwanie odcina jakąkolwiek wieś: {dl(krytyczne):.1f} km")
print(f"  z tego przy potoku (<60 m) lub na moście: {dl(kryt_woda):.1f} km; mosty OSM na nich: {sum(1 for e in kryt_woda if G.edges[e]['most'])} segmentów")
print(f"  wsie nieodcinalne jednym przerwaniem: {sorted(w for w, z in per_wies.items() if not z and w not in nieosiagalne)}")
print(f"  lot 10 m/s: wszystkie drogi {dl(wszystkie)/36:.1f} h vs krytyczne przy wodzie {dl(kryt_woda)/36*60:.0f} min")
przy_wodzie = [e for e in wszystkie if G.edges[e]["most"] or blisko_wody(e[0]) or blisko_wody(e[1])]
print(f"  wszystkie drogi przy potokach lub na mostach (naiwny zakres zwiadu): {dl(przy_wodzie):.0f} km = {dl(przy_wodzie)/36:.1f} h lotu")
print(f"  wsie z pojedynczym punktem awarii: {sum(1 for w,z in per_wies.items() if z)} z {len(wsie)}")

# --- przybliżona trasa lotu z bazy (najbliższy sąsiad po skupiskach odcinków), lot po prostej między skupiskami ---
def trasa(krawedzie, baza):
    S_ = nx.Graph(); S_.add_edges_from(krawedzie)
    skupiska = [(set(c), dl(S_.subgraph(c).edges)) for c in nx.connected_components(S_)]
    poz, km = baza, 0.0
    while skupiska:
        i, (c, wzdluz) = min(enumerate(skupiska), key=lambda x: min(hav(poz, n) for n in x[1][0]))
        wejscie = min(c, key=lambda n: hav(poz, n)); km += hav(poz, wejscie) / 1000 + wzdluz
        poz = max(c, key=lambda n: hav(wejscie, n)); skupiska.pop(i)
    return km + hav(poz, baza) / 1000
UZYTECZNE_MIN = 18  # 25 min lotu minus 25–30% rezerwy (patrz ustalenia.md §9); skalibrować testem
baza = wsie["Cisna"]  # założenie: dok przy remizie w Cisnej (do weryfikacji)
for nazwa, zb in [("krytyczne przy potokach", kryt_woda), ("wszystkie przy potokach", przy_wodzie)]:
    km = trasa(zb, baza)
    print(f"  trasa z Cisnej: {nazwa}: {km:.0f} km ≈ {km/36*60:.0f} min lotu przy 10 m/s ≈ {math.ceil(km/36*60/UZYTECZNE_MIN)} lotów ({UZYTECZNE_MIN} min użytecznych z 25 min, reszta to rezerwa)")
