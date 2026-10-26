// Pack one dataset (GeoJSON) into the compact TopoJSON file the site loads.
//   cd tools && npm install && node pack.js input.geojson ../data/xx/2021/communes.json
//
// Input: a GeoJSON FeatureCollection whose features have these properties
//   n  name of the area                         (required)
//   j  name of the parent region, e.g. county   (only for the finest level; used for region borders and the table)
//   nb / jb  (optional) the same two names in Bulgarian; shown instead of n / j when the interface language is Bulgarian
//            (breakdown entries may carry nb too)
//   p  total resident population                (required)
//   e  array of ethnicity counts, same order as names.eth in meta.json   (-1 = value withheld by the statistics office,
//      null = category not recorded; the whole array may be null = no ethnicity data for this area)
//   r  array of religion counts,  same order as names.rel in meta.json   (same rules; may be null)
//   u  (optional) id of a note in meta.json ("unofficial" / "relNote", keyed by this id): the area is marked with a dagger and the note is shown
//   b  (optional) breakdown shown by the "Select area" card: array of {n, p, e, r, y?, c?}
//      = name, population, ethnicity counts, religion counts (null = none), y = kind ('t' town, 's' sector),
//      a = 1 when the population is only approximate, nested children (same shape)
//      Moldova uses it for its towns/communes and the Chisinau sectors.
// Geometry is NOT simplified any more (see README.md); coordinates are only quantized to a 100,000 x 100,000 grid over the country (about 5-10 m) by this script.
const fs = require('fs');
const { topology } = require('topojson-server');
const [, , inp, out, q] = process.argv;
if (!inp || !out) { console.error('usage: node pack.js input.geojson output.json [quantization=100000]'); process.exit(1); }
const fc = JSON.parse(fs.readFileSync(inp, 'utf8'));
if (fc.type !== 'FeatureCollection') throw new Error('input must be a FeatureCollection');
let le = null, lr = null; // category counts, taken from the first feature that has data
fc.features.forEach((f, i) => {
  const p = f.properties || {};
  for (const k of ['n', 'p', 'e', 'r']) if (p[k] === undefined) throw new Error(`feature ${i} (${p.n}) has no "${k}" (use null when there is no data)`);
  if (le === null && p.e) le = p.e.length;
  if (lr === null && p.r) lr = p.r.length;
  if ((p.e && p.e.length !== le) || (p.r && p.r.length !== lr)) throw new Error(`feature ${i} (${p.n}): e/r length differs from the first feature`);
  if (p.b) { // validate the breakdown: every entry needs the same number of categories as the area itself
    const chk = (u, where) => {
      if (u.n === undefined || u.p === undefined || u.e === undefined || u.r === undefined) throw new Error(`${where}: breakdown entry ${JSON.stringify(u.n)} is missing n/p/e/r (use null when there is no data)`);
      if ((u.e && u.e.length !== le) || (u.r && u.r.length !== lr)) throw new Error(`${where}: breakdown entry ${u.n} has a different number of categories`);
      (u.c || []).forEach(c => chk(c, where));
    };
    p.b.forEach(u => chk(u, p.n));
  }
  f.properties = { n: p.n, ...(p.nb ? { nb: p.nb } : {}), ...(p.j ? { j: p.j } : {}), ...(p.jb ? { jb: p.jb } : {}), p: p.p, e: p.e, r: p.r, ...(p.u ? { u: p.u } : {}), ...(p.b ? { b: p.b } : {}) }; // drop everything else
});
const topo = topology({ u: fc }, +q || 1e5); // the object must be called "u"
fs.writeFileSync(out, JSON.stringify(topo));
console.log(`${out}: ${fs.statSync(out).size} bytes, ${fc.features.length} features, ${le} ethnicity + ${lr} religion categories`);
