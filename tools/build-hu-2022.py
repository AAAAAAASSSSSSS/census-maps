#!/usr/bin/env python3
"""Hungary 2022 census -> the three GeoJSON files that geo2topo.py (or pack.js) turns into data/hu/2022/*.json

Inputs (keep them in raw/, which is not committed):
  geoBoundaries-HUN-ADM2-districts.geojson        198 district shapes (174 districts + 23 Budapest districts + one stale one, see below)
  religion_ethnicity_level1_2_3.xlsx              KSH census database table WBS003: country, regions, counties
  religion_ethnicity_level3_4.xlsx                the same table: Budapest, Budapest districts, counties, districts (járás)
  religion_ethnicity_budapest_pest_central_transdanubia.xlsx   the same table down to settlements: Budapest, Pest, Fejér, Komárom-Esztergom, Veszprém
  religion_ethnicity_west_south_transdanubia.xlsx              the same table down to settlements: Győr-Moson-Sopron, Vas, Zala, Baranya, Somogy, Tolna
  religion_ethnicity_northernhungary_north_south_greatplain.xlsx   the same table down to settlements: Borsod-Abaúj-Zemplén, Heves, Nógrád, Hajdú-Bihar, Jász-Nagykun-Szolnok,
                                                               Szabolcs-Szatmár-Bereg, Bács-Kiskun, Békés, Csongrád-Csanád
  (all tables come from https://nepszamlalas2022.ksh.hu/ ; the geoBoundaries ADM0/ADM1/ADM3 files are not used, see "Shapes")

Usage (from the repo root; needs `pip install openpyxl numpy`):
  python3 tools/build-hu-2022.py raw build
  python3 tools/geo2topo.py build/hu_districts.geojson data/hu/2022/districts.json
  python3 tools/geo2topo.py build/hu_counties.geojson  data/hu/2022/counties.json
  python3 tools/geo2topo.py build/hu_country.geojson   data/hu/2022/country.json

Levels. unit = district (járás, 174) + the 23 districts of Budapest; region = county (19 + Budapest); country.
Settlement figures (the `b` breakdown of every district except the Budapest districts) are shown by the "Select area" card.

Counts only (p, e, r); percentages and majorities are calculated in the browser. KSH marks values withheld for data protection with "…"
(stored here as -1); an empty cell means zero.
Categories (order = data/hu/2022/meta.json):
  ethnicity: Hungarian, Roma, German, Slovak, Croatian, Ukrainian, Romanian, Serbian, Polish, Ruthenian, Greek, Bulgarian, Armenian, Slovene (largest first
             after Hungarian), Other, No answer.  People could declare more than one ethnic identity, so the groups add up to MORE than the population.
  religion:  Roman Catholic, Greek Catholic, Catholic (other or unspecified) = KSH "Catholic" minus the two, Reformed, Evangelical (Lutheran), Orthodox Christian,
             Other Christian, Jewish, Other religious community, No religious community, No answer.  These are exclusive and add up to the population.

Shapes. Everything is derived from the ADM2 district shapes, because they are the only ones that share their borders exactly (checked: no gaps, no overlaps):
  - the geoBoundaries ADM1 file has no Budapest (it is inside Pest) and its vertices do not match ADM2, so counties are dissolved from the districts instead;
  - the country is the dissolve of all districts (same outline as the district map);
  - ADM3 has broken characters in its names (and 3,357 shapes), so it cannot be matched to the census.
  - ADM2 still has the former Polgárdi district; the 2022 census has no such district (Polgárdi belongs to Székesfehérvár district), so the two shapes are merged.
"""
import json, sys, os, re, difflib, unicodedata
from collections import defaultdict
import openpyxl

raw, out = (sys.argv + ['raw', 'build'])[1:3]
os.makedirs(out, exist_ok=True)

# ---------------------------------------------------------------- shape helpers: dissolve polygons whose shared borders have identical vertices
def polys_of(g): return g['coordinates'] if g['type'] == 'MultiPolygon' else [g['coordinates']]
def area2(r): return sum(r[i][0] * r[i + 1][1] - r[i + 1][0] * r[i][1] for i in range(len(r) - 1))
def key(p): return (round(p[0], 7), round(p[1], 7))
def pip(pt, r):
    x, y = pt; c = False
    for i in range(len(r) - 1):
        x1, y1 = r[i]; x2, y2 = r[i + 1]
        if (y1 > y) != (y2 > y) and x < (x2 - x1) * (y - y1) / (y2 - y1) + x1: c = not c
    return c
