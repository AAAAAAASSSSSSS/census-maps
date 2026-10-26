#!/usr/bin/env python3
"""Put the most detailed shapes (geoBoundaries, NOT simplified) into the data files, and build the Hungarian municipality map.

  python3 tools/rebuild-shapes.py raw build [only]        (from the repo root; needs `pip install shapely numpy`, and `cd tools && npm install`)

  raw/   the geoBoundaries files (https://www.geoboundaries.org, release "gbOpen"), under these names:
           geoBoundaries-HUN-ADM2-districts.geojson   geoBoundaries-HUN-ADM3-municipalities.geojson
           geoBoundaries-ROU-ADM0.geojson  -ADM1  -ADM2        geoBoundaries-MDA-ADM0.geojson  -ADM1        geoBoundaries-BGR-ADM0.geojson  -ADM1  -ADM2
  build/ the GeoJSON files written here (then packed into data/ by pack.js; build/ is not committed)
  only   optional: hu, ro, md or bg, to rebuild one country

What it does. The numbers (p, e, r, b ...) and the names of every area stay exactly as they are in data/<cc>/<census>/*.json; only the
geometry is replaced. Each existing area is paired with its detailed shape by position (the area's inner point must fall inside the new
shape), so no names are needed. Shapes that belong to an area but did not get paired (parts of a commune that lie apart, the Bucharest
sectors, Bender next to Transnistria, Polgárdi next to Székesfehérvár) are joined to it. Nothing is simplified: pack.js only quantizes the
coordinates to a 100,000 x 100,000 grid over the country (about 5-10 m), far finer than the highest zoom of the map shows.

Shapes (per dataset)
  hu districts   ADM2 (the only Hungarian level with the 23 districts of Budapest) | hu counties = districts dissolved by county | hu country = all districts dissolved
  hu settlements ADM3, one shape per census settlement (3,154) + Budapest as one municipality (its 23 districts are its breakdown `b`).
                 The ADM3 names are corrupted, so tools/hu-settlements.json says which shape (shapeID) is which settlement
                 (made by tools/match-hu-settlements.py); this is the "Municipalities" map mode of Hungary.
  ro communes ADM2 | counties ADM1 | country = the 42 counties dissolved (ADM0 has only 2,903 points, the counties 740,000)
  md raions   ADM1 | country ADM0
  bg municipalities ADM2 | oblasts ADM1 | country ADM0
The geoBoundaries files of all four countries share their border vertices exactly (checked), which pack.js needs to store every border once and
the site needs to draw region borders; nothing here changes that.
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
    """old = [(props, geom)] (existing areas), new = [(props, geom)] (detailed shapes).
    Returns owner[j] = index of the old area whose inner point lies in new shape j (None = not paired). Every old area must get exactly one."""
    tree = STRtree([g for _, g in new])
    owner = [None] * len(new)
    for i, (p, g) in enumerate(old):
        cands = []
        # an inner point of the old (simplified) area; try the point of its largest part first
        parts = sorted(polys(g), key=lambda x: -x.area)
        for part in parts:
            pt = part.representative_point()
            cands = [j for j in tree.query(pt) if new[j][1].contains(pt)]
            if len(cands) == 1: break
        assert len(cands) == 1, f'{label}: {p.get("n")} has {len(cands)} shapes at its inner point'
        assert owner[cands[0]] is None, f'{label}: two areas ({old[owner[cands[0]]][0].get("n")}, {p.get("n")}) fall in the same shape'
        owner[cands[0]] = i
    return owner

def attach(new, owner, label, name_of_old=None, forced=None):
    """Join the shapes that are not paired to the paired area they belong to.
    forced(j) -> old index or None (explicit rule). Otherwise: a paired neighbour with the same name, else the neighbour with the longest shared border,
    else (the part lies apart) the nearest paired shape with the same name."""
    tree = STRtree([g for _, g in new])
    rest = [j for j, o in enumerate(owner) if o is None]
    for j in rest:
        pj, gj = new[j]
        if forced and forced(j) is not None: owner[j] = forced(j); log(f'  {label}: {pj.get("shapeName")} joined to {forced(j)} (rule)'); continue
        near = [k for k in tree.query(gj.buffer(1e-5)) if owner[k] is not None and k != j and new[k][1].distance(gj) < 1e-5]
        pick = None
        if near:
            same = [k for k in near if name_of_old and fold(pj['shapeName']) == name_of_old(owner[k])]
            pool = same or near
            pick = max(pool, key=lambda k: new[k][1].boundary.intersection(gj.buffer(1e-5)).length)
        else:
            same = [k for k, o in enumerate(owner) if o is not None and name_of_old and fold(pj['shapeName']) == name_of_old(o)]
            if same: pick = min(same, key=lambda k: new[k][1].distance(gj))
        assert pick is not None, f'{label}: shape {pj.get("shapeName")} ({pj.get("shapeID")}) belongs to no area'
        owner[j] = owner[pick]
    log(f'{label}: {len(rest)} shapes joined to a neighbour')

def merged(new, owner, n_old, label):
    geoms = []
    for i in range(n_old):
        parts = [new[j][1] for j, o in enumerate(owner) if o == i]
        assert parts, f'{label}: area {i} has no shape'
        geoms.append(parts[0] if len(parts) == 1 else unary_union(parts))
    return geoms

def dissolve(geoms, fill=1e-5):
    """union; holes smaller than `fill` deg2 (slivers between shapes that do not quite touch) are filled"""
    u = unary_union(geoms)
    ps = []
    for p in polys(u):
        ps.append(Polygon(p.exterior, [r for r in p.interiors if Polygon(r).area >= fill]))
    return only_polygons(unary_union(ps))

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
    # --- districts: pair, join Polgárdi (former district, part of Székesfehérvár district in 2022), node
    owner = pair(old_d, d2, 'hu districts')
    attach(d2, owner, 'hu districts', name_of_old=None)
    g = merged(d2, owner, len(old_d), 'hu districts')
    write_pack('hu_districts', [p for p, _ in old_d], g, 'data/hu/2022/districts.json')
    # --- counties = districts dissolved by county; country = all districts
    cg = []
    for pc, _ in old_c:
        parts = [g[i] for i, (p, _) in enumerate(old_d) if p['j'] == pc['n']]
        assert parts, pc['n']
        cg.append(dissolve(parts))
    assert len(cg) == len(old_c)
    write_pack('hu_counties', [p for p, _ in old_c], cg, 'data/hu/2022/counties.json')
    write_pack('hu_country', [p for p, _ in old_k], [dissolve(g)], 'data/hu/2022/country.json')
    # --- settlements (municipalities): ADM3 shapes picked by tools/hu-settlements.json
    mp = json.load(open(os.path.join(HERE, 'hu-settlements.json'), encoding='utf-8'))
    by_id = {p['shapeID']: gg for p, gg in d3}
    assert len(by_id) == len(d3)
    props, geoms, seen = [], [], set()
    for pd, _ in old_d:
        for s in pd.get('b', []):
            sid = mp['shapes'][f"{pd['j']}|{pd['n']}|{s['n']}"]; assert sid not in seen; seen.add(sid)
            props.append(dict(n=s['n'], j=pd['j'], p=s['p'], e=s['e'], r=s['r'])); geoms.append(by_id[sid])
    assert len(props) == 3154
    bp = next(p for p, _ in old_c if p['n'] == 'Budapest')                  # Budapest is one settlement; its 23 districts are the breakdown
    bud = [by_id[i] for i in mp['budapest']]; assert not seen & set(mp['budapest'])
    props.append(dict(n='Budapest', j='Budapest', p=bp['p'], e=bp['e'], r=bp['r'], b=bp['b'])); geoms.append(dissolve(bud))
    assert sum(p['p'] for p in props) == old_k[0][0]['p'], 'settlement populations do not add up to the country'
    write_pack('hu_settlements', props, geoms, 'data/hu/2022/settlements.json')

def write_pack(name, props, geoms, dst):
    pack(write(name, props, geoms), dst)

# ================================================================ ROMANIA
def romania():
    n2 = read_geo('geoBoundaries-ROU-ADM2.geojson'); n1 = read_geo('geoBoundaries-ROU-ADM1.geojson')
    old = read_topo(DATA('ro/2021/communes'))
    owner = pair(old, n2, 'ro communes')
    bucharest = next(i for i, (p, _) in enumerate(old) if p['n'] == 'MUNICIPIUL BUCUREȘTI')
    core = lambda i: fold(re.sub(r'^(MUNICIPIUL|ORAȘ|ORAŞ|COMUNA)\s+', '', old[i][0]['n']))
    attach(n2, owner, 'ro communes', name_of_old=core, forced=lambda j: bucharest if fold(n2[j][0]['shapeName']).startswith('sector ') else None)
    # the pairing may have put the point of Bucharest into sector 1 only: all six sectors are now owned by Bucharest
    g = merged(n2, owner, len(old), 'ro communes')
    write_pack('ro_communes', [p for p, _ in old], g, 'data/ro/2021/communes.json')
    del g
    oc = read_topo(DATA('ro/2021/counties')); o1 = pair(oc, n1, 'ro counties'); assert None not in o1
    gc = merged(n1, o1, len(oc), 'ro counties')
    write_pack('ro_counties', [p for p, _ in oc], gc, 'data/ro/2021/counties.json')
    ok = read_topo(DATA('ro/2021/country'))
    write_pack('ro_country', [p for p, _ in ok], [dissolve(gc)], 'data/ro/2021/country.json')

# ================================================================ MOLDOVA
def moldova():
    n1 = read_geo('geoBoundaries-MDA-ADM1.geojson'); n0 = read_geo('geoBoundaries-MDA-ADM0.geojson')
    old = read_topo(DATA('md/2024/raions'))
    tr = next(i for i, (p, _) in enumerate(old) if p.get('u') == 'tr')           # Transnistria = MD-SN + MD-BD (Bender)
    owner = pair(old, n1, 'md raions')
    attach(n1, owner, 'md raions', forced=lambda j: tr if n1[j][0]['shapeISO'] in ('MD-SN', 'MD-BD') else None)
    assert sum(o is not None for o in owner) == len(owner)
    g = merged(n1, owner, len(old), 'md raions')
    write_pack('md_raions', [p for p, _ in old], g, 'data/md/2024/raions.json')
    ok = read_topo(DATA('md/2024/country'))
    write_pack('md_country', [p for p, _ in ok], [n0[0][1]], 'data/md/2024/country.json')

# ================================================================ BULGARIA
def bulgaria():
    n2 = read_geo('geoBoundaries-BGR-ADM2.geojson'); n1 = read_geo('geoBoundaries-BGR-ADM1.geojson'); n0 = read_geo('geoBoundaries-BGR-ADM0.geojson')
    old = read_topo(DATA('bg/2021/municipalities'))
    # geoBoundaries has no shape of its own for Sarnitsa (it is inside "Velingrad", 646 km2 = 492 + 158): cut it out along the existing Sarnitsa outline
    vel = next(g for p, g in old if p['n'] == 'Velingrad')
    iv = next(j for j, (p, _) in enumerate(n2) if p['shapeName'] == 'Velingrad')
    v = n2[iv][1]; s_new = v.difference(vel)                               # what is not Velingrad is Sarnitsa (this fits the old areas better than cutting along the Sarnitsa outline)
    sp = sorted(polys(s_new), key=lambda x: -x.area)                       # slivers left along the cut go back to Velingrad
    s_new = sp[0]; v_new = only_polygons(unary_union([v.difference(s_new)]))
    log(f'bg: Velingrad shape split: {v_new.area*7500:.0f} + {s_new.area*7500:.0f} km2 (was {v.area*7500:.0f})')
    n2[iv] = (n2[iv][0], v_new); n2.append(({'shapeName': 'Sarnitsa', 'shapeID': 'split-from-Velingrad'}, s_new))
    core = lambda i: fold(old[i][0]['n'])
    owner = pair(old, n2, 'bg municipalities')
    attach(n2, owner, 'bg municipalities', name_of_old=core)                  # the second part of Zlatitsa
    write_pack('bg_municipalities', [p for p, _ in old], merged(n2, owner, len(old), 'bg municipalities'), 'data/bg/2021/municipalities.json')
    oo = read_topo(DATA('bg/2021/oblasts')); owner = pair(oo, n1, 'bg oblasts'); assert None not in owner
    write_pack('bg_oblasts', [p for p, _ in oo], merged(n1, owner, len(oo), 'bg oblasts'), 'data/bg/2021/oblasts.json')
    ok = read_topo(DATA('bg/2021/country'))
    write_pack('bg_country', [p for p, _ in ok], [n0[0][1]], 'data/bg/2021/country.json')

if __name__ == '__main__':
    for key, fn in (('hu', hungary), ('md', moldova), ('bg', bulgaria), ('ro', romania)):
        if only in (None, key): log('=====', key); fn()
    log('done')
