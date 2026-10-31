#!/usr/bin/env python3
"""North Macedonia 2021 census -> the three GeoJSON files that pack.js turns into data/mk/2021/*.json

Inputs (keep them in raw/, which is not committed). All tables are from MakStat (makstat.stat.gov.mk/PXWeb/pxweb/mk/MakStat/):
  north_mkd_ethnic.xlsx                  T1008P21  ethnic affiliation by municipality (Cyrillic)
  north_mkd_religion.xlsx                T1012P21  religious affiliation by municipality (Cyrillic)
  north_mkd_population.xlsx              T1019P21  population by municipality (only a double check)
  ethnic_settlements_north_mkd.xlsx      T1503P21  ethnic affiliation by settlement (Latin; "Name (Municipality)")
  population_settlements_north_mkd.xlsx  T1501P21  population by settlement (only a double check)
  mkd_settlements.gpkg                   the settlement polygons of the national register (NTES): Cyrillic names, municipality and statistical
                                         region of each settlement; coordinates in MGI 1901 / Balkans zone 7 (EPSG:6316) although the file says "undefined"

Usage (from the repo root; needs `pip install openpyxl geopandas shapely pyproj numpy`, and `cd tools && npm install`):
  python3 tools/build-mk-2021.py raw build
  cd tools
  node pack.js ../build/mk_settlements.geojson    ../data/mk/2021/settlements.json
  node pack.js ../build/mk_municipalities.geojson ../data/mk/2021/municipalities.json
  node pack.js ../build/mk_country.geojson        ../data/mk/2021/country.json

Levels. Settlement (1,781) -> municipality (80) -> country. The municipality and country shapes are the union of the settlement shapes (the earlier version used
the geoBoundaries municipalities, which still had the 84 pre-2013 municipalities). Religion is published down to the municipality only, so the settlements have
e (ethnicity) and p but r = null ("No data" in the religious mode).

Settlements. The gpkg has 1,792 features; 11 of them (Spikovo, Čiflik, Kolonija, Gorna Maala, Voinović, Kalkovo, Lag, Kosturnik, Gorna Arnakija, Kalnik, Lukare) have an
empty geometry and no row in the census tables, so they are left out. The 1,781 others pair with the 1,781 table rows (they add up to the national total):
  - the rows are "Name (Municipality)" in the MakStat romanisation (ц = c, џ = dj, ж = zh ...); the polygons have Cyrillic names. Both sides are romanised the same way and
    compared inside the municipality. Four pairs differ in spelling in the English table and are paired because they are the only one left in their municipality:
    Godivle (Krivogaštani; the table says Godivje) / Godivje (Debrca; the table says Godivle), Žitoše (table: Zhitoše), Sopotsko (table: Sopocko). Godivle/Godivje looks
    swapped in the English table; the numbers are taken as the table gives them for the municipality.
  - each municipality's settlements add up to the municipality row of the ethnic table (checked below), so no settlement is in the wrong municipality.
  - "Skopje (City of Skopje)" in the table is only the total of the ten "Skopje - X" parts (one settlement spread over ten municipalities): left out, the parts are used.
  - 205 settlements have no residents (the table shows "-"). They stay on the map (p = 0, e = null: "No data" in the ethnic mode, no bar in 3D) but are not listed in the
    breakdown of their municipality. The app divides by p, and a group of zeros would make them look like "Macedonian" areas.
  - separate pieces of a settlement smaller than 1,000 m2 (16: seams of the cadastral sheets) are dropped; the largest piece is always kept.
  - n = the Cyrillic name romanised as the municipalities are (see below), so "Zovikj 2" and "R’žanovo" are spelled the same way as the tables; "Skopje - Aerodrom" keeps its
    spaced hyphen. j = the municipality. y = 't' for the 43 settlements the register calls urban ("урбано"; shown as "(town)" in the breakdown).

Municipalities. 80, as in the census tables (the 2013 reform; Drugovo, Oslomej, Zajas and Vraneštica are part of Kičevo; the ten of the City of Skopje carry
j = "City of Skopje", and in the country file they are nested (c) under one "City of Skopje" row). Names: the Cyrillic name letter by letter - ж ч ш = ž č š, ѓ = gj,
ќ = kj, џ = dž, ѕ = dz, љ = lj, њ = nj, ц = c, х = h; only "Маврово и Ростуше" is written "Mavrovo and Rostuša".

Categories (order = data/mk/2021/meta.json)
  ethnicity: Macedonian, Albanian, Turkish, Roma, Vlach, Serbian, Bosniak, Other, then Not declared, Unknown, Data from administrative sources
  religion:  Orthodox, Muslim, Catholic, Christian (denomination not specified), Protestant, Evangelical, Evangelical-Methodist, Jehovah’s Witnesses,
             Atheist (not a believer), Other, then Not declared, Unknown, Data from administrative sources
"Data from administrative sources" = people with no interview, so no ethnicity or religion (132,260, 7.2%). In all tables "-" means zero.
Only counts are stored (p, e, r); percentages, majorities and shares are calculated in the browser.
"""
import json, sys, os, re, unicodedata, collections
import numpy as np
import openpyxl
import geopandas as gpd
from shapely.geometry import Polygon, MultiPolygon
from shapely.geometry.polygon import orient
from shapely.ops import unary_union
from shapely import make_valid

