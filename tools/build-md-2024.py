#!/usr/bin/env python3
"""Moldova 2024 census -> the two GeoJSON files that pack.js turns into data/md/2024/*.json

Inputs (keep them in raw/, which is not committed):
  geoBoundaries-MDA-ADM1.geojson               raion shapes
  geoBoundaries-MDA-ADM0.geojson               country shape
  Anexa_Caracteristici_Etnoculturale_RPL2024.xlsx   tables 5.6 (ethnicity) and 5.31 (religion)
  Anexa_Localitati_RPL2024.xlsx                tables 8.2 / 8.3, used only to double-check populations

Usage (from the repo root; needs `pip install openpyxl`):
  python3 tools/build-md-2024.py raw build
  cd tools && npm install
  node pack.js ../build/md_raions.geojson    ../data/md/2024/raions.json
  node pack.js ../build/md_country.geojson ../data/md/2024/country.json

Transnistria (unofficial, u = 'tr'): the Moldovan census did not enumerate it. Its figures are the 2015 census of the self-proclaimed
Pridnestrovian Moldavian Republic (PMR) as reported by newspmr.com (copy on privetpmr.ru, web.archive.org snapshot 20180814231257):
475,373 residents and ethnic shares of the whole republic, plus the population of each region. The press text gives shares only
for the republic as a whole, so Transnistria is ONE area (Bender is part of the PMR figures, so MD-SN and MD-BD are merged).
Shares as published: Russians 29.1, Moldovans 28.6, Ukrainians 22.9, Bulgarians 2.4, Gagauz 1.1, Belarusians 0.5, "Pridnestrovians" 0.2,
other 1.4, not stated "about 14" - 100.2% in total; that is kept as published and flagged on the map (u = 'tr'). (The ru.wikipedia article on the PMR
gives different 2015 shares, calculated among those who stated an ethnicity, so it is not used for them; the separate ru.wikipedia article on the
2015 census agrees except for "other" = 1.2.)
Belarusian and Transnistrian are ethnicity categories of their own in meta.json (indexes 7 and 8), but the Moldovan census has no such
categories (those people are in "Other ethnicity" there): they are null for every census area and only have values for Transnistria.
Religion was not published, so r = null. The country-level shape (ADM0, which includes the left bank) adds Transnistria's population (u = 'co'); with no religion data it is counted as "Not declared" there. Romanians and Roma are not separate categories there, so their counts are null.

Only counts are stored (p, e, r). Percentages, majorities and shares are calculated in the browser.
In these tables "-" means zero (there are no withheld "*" values), so every "-" is stored as 0.
Each raion also carries `b` (breakdown): its towns/communes (and the Chisinau sectors, nested under the town of Chisinau)
with their own p/e/r, which the "Select area" card shows.
"""
import json, sys, os, unicodedata
import openpyxl

raw, out = (sys.argv + ['raw', 'build'])[1:3]
os.makedirs(out, exist_ok=True)

# geoBoundaries ISO code -> CUATM code used by the census tables. Bender (MD-BD) and Transnistria (MD-SN) were not
# enumerated by the Moldovan census (footnote 1 of the tables); they are added back below from the PMR 2015 census.
ISO = {'MD-CA':1700000,'MD-GA':9600000,'MD-TA':8700000,'MD-CT':2100000,'MD-BS':1200000,'MD-LE':5700000,'MD-CM':2900000,
 'MD-SV':8500000,'MD-CS':2700000,'MD-HI':5300000,'MD-IA':5500000,'MD-NI':6000000,'MD-CU':100000,'MD-AN':1000000,
 'MD-CR':3100000,'MD-ST':8000000,'MD-UN':9200000,'MD-DU':3800000,'MD-CL':2500000,'MD-FA':4300000,'MD-OR':6400000,
 'MD-GL':4800000,'MD-BA':300000,'MD-TE':8900000,'MD-SI':7400000,'MD-RI':7100000,'MD-RE':6700000,'MD-SD':8300000,
 'MD-FL':4500000,'MD-DR':3600000,'MD-ED':4100000,'MD-BR':1400000,'MD-SO':7800000,'MD-DO':3400000,'MD-OC':6200000}
SECTORS = {110000, 120000, 130000, 140000, 150000}
FIX = str.maketrans('şŞţŢ', 'șȘțȚ')          # cedilla -> comma-below, so every name is spelled the same way
flat = lambda s: ''.join(c for c in unicodedata.normalize('NFD', s) if not unicodedata.combining(c)).lower()

