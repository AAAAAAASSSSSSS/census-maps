#!/usr/bin/env python3
"""North Macedonia: rebuild ONLY the geometry of data/mk/2021/{settlements,municipalities,country}.json from mkd_settlements.gpkg.

Why: the old build converted the gpkg (MGI 1901 / Balkans zone 7) to WGS84 with PROJ, which silently used two different datum
transformations (each only valid inside its own rectangular "area of use"). Inside the rectangle north of lat ~41.85 / west of
lon ~21.8 the points were moved differently from the rest, so every settlement crossing that rectangle's edge was torn: straight
lines and distorted shapes in Kumanovo, Petrovec, Veles, Zelenikovo, Studeničani, Želino, Brvenica, Gostivar ...
Here ONE smooth transformation is applied to every vertex (mk_crs.py), so neighbouring shapes keep sharing their borders.

All census numbers/names (properties) are copied from the existing files untouched.

Usage (repo root; needs only numpy):  python3 tools/rebuild-mk-geometry.py path/to/mkd_settlements.gpkg
"""
import sys, os, json, struct, sqlite3, collections
import numpy as np
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from mk_crs import to_wgs84

gpkg = sys.argv[1] if len(sys.argv) > 1 else 'raw/mkd_settlements.gpkg'
DATA = os.path.join(os.path.dirname(os.path.abspath(__file__)), '..', 'data', 'mk', '2021')

# ------------------------------------------------------------------ read the gpkg (plain WKB, also MultiSurface / CurvePolygon / CompoundCurve made of straight parts)
def hdr(b): return 8 + [0, 32, 48, 48, 64][(b[3] >> 1) & 7]
def rd(b, o):
    e = '<' if b[o] == 1 else '>'; t = struct.unpack_from(e + 'I', b, o + 1)[0]; o += 5
    if t in (12, 6, 11, 7):
        n = struct.unpack_from(e + 'I', b, o)[0]; o += 4; res = []
        for _ in range(n): r, o = rd(b, o); res += r
        return res, o
    if t == 10:
        n = struct.unpack_from(e + 'I', b, o)[0]; o += 4; rings = []
        for _ in range(n): r, o = rd(b, o); rings.append(r[0])
        return [rings], o
    if t == 9:
        n = struct.unpack_from(e + 'I', b, o)[0]; o += 4; pts = []
        for _ in range(n): r, o = rd(b, o); pts.append(r[0] if not pts else r[0][1:])
        return [np.vstack(pts)], o
    if t == 8: raise SystemExit('the file contains circular arcs: densify them first (QGIS: Processing > Segmentize)')
    if t == 2:
        n = struct.unpack_from(e + 'I', b, o)[0]; o += 4
        return [np.frombuffer(b, dtype=e + 'f8', count=n * 2, offset=o).reshape(n, 2).astype(float)], o + n * 16
    if t == 3:
        nr = struct.unpack_from(e + 'I', b, o)[0]; o += 4; rings = []
        for _ in range(nr):
            n = struct.unpack_from(e + 'I', b, o)[0]; o += 4
            rings.append(np.frombuffer(b, dtype=e + 'f8', count=n * 2, offset=o).reshape(n, 2).astype(float)); o += n * 16
        return [rings], o
    raise SystemExit(f'geometry type {t} not supported')
con = sqlite3.connect(gpkg); con.row_factory = sqlite3.Row
tbl = con.execute('select table_name from gpkg_contents').fetchone()[0]
feats = []
for r in con.execute(f'select * from "{tbl}" order by fid'):
    g = r['geom']
    if g is None or len(g) <= hdr(g) + 9: continue                       # the 11 settlements with an empty geometry
    polys, _ = rd(g, hdr(g))
    feats.append(dict(sn=r['ntes_settlement_name'], mn=r['ntes_municipality_name'], polys=polys))
print(len(feats), 'settlements with geometry')

LAT = dict(zip('абвгдѓежзѕијклљмнњопрстќуфхцчџш', ['a','b','v','g','d','gj','e','ž','z','dz','i','j','k','l','lj','m','n','nj','o','p','r','s','t','kj','u','f','h','c','č','dž','š']))
def latin(s):
    if s.lower() == 'маврово и ростуше': return 'Mavrovo and Rostuša'
    if s.upper().startswith('СКОПЈЕ - '): return 'Skopje - ' + latin(s[9:])
    ws = []
    for w in s.replace(' - ', '-').split(' '):
        parts = [''.join(LAT.get(c, c) for c in x.lower()) for x in w.split('-')]
        ws.append('-'.join(p[:1].upper() + p[1:] for p in parts))
    return ' '.join(ws)

