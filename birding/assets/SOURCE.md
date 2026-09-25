# Coastline overview

`uk-context.geojson` contains editable coordinate source data derived from GSHHG
2.3.6 as distributed in basemap-data 2.0.0. It retains LGPL-3.0-or-later.
Copyright and authorship remain with the original data contributors.

Source projects:
- https://www.soest.hawaii.edu/pwessel/gshhg/
- https://github.com/matplotlib/basemap
- https://pypi.org/project/basemap-data/2.0.0/

Changes: intermediate-resolution data, area threshold 12 km², clipped to
longitude [-14, 8], latitude [47, 63], simplified by 0.005 degrees with topology
preservation and rounded to 4 decimal places. Land and lake polygons are retained.
No map tiles were downloaded.

Reproducible conversion: `tools/rebuild_map_outline.py`. The runtime website reads
this GeoJSON directly; no opaque compiled map data is required. See the included
LGPL and GPL text in `licenses/`. This small-scale overview is not for navigation.

`homepage-birding.webp` is a metadata-free, reduced-size copy of the user-provided
`Figures/birds.JPG`, for the homepage entry card. It is not a new photograph or a
claim of a sighting at any of the example places.

# City labels

`uk-cities.js` contains 47 city and regional town labels for the local overview,
selected from Natural Earth's 1:10m populated places (simple) dataset. Coordinates
are rounded to four decimal places; `minZoom` controls visibility relative to the
UK overview, and array order controls label collision priority.

- Source: https://raw.githubusercontent.com/nvkelso/natural-earth-vector/ca96624a56bd078437bca8184e78163e5039ad19/geojson/ne_10m_populated_places_simple.geojson
- Dataset: https://www.naturalearthdata.com/downloads/10m-cultural-vectors/10m-populated-places/
- License: public domain, https://www.naturalearthdata.com/about/terms-of-use/

These are general map labels, separate from the authored birding records.

# Leaflet

`leaflet/` bundles the Leaflet 1.9.4 distribution and its image assets from
https://unpkg.com/leaflet@1.9.4/dist/ . The BSD-2-Clause license is included in
`leaflet/LICENSE`. JavaScript and CSS match the upstream SHA-256 integrity values
in `birding/config.js`. Loading the map library therefore needs no external CDN.
Detailed map tiles are still requested from OpenStreetMap as visitors browse;
they are not bundled or downloaded for offline use.
