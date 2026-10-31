#!/usr/bin/env python3
"""Albania 2023 census -> the four GeoJSON files that pack.js turns into data/al/2023/*.json

Inputs (keep them in raw/, which is not committed):
  albania_population.xlsx        INSTAT PxWeb (databaza.instat.gov.al:8083/pxweb/sq/DST): resident population of every
                                 municipality ("BASHKIA ...") and of every administrative unit under it (373), one column each
  albania_ethnic.xlsx            INSTAT PxWeb: ethnicity by county (qark), 12 counties
  albania_religion.xlsx          INSTAT PxWeb: religion by county
  alb_tab7.xlsx                  INSTAT census publication, Tab. 7 (bilingual): population by municipality - only used for the
                                 municipality names (the PxWeb headers are ALL CAPS) and as a second check of the municipality totals
  geoBoundaries-ALB-ADM3.geojson 373 shapes = the 373 administrative units (njesi administrative)

Usage (from the repo root; needs `pip install openpyxl shapely scipy numpy`, and `cd tools && npm install`):
  python3 tools/build-al-2023.py raw build
  cd tools
  node pack.js ../build/al_units.geojson          ../data/al/2023/units.json
  node pack.js ../build/al_municipalities.geojson ../data/al/2023/municipalities.json
  node pack.js ../build/al_counties.geojson       ../data/al/2023/counties.json
  node pack.js ../build/al_country.geojson        ../data/al/2023/country.json

Levels. Administrative unit (373) -> municipality (61) -> county (12) -> country. The census tables give ethnicity and religion ONLY for
the counties (the official county/municipality publications of INSTAT have no ethnicity or religion table below the county, checked
in the table of contents of the 12 publications "Prefectures / Municipalities"), so the units and municipalities have p only (e = r = null =
"No data" in the ethnic / religious modes). Every upper level is the union of the level under it (as in the other countries).

Which municipality / county a unit belongs to comes from the ORDER of the PxWeb population table: columns run county by county,
municipality by municipality (BASHKIA header, then its units). The county split is verified: the municipalities of each county add up
exactly to the county total of the ethnicity / religion tables.

Shapes <-> units. Names are used where they are unique and equal (after removing accents); the geoBoundaries names have typos
(e.g. "Rashbull" / "Rrashbull", "Vau-Dejes" / "Vau i Dejes") and 22 units are paired through ALIASES below. 9 names occur in several
municipalities (Klos, Fierze x3, Mollas, Shushice, Golem, Selite, Novosele, Kolsh/Kolc, Dajc) and 8 units are called "Qender ..." in the table
but just "Qender" in the shapes: these are decided by distance to the centre of the municipality formed by the units that matched
unambiguously (Hungarian assignment, repeated until stable). The result was checked by hand against the real positions (e.g. Fierze in
Tropoje = the Fierze dam at 42.3N, Klos in Dibër = 41.5N). "Dimal" (unit) = the shape "Ura Vajgurore"; "Qender Korce" = the shape
"Qender Bulgarec"; "Hore Vranisht" = "Vranisht"; "Novosele" (Kolonje) = "Piskal-Novosele".

Names. n = the INSTAT table spelling (units, counties) or Tab. 7 (municipalities; "Fushë Arrës" is corrected to the official Fushë-Arrëz).
Duplicate unit names are told apart by `j` (the county).

Categories (order = data/al/2023/meta.json)
  ethnicity: Albanian, Greek, Macedonian, Montenegrin, Aromanian, Roma, Egyptian, Bosniak, Serbian, Bulgarian, Mixed, Other, then
             No ethnicity, Prefer not to answer, Not available
  religion:  Muslim, Muslim - Bektashi, Catholic, Orthodox, Evangelical (Protestant), Believers (denomination unspecified), Atheist, Other,
             then Prefer not to answer, Not available
Only counts are stored. No value is withheld in these tables ("withheld": false in meta.json).
"""
import json, sys, os, re, unicodedata, collections
import numpy as np
import openpyxl
from scipy.optimize import linear_sum_assignment
from shapely.geometry import shape, mapping, Polygon, MultiPolygon
from shapely.geometry.polygon import orient
from shapely.ops import unary_union
from shapely import make_valid

raw, out = (sys.argv + ['raw', 'build'])[1:3]
os.makedirs(out, exist_ok=True)
fold = lambda s: re.sub(r'\s+', ' ', ''.join(c for c in unicodedata.normalize('NFD', s) if not unicodedata.combining(c)).lower().replace('-', ' ')).strip()

# ---------------------------------------------------------------- population: municipalities and units, in table order
rows = list(openpyxl.load_workbook(os.path.join(raw, 'albania_population.xlsx'), read_only=True).active.iter_rows(values_only=True))
hdr, val = rows[2], rows[4]
assert val[2] == '2023' and hdr[3] and str(hdr[3]).startswith('BASHKIA')
munis = []
for i in range(3, len(hdr)):
    h = hdr[i]
    if not h: continue
    if h.startswith('BASHKIA'): munis.append(dict(raw=h.strip(), p=int(val[i]), units=[]))
    else: munis[-1]['units'].append(dict(n=h.strip(), p=int(val[i])))