raw, out = (sys.argv + ['raw', 'build'])[1:3]
os.makedirs(out, exist_ok=True)
read = lambda f: list(openpyxl.load_workbook(os.path.join(raw, f), read_only=True).active.iter_rows(values_only=True))
def num(v):
    if v == '-': return 0
    if isinstance(v, (int, float)): return int(v)
    raise ValueError(f'unexpected cell {v!r}')

# ---------------------------------------------------------------- municipality tables
def table(f, ncat):
    res = []
    for r in read(f)[4:]:
        if r[0] is None: break                                    # footnotes start after an empty row
        res.append(dict(name=str(r[0]).strip(), p=num(r[1]), c=[num(x) for x in r[2:2 + ncat]]))
    return res
eth, rel = table('north_mkd_ethnic.xlsx', 11), table('north_mkd_religion.xlsx', 13)
pop = {r[0].strip(): num(r[2]) for r in read('north_mkd_population.xlsx')[4:] if r[0] and r[1] == 'Возрасна група - ВКУПНО'}
assert [(a['name'], a['p']) for a in eth] == [(a['name'], a['p']) for a in rel] and len(eth) == 82, 'ethnicity and religion tables do not line up'
for a in eth + rel: assert sum(a['c']) == a['p'], f"{a['name']}: categories do not add up"
assert all(pop[a['name']] == a['p'] for a in eth), 'population differs from T1019P21'
country, skopje = eth[0], eth[1]; cr = rel[0]
assert country['name'] == 'Република Северна Македонија' and skopje['name'] == 'Град Скопје'
muni_e, muni_r = eth[2:], rel[2:]
assert len(muni_e) == 80 and sum(a['p'] for a in muni_e) == country['p'] == 1836713
SK = muni_e[:10]; assert sum(a['p'] for a in SK) == skopje['p'] and SK[0]['name'] == 'Аеродром'
sk_names = {a['name'] for a in SK}

# ---------------------------------------------------------------- names
LAT = dict(zip('абвгдѓежзѕијклљмнњопрстќуфхцчџш', ['a','b','v','g','d','gj','e','ž','z','dz','i','j','k','l','lj','m','n','nj','o','p','r','s','t','kj','u','f','h','c','č','dž','š']))
def latin(s):
    """Cyrillic (any case) -> usual English spelling, each word capitalised"""
    if s.lower() == 'маврово и ростуше': return 'Mavrovo and Rostuša'
    if s.upper().startswith('СКОПЈЕ - '): return 'Skopje - ' + latin(s[9:])
    ws = []
    for w in s.replace(' - ', '-').split(' '):
        parts = [''.join(LAT.get(c, c) for c in x.lower()) for x in w.split('-')]
        ws.append('-'.join(p[:1].upper() + p[1:] for p in parts))
    return ' '.join(ws)
TAB = dict(zip('абвгдѓежзѕијклљмнњопрстќуфхцчџш', ['a','b','v','g','d','gj','e','zh','z','dz','i','j','k','l','lj','m','n','nj','o','p','r','s','t','kj','u','f','h','c','ch','dj','sh']))
fold = lambda s: re.sub(r"[^a-z0-9']", '', ''.join(c for c in unicodedata.normalize('NFD', s.lower()) if not unicodedata.combining(c)))
tab_key = lambda cyr: fold(''.join(TAB.get(c, c) for c in cyr.lower().replace('’', "'")))      # romanised like the MakStat settlement table

