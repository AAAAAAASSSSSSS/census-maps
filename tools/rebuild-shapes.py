#!/usr/bin/env python3
"""Shapes of the site: the LOWEST administrative level is the base, every higher level is made by joining the units under it.

  python3 tools/rebuild-shapes.py raw build [only]        (from the repo root; needs `pip install shapely numpy`, and `cd tools && npm install`)

  raw/   the geoBoundaries files (https://www.geoboundaries.org, release "gbOpen"), under these names:
           geoBoundaries-HUN-ADM2-districts.geojson   geoBoundaries-HUN-ADM3-municipalities.geojson
           geoBoundaries-ROU-ADM2.geojson             geoBoundaries-MDA-ADM1.geojson
  build/ the GeoJSON files written here (then packed into data/ by pack.js; build/ is not committed)
  only   optional: hu, ro, md or bg, to rebuild one country

The numbers (p, e, r, b ...) and the names of every area stay exactly as they are in data/<cc>/<census>/*.json; only geometry is made here.

  base (lowest level)                                  made of
  hu settlements  3,154 ADM3 shapes + the 23 districts of Budapest       tools/hu-settlements.json says which shape is which settlement
  hu districts    járás = its settlements; the 23 Budapest districts = Budapest cut along the ADM2 district borders
  hu counties     = their districts          hu country = all counties
  ro communes     ADM2 (3,181 areas; the pieces of a commune that lie apart and the 6 Bucharest sectors are joined to it)
  ro counties     = their communes (`j`)     ro country = all counties
  md raions       ADM1 (Transnistria = MD-SN + Bender MD-BD)        md country = all raions
  bg municipalities  NOT made here: data/bg/2021/municipalities.json is the base (see below)
  bg oblasts      = their municipalities (`j`)    bg country = all oblasts

Every existing area is paired with its detailed shape by position (the inner point of the old area must fall inside the new shape), so no names
are needed. Nothing is simplified: pack.js only quantizes the coordinates to a 100,000 x 100,000 grid over the country (about 5-10 m).
Because the upper levels are unions of the base, their borders are exactly the base borders (no second source that could disagree).

Bulgaria: the geoBoundaries BGR-ADM2 shapes differ a lot from the municipality shapes of the NSI/OCHA file (bgr_admin2.geojson) that
build-bg-2021.py uses (on average a quarter of an area, up to 100% for small municipalities; geoBoundaries has no Sarnitsa at all), so the municipalities stay
as built by build-bg-2021.py. Run `python3 tools/build-bg-2021.py raw build` and pack ONLY build/bg_municipalities.geojson (geo2topo.py now keeps every point)
to get them at full detail, then run this script: it makes the oblasts and the country out of them.
"""
import json, sys, os, subprocess, collections, unicodedata, re, time
import numpy as np
from shapely.geometry import shape, mapping, Point, Polygon, MultiPolygon
from shapely.geometry.polygon import orient
from shapely.ops import unary_union, polygonize
from shapely.strtree import STRtree
from shapely import make_valid

HERE = os.path.dirname(os.path.abspath(__file__))
ROOT = os.path.dirname(HERE)
raw, out = (sys.argv + ['raw', 'build'])[1:3]
only = sys.argv[3] if len(sys.argv) > 3 else None
os.makedirs(out, exist_ok=True)
T0 = time.time()
def log(*a): print(f'[{time.time() - T0:6.1f}s]', *a, flush=True)
fold = lambda s: ''.join(c for c in unicodedata.normalize('NFD', s) if not unicodedata.combining(c)).lower().strip()

