#!/usr/bin/env python3
"""Greece 2021 census -> data/gr/2021/*.json (numpy + openpyxl only).

Inputs (put them in raw/ or give the paths):
  A1602_SAM03_TB_DC_00_2021_C01_F_GR.xlsx   ELSTAT table "Γ01 - permanent population by sex and age group", from the whole country down to settlements
  geoBoundaries-GRC-ADM3.geojson            the 326 municipality polygons

Usage:  python3 tools/build-gr-2021.py [xlsx] [geojson]
Greece has no ethnicity or religion question, so every area has population only (e = r = null).
The geoBoundaries file still has the 2011 municipalities. Greece split a few of them in 2019 (Corfu, Cephalonia, Servia-Velventos, Lesbos, Samos,
Mylopotamos); the census uses the new ones. Where the polygon is older than the census the census municipalities are added together onto that polygon.
"""
import sys, os, re, json, difflib, collections
import numpy as np, openpyxl
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from elot import elot
from topo_lite import union, topology, shoelace

xlsx = sys.argv[1] if len(sys.argv) > 1 else 'raw/A1602_SAM03_TB_DC_00_2021_C01_F_GR.xlsx'
gjs = sys.argv[2] if len(sys.argv) > 2 else 'raw/geoBoundaries-GRC-ADM3.geojson'
OUT = os.path.join(os.path.dirname(os.path.abspath(__file__)), '..', 'data', 'gr', '2021'); os.makedirs(OUT, exist_ok=True)

# ---------------------------------------------------------------- census table
rows = [r for r in list(openpyxl.load_workbook(xlsx, read_only=True).active.iter_rows(values_only=True))[6:] if r[0] is not None]
lvl = collections.defaultdict(list)
for r in rows: lvl[r[0]].append((str(r[1]), r[2].strip(), int(r[3])))      # (code, Greek name, both sexes total)
country_p = lvl[0][0][2]
PERI = {'111': 'East Macedonia and Thrace', '112': 'Central Macedonia', '121': 'Western Macedonia', '122': 'Epirus', '231': 'Thessaly', '232': 'Central Greece', '241': 'Ionian Islands',
        '242': 'Western Greece', '243': 'Peloponnese', '351': 'Attica', '461': 'North Aegean', '462': 'South Aegean', '471': 'Crete'}
RU = {'11101': 'Rhodope', '11102': 'Drama', '11103': 'Evros', '11104': 'Thasos', '11105': 'Kavala', '11106': 'Xanthi', '11207': 'Thessaloniki', '11208': 'Imathia', '11209': 'Kilkis', '11210': 'Pella', '11211': 'Pieria',
      '11212': 'Serres', '11213': 'Chalkidiki', '11299': 'Mount Athos', '12114': 'Kozani', '12115': 'Grevena', '12116': 'Kastoria', '12117': 'Florina', '12218': 'Ioannina', '12219': 'Arta', '12220': 'Thesprotia',
      '12221': 'Preveza', '23122': 'Larissa', '23123': 'Karditsa', '23124': 'Magnesia', '23125': 'Sporades', '23126': 'Trikala', '23227': 'Phthiotis', '23228': 'Boeotia', '23229': 'Euboea', '23230': 'Evrytania',
      '23231': 'Phocis', '24132': 'Corfu', '24133': 'Zakynthos', '24134': 'Ithaca', '24135': 'Cephalonia', '24136': 'Lefkada', '24237': 'Achaea', '24238': 'Aetolia-Acarnania', '24239': 'Elis', '24340': 'Arcadia',
      '24341': 'Argolis', '24342': 'Corinthia', '24343': 'Laconia', '24344': 'Messenia', '35145': 'Central Athens', '35146': 'North Athens', '35147': 'West Athens', '35148': 'South Athens', '35149': 'East Attica',
      '35150': 'West Attica', '35151': 'Piraeus', '35152': 'Islands', '46153': 'Lesbos', '46154': 'Ikaria', '46155': 'Lemnos', '46156': 'Samos', '46157': 'Chios', '46258': 'Syros', '46259': 'Andros', '46260': 'Thira',
      '46261': 'Kalymnos', '46262': 'Karpathos-Kasos', '46263': 'Kea-Kythnos', '46264': 'Kos', '46265': 'Milos', '46266': 'Mykonos', '46267': 'Naxos', '46268': 'Paros', '46269': 'Rhodes', '46270': 'Tinos',
      '47171': 'Heraklion', '47172': 'Lasithi', '47173': 'Rethymno', '47174': 'Chania'}