# ------------------------------------------------------------------ vertices: one id per distinct source point, one transformation for all
shoelace = lambda r: 0.5 * (np.dot(r[:, 0], np.roll(r[:, 1], -1)) - np.dot(r[:, 1], np.roll(r[:, 0], -1)))
allpts = np.vstack([r for f in feats for p in f['polys'] for r in p])
uniq, inv = np.unique(np.round(allpts, 3), axis=0, return_inverse=True)
inv = inv.reshape(-1)
lon, lat = to_wgs84(uniq[:, 0], uniq[:, 1])
LL = np.round(np.c_[lon, lat], 6)
pos = 0
SLIVER = 1000.0                                                           # m2: seams of the cadastral sheets leave tiny separate pieces; the largest piece is always kept
for f in feats:
    f['P'] = []
    for p in f['polys']:
        rings = []
        for r in p:
            ids = inv[pos:pos + len(r)]; pos += len(r)
            if (ids[0] != ids[-1]): ids = np.append(ids, ids[0])
            rings.append(ids)
        # orientation: exterior counter-clockwise, holes clockwise (needed so that shared borders cancel)
        out = []
        for k, ids in enumerate(rings):
            a = shoelace(uniq[ids])
            if (k == 0 and a < 0) or (k > 0 and a > 0): ids = ids[::-1]
            out.append(ids)
        f['P'].append(dict(rings=out, area=abs(shoelace(uniq[out[0]])) - sum(abs(shoelace(uniq[h])) for h in out[1:])))
    big = max(q['area'] for q in f['P'])
    f['P'] = [q for q in f['P'] if q['area'] == big or q['area'] >= SLIVER]
assert pos == len(allpts)

# ------------------------------------------------------------------ union of shapes by cancelling shared borders
def union(plist, fill_m2=92000.0):
    """plist: polygons (dict rings=[ext, holes..] as vertex-id arrays, exterior ccw). Returns a list of polygons (lists of rings of vertex ids).
    Edges used in both directions disappear; what is left is the outline. Holes smaller than fill_m2 (~1e-5 deg2, slivers where shapes do not quite touch) are filled."""
    E = collections.Counter()
    for q in plist:
        for ids in q['rings']:
            for a, b in zip(ids[:-1], ids[1:]):
                if a != b: E[(int(a), int(b))] += 1
    left = collections.defaultdict(list)
    for (a, b), n in E.items():
        back = E.get((b, a), 0)
        if n > back: left[a] += [b] * (n - back)
    rings = []
    while left:
        a0 = next(iter(left)); ring = [a0]; cur = a0; prev = None
        while True:
            outs = left[cur]
            if len(outs) > 1 and prev is not None:                           # touching rings: take the sharpest right turn so the pieces stay separate
                v0 = uniq[cur] - uniq[prev]
                ang = lambda c: (np.arctan2(*(uniq[c] - uniq[cur])[::-1]) - np.arctan2(v0[1], v0[0]) + np.pi) % (2 * np.pi)
                nxt = min(outs, key=ang)
            else: nxt = outs[0]
            outs.remove(nxt)
            if not outs: del left[cur]
            prev, cur = cur, nxt; ring.append(cur)
            if cur == a0: break
        rings.append(np.array(ring))
    ext = [r for r in rings if shoelace(uniq[r]) > 0]; hol = [r for r in rings if shoelace(uniq[r]) <= 0]
    polys = [[r] for r in ext]
    def inside(pt, r):
        x, y = pt; xs, ys = uniq[r][:, 0], uniq[r][:, 1]
        c = ((ys[:-1] > y) != (ys[1:] > y)) & (x < (xs[1:] - xs[:-1]) * (y - ys[:-1]) / (ys[1:] - ys[:-1] + 1e-30) + xs[:-1])
        return c.sum() % 2 == 1
    for h in hol:
        if abs(shoelace(uniq[h])) < fill_m2: continue
        cand = [(abs(shoelace(uniq[p[0]])), p) for p in polys if inside(uniq[h[0]], p[0])]
        if cand: min(cand, key=lambda c: c[0])[1].append(h)
    return polys