# ---------------------------------------------------------------- reading
def read_topo(path):
    """The site's TopoJSON -> [(properties, shapely geometry)]"""
    t = json.load(open(path, encoding='utf-8'))
    sx, sy = t['transform']['scale']; tx, ty = t['transform']['translate']
    arcs = []
    for a in t['arcs']:
        a = np.asarray(a, dtype='float64').cumsum(axis=0)
        arcs.append(np.column_stack([a[:, 0] * sx + tx, a[:, 1] * sy + ty]))
    arc = lambda i: arcs[i] if i >= 0 else arcs[~i][::-1]
    def ring(ix):
        pts = np.vstack([arc(i) if k == 0 else arc(i)[1:] for k, i in enumerate(ix)])
        return pts if (pts[0] == pts[-1]).all() else np.vstack([pts, pts[:1]])
    res = []
    for g in t['objects']['u']['geometries']:
        polys = [g['arcs']] if g['type'] == 'Polygon' else g['arcs']
        ps = [Polygon(ring(p[0]), [ring(r) for r in p[1:]]) for p in polys]
        ps = [q if q.is_valid else make_valid(q) for q in ps]
        geom = unary_union(ps) if len(ps) > 1 else ps[0]
        res.append((g.get('properties', {}), geom))
    return res

def read_geo(name):
    """a geoBoundaries file -> [(properties, shapely geometry)]"""
    fs = json.load(open(os.path.join(raw, name), encoding='utf-8'))['features']
    res = []
    for f in fs:
        g = shape(f['geometry'])
        res.append((f['properties'], g if g.is_valid else make_valid(g)))
    log(f'read {name}: {len(res)} shapes, {sum(count_pts(g) for _, g in res):,} points')
    return res

def polys(g): return list(g.geoms) if g.geom_type in ('MultiPolygon', 'GeometryCollection') else [g]
def count_pts(g): return sum(len(p.exterior.coords) + sum(len(r.coords) for r in p.interiors) for p in polys(g) if p.geom_type == 'Polygon')
def only_polygons(g):
    ps = [p for p in polys(g) if p.geom_type == 'Polygon' and not p.is_empty]
    return ps[0] if len(ps) == 1 else MultiPolygon(ps)

# ---------------------------------------------------------------- pairing
def pair(old, new, label):
    """old = [(props, geom)] (existing areas, simplified), new = [(props, geom)] (detailed shapes).
    Each old area gets the new shape it overlaps most (intersection / union); the best overlaps are settled first, so a shape is used once.
    Returns owner[j] = index of the old area that owns new shape j (None = not paired). Every old area must get a shape."""
    tree = STRtree([g for _, g in new])
    cand = []
    for i, (p, g) in enumerate(old):
        for j in tree.query(g):
            ng = new[j][1]; inter = g.intersection(ng).area
            if inter > 0: cand.append((inter / (g.area + ng.area - inter), i, j))
    cand.sort(reverse=True)
    owner = [None] * len(new); got = {}
    for iou, i, j in cand:
        if i not in got and owner[j] is None: got[i] = (j, iou); owner[j] = i
    missing = [old[i][0].get('n') for i in range(len(old)) if i not in got]
    assert not missing, f'{label}: no shape for {missing[:10]}'
    low = sorted((iou, old[i][0].get('n')) for i, (j, iou) in got.items() if iou < 0.5)
    if low: log(f'  {label}: {len(low)} areas overlap their shape by less than 50%: {[(round(a, 2), b) for a, b in low[:8]]}')
    return owner