assert {c for c, _, _ in lvl[4]} == set(RU) and {c for c, _, _ in lvl[3]} == set(PERI)

# ---------------------------------------------------------------- municipality polygons <-> census municipalities
g = json.load(open(gjs, encoding='utf-8'))
gb = [(f['properties']['shapeName'], f['properties']['shapeID'], f['geometry']) for f in g['features']]
norm = lambda s: re.sub(r'[^a-z]', '', s.lower().replace('ph', 'f').replace('ks', 'x'))
muni = [(c, n.replace('ΔΗΜΟΣ ', '').replace('(ΑΥΤΟΔΙΟΙΚΗΤΟ)', '').strip(), p) for c, n, p in lvl[5]]
cand = sorted(((difflib.SequenceMatcher(None, norm(elot(n)), norm(b[0])).ratio(), c, i) for c, n, p in muni for i, b in enumerate(gb)), reverse=True)
assign, used = {}, set()
for sc, c, i in cand:
    if sc >= 0.8 and c not in assign and i not in used: assign[c] = i; used.add(i)
by = {}
for i, b in enumerate(gb): by.setdefault(b[0], []).append(i)
MAN = {'1120713': 'Chalkidona', '1120714': 'Oraiokastro#0', '1120803': 'Naousa', '1121201': 'Serres', '1129901': 'Mount Anthos', '1211402': 'Servia-Velventos', '1211405': 'Servia-Velventos', '1211602': 'Orestida',
 '1211703': 'Prespes', '1221802': 'North Tzoumerka', '1221901': 'Arta', '1221903': 'Central Tzoumerka', '1222003': 'Filiates', '2312201': 'Larissa', '2312205': 'Tempi', '2312303': 'Lake Plastiras', '2312306': 'Sofades',
 '2312404': 'South Pelion', '2312601': 'Trikala', '2322701': 'Lamia', '2322704': 'Molos-Agios Konstantinos', '2322801': 'Livadeia', '2322802': 'Aliartos', '2322804': 'Thebes', '2323002': 'Agrafa', '2323101': 'Delphi',
 '2323102': 'Dorida', '2413201': 'Corfu', '2413202': 'Corfu', '2413203': 'Corfu', '2413401': 'Ithaca', '2413501': 'Cephalonia', '2413502': 'Cephalonia', '2413503': 'Cephalonia', '2423701': 'Patras', '2423703': 'West Achaea',
 '2423801': 'Missolonghi', '2423904': 'Olympia', '2434002': 'North Kynouria', '2434005': 'South Kynouria', '2434103': 'Epidaurus', '2434201': 'Corinth', '2434203': 'Loutraki-Agioi Theodoroi', '2434206': 'Sikyona',
 '2434301': 'Sparta', '2434302': 'East Mani', '2434402': 'West Mani', '3514501': 'Athens', '3514508': 'Filadelfeia-Chalkidona', '3514604': 'Irakleio', '3514704': 'Egaleo', '3514901': 'Acharnes', '3514912': 'Spata-Artemida',
 '3515004': 'Megara', '3515101': 'Pireas', '3515203': 'Aegina', '3515206': 'Spetses', '4615301': 'Lesbos', '4615302': 'Lesbos', '4615501': 'Lemnos', '4615601': 'Samos', '4615602': 'Samos', '4615702': 'Psara',
 '4615703': 'Oinousses', '4625801': 'Syros', '4626001': 'Santorini', '4626202': 'Kasos', '4626302': 'Kithnos', '4626601': 'Mikonos', '4626702': 'Naxos and Lesser Cyclades', '4626901': 'Rhodes', '4626902': 'Kastellorizo',
 '4626905': 'Halki', '2322901': 'Chalcis', '4717203': 'Lasithi Plateau', '4717304': 'Mylopotamos', '4717401': 'Chania', '4717407': 'Sfakia', '4717101': 'Heraklion'}
