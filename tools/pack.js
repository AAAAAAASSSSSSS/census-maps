// Pack one dataset (GeoJSON) into the compact TopoJSON file the site loads.
//   cd tools && npm install && node pack.js input.geojson ../data/xx/2021/communes.json
//
// Input: a GeoJSON FeatureCollection whose features have these properties
//   n  name of the area                         (required)
//   j  name of the parent region, e.g. county   (only for the finest level; used for region borders and the table)
//   p  total resident population                (required)
//   e  array of ethnicity counts, same order as names.eth in meta.json   (-1 = value withheld by the statistics office)
//   r  array of religion counts,  same order as names.rel in meta.json
// Geometry should already be simplified (see README.md); coordinates are quantized to ~1 m by this script.
const fs = require('fs');
const { topology } = require('topojson-server');
const [, , inp, out, q] = process.argv;
if (!inp || !out) { console.error('usage: node pack.js input.geojson output.json [quantization=100000]'); process.exit(1); }
const fc = JSON.parse(fs.readFileSync(inp, 'utf8'));
if (fc.type !== 'FeatureCollection') throw new Error('input must be a FeatureCollection');
let le = null, lr = null;
fc.features.forEach((f, i) => {
  const p = f.properties || {};
  for (const k of ['n', 'p', 'e', 'r']) if (p[k] === undefined) throw new Error(`feature ${i} (${p.n}) has no "${k}"`);
  if (le === null) { le = p.e.length; lr = p.r.length; }
  if (p.e.length !== le || p.r.length !== lr) throw new Error(`feature ${i} (${p.n}): e/r length differs from the first feature`);
  f.properties = { n: p.n, ...(p.j ? { j: p.j } : {}), p: p.p, e: p.e, r: p.r }; // drop everything else
});
const topo = topology({ u: fc }, +q || 1e5); // the object must be called "u"
fs.writeFileSync(out, JSON.stringify(topo));
console.log(`${out}: ${fs.statSync(out).size} bytes, ${fc.features.length} features, ${le} ethnicity + ${lr} religion categories`);