# ------------------------------------------------------------------ TopoJSON writer (shared borders become shared arcs, like topojson-server)
def topology(feature_polys, props, bbox, n=100000):
    """feature_polys: per feature, a list of polygons; polygon = list of rings of vertex ids"""
    x0, y0, x1, y1 = bbox; kx, ky = (n - 1) / (x1 - x0), (n - 1) / (y1 - y0)
    Q = np.c_[np.round((LL[:, 0] - x0) * kx), np.round((LL[:, 1] - y0) * ky)].astype(np.int64)
    rings = []                                                              # (feature, polygon, ring) -> list of quantised points (closed)
    for fi, polys in enumerate(feature_polys):
        for pi, poly in enumerate(polys):
            for ri, r in enumerate(poly):
                pts = [tuple(Q[i]) for i in r]
                pts = [p for k, p in enumerate(pts) if k == 0 or p != pts[k - 1]]
                if len(pts) >= 4 and pts[0] == pts[-1]: rings.append(((fi, pi, ri), pts))
                else: rings.append(((fi, pi, ri), None))
    nb = collections.defaultdict(set)
    for _, pts in rings:
        if pts is None: continue
        m = len(pts) - 1
        for k in range(m): nb[pts[k]].add(frozenset((pts[k - 1], pts[(k + 1) % m])))
    junction = {v for v, s in nb.items() if len(s) > 1}
    arcs, key2i, ref = [], {}, {}
    def loopkey(core):                                                      # a closed ring without junctions: same key for both directions
        def canon(c):
            k = min(range(len(c)), key=lambda i: c[i]); return tuple(c[k:] + c[:k])
        return canon(list(core)), canon(list(core)[::-1])
    for rid, pts in rings:
        if pts is None: ref[rid] = None; continue
        core = pts[:-1]; m = len(core)
        js = [k for k in range(m) if core[k] in junction]
        refs = []
        if not js:
            kf, kb = loopkey(core)
            if kf in key2i: refs.append(key2i[kf])
            elif kb in key2i: refs.append(~key2i[kb])
            else: key2i[kf] = len(arcs); arcs.append(list(kf) + [kf[0]]); refs.append(len(arcs) - 1)
        else:
            seq = core[js[0]:] + core[:js[0]]
            cut = [k for k in range(m) if seq[k] in junction] + [m]
            for a_, b_ in zip(cut, cut[1:]):
                pc = seq[a_:b_ + 1] if b_ < m else seq[a_:] + [seq[0]]
                fw, bw = tuple(pc), tuple(pc[::-1])
                if fw in key2i: refs.append(key2i[fw])
                elif bw in key2i: refs.append(~key2i[bw])
                else: key2i[fw] = len(arcs); arcs.append(list(pc)); refs.append(len(arcs) - 1)
        ref[rid] = refs
    geoms = []
    for fi, polys in enumerate(feature_polys):
        pl = []
        for pi, poly in enumerate(polys):
            rs = [ref[(fi, pi, ri)] for ri in range(len(poly)) if ref[(fi, pi, ri)] is not None]
            if rs and ref[(fi, pi, 0)] is not None: pl.append(rs)
        geoms.append({'type': 'Polygon' if len(pl) == 1 else 'MultiPolygon', 'arcs': pl[0] if len(pl) == 1 else pl, 'properties': props[fi]})
    enc = []
    for a in arcs:
        a = np.array(a); d = np.diff(a, axis=0, prepend=[[0, 0]]); enc.append(d.tolist())
    return {'type': 'Topology', 'objects': {'u': {'type': 'GeometryCollection', 'geometries': geoms}}, 'arcs': enc,
            'bbox': [x0, y0, x1, y1], 'transform': {'scale': [1 / kx, 1 / ky], 'translate': [x0, y0]}}

# ------------------------------------------------------------------ old properties
def old(name): return json.load(open(os.path.join(DATA, name)))
os_, om, oc = old('settlements.json'), old('municipalities.json'), old('country.json')
sprops = [g['properties'] for g in os_['objects']['u']['geometries']]
assert len(sprops) == len(feats) == 1781
for f, p in zip(feats, sprops):
    assert latin(f['sn']) == p['n'] and latin(f['mn']) == p['j'], (f['sn'], p['n'], f['mn'], p['j'])
bbox = om['bbox']

# settlements
sp = [[q['rings'] for q in f['P']] for f in feats]
write = lambda name, t: json.dump(t, open(os.path.join(DATA, name), 'w', encoding='utf-8'), ensure_ascii=False, separators=(',', ':'))
write('settlements.json', topology(sp, sprops, bbox))

# municipalities (union of their settlements)
bym = collections.defaultdict(list)
for f in feats: bym[latin(f['mn'])].append(f)
mprops = [g['properties'] for g in om['objects']['u']['geometries']]
mshape = []
for p in mprops:
    u = union([q for f in bym[p['n']] for q in f['P']])
    print(f"{p['n']:28s} {len(u)} part(s), holes kept: {sum(len(x) - 1 for x in u)}")
    mshape.append(u)
assert set(bym) == {p['n'] for p in mprops}
write('municipalities.json', topology(mshape, mprops, bbox))

# country
cprops = [g['properties'] for g in oc['objects']['u']['geometries']]
write('country.json', topology([union([q for f in feats for q in f['P']])], cprops, bbox))
print('done')