def attach(new, owner, label, old=None, name_of_old=None, forced=None):
    """Join the shapes that are not paired to the area they belong to. In this order:
    forced(j) -> old index (explicit rule) | the area of the same name nearest to it (when name_of_old is given; parts of a commune can lie apart) |
    the area whose (simplified) outline contains the shape | the neighbour with the longest shared border."""
    tree = STRtree([g for _, g in new]); otree = STRtree([g for _, g in old]) if old else None
    rest = [j for j, o in enumerate(owner) if o is None]
    for j in rest:
        pj, gj = new[j]; why = None
        if forced and forced(j) is not None: owner[j] = forced(j); why = 'rule'
        if why is None and name_of_old:                                     # a part of a commune that lies apart: the nearest area of the same name
            same = [i for i in set(o for o in owner if o is not None) if fold(pj['shapeName']) == name_of_old(i)]
            if same:
                pt = gj.representative_point(); i = min(same, key=lambda i: old[i][1].distance(pt) if old else 0)
                if old[i][1].distance(pt) < 0.3: owner[j] = i; why = 'same name'
        if why is None and otree is not None:
            pt = gj.representative_point(); hit = [i for i in otree.query(pt) if old[i][1].contains(pt)]
            if len(hit) == 1: owner[j] = hit[0]; why = 'inside'
        if why is None:
            near = [k for k in tree.query(gj.buffer(1e-5)) if owner[k] is not None and k != j and new[k][1].distance(gj) < 1e-5]
            assert near, f'{label}: shape {pj.get("shapeName")} ({pj.get("shapeID")}) belongs to no area'
            k = max(near, key=lambda k: new[k][1].boundary.intersection(gj.buffer(1e-5)).length); owner[j] = owner[k]; why = 'border'
        log(f'  {label}: {pj.get("shapeName")} ({gj.area * 7500:.1f} km2) -> {old[owner[j]][0].get("n") if old else owner[j]}  [{why}]')
    log(f'{label}: {len(rest)} shapes joined')

def merged(new, owner, n_old, label):
    geoms = []
    for i in range(n_old):
        parts = [new[j][1] for j, o in enumerate(owner) if o == i]
        assert parts, f'{label}: area {i} has no shape'
        geoms.append(parts[0] if len(parts) == 1 else unary_union(parts))
    return geoms

def dissolve(geoms, fill=0):
    """union of the shapes under an area; holes smaller than `fill` deg2 (slivers between shapes that do not quite touch) are filled"""
    u = unary_union(geoms)
    if not fill: return only_polygons(u)
    return only_polygons(unary_union([Polygon(p.exterior, [r for r in p.interiors if Polygon(r).area >= fill]) for p in polys(u) if p.geom_type == 'Polygon']))

# ---------------------------------------------------------------- writing GeoJSON, packing
def ring_xy(r, nd=6):
    a = np.round(np.asarray(r.coords), nd)
    keep = np.concatenate([[True], (a[1:] != a[:-1]).any(axis=1)])
    return a[keep]
def geo_coords(g):
    res = []
    for p in polys(g):
        p = orient(p, 1.0)
        rings = [ring_xy(p.exterior)] + [ring_xy(r) for r in p.interiors]
        rings = [r.tolist() for r in rings if len(r) >= 4]
        if rings and len(rings[0]) >= 4: res.append(rings)
    return res
def write(name, props_list, geoms):
    fs = []
    for p, g in zip(props_list, geoms):
        c = geo_coords(g)
        assert c, f'{name}: {p.get("n")} has no geometry left'
        fs.append({'type': 'Feature', 'properties': p, 'geometry': {'type': 'MultiPolygon', 'coordinates': c} if len(c) > 1 else {'type': 'Polygon', 'coordinates': c[0]}})
    path = os.path.join(out, name + '.geojson')
    json.dump({'type': 'FeatureCollection', 'features': fs}, open(path, 'w', encoding='utf-8'), ensure_ascii=False, separators=(',', ':'))
    log(f'wrote {path}: {len(fs)} features, {sum(len(r) for f in fs for p in (f["geometry"]["coordinates"] if f["geometry"]["type"] == "MultiPolygon" else [f["geometry"]["coordinates"]]) for r in p):,} points')
    return path
def pack(src, dst):
    env = dict(os.environ, NODE_OPTIONS='--max-old-space-size=2800')
    r = subprocess.run(['node', os.path.join(HERE, 'pack.js'), src, os.path.join(ROOT, dst)], capture_output=True, text=True, env=env)
    assert r.returncode == 0, r.stderr[-2000:]
    log(r.stdout.strip())

DATA = lambda p: os.path.join(ROOT, 'data', p + '.json')