def num(v):
    if v == '-': return 0
    if isinstance(v, (int, float)): return int(v)
    raise ValueError(f'unexpected cell {v!r}')

wb = openpyxl.load_workbook(os.path.join(raw, 'Anexa_Caracteristici_Etnoculturale_RPL2024.xlsx'), read_only=True)
def table(name, ncat):
    rows = []
    for r in wb[name].iter_rows(min_row=10, values_only=True):
        if r[2] is None: continue
        if r[3] is None: break                  # footnotes start here
        rows.append(dict(code=r[1], name=str(r[2]).strip().translate(FIX), p=num(r[3]), c=[num(x) for x in r[4:4 + ncat]]))
    return rows
eth, rel = table(' 5.6', 9), table('5.31', 15)   # 5.6: 7 ethnicities + other + not declared (Belarusian / Transnistrian are inserted before "other" below); 5.31: 13 religions/beliefs + other + not declared (order = data/md/2024/meta.json)
assert [(a['code'], a['name'], a['p']) for a in eth] == [(a['code'], a['name'], a['p']) for a in rel], 'tables 5.6 and 5.31 do not line up'
for a in eth + rel: assert sum(a['c']) == a['p'], f"{a['name']}: categories do not add up to the total"

total = eth[0]; assert total['name'] == 'Total'
units, cur = {}, None
for a, b in zip(eth[1:], rel[1:]):
    if a['code'] is None: continue                                   # development-region header rows
    n = a['name']
    if n.startswith(('Raionul ', 'Mun. ', 'UTA ')):
        cur = units[a['code']] = dict(name=n, p=a['p'], e=a['c'], r=b['c'], b=[])
    elif a['code'] in SECTORS:
        cur['b'][-1].setdefault('c', []).append(dict(n=n, y='s', p=a['p'], e=a['c'], r=b['c']))   # sectors sit under "or. Chisinau"
    else:
        town = n.startswith('or. ')
        u = dict(n=n[4:] if town else n, p=a['p'], e=a['c'], r=b['c'])
        if town: u['y'] = 't'
        cur['b'].append(u)
        if a['code'] == 101000: u['n'] = 'Chișinău'

# ---- double-check against the Localitati workbook (tables 8.2 and 8.3) and against the country row
wl = openpyxl.load_workbook(os.path.join(raw, 'Anexa_Localitati_RPL2024.xlsx'), read_only=True)
p83 = {}
for r in wl['8.3'].iter_rows(min_row=10, values_only=True, max_col=5):
    if r[1] is not None and isinstance(r[4], (int, float)): p83.setdefault(str(r[1]).lstrip('0'), int(r[4]))
codes = {a['code']: a['p'] for a in eth[1:] if a['code'] is not None}
bad = [(c, p, p83.get(str(c))) for c, p in codes.items() if p83.get(str(c)) != p]
assert not bad, f'population differs from table 8.3: {bad[:5]}'
for R in units.values():
    assert R['p'] == sum(u['p'] for u in R['b']), R['name']
    assert all(R['e'][i] == sum(u['e'][i] for u in R['b']) for i in range(9)), R['name']
    assert all(R['r'][i] == sum(u['r'][i] for u in R['b']) for i in range(15)), R['name']
assert sum(R['p'] for R in units.values()) == total['p']
print(f'{len(units)} raions, {sum(len(R["b"]) for R in units.values())} towns/communes, population {total["p"]:,} (all match tables 8.2/8.3)')

# ---- Belarusian / Transnistrian: new categories (indexes 7, 8, between Roma and "Other ethnicity"); not recorded in the Moldovan census -> None
ins = lambda e: None if e is None else e[:7] + [None, None] + e[7:]
def widen(b):
    for u in b:
        u['e'] = ins(u['e'])
        widen(u.get('c', []))
for R in units.values():
    R['e'] = ins(R['e']); widen(R['b'])

# ---- shapes
def short(n):                                # 'Raionul Briceni' -> 'Briceni', 'Mun. Bălți' -> 'Bălți', 'UTA Găgăuzia' -> 'Gagauzia'
    return 'Gagauzia' if n == 'UTA Găgăuzia' else n.split(' ', 1)[1]
