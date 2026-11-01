"""Tiny TopoJSON toolkit (numpy only), used by the rebuild scripts.
union(): merge shapes that share exact vertices by cancelling the borders they share.
topology(): write TopoJSON where shared borders become shared arcs (what topojson-server does)."""
import collections
import numpy as np
shoelace = lambda r: 0.5 * (np.dot(r[:, 0], np.roll(r[:, 1], -1)) - np.dot(r[:, 1], np.roll(r[:, 0], -1)))

# ------------------------------------------------------------------ union of shapes by cancelling shared borders
def union(plist, uniq, fill_m2=92000.0):
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
def topology(feature_polys, props, bbox, LL, n=100000):
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