# ---------------------------------------------------------------- settlement table
S_RAW = [r for r in read('ethnic_settlements_north_mkd.xlsx')[3:] if r[0]]
nat = S_RAW[0]; assert nat[0].startswith('Republic') and nat[1] == country['p'] and [num(x) for x in nat[2:13]] == country['c']
srows = {}
for r in S_RAW[1:]:
    m = re.match(r'(.*) \(([^()]+)\)$', str(r[0]))
    if not m or str(r[0]).startswith('Skopje (City'): continue
    assert (fold(m.group(2)), fold(m.group(1))) not in srows
    c = [num(x) for x in r[2:13]]
    assert sum(c) == num(r[1]), r[0]
    srows[(fold(m.group(2)), fold(m.group(1)))] = dict(p=num(r[1]), c=c, label=r[0])
assert len(srows) == 1781 and sum(v['p'] for v in srows.values()) == country['p']
assert all(sum(v['c'][i] for v in srows.values()) == country['c'][i] for i in range(11)), 'settlements do not add up to the national figures'
spop = {str(r[0]): num(r[1]) for r in read('population_settlements_north_mkd.xlsx')[3:] if r[0] and r[1] is not None}
assert all(spop[v['label']] == v['p'] for v in srows.values()), 'population differs from T1501P21'

# ---------------------------------------------------------------- polygons
g = gpd.read_file(os.path.join(raw, 'mkd_settlements.gpkg')).set_crs('EPSG:6316', allow_override=True)
assert len(g) == 1792
empty = g.geometry.is_empty | g.geometry.isna()
assert empty.sum() == 11 and g.loc[empty, 'st_area(shape)'].isna().all()
g = g[~empty].to_crs('EPSG:4326').reset_index(drop=True)
assert len(g) == 1781
mname = {a['name'].upper(): a['name'] for a in muni_e}
assert set(g.ntes_municipality_name) == set(mname), set(g.ntes_municipality_name) ^ set(mname)
cyr2tab = {n: tab_key(n.replace(' - ', '-')) for n in mname}
pair, left = {}, []
for i, row in g.iterrows():
    k = (cyr2tab[row.ntes_municipality_name], tab_key(row.ntes_settlement_name))
    if k in srows and k not in pair.values(): pair[i] = k
    else: left.append(i)
free = collections.defaultdict(list)
for k in srows:
    if k not in pair.values(): free[k[0]].append(k)
for i in left:                                                     # spelling differs: the only row left in the municipality
    m = cyr2tab[g.ntes_municipality_name[i]]
    assert len(free[m]) == 1 or sum(1 for j in left if cyr2tab[g.ntes_municipality_name[j]] == m) == 1, g.ntes_settlement_name[i]
    pair[i] = free[m].pop()
print('settlements paired by spelling:', [(g.ntes_settlement_name[i], srows[pair[i]]['label']) for i in left])
assert len(left) == 4 and len(set(pair.values())) == 1781

# municipality checks: the settlements of each municipality add up to the municipality row
byM = collections.defaultdict(lambda: [0] * 11)
for i, k in pair.items():
    for x in range(11): byM[g.ntes_municipality_name[i]][x] += srows[k]['c'][x]
for a in muni_e: assert byM[a['name'].upper()] == a['c'], f"{a['name']}: settlements do not add up to the municipality"

# ---------------------------------------------------------------- geometry helpers (as in rebuild-shapes.py)
polys = lambda g_: list(g_.geoms) if g_.geom_type in ('MultiPolygon', 'GeometryCollection') else [g_]
def only_polygons(g_):
    ps = [p for p in polys(g_) if p.geom_type == 'Polygon' and not p.is_empty]
    return ps[0] if len(ps) == 1 else MultiPolygon(ps)
def dissolve(geoms, fill=1e-5):
    """union of the shapes under an area; holes smaller than `fill` deg2 (slivers between shapes that do not quite touch) are filled"""
    u = unary_union(geoms)
    return only_polygons(unary_union([Polygon(p.exterior, [r for r in p.interiors if Polygon(r).area >= fill]) for p in polys(u) if p.geom_type == 'Polygon']))