g = json.load(open(os.path.join(raw, 'geoBoundaries-MDA-ADM1.geojson')))
feats = []
for f in g['features']:
    code = ISO.get(f['properties']['shapeISO'])
    if code is None: continue
    R = units[code]; nm = short(R['name']).translate(FIX)
    assert flat(nm).replace('-', ' ') == flat(f['properties']['shapeName']).replace('-', ' ') or nm == 'Gagauzia', (nm, f['properties']['shapeName'])
    feats.append(dict(type='Feature', geometry=f['geometry'], properties=dict(n=nm, p=R['p'], e=R['e'], r=R['r'], b=R['b'])))
assert len(feats) == len(units) == 35

# ---- Transnistria / PMR 2015 (unofficial)
TR_P = 475373
SHARE = dict(moldovan=28.6, ukrainian=22.9, russian=29.1, gagauz=1.1, bulgarian=2.4,
             belarusian=0.5, transnistrian=0.2, other=1.4,     # "other nationalities"
             undeclared=14.0)                  # "around 14%"
n = lambda k: round(TR_P * SHARE[k] / 100)
tr_e = [n('moldovan'), None, n('ukrainian'), n('russian'), n('gagauz'), n('bulgarian'), None, n('belarusian'), n('transnistrian'), n('other'), n('undeclared')]  # order of meta.json (None = not recorded)
print('PMR shares add up to', round(sum(SHARE.values()), 1), '%')
def part(name, p, y=None, a=0, c=None):
    d = dict(n=name, p=p, e=None, r=None)
    if y: d['y'] = y
    if a: d['a'] = 1                              # rounded figure ("~")
    if c: d['c'] = c
    return d
# Regions as listed in the PMR census report (republic = 5 districts + 2 cities of republican subordination: Tiraspol, Bender).
# District figures include the district centre; the town figures nested under them come from the Russian Wikipedia article on the PMR.
tr_b = [part('Tiraspol', 129367, 't'), part('Bender (Tighina)', 91197, 't'),
        part('Slobozia district', 83798, c=[part('Slobozia', 14618, 't')]),
        part('Rîbnița district', 69000, a=1, c=[part('Rîbnița', 47949, 't')]),
        part('Grigoriopol district', 40000, a=1, c=[part('Grigoriopol', 9381, 't')]),
        part('Dubăsari district', 31000, a=1, c=[part('Dubăsari', 25060, 't')]),
        part('Camenca district', 20542, c=[part('Camenca', 8871, 't')]),
        part('Dnestrovsk', 9744, 't')]           # listed separately in the source (administratively it belongs to Tiraspol)
polys = []
for f in g['features']:
    if f['properties']['shapeISO'] in ('MD-SN', 'MD-BD'):
        polys += f['geometry']['coordinates'] if f['geometry']['type'] == 'MultiPolygon' else [f['geometry']['coordinates']]
assert len(polys) >= 2
feats.append(dict(type='Feature', geometry=dict(type='MultiPolygon', coordinates=polys),
                  properties=dict(n='Transnistria', p=TR_P, e=tr_e, r=None, u='tr', b=tr_b)))
json.dump(dict(type='FeatureCollection', features=feats), open(os.path.join(out, 'md_raions.geojson'), 'w'), ensure_ascii=False)

# ---- country: the whole ADM0 shape (it includes the left bank) = Moldovan census area + Transnistria
c = json.load(open(os.path.join(raw, 'geoBoundaries-MDA-ADM0.geojson')))['features'][0]
cen_e, cen_r = ins(total['c']), rel[0]['c']
co_e = [a + (b or 0) if a is not None else None for a, b in zip(cen_e, tr_e)]            # Romanians / Roma: Moldovan census only (not recorded separately in the PMR census)
co_e[9] += tr_e[7] + tr_e[8]                                   # the Moldovan census has no Belarusian / Transnistrian category: the PMR's go into "Other ethnicity" at country level
co_r = list(cen_r); co_r[14] += TR_P                           # no religion data for Transnistria -> counted as "Not declared"
co_b = [dict(n='Area enumerated by the 2024 census', p=total['p'], e=cen_e, r=cen_r),
        dict(n='Transnistria', p=TR_P, e=tr_e, r=None, u='tr')]
assert sum(co_r) == total['p'] + TR_P
json.dump(dict(type='FeatureCollection', features=[dict(type='Feature', geometry=c['geometry'],
    properties=dict(n='Moldova', p=total['p'] + TR_P, e=co_e, r=co_r, u='co', b=co_b))]), open(os.path.join(out, 'md_country.geojson'), 'w'), ensure_ascii=False)
print('wrote', out)