# ================================================================ HUNGARY
def hungary():
    d2 = read_geo('geoBoundaries-HUN-ADM2-districts.geojson')
    d3 = read_geo('geoBoundaries-HUN-ADM3-municipalities.geojson')
    old_d = read_topo(DATA('hu/2022/districts')); old_c = read_topo(DATA('hu/2022/counties')); old_k = read_topo(DATA('hu/2022/country'))
    mp = json.load(open(os.path.join(HERE, 'hu-settlements.json'), encoding='utf-8'))
    idx = {p['shapeID']: i for i, (p, _) in enumerate(d3)}; assert len(idx) == len(d3)
    bud_ids = set(mp['budapest'])
    # --- Budapest: the 203 ADM3 shapes only give its outline; the 23 districts come from the ADM2 shapes. Both are cut along each other
    #     (every border is noded), so the districts, the settlements around Budapest and the country all share their border vertices exactly.
    bd = {}
    for p, _ in old_d:
        if p['j'] == 'Budapest':
            bd[p['n']] = next(g for q, g in d2 if q['shapeName'] == p['n'].split()[1] + '. kerület')
    bud = unary_union([d3[idx[i]][1] for i in bud_ids])
    S = [i for i, (_, g) in enumerate(d3) if g.intersects(bud.buffer(1e-4))]
    faces = list(polygonize(unary_union([d3[i][1].boundary for i in S] + [g.boundary for g in bd.values()])))
    stree = STRtree([d3[i][1] for i in S]); names = list(bd)
    mine = collections.defaultdict(list); lost = 0.0
    for f in faces:
        pt = f.representative_point(); hit = [S[k] for k in stree.query(pt) if d3[S[k]][1].contains(pt)]
        if not hit: lost += f.area; continue
        if d3[hit[0]][0]['shapeID'] in bud_ids:
            inside = [n for n in names if bd[n].contains(pt)]
            mine[('d', inside[0] if inside else min(names, key=lambda n: bd[n].distance(f)))].append(f)
        else: mine[('s', hit[0])].append(f)
    bgeo = {n: only_polygons(unary_union(mine[('d', n)])) for n in names}
    sgeo = {p['shapeID']: g for p, g in d3}
    for (kind, i), fs in mine.items():
        if kind == 's':
            g = only_polygons(unary_union(fs)); assert abs(g.area - d3[i][1].area) < 1e-9, d3[i][0]['shapeID']; sgeo[d3[i][0]['shapeID']] = g
    assert abs(sum(g.area for g in bgeo.values()) - bud.area) < 1e-7
    log(f'hu: Budapest cut into {len(bgeo)} districts ({len(faces)} faces, {lost:.1e} deg2 of ADM2 outside the ADM3 outline dropped)')
    # --- settlements (base), districts, counties, country
    sp, sg, dg = [], [], []
    for pd, _ in old_d:
        if pd['j'] == 'Budapest': dg.append(bgeo[pd['n']]); continue
        parts = []
        for s in pd['b']:
            sid = mp['shapes'][f"{pd['j']}|{pd['n']}|{s['n']}"]; parts.append(sgeo[sid])
            sp.append(dict(n=s['n'], j=pd['j'], p=s['p'], e=s['e'], r=s['r'])); sg.append(sgeo[sid])
        dg.append(dissolve(parts))
    assert len(sp) == 3154
    for pd, _ in old_d:                                                      # Budapest has no figures per settlement: its 23 districts are the units
        if pd['j'] == 'Budapest': sp.append(dict(n=pd['n'], j='Budapest', p=pd['p'], e=pd['e'], r=pd['r'])); sg.append(bgeo[pd['n']])
    assert sum(p['p'] for p in sp) == old_k[0][0]['p'], 'settlement populations do not add up to the country'
    write_pack('hu_settlements', sp, sg, 'data/hu/2022/settlements.json')
    write_pack('hu_districts', [p for p, _ in old_d], dg, 'data/hu/2022/districts.json')
    cg = []
    for pc, _ in old_c:
        parts = [dg[i] for i, (p, _) in enumerate(old_d) if p['j'] == pc['n']]; assert parts, pc['n']
        cg.append(dissolve(parts))
    write_pack('hu_counties', [p for p, _ in old_c], cg, 'data/hu/2022/counties.json')
    write_pack('hu_country', [p for p, _ in old_k], [dissolve(cg, fill=1e-5)], 'data/hu/2022/country.json')