def dissolve(geoms):
    """Cancel the edges that two polygons have in common (one runs a->b, the other b->a), chain what is left into rings."""
    E = defaultdict(int)
    for g in geoms:
        for poly in polys_of(g):
            for k, r in enumerate(poly):
                r = [key(p) for p in r]
                if r[0] != r[-1]: r.append(r[0])
                if (area2(r) > 0) != (k == 0): r = r[::-1]            # outer rings counter-clockwise, holes clockwise
                for p, q in zip(r, r[1:]):
                    if p != q: E[(p, q)] += 1
    nxt = defaultdict(list)
    for (p, q), c in E.items():
        for _ in range(c - E.get((q, p), 0)): nxt[p].append(q)
    rings = []
    while nxt:
        p0 = next(iter(nxt)); ring = [p0]; p = p0
        while True:
            q = nxt[p].pop()
            if not nxt[p]: del nxt[p]
            ring.append(q); p = q
            if p == p0: break
            assert p in nxt, f'open ring at {p}: the shared borders do not match exactly'
        rings.append(ring)
    polys = [[r] for r in rings if area2(r) > 0]
    for h in (r for r in rings if area2(r) < 0):
        P = next(P for P in polys if pip(h[0], P[0])); P.append(h)
    return {'type': 'MultiPolygon', 'coordinates': [[[list(p) for p in r] for r in P] for P in polys]}

# ---------------------------------------------------------------- read the KSH tables (one column per area, one row per category)
def num(v):
    if v is None or (isinstance(v, str) and v.strip() == ''): return 0       # empty cell: zero / cannot occur
    if v == '…': return -1                                                   # withheld for data protection
    if isinstance(v, (int, float)): return int(v)
    if isinstance(v, str) and v.strip().isdigit(): return int(v)
    raise ValueError(f'unexpected cell {v!r}')
def read(f):
    rows = list(openpyxl.load_workbook(os.path.join(raw, f), read_only=True)['Adattábla'].iter_rows(values_only=True))
    labels = [r[0] for r in rows[3:]]
    return [(name, {l: num(r[j + 1]) for l, r in zip(labels, rows[3:])}) for j, name in enumerate(rows[2][1:])]

ETH = [('Magyar', 'Magyar nemzetiségű'), ('Roma', 'Cigány (roma) nemzetiségű'), ('German', 'Német nemzetiségű'), ('Slovak', 'Szlovák nemzetiségű'),
       ('Croatian', 'Horvát nemzetiségű'), ('Ukrainian', 'Ukrán nemzetiségű'), ('Romanian', 'Román nemzetiségű'), ('Serbian', 'Szerb nemzetiségű'),
       ('Polish', 'Lengyel nemzetiségű'), ('Ruthenian', 'Ruszin nemzetiségű'), ('Greek', 'Görög nemzetiségű'), ('Bulgarian', 'Bolgár nemzetiségű'),
       ('Armenian', 'Örmény nemzetiségű'), ('Slovene', 'Szlovén nemzetiségű'), ('Other', 'Más nemzetiségű'), ('No answer', 'Nem válaszolt a nemzetiségi kérdésekre')]
def vec_e(c): return [c[l] for _, l in ETH]
def vec_r(c):
    cath, rc, gc = c['Katolikus'], c['Katolikuson belül római katolikus'], c['Katolikuson belül görögkatolikus']
    rest = -1 if min(cath, rc, gc) < 0 else cath - rc - gc
    assert rest >= -1 and (rest >= 0 or min(cath, rc, gc) < 0), 'Roman + Greek Catholic exceed all Catholics'
    return [rc, gc, rest, c['Református'], c['Evangélikus'], c['Ortodox keresztény'], c['Más keresztény felekezet'], c['Izraelita'],
            c['Más vallási közösséghez, felekezethez tartozó'], c['Vallási közösséghez, felekezethez nem tartozó'], c['Nem válaszolt']]
