#!/usr/bin/env python3
"""How tools/hu-settlements.json was made (kept for reference; you only need to run it again if the census settlements or the ADM3 file change).

The names in geoBoundaries-HUN-ADM3-municipalities.geojson are corrupted (accented letters are garbled or lost, 695 of 3,357 names are a single
letter), so shapes cannot be matched by name. Instead each census settlement (data/hu/2022/districts.json, `b`) gets a point from a public list
of settlement coordinates (github.com/kobanya/nevek, magyar.py, `telepules_megye_koordinata`) and the ADM3 shape that contains the point is its shape.
  - a point that falls outside its own district (geocoding errors, e.g. Békés, Nemesrádó) is discarded;
  - the ~37 settlements left without a point (new settlements such as Monorierdő, Pári, Gibárt) are paired with the ~37 shapes left without a point by
    name similarity and distance to their district (optimal assignment);
  - the 203 shapes inside Budapest are not settlements: together they are Budapest.
The result was checked: 3,154 distinct shapes, and every shape name that is still readable agrees with its settlement.
Usage: curl -o magyar.py https://raw.githubusercontent.com/kobanya/nevek/master/magyar.py ; python3 tools/match-hu-settlements.py magyar.py raw
Needs shapely, numpy, scipy."""
import sys, json, ast, collections, unicodedata, difflib
import numpy as np
from shapely.geometry import shape, Point
from shapely.ops import unary_union
from shapely.strtree import STRtree
from scipy.optimize import linear_sum_assignment

magyar, raw = sys.argv[1], sys.argv[2]
fold = lambda s: ''.join(c for c in unicodedata.normalize('NFD', s) if not unicodedata.combining(c)).lower().replace('-', ' ').replace('.', '').strip()
src = open(magyar, encoding='utf-8').read(); i = src.index('telepules_megye_koordinata = [')
pts = ast.literal_eval(src[i + len('telepules_megye_koordinata = '):src.index(']\n', i) + 1])
a3 = json.load(open(f'{raw}/geoBoundaries-HUN-ADM3-municipalities.geojson', encoding='utf-8'))['features']
FIX = {'Pannonhalm': 'Pannonhalma', 'Kunszentmártonj': 'Kunszentmárton'}                      # misspelt shape names in the ADM2 file
a2 = {FIX.get(f['properties']['shapeName'], f['properties']['shapeName']): shape(f['geometry']) for f in json.load(open(f'{raw}/geoBoundaries-HUN-ADM2-districts.geojson', encoding='utf-8'))['features']}
g3 = [shape(f['geometry']) for f in a3]; tree = STRtree(g3)
sname = lambda i: a3[i]['properties']['shapeName']
old = json.load(open('data/hu/2022/districts.json', encoding='utf-8'))['objects']['u']['geometries']
cen, dist = [], {}
for x in old:
    p = x['properties']
    dist[(p['j'], p['n'])] = a2[p['n'].split()[1] + '. kerület'] if p['j'] == 'Budapest' else a2[p['n']]
    for s in p.get('b', []): cen.append((p['j'], p['n'], s['n']))
dist[('Fejér', 'Székesfehérvár')] = unary_union([dist[('Fejér', 'Székesfehérvár')], a2['Polgard']])   # Polgárdi district is part of it in 2022
byname = collections.defaultdict(list)
for q in pts: byname[fold(q[0])].append(q)
cfix = lambda c: 'Csongrád-Csanád' if c == 'Csongrád' else c
bud = unary_union([g for k, g in dist.items() if k[0] == 'Budapest'])
inbud = {i for i, g in enumerate(g3) if bud.contains(g.representative_point())}
sh = {}
for k in cen:
    c = [q for q in byname.get(fold(k[2]), []) if fold(cfix(q[1])) == fold(k[0])]
    if len(c) > 1: c = [q for q in c if q[0] == k[2]]
    if len(c) != 1: continue
    p = Point(c[0][3], c[0][2])
    if not dist[(k[0], k[1])].contains(p): continue
    h = [j for j in tree.query(p) if g3[j].contains(p)]
    if h: sh.setdefault(h[0], []).append(k)
for j, ks in list(sh.items()):                         # two settlements in one shape: a wrong point (county-named towns); keep the one whose name fits
    if len(ks) > 1:
        sh[j] = [max(ks, key=lambda k: difflib.SequenceMatcher(None, fold(k[2]), fold(sname(j))).ratio())]
done = {k for v in sh.values() for k in v}
lk = [k for k in cen if k not in done]; ls = [j for j in range(len(g3)) if j not in sh and j not in inbud]
sc = lambda k, j: difflib.SequenceMatcher(None, fold(k[2]), fold(sname(j))).ratio() - 0.15 * min(dist[(k[0], k[1])].distance(g3[j].representative_point()) * 111, 10)
r, c = linear_sum_assignment(np.array([[-sc(k, j) for j in ls] for k in lk]))
final = {k: j for j, v in sh.items() for k in v}; final.update({lk[a]: ls[b] for a, b in zip(r, c)})
assert len(final) == len(cen) == len(set(final.values())), (len(final), len(cen))
out = {'_': 'geoBoundaries HUN ADM3 shapeID of every census settlement of data/hu/2022 (key = county|district|settlement); budapest = the ADM3 shapes that make up Budapest. The ADM3 names are corrupted, so the shapes were matched through settlement coordinates (see tools/match-hu-settlements.py).',
       'budapest': sorted(a3[i]['properties']['shapeID'] for i in inbud), 'shapes': {'|'.join(k): a3[j]['properties']['shapeID'] for k, j in final.items()}}
json.dump(out, open('tools/hu-settlements.json', 'w', encoding='utf-8'), ensure_ascii=False, separators=(',', ':'))
print(len(final), 'settlements matched,', len(inbud), 'shapes in Budapest')
