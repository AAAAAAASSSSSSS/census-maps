# Census maps - mostly population, ethnic and religious

A static site (GitHub Pages) that draws census data as 3D maps. Every dataset is its own small file that the browser downloads only when someone opens it. For now the countries that have a map are: Bulgaria, Republic of Moldova and Romania.

## Internal structure

```
index.html                 the app (code + interface text only)
README.md
.gitignore                 
data/
  registry.json            list of countries > censuses > datasets (+ names, map start position)
  ro/                      one folder per country (ISO 2-letter code, lowercase)
    2021/                  one folder per census
      meta.json           category names (per language), colors, info/source text
      communes.json       finest level   (TopoJSON: shapes + numbers in one file)
      counties.json       middle level
      country.json        whole country (there can be more levels)
  md/2024/                 Moldova (raions + country; Transnistria is unofficial data -> real bummer! )
  bg/2021/                 Bulgaria (municipalities, oblasts, country)
tools/
  pack.js                  GeoJSON -> data file
  build-md-2024.py         Moldova: census tables + shapes -> GeoJSON for pack.js
  build-bg-2021.py         Bulgaria: NSI tables + shapes -> GeoJSON for pack.js (also checks the romanisation of the names)
```

Why one file per dataset: the geometry and its numbers always travel together (no join to get wrong), and the browser fetches only what is on screen. GitHub Pages compresses the JSON automatically.

## Data format
Every dataset file is TopoJSON with one object named `u`. Each area has only these properties:

| key | meaning |
|---|---|
| `n` | name |
| `nb` | (optional) the name in Bulgarian, shown when the interface language is Bulgarian |
| `j` | parent region (finest level only); `jb` is its Bulgarian name |
| `p` | total resident population |
| `e` | array of ethnicity counts, same order as `names.eth` in `meta.json` |
| `r` | array of religion counts, same order as `names.rel` |

`-1` means the statistics office withheld the value (`*`). Majority, share and "mixed" are calculated in the browser, and region borders on the commune map are derived from the communes, so none of that is stored.

`meta.json` has `names` (`eth`/`rel`, one list per language), `colors` (hex per category index), `other` and `unavailable` (index of "Other" and of "Not given", excluded when choosing the majority; `unavailable` may be a list when a census has several such categories, as in Bulgaria) and `info` (source text per language, shown in the information box). `unofficial` holds the footnote of every flagged area (an area with `u`), `short` the tooltip label of that flag (default "Unofficial data †"), `relNote` a religion-only note. The last row of the information box is the same for every census and comes from `index.html` (`contact`).

In `registry.json` a dataset may have `subs`, the title of its breakdown table in the "Select area" card (default "Towns and villages").

## How countries or census years are added - step-by-step process
1. Simplify the shapes (about 1-5 % keeps borders recognisable): `npx mapshaper yyy/xx_adm2.geojson -simplify 5% keep-shapes -o precision=0.0001 build/xx_communes.geojson`
2. Join the census table to the shapes so every feature has `n`, `j`, `p`, `e`, `r` (a small script per country; the INS tables are keyed by name).
3. `cd tools && npm install && node pack.js ../build/xx_communes.geojson ../data/xx/2023/communes.json` (repeat per level).
4. Create `data/xx/2023/meta.json`.
5. Add the country/census/datasets to `data/registry.json`. Dataset `role` is `unit` (finest level, shows the region column and region borders), `region` or `country`.
6. Commit `data/` and push. Nothing in `index.html` changes, except the language list if you add a UI language.

Interface languages: English, Bulgarian, Romanian. A census is only shown in a language that has its category names and info text in `meta.json` (otherwise a notice offers another country); `nb`/`jb` names fall back to `n`/`j`.
