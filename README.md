# Census maps - mostly population, ethnic and religious

A static site (GitHub Pages) that draws census data as 3D maps. Every dataset is its own small file that the browser downloads only when someone opens it.

## What goes where

```
index.html                 the app (code + interface text)
README.md
.gitignore                 
data/
  registry.json            list of countries > censuses > datasets (+ names, map start position)
  ro/                      one folder per country (ISO 2-letter code, lowercase)
    2021/                  one folder per census
      meta.json           category names (per language), colours, info/source text
      communes.json       finest level   (TopoJSON: shapes + numbers in one file)
      counties.json       middle level
      country.json        whole country
  hu/2022/                 Hungary (municipalities, districts, counties, country)
  md/2024/                 Moldova (raions + country; Transnistria is unofficial data)
  bg/2021/                 Bulgaria (municipalities, oblasts, country; English + Bulgarian)
tools/
  pack.js                  GeoJSON -> data file (no simplification)
  rebuild-shapes.py        puts the full-detail geoBoundaries shapes into every data file; builds Hungary's Municipalities map
  match-hu-settlements.py  how the 3,154 Hungarian settlements were matched to ADM3 shapes (result: hu-settlements.json)
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

`-1` means the statistics office withheld the value (`*`). Majority, share and "mixed" are calculated in the browser.

`meta.json` has `names` (`eth`/`rel`, one list per language), `colors` (hex per category index), `other` and `unavailable` (index of "Other" and of "Not given", excluded when choosing the majority; `unavailable` may be a list when a census has several such categories, as in Bulgaria) and `info` (source text per language, shown in the information box). `unofficial` holds the footnote of every flagged area (an area with `u`), `short` the tooltip label of that flag (default "Unofficial data †"), `relNote` a religion-only note. The last row of the information box (the contact e-mail) is the same for every census and comes from `index.html` (`contact`).

In `registry.json` a dataset may have `subs`, the title of its breakdown table in the "Select area" card (default "Towns and villages").

A census is only shown in a language that has its category names and info text in `meta.json` (otherwise a notice offers another country); `nb`/`jb` names fall back to `n`/`j`.

## Shapes
All shapes are the geoBoundaries files at full detail, **not simplified** (an earlier version simplified them to about 12%). `tools/rebuild-shapes.py` keeps the names and numbers of every data file and replaces only the geometry; pack.js quantizes the coordinates to a 100,000 x 100,000 grid over the country (about 5-10 m), finer than the map can show.
Hungary's *Municipalities* map has one shape per settlement (3,154) plus Budapest as a single municipality whose 23 districts are its breakdown. The geoBoundaries ADM3 names are corrupted, so the shape of each settlement is listed in `tools/hu-settlements.json` (by shapeID).
Bulgaria: geoBoundaries has no separate Sarnitsa (it is inside Velingrad); it is cut out along the outline that was already in the data. Romania's communes are large (about 16 MB); that is the cost of full detail.