def rec(name, c):
    assert c['Vallás'] == c['Nemzetiség'] and c['Vallás'] >= 0, f'{name}: population missing or tables differ'
    d = dict(p=c['Vallás'], e=vec_e(c), r=vec_r(c))
    if min(d['r']) >= 0: assert sum(d['r']) == d['p'], f'{name}: religion does not add up'
    return d

def lv(n):
    return ('county' if n.endswith('vármegye') else 'district' if n.endswith('járás') else 'ker' if re.fullmatch(r'Budapest \d\d\. ker\.', n)
            else 'bp' if n == 'Budapest' else 'region' if n.endswith('régió') else 'country' if n == 'Magyarország' else 'settle')
def cname(n): return 'Budapest' if n == 'Budapest' else n[:-len(' vármegye')]
ROM = ['I','II','III','IV','V','VI','VII','VIII','IX','X','XI','XII','XIII','XIV','XV','XVI','XVII','XVIII','XIX','XX','XXI','XXII','XXIII']
def kname(n): return 'Budapest ' + ROM[int(n[9:11]) - 1]
UNALLOC = 'Budapest kerületre nem bontható adatai'          # "Budapest data that cannot be split into districts": an empty column in every table (nobody is unallocated)

country = rec('Magyarország', dict(read('religion_ethnicity_level1_2_3.xlsx'))['Magyarország'])
counties, districts, order = {}, {}, []        # districts: (county, name) -> record
cur = None
for n, c in read('religion_ethnicity_level3_4.xlsx'):
    if n == UNALLOC: assert not any(c.values()); continue
    L = lv(n)
    if L == 'bp': cur = 'Budapest'; counties[cur] = rec(n, c)
    elif L == 'county': cur = cname(n); counties[cur] = rec(n, c)
    elif L == 'ker': districts[(cur, kname(n))] = rec(n, c); order.append((cur, kname(n)))
    elif L == 'district': districts[(cur, n[:-len(' járás')])] = rec(n, c); order.append((cur, n[:-len(' járás')]))
    else: raise ValueError(n)
assert len(counties) == 20 and len(districts) == 197, (len(counties), len(districts))
# the county table of level 1-2-3 must agree with level 3-4
for n, c in read('religion_ethnicity_level1_2_3.xlsx'):
    if lv(n) == 'county': assert rec(n, c) == counties[cname(n)], n

# settlements
settle, nset = defaultdict(list), 0
for f in ('religion_ethnicity_budapest_pest_central_transdanubia.xlsx', 'religion_ethnicity_west_south_transdanubia.xlsx',
          'religion_ethnicity_northernhungary_north_south_greatplain.xlsx'):
    cur_c = cur_d = None
    for n, c in read(f):
        if n == UNALLOC: assert not any(c.values()); continue
        L = lv(n)
        if L == 'bp': cur_c = 'Budapest'; cur_d = None
        elif L == 'county': cur_c = cname(n); cur_d = None
        elif L == 'ker':
            assert rec(n, c) == districts[(cur_c, kname(n))], n         # Budapest districts are listed again here: same figures
        elif L == 'district': cur_d = (cur_c, n[:-len(' járás')]); assert cur_d in districts, cur_d
        elif L == 'settle':
            assert cur_d, n
            s = rec(n, c); s['n'] = n; settle[cur_d].append(s); nset += 1
        else: raise ValueError(n)
assert len(settle) == 174, len(settle)                       # every district except the 23 Budapest districts
print(f'{len(counties)} counties, {len(districts)} districts, {nset} settlements in {len(settle)} districts, population {country["p"]:,}')

# ---------------------------------------------------------------- consistency between the levels
def tot(items):
    return [sum(max(0, x[k]) if isinstance(x[k], int) else 0 for x in items) for k in ('p',)]
def check_sum(parent, kids, what):
    for k in ('p', 'e', 'r'):
        a = parent[k] if k != 'p' else [parent['p']]
        for i, v in enumerate(a):
            vs = [(x[k] if k != 'p' else [x['p']])[i] for x in kids]
            if v < 0 or min(vs) < 0: continue               # withheld somewhere: cannot be compared
            assert v == sum(vs), f'{what}: {k}[{i}] {v} != {sum(vs)}'
