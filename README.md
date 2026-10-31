# Census maps - population, ethnic and religious

A static site (GitHub Pages) that draws census data as 3D maps. Every dataset is its own small file that the browser downloads only when someone opens it.

## Structure

```
index.html                 the app (code + interface text)
README.md
.gitignore                 
data/
  registry.json            list of countries > censuses > datasets (+ names, map start position)
  ro/                      one folder per country
    2021/                  one folder per census
      meta.json           category names (per language), colours, info/source text
      communes.json       finest level   (TopoJSON: shapes + numbers in one file)
      counties.json       middle level
      country.json        whole country
  hu/2022/                 Hungary (municipalities, districts, counties, country)
  md/2024/                 Moldova (raions + country; Transnistria is unofficial data)
  bg/2021/                 Bulgaria (municipalities, oblasts, country)
  al/2023/                 Albania (administrative units, municipalities, counties, country)
  mk/2021/                 North Macedonia (settlements, municipalities, country; English only)
tools/
  pack.js                  GeoJSON -> data file (no simplification)
  rebuild-shapes.py        puts the full-detail geoBoundaries shapes into every data file; builds Hungary's Municipalities map
  match-hu-settlements.py  how the 3,154 Hungarian settlements were matched to ADM3 shapes (result: hu-settlements.json)
  build-md-2024.py         Moldova: census tables + shapes -> GeoJSON for pack.js
  build-bg-2021.py         Bulgaria: NSI tables + shapes -> GeoJSON for pack.js (also checks the romanisation of the names)
  build-al-2023.py         Albania: INSTAT tables + shapes -> GeoJSON for pack.js (shapes are matched to the 373 admin units here)
  build-mk-2021.py         North Macedonia: MakStat tables + settlement polygons -> GeoJSON for pack.js
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
All shapes are the geoBoundaries files at full detail, **not simplified**. `tools/rebuild-shapes.py` keeps the names and numbers of every data file and replaces only the geometry; pack.js quantizes the coordinates to a 100,000 x 100,000 grid over the country (about 5-10 m), finer than the map can show.
Hungary's *Municipalities* map has one shape per settlement plus the 23 districts of Budapest (which has no figures per settlement). The shape of each settlement is listed in `tools/hu-settlements.json` (by shapeID).
Every upper level is the union of the level under it (Hungary: settlements -> districts -> counties -> country). Bulgaria's municipalities are the shapes of `build-bg-2021.py`.

## Several countries on one map
The button right of *Select area* opens a box with a checkbox per country (the current one ticked). With two or more ticked, each country gets its census and its levels in the panel, and all of them are drawn together. The groups of all censuses are merged by name (a few religions that have different official names in different countries are merged through `ALIAS` in index.html), ordered by their total number of people in the selected countries, and every area keeps its own country's figures. Notes and warnings of every selected country are shown (information button, notes below the legend, area cards). Ticking only one country returns to the normal map.