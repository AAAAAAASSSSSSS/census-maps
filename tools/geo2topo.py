#!/usr/bin/env python3
"""Pack (and, only if keep < 1, simplify) a GeoJSON FeatureCollection and pack it into the TopoJSON file the site loads.
By default (keep=1.0) nothing is simplified, the shapes keep every point. keep=0.12 does what `mapshaper -simplify 12% keep-shapes` + `node pack.js` do  (numpy is the only dependency), for when those are not available.

  python3 tools/geo2topo.py input.geojson output.json [keep=1.0] [quantization=100000]

Input: a FeatureCollection with the properties described in tools/pack.js (n, nb, j, jb, p, e, r, u, b). Neighbouring polygons must share
their border vertices exactly (true for the boundary files used here); shared borders become shared arcs, so simplifying cannot open gaps
between neighbours and the region borders drawn by the site (topojson.mesh) keep working.
  1. coordinates are quantized (default 1e5 steps over the bounding box, the same grid pack.js uses)
  2. rings are cut into arcs wherever the set of polygons using a border changes; identical arcs are stored once
  3. every arc is simplified with Visvalingam-Whyatt; the `keep` fraction of all removable vertices with the largest effective area survives
  4. a ring never drops below 4 points (keep-shapes)
"""
import json, sys, heapq
import numpy as np

KEEP_KEYS = ('n', 'nb', 'j', 'jb', 'p', 'e', 'r', 'u', 'b')

def vw(pts):
    """Visvalingam-Whyatt effective areas of the interior points of an open polyline (ends get inf)."""
    n = len(pts); eff = [float('inf')] * n
    if n < 3: return eff
    prv = list(range(-1, n - 1)); nxt = list(range(1, n + 1)); alive = [True] * n
    def tri(i):
        (ax, ay), (bx, by), (cx, cy) = pts[prv[i]], pts[i], pts[nxt[i]]
        return abs((bx - ax) * (cy - ay) - (cx - ax) * (by - ay)) / 2
    h = [(tri(i), i) for i in range(1, n - 1)]; heapq.heapify(h)
    cur = {i: a for a, i in h}; last = 0.0
    while h:
        a, i = heapq.heappop(h)
        if not alive[i] or cur.get(i) != a: continue
        last = max(last, a); eff[i] = last; alive[i] = False
        p, q = prv[i], nxt[i]; nxt[p] = q; prv[q] = p
        for j in (p, q):
            if 0 < j < n - 1 and alive[j]:
                cur[j] = tri(j); heapq.heappush(h, (cur[j], j))
    return eff