def ring_xy(r, nd=6):
    a = np.round(np.asarray(r.coords), nd)
    return a[np.concatenate([[True], (a[1:] != a[:-1]).any(axis=1)])]
def geometry(g_):
    res = []
    for p in polys(g_):
        if p.geom_type != 'Polygon' or p.is_empty: continue
        rp = Polygon(ring_xy(p.exterior), [ring_xy(r) for r in p.interiors if len(r.coords) >= 4])      # rounding to 6 decimals can make a ring touch itself
        for q in (polys(make_valid(rp)) if not rp.is_valid else [rp]):
            if q.geom_type != 'Polygon' or q.is_empty: continue
            q = orient(q, 1.0)
            rings = [np.asarray(r.coords).tolist() for r in [q.exterior] + list(q.interiors) if len(r.coords) >= 4]
            if rings: res.append(rings)
    assert res
    return {'type': 'MultiPolygon', 'coordinates': res} if len(res) > 1 else {'type': 'Polygon', 'coordinates': res[0]}
def write(name, fs):
    path = os.path.join(out, name + '.geojson')
    json.dump({'type': 'FeatureCollection', 'features': [{'type': 'Feature', 'properties': p, 'geometry': geometry(g_)} for p, g_ in fs]}, open(path, 'w', encoding='utf-8'), ensure_ascii=False, separators=(',', ':'))
    print('wrote', path, len(fs), 'features')

# ---------------------------------------------------------------- the three levels
SLIVER = 1.1e-7                                                   # deg2 = about 1,000 m2
def no_slivers(x):
    """seams of the cadastral sheets leave tiny separate pieces (16 of them under 1,000 m2); a settlement's largest part is always kept"""
    ps = polys(x)
    if len(ps) == 1: return x
    big = max(p.area for p in ps)
    return only_polygons(unary_union([p for p in ps if p.area == big or p.area >= SLIVER]))
geom = [no_slivers(make_valid(x) if not x.is_valid else x) for x in g.geometry]
mlat = {a['name'].upper(): latin(a['name']) for a in muni_e}
st_f, per_m = [], collections.defaultdict(list)
for i in range(len(g)):
    row, v = g.loc[i], srows[pair[i]]
    n, j = latin(row.ntes_settlement_name), mlat[row.ntes_municipality_name]
    props = dict(n=n, j=j, p=v['p'], e=v['c'] if v['p'] else None, r=None)
    st_f.append((props, geom[i]))
    if v['p']:
        b = dict(n=n, p=v['p'], e=v['c'], r=None)
        if row.settlement_type == 'урбано': b['y'] = 't'
        per_m[row.ntes_municipality_name].append(b)
assert sum(1 for p, _ in st_f if not p['p']) == 205
write('mk_settlements', st_f)

mg = {}
for a in muni_e: mg[a['name'].upper()] = dissolve([geom[i] for i in range(len(g)) if g.ntes_municipality_name[i] == a['name'].upper()])
mf = []
for a, b in zip(muni_e, muni_r):
    p = dict(n=mlat[a['name'].upper()], p=a['p'], e=a['c'], r=b['c'], b=per_m[a['name'].upper()])
    assert sum(x['p'] for x in p['b']) == p['p']
    if a['name'] in sk_names: p['j'] = 'City of Skopje'
    mf.append((p, mg[a['name'].upper()]))
write('mk_municipalities', mf)

rows_ = [p for p, _ in mf]
cb = [dict(n=p['n'], p=p['p'], e=p['e'], r=p['r']) for p in rows_ if 'j' not in p]
sk_row = dict(n='City of Skopje', p=skopje['p'], e=eth[1]['c'], r=rel[1]['c'], c=[dict(n=p['n'], p=p['p'], e=p['e'], r=p['r']) for p in rows_ if 'j' in p])
assert len(cb) == 70 and sum(u['p'] for u in sk_row['c']) == sk_row['p']
write('mk_country', [(dict(n='North Macedonia', p=country['p'], e=country['c'], r=cr['c'], b=[sk_row] + cb), dissolve(list(mg.values())))])
print(f"{len(st_f)} settlements, {len(mf)} municipalities, population {country['p']:,}")