def outer_area(i):
    geo = gb[i][2]; P = [geo['coordinates']] if geo['type'] == 'Polygon' else geo['coordinates']
    return sum(abs(shoelace(np.array(p[0], float))) for p in P)
for c, nm in MAN.items():
    ids = by[nm.split('#')[0]]
    assign[c] = max(ids, key=outer_area) if '#' in nm else ids[0]       # two polygons are called Oraiokastro: the big one is the municipality, the tiny one a piece of it
assert set(assign) == {c for c, _, _ in muni}, 'census municipality without polygon'
SLIVER = [i for i, b in enumerate(gb) if b[0] == 'Oraiokastro' and i != assign['1120714']]   # a tiny piece labelled Oraiokastro: kept as part of Oraiokastro
assert len(SLIVER) == 1
grp = collections.defaultdict(list)                                      # polygon -> census municipalities
for c, n, p in muni: grp[assign[c]].append(c)
assert set(grp) | set(SLIVER) == set(range(len(gb)))

# ---------------------------------------------------------------- English names
FIX = {'Komotinis': 'Komotini', 'Arrianon': 'Arriana', 'Iasmou': 'Iasmos', 'Maronias-Sapon': 'Maroneia-Sapes', 'Dramas': 'Drama', 'Doxatou': 'Doxato', 'Kato Nevrokopiou': 'Kato Nevrokopi', 'Paranestiou': 'Paranesti',
 'Prosotsanis': 'Prosotsani', 'Orestiadas': 'Orestiada', 'Samothrakis': 'Samothrace', 'Soufliou': 'Soufli', 'Thassou': 'Thasos', 'Kavalas': 'Kavala', 'Nestou': 'Nestos', 'Pangeou': 'Pangaio', 'Xanthis': 'Xanthi',
 'Avdiron': 'Avdira', 'Mykis': 'Myki', 'Topirou': 'Topeiros', 'Didymoteichou': 'Didymoteicho', 'Mount Anthos': 'Mount Athos', 'Mikonos': 'Mykonos', 'Kithnos': 'Kythnos', 'Pydna - Kolindros': 'Pydna-Kolindros',
 'Chalcis': 'Chalcis', 'Pireas': 'Piraeus', 'Egaleo': 'Egaleo', 'Heraklion': 'Heraklion', 'Irakleio': 'Irakleio', 'Alexandroupolis': 'Alexandroupoli', 'Naxos and Lesser Cyclades': 'Naxos and Lesser Cyclades'}
SPLIT = {'1211402': 'Velventos', '1211405': 'Servia', '2413201': 'Central Corfu and the Diapontian Islands', '2413202': 'North Corfu', '2413203': 'South Corfu', '2413501': 'Argostoli', '2413502': 'Lixouri',
         '2413503': 'Sami', '4615301': 'Mytilene', '4615302': 'West Lesbos', '4615601': 'East Samos', '4615602': 'West Samos', '4717304': 'Anogeia', '4717305': 'Mylopotamos'}
pname = lambda i: FIX.get(gb[i][0], gb[i][0])
cname = {c: SPLIT.get(c, pname(assign[c])) for c, n, p in muni}

# settlements (level 8) -> by municipality (first 7 digits of the code)
ART = re.compile(r',\s*(ο|η|το|οι|τα|αι)(?=\s|\)|$)')                   # "Κομοτηνή,η" = the article of the name, also inside "Α,η - Β,ο" and "Α,το (Β,η)"
def sname(s): return elot(re.sub(r'\s+', ' ', ART.sub('', s)).strip())
setl = collections.defaultdict(list)
for c, n, p in lvl[8]: setl[c[:7]].append({'n': sname(n), 'p': p, 'e': None, 'r': None})
srt = lambda L: sorted(L, key=lambda x: x['n'])
pop_c = {c: p for c, n, p in muni}

# ---------------------------------------------------------------- geometry
polys = []                                                               # per gb index: list of polygons (rings of lon/lat)
for n, s, geo in gb:
    P = [geo['coordinates']] if geo['type'] == 'Polygon' else geo['coordinates']
    polys.append([[np.array(r, float) for r in p] for p in P])