assert len(munis) == 61 and sum(len(m['units']) for m in munis) == 373
for m in munis: assert m['p'] == sum(u['p'] for u in m['units']), m['raw']

t7 = [r for r in openpyxl.load_workbook(os.path.join(raw, 'alb_tab7.xlsx'), read_only=True).active.iter_rows(values_only=True) if r[0] and isinstance(r[1], int)]
assert t7[0][0].startswith('Gjithsej') and len(t7) == 62
for m, r in zip(munis, t7[1:]):
    assert m['p'] == r[1], (m['raw'], m['p'], r[1])           # Tab. 7 lists the municipalities in the same order and with the same totals
    m['n'] = 'Fushë-Arrëz' if r[0] == 'Fushë Arrës' else r[0]
TOTAL = sum(m['p'] for m in munis); assert TOTAL == t7[0][1] == 2402113

# ---------------------------------------------------------------- ethnicity / religion: counties
ETH = [('Shqiptare', 'Albanian'), ('Greke', 'Greek'), ('Maqedonase', 'Macedonian'), ('Malazeze', 'Montenegrin'), ('Aromune', 'Aromanian'),
       ('Rome', 'Roma'), ('Egjyptiane', 'Egyptian'), ('Boshnjake', 'Bosniak'), ('Serbe', 'Serbian'), ('Bullgare', 'Bulgarian'),
       ('Grup etno-kulturor i përzier', 'Mixed ethnicity'), ('Tjetër grup etno-kulturor', 'Other ethnicity'),
       ('Asnjë', 'No ethnicity'), ('Preferoj të mos përgjigjem', 'Prefer not to answer'), ('Nuk disponohet', 'Not available')]
REL = [('Mysliman', 'Muslim'), ('Mysliman - Bektashi', 'Muslim - Bektashi'), ('Krishterë - Katolik', 'Catholic'), ('Krishterë - Ortodoks', 'Orthodox'),
       ('Krishterë - Ungjillore (Protestant)', 'Evangelical (Protestant)'), ('Besimtarë të pacilcësuar', 'Believers (denomination unspecified)'),
       ('Ateist', 'Atheist'), ('Tjetër besim fetar', 'Other religion'), ('Preferoj të mos përgjigjem', 'Prefer not to answer'), ('Nuk disponohet', 'Not available')]
def county_table(f, cats):
    rr = list(openpyxl.load_workbook(os.path.join(raw, f), read_only=True).active.iter_rows(values_only=True))
    cols = [i for i, h in enumerate(rr[3]) if i >= 3 and h]
    body = {r[2].strip(): r for r in rr[5:5 + len(cats)]}
    assert set(body) == {a for a, _ in cats}, set(body) ^ {a for a, _ in cats}
    res = {}
    for i in cols:
        c = [int(body[a][i]) for a, _ in cats]
        assert sum(c) == rr[4][i], f'{f}: {rr[3][i]} does not add up'
        res[rr[3][i].strip()] = (int(rr[4][i]), c)
    return res
eth, rel = county_table('albania_ethnic.xlsx', ETH), county_table('albania_religion.xlsx', REL)
assert list(eth) == list(rel) and len(eth) == 12 and all(eth[k][0] == rel[k][0] for k in eth)

# counties from the order of the population table: consecutive municipalities add up exactly to each county's total
i = 0
for cn, (cp, _) in eth.items():
    s, ms = 0, []
    while s < cp: s += munis[i]['p']; ms.append(i); i += 1
    assert s == cp, f'{cn}: municipalities do not add up to the county total'
    for k in ms: munis[k]['county'] = cn
assert i == 61 and sum(c[0] for c in eth.values()) == TOTAL

# ---------------------------------------------------------------- shapes <-> units
shapes = json.load(open(os.path.join(raw, 'geoBoundaries-ALB-ADM3.geojson'), encoding='utf-8'))['features']
assert len(shapes) == 373
geo = []
for f in shapes:
    g = shape(f['geometry']); geo.append(g if g.is_valid else make_valid(g))
sname = [fold(f['properties']['shapeName']) for f in shapes]
tab = [(mi, ui, fold(u['n'])) for mi, m in enumerate(munis) for ui, u in enumerate(m['units'])]
tc, sc = collections.Counter(n for *_, n in tab), collections.Counter(sname)
ALIASES = {'balldren': ['balldren i ri'], 'fushe muhur': ['fushe muhurr'], 'kthjelle': ['kthelle'], 'novosele': ['novosele', 'piskal novosele'],
           'prrenjas': ['perrenjas'], 'rrajce': ['rajce'], 'rrashbull': ['rashbull'], 'rremas': ['remas'], 'ujemisht': ['ujmisht'],
           'vau i dejes': ['vau dejes'], 'zavalin': ['zavaline'], 'hore vranisht': ['vranisht'], 'dimal': ['ura vajgurore'], 'kolsh': ['kolsh', 'kolc']}
