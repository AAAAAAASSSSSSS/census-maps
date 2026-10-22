# Census maps - mostly population, ethnic and religious (MAYBE language)

A static site (GitHub Pages) that draws census data as 3D maps. **No data is stored inside `index.html`**: every dataset is its own small file that the browser downloads only when someone opens it.

## What goes where

```
index.html                 the app (code + interface text only, ~30 KB)
README.md
.gitignore                 keeps raw/ out of the repository
data/
  registry.json            list of countries > censuses > datasets (+ names, map start position)
  ro/                      one folder per country (ISO 2-letter code, lowercase)
    2021/                  one folder per census
      meta.json           category names (per language), colours, info/source text
      communes.json       finest level   (TopoJSON: shapes + numbers in one file)
      counties.json       middle level
      country.json        whole country
tools/
  pack.js                  GeoJSON -> data file (see "Adding a country")
raw/                       NOT committed: original geojsons and INS tables
```

Why one file per dataset: the geometry and its numbers always travel together (no join to get wrong), and the browser fetches only what is on screen. GitHub Pages compresses the JSON automatically, so Romania costs about **0.75 MB** on first open of the commune map and a few KB for counties/country.

## Keep `raw/` out of GitHub
GitHub rejects files over 100 MB and `geoBoundaries-ROU-ADM2_communes.geojson` is 195 MB. Keep the originals on your computer (or in a release/cloud drive); the `.gitignore` already skips a `raw/` folder.

## Testing locally
Opening `index.html` by double-click will not work (browsers block `fetch` on `file://`). Run in the repo folder:
`python3 -m http.server 8000` and open http://localhost:8000

## Data format
Every dataset file is TopoJSON with one object named `u`. Each area has only these properties:

| key | meaning |
|---|---|
| `n` | name |
| `j` | parent region (finest level only) |
| `p` | total resident population |
| `e` | array of ethnicity counts, same order as `names.eth` in `meta.json` |
| `r` | array of religion counts, same order as `names.rel` |

`-1` means the statistics office withheld the value (`*`). Majority, share and "mixed" are **calculated in the browser**, and region borders on the commune map are derived from the communes, so none of that is stored.

`meta.json` has `names` (`eth`/`rel`, one list per language), `colors` (hex per category index), `other` and `unavailable` (index of "Other" and "Not given", excluded when choosing the majority) and `info` (source text per language).

## Adding a country (or a new census year)
1. Put the source files in `raw/`.
2. Simplify the shapes (about 1-5 % keeps borders recognisable): `npx mapshaper raw/xx_adm2.geojson -simplify 5% keep-shapes -o precision=0.0001 build/xx_communes.geojson`
3. Join the census table to the shapes so every feature has `n`, `j`, `p`, `e`, `r` (a small script per country; the INS tables are keyed by name).
4. `cd tools && npm install && node pack.js ../build/xx_communes.geojson ../data/xx/2023/communes.json` (repeat per level).
5. Create `data/xx/2023/meta.json` (copy the Romanian one and edit).
6. Add the country/census/datasets to `data/registry.json`. Dataset `role` is `unit` (finest level, shows the region column and region borders), `region` or `country`.
7. Commit `data/` and push. Nothing in `index.html` changes, except the language list if you add a UI language.

Check the numbers against the official table before publishing: the country row of the table is the truth for the country level (the sum of the communes is lower because small values are withheld).