def write_pack(name, props, geoms, dst):
    pack(write(name, props, geoms), dst)

# ================================================================ ROMANIA
def romania():
    n2 = read_geo('geoBoundaries-ROU-ADM2.geojson')
    old = read_topo(DATA('ro/2021/communes'))
    owner = pair(old, n2, 'ro communes')
    bucharest = next(i for i, (p, _) in enumerate(old) if p['n'] == 'MUNICIPIUL BUCUREȘTI')
    core = lambda i: fold(re.sub(r'^(MUNICIPIUL|ORAȘ|ORAŞ|COMUNA)\s+', '', old[i][0]['n']))
    attach(n2, owner, 'ro communes', old=old, name_of_old=core, forced=lambda j: bucharest if fold(n2[j][0]['shapeName']).startswith('sector ') else None)
    g = merged(n2, owner, len(old), 'ro communes'); del n2
    write_pack('ro_communes', [p for p, _ in old], g, 'data/ro/2021/communes.json')
    oc = read_topo(DATA('ro/2021/counties')); ok = read_topo(DATA('ro/2021/country'))
    byj = collections.defaultdict(list)
    for (p, _), gg in zip(old, g): byj[p['j']].append(gg)
    assert set(byj) == {p['n'] for p, _ in oc}, set(byj) ^ {p['n'] for p, _ in oc}
    gc = [dissolve(byj[p['n']], fill=1e-5) for p, _ in oc]
    write_pack('ro_counties', [p for p, _ in oc], gc, 'data/ro/2021/counties.json')
    write_pack('ro_country', [p for p, _ in ok], [dissolve(gc, fill=1e-5)], 'data/ro/2021/country.json')

# ================================================================ MOLDOVA
def moldova():
    n1 = read_geo('geoBoundaries-MDA-ADM1.geojson')
    old = read_topo(DATA('md/2024/raions'))
    tr = next(i for i, (p, _) in enumerate(old) if p.get('u') == 'tr')           # Transnistria = MD-SN + MD-BD (Bender)
    owner = pair(old, n1, 'md raions')
    attach(n1, owner, 'md raions', old=old, forced=lambda j: tr if n1[j][0]['shapeISO'] in ('MD-SN', 'MD-BD') else None)
    g = merged(n1, owner, len(old), 'md raions')
    write_pack('md_raions', [p for p, _ in old], g, 'data/md/2024/raions.json')
    ok = read_topo(DATA('md/2024/country'))
    write_pack('md_country', [p for p, _ in ok], [dissolve(g, fill=1e-5)], 'data/md/2024/country.json')

# ================================================================ BULGARIA
def bulgaria():
    mu = read_topo(DATA('bg/2021/municipalities')); oo = read_topo(DATA('bg/2021/oblasts')); ok = read_topo(DATA('bg/2021/country'))
    byj = collections.defaultdict(list)
    for p, g in mu: byj[p['j']].append(g)
    assert set(byj) == {p['n'] for p, _ in oo}, set(byj) ^ {p['n'] for p, _ in oo}
    go = [dissolve(byj[p['n']], fill=1e-5) for p, _ in oo]
    write_pack('bg_oblasts', [p for p, _ in oo], go, 'data/bg/2021/oblasts.json')
    write_pack('bg_country', [p for p, _ in ok], [dissolve(go, fill=1e-5)], 'data/bg/2021/country.json')

if __name__ == '__main__':
    for key, fn in (('hu', hungary), ('md', moldova), ('bg', bulgaria), ('ro', romania)):
        if only in (None, key): log('=====', key); fn()
    log('done')