allp = np.vstack([r for P in polys for p in P for r in p])
uniq, inv = np.unique(np.round(allp, 6), axis=0, return_inverse=True); inv = inv.reshape(-1)
pos = 0; P2 = []
for P in polys:
    out = []
    for p in P:
        rings = []
        for k, r in enumerate(p):
            ids = inv[pos:pos + len(r)]; pos += len(r)
            if ids[0] != ids[-1]: ids = np.append(ids, ids[0])
            a = shoelace(uniq[ids])
            if (k == 0 and a < 0) or (k > 0 and a > 0): ids = ids[::-1]
            rings.append(ids)
        out.append(dict(rings=rings))
    P2.append(out)
FILL = 5e-4                                                               # deg2 (about 4 km2): smaller holes in the merged levels are gaps between neighbouring polygons, not lakes
poly_of = lambda i: P2[i] + (P2[SLIVER[0]] if i == assign['1120714'] else [])
bbox = [round(float(uniq[:, 0].min()) - .01, 3), round(float(uniq[:, 1].min()) - .01, 3), round(float(uniq[:, 0].max()) + .01, 3), round(float(uniq[:, 1].max()) + .01, 3)]
LL = np.round(uniq, 6)

# ---------------------------------------------------------------- features
ru_of = lambda c: c[:5]; pe_of = lambda c: c[:3]
mf, mg, mprops = [], [], []
for i in sorted(grp, key=lambda i: min(grp[i])):
    cs = sorted(grp[i]); b = srt([s for c in cs for s in setl[c]])
    ru = ru_of(cs[0]); assert len({ru_of(c) for c in cs}) == 1
    mprops.append({'n': pname(i), 'j': RU[ru], 'p': sum(pop_c[c] for c in cs), 'e': None, 'r': None, 'b': b})
    mg.append(poly_of(i))
mgeo = [[q['rings'] for q in P] for P in mg]
byru = collections.defaultdict(list); byper = collections.defaultdict(list)
for i, P in zip(sorted(grp, key=lambda i: min(grp[i])), mg):
    c0 = min(grp[i]); byru[ru_of(c0)] += P; byper[pe_of(c0)] += P
rprops = []; rgeo = []
for c, n, p in lvl[4]:
    members = [(cc, nn, pp) for cc, nn, pp in muni if ru_of(cc) == c]
    rprops.append({'n': RU[c], 'j': PERI[c[:3]], 'p': p, 'e': None, 'r': None, 'b': srt([{'n': cname[cc], 'p': pp, 'e': None, 'r': None} for cc, nn, pp in members])})
    rgeo.append(union(byru[c], uniq, FILL))
pprops = []; pgeo = []
for c, n, p in lvl[3]:
    pprops.append({'n': PERI[c], 'p': p, 'e': None, 'r': None, 'b': srt([{'n': RU[cc], 'p': pp, 'e': None, 'r': None} for cc, nn, pp in lvl[4] if cc[:3] == c])})
    pgeo.append(union(byper[c], uniq, FILL))
allm = [q for P in byper.values() for q in P]
cprops = [{'n': 'Greece', 'p': country_p, 'e': None, 'r': None, 'b': srt([{'n': PERI[c], 'p': p, 'e': None, 'r': None} for c, n, p in lvl[3]])}]
cgeo = [union(allm, uniq, FILL)]

for nm, geo in (('regional units', rgeo), ('peripheries', pgeo), ('country', cgeo)):
    print(nm, 'parts:', collections.Counter(len(x) for x in geo).most_common(6), 'holes:', sum(len(p) - 1 for x in geo for p in x))
W = lambda f, t: json.dump(t, open(os.path.join(OUT, f), 'w', encoding='utf-8'), ensure_ascii=False, separators=(',', ':'))
W('municipalities.json', topology(mgeo, mprops, bbox, LL))
W('regional-units.json', topology(rgeo, rprops, bbox, LL))
W('peripheries.json', topology(pgeo, pprops, bbox, LL))
W('country.json', topology(cgeo, cprops, bbox, LL))
print(len(mprops), 'municipality shapes;', sum(x['p'] for x in mprops), 'people in municipalities;', country_p, 'in the country')