check_sum(country, list(counties.values()), 'country')
for cn, c in counties.items(): check_sum(c, [d for (cc, _), d in districts.items() if cc == cn], cn)
for dk, ss in settle.items(): check_sum(districts[dk], ss, '/'.join(dk))
wh = sum(1 for d in districts.values() for v in d['e'] + d['r'] if v < 0), sum(1 for ss in settle.values() for s in ss for v in s['e'] + s['r'] if v < 0)
print('withheld (-1) values: districts', wh[0], ', settlements', wh[1])
print('ethnic groups add up to', sum(max(0, v) for v in country['e']), 'for a population of', country['p'], '(more than one identity allowed)')

# ---------------------------------------------------------------- shapes: ADM2 -> census districts
nq = lambda s: unicodedata.normalize('NFD', s).encode('ascii', 'ignore').decode().lower()
shapes = {f['properties']['shapeName']: f['geometry'] for f in json.load(open(os.path.join(raw, 'geoBoundaries-HUN-ADM2-districts.geojson'), encoding='utf-8'))['features']}
assert len(shapes) == 198
SHAPE_NAME_FIX = {'Pannonhalm': 'Pannonhalma', 'Kunszentmártonj': 'Kunszentmárton'}   # names cut short / misspelt in the shape file
geom, used, disp = {}, set(), {}      # disp: the district's name for the site ("Ajkai járás" -> "Ajka"; irregular ones such as Egri -> Eger come from the shape file)
for (cn, dn) in districts:
    if cn == 'Budapest':
        s = dn.split()[1] + '. kerület'; assert s in shapes, s; disp[(cn, dn)] = dn
    else:
        stem = dn[:-1] if dn.endswith('i') else dn                  # "Ajkai" -> "Ajka"; a few shape names are cut short ("Pannonhalm") or misspelt ("Kunszentmartonj")
        cand = sorted(((difflib.SequenceMatcher(None, nq(stem), nq(x)).ratio(), x) for x in shapes if 'kerület' not in x), reverse=True)
        assert cand[0][0] > 0.8 and cand[0][0] - cand[1][0] > 0.1, f'unclear match for {dn}: {cand[:2]}'
        s = cand[0][1]; disp[(cn, dn)] = SHAPE_NAME_FIX.get(s, s)
    assert s not in used; used.add(s); geom[(cn, dn)] = shapes[s]
leftover = set(shapes) - used
assert leftover == {'Polgard'}, leftover                             # the former Polgárdi district: part of Székesfehérvár district in 2022
geom[('Fejér', 'Székesfehérvári')] = dissolve([geom[('Fejér', 'Székesfehérvári')], shapes['Polgard']])
assert len(geom[('Fejér', 'Székesfehérvári')]['coordinates']) == 1, 'Polgárdi does not touch Székesfehérvár'

# ---------------------------------------------------------------- GeoJSON for geo2topo.py
def feat(g, **p): return {'type': 'Feature', 'properties': p, 'geometry': g}
def brk(items): return [dict(n=n, p=d['p'], e=d['e'], r=d['r']) for n, d in items]
D = [feat(geom[k], n=disp[k], j=k[0], p=districts[k]['p'], e=districts[k]['e'], r=districts[k]['r'],
          **({'b': brk((s['n'], s) for s in settle[k])} if k in settle else {})) for k in order]
C = []
for cn, c in counties.items():
    ks = [k for k in order if k[0] == cn]
    C.append(feat(dissolve([geom[k] for k in ks]), n=cn, p=c['p'], e=c['e'], r=c['r'], b=brk((disp[k], districts[k]) for k in ks)))
H = [feat(dissolve([geom[k] for k in order]), n='Hungary', p=country['p'], e=country['e'], r=country['r'], b=brk(counties.items()))]
for name, fs in (('districts', D), ('counties', C), ('country', H)):
    json.dump({'type': 'FeatureCollection', 'features': fs}, open(os.path.join(out, f'hu_{name}.geojson'), 'w', encoding='utf-8'), ensure_ascii=False, separators=(',', ':'))
    print(name, len(fs), 'features,', sum(len(polys_of(f['geometry'])) for f in fs), 'polygons')