def main():
    inp, out = sys.argv[1], sys.argv[2]
    keep = float(sys.argv[3]) if len(sys.argv) > 3 else 1.0
    q = int(sys.argv[4]) if len(sys.argv) > 4 else 100000
    fc = json.load(open(inp, encoding='utf-8'))
    xs = [pt[0] for f in fc['features'] for poly in (f['geometry']['coordinates'] if f['geometry']['type'] == 'MultiPolygon' else [f['geometry']['coordinates']]) for r in poly for pt in r]
    ys = [pt[1] for f in fc['features'] for poly in (f['geometry']['coordinates'] if f['geometry']['type'] == 'MultiPolygon' else [f['geometry']['coordinates']]) for r in poly for pt in r]
    x0, x1, y0, y1 = min(xs), max(xs), min(ys), max(ys)
    kx, ky = (q - 1) / (x1 - x0), (q - 1) / (y1 - y0)
    Q = lambda pt: (round((pt[0] - x0) * kx), round((pt[1] - y0) * ky))

    # ---- rings, quantized, without repeated points (rings are stored open: the closing point is implied)
    rings, owner_of = [], []        # rings[k] = list of points; owner_of[k] = (feature, polygon, ring index)
    for fi, f in enumerate(fc['features']):
        g = f['geometry']; polys = g['coordinates'] if g['type'] == 'MultiPolygon' else [g['coordinates']]
        for pi, poly in enumerate(polys):
            for ri, ring in enumerate(poly):
                pts = []
                for pt in ring:
                    c = Q(pt)
                    if not pts or pts[-1] != c: pts.append(c)
                if len(pts) > 1 and pts[0] == pts[-1]: pts.pop()
                owner_of.append((fi, pi, ri)); rings.append(pts if len(pts) >= 3 else None)
    # ---- which rings use each edge
    edge = {}
    for k, r in enumerate(rings):
        if r is None: continue
        for a, b in zip(r, r[1:] + r[:1]):
            edge.setdefault((a, b) if a < b else (b, a), set()).add(k)
    E = lambda a, b: edge[(a, b) if a < b else (b, a)]
    # ---- cut into arcs, de-duplicate
    arcs, arc_ix, ring_arcs = [], {}, []
    def add(pts):
        t = tuple(pts)
        if t in arc_ix: return arc_ix[t]
        rt = t[::-1]
        if rt in arc_ix: return ~arc_ix[rt]
        arcs.append(list(t)); arc_ix[t] = len(arcs) - 1; return len(arcs) - 1
    for k, r in enumerate(rings):
        if r is None: ring_arcs.append(None); continue
        n = len(r)
        brk = [i for i in range(n) if E(r[i - 1], r[i]) != E(r[i], r[(i + 1) % n])]
        if not brk:      # a ring that is entirely shared or entirely free: one closed arc, started at its smallest point
            s = min(range(n), key=lambda i: r[i]); rr = r[s:] + r[:s]
            ring_arcs.append([add(rr + [rr[0]])]); continue      # the same ring walked the other way is found by add() as a reversed arc
        seq = []
        for a, b in zip(brk, brk[1:] + [brk[0] + n]):
            seq.append(add([r[i % n] for i in range(a, b + 1)]))
        ring_arcs.append(seq)
    # ---- simplify (global threshold on effective area)
    effs = [vw(a) for a in arcs]
    allv = np.array([v for e in effs for v in e[1:-1]])
    thr = 0 if keep >= 1 else float(np.partition(allv, int(len(allv) * (1 - keep)))[int(len(allv) * (1 - keep))]) if len(allv) else 0
    kept = [[i == 0 or i == len(e) - 1 or v >= thr for i, v in enumerate(e)] for e in effs]
    def npts(k):      # distinct points a ring still has
        return len({p for ai in ring_arcs[k] for p, kp in zip(arcs[ai if ai >= 0 else ~ai], kept[ai if ai >= 0 else ~ai]) if kp})
    for k, ra in enumerate(ring_arcs):          # keep-shapes
        if ra is None: continue
        while npts(k) < 3:
            best = max(((effs[a if a >= 0 else ~a][i], a if a >= 0 else ~a, i) for a in ra for i in range(len(effs[a if a >= 0 else ~a])) if not kept[a if a >= 0 else ~a][i]), default=None)
            if not best: break
            kept[best[1]][best[2]] = True
    arcs = [[p for p, kp in zip(a, kk) if kp] for a, kk in zip(arcs, kept)]
    # ---- geometries
    pos = {o: k for k, o in enumerate(owner_of)}
    G = []
    for fi, f in enumerate(fc['features']):
        g = f['geometry']; polys = g['coordinates'] if g['type'] == 'MultiPolygon' else [g['coordinates']]
        op = [[ring_arcs[pos[(fi, pi, ri)]] for ri in range(len(poly)) if ring_arcs[pos[(fi, pi, ri)]] is not None] for pi, poly in enumerate(polys)]
        op = [p for p in op if p and p[0]]
        pr = {k: f['properties'][k] for k in KEEP_KEYS if f['properties'].get(k) is not None}
        G.append({'type': 'MultiPolygon' if len(op) > 1 else 'Polygon', 'arcs': op if len(op) > 1 else op[0], 'properties': pr})
    enc = []
    for a in arcs:
        px = py = 0; e = []
        for x, y in a: e.append([x - px, y - py]); px, py = x, y
        enc.append(e)
    topo = {'type': 'Topology', 'objects': {'u': {'type': 'GeometryCollection', 'geometries': G}}, 'arcs': enc,
            'bbox': [x0, y0, x1, y1], 'transform': {'scale': [1 / kx, 1 / ky], 'translate': [x0, y0]}}
    json.dump(topo, open(out, 'w', encoding='utf-8'), ensure_ascii=False, separators=(',', ':'))
    import os
    print(f'{out}: {os.path.getsize(out)} bytes, {len(G)} features, {len(arcs)} arcs, {sum(len(a) for a in arcs)} points (threshold {thr:.1f})')

main()