match, used = {}, set()
for mi, ui, n in tab:
    if tc[n] == 1 and sc[n] == 1: j = sname.index(n); match[(mi, ui)] = j; used.add(j)
todo = [(mi, ui, n) for mi, ui, n in tab if (mi, ui) not in match]
free = [j for j in range(373) if j not in used]
assert len(todo) == len(free)
compat = lambda n, sn: sn.startswith('qender') if n.startswith('qender') else sn in ALIASES.get(n, [n])
def centre(mi): return unary_union([geo[match[(mi, ui)]] for ui in range(len(munis[mi]['units'])) if (mi, ui) in match]).centroid
prev = None
for it in range(10):
    ctr = {mi: centre(mi) for mi in range(61)}
    C = np.full((len(todo), len(free)), 1e6)
    for a, (mi, ui, n) in enumerate(todo):
        for b, j in enumerate(free):
            if compat(n, sname[j]): C[a, b] = ctr[mi].distance(geo[j].centroid)
    r, c = linear_sum_assignment(C)
    new = {todo[a][:2]: free[b] for a, b in zip(r, c)}
    assert all(C[a, b] < 1e6 for a, b in zip(r, c)), 'a unit has no compatible shape'
    match.update(new)
    if new == prev: break
    prev = new
assert len(set(match.values())) == 373 == len(match)
print(f'{len(todo)} units paired by alias / distance, stable after {it + 1} rounds')

# ---------------------------------------------------------------- geometry helpers (as in rebuild-shapes.py)
polys = lambda g: list(g.geoms) if g.geom_type in ('MultiPolygon', 'GeometryCollection') else [g]
def only_polygons(g):
    ps = [p for p in polys(g) if p.geom_type == 'Polygon' and not p.is_empty]
    return ps[0] if len(ps) == 1 else MultiPolygon(ps)
def dissolve(geoms, fill=1e-5):
    """union of the shapes under an area; holes smaller than `fill` deg2 (slivers between shapes that do not quite touch) are filled"""
    u = unary_union(geoms)
    return only_polygons(unary_union([Polygon(p.exterior, [r for r in p.interiors if Polygon(r).area >= fill]) for p in polys(u) if p.geom_type == 'Polygon']))
def ring_xy(r, nd=6):
    a = np.round(np.asarray(r.coords), nd)
    return a[np.concatenate([[True], (a[1:] != a[:-1]).any(axis=1)])]
def geometry(g):
    res = []
    for p in polys(g):
        p = orient(p, 1.0)
        rings = [r.tolist() for r in [ring_xy(p.exterior)] + [ring_xy(r) for r in p.interiors] if len(r) >= 4]
        if rings and len(rings[0]) >= 4: res.append(rings)
    assert res
    return {'type': 'MultiPolygon', 'coordinates': res} if len(res) > 1 else {'type': 'Polygon', 'coordinates': res[0]}
def write(name, feats):
    path = os.path.join(out, name + '.geojson')
    json.dump({'type': 'FeatureCollection', 'features': [{'type': 'Feature', 'properties': p, 'geometry': geometry(g)} for p, g in feats]}, open(path, 'w', encoding='utf-8'), ensure_ascii=False, separators=(',', ':'))
    print('wrote', path, len(feats), 'features')

# ---------------------------------------------------------------- the four levels
tot = lambda tbl: [sum(col) for col in zip(*[v[1] for v in tbl.values()])]     # country = sum of the counties
unit_f, muni_f, geo_m = [], [], {}
for mi, m in enumerate(munis):
    ug = [geo[match[(mi, ui)]] for ui in range(len(m['units']))]
    for u, g in zip(m['units'], ug): unit_f.append((dict(n=u['n'], j=m['county'], p=u['p'], e=None, r=None), g))
    geo_m[mi] = dissolve(ug)
    muni_f.append((dict(n=m['n'], j=m['county'], p=m['p'], e=None, r=None, b=[dict(n=u['n'], p=u['p'], e=None, r=None) for u in m['units']]), geo_m[mi]))
write('al_units', unit_f)
write('al_municipalities', muni_f)
cty_f, geo_c = [], {}
for cn, (cp, _) in eth.items():
    ms = [mi for mi, m in enumerate(munis) if m['county'] == cn]
    geo_c[cn] = dissolve([geo_m[mi] for mi in ms])
    cty_f.append((dict(n=cn, p=cp, e=eth[cn][1], r=rel[cn][1], b=[dict(n=munis[mi]['n'], p=munis[mi]['p'], e=None, r=None) for mi in ms]), geo_c[cn]))
write('al_counties', cty_f)
co_e, co_r = tot(eth), tot(rel)
assert sum(co_e) == sum(co_r) == TOTAL
write('al_country', [(dict(n='Albania', p=TOTAL, e=co_e, r=co_r, b=[dict(n=cn, p=v[0], e=v[1], r=rel[cn][1]) for cn, v in eth.items()]), dissolve(list(geo_c.values())))])
print(f'{len(eth)} counties, {len(munis)} municipalities, 373 units, population {TOTAL:,}')
