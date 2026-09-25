#!/usr/bin/env python3
"""Optional developer task, NOT needed to add birding records.

Rebuild the supplied, editable GeoJSON overview from basemap-data 2.0.0.
Install optional dependencies: python -m pip install basemap==2.0.0 shapely
The GSHHG-derived coordinates retain LGPL-3.0-or-later; see birding/assets/licenses/.
"""
from pathlib import Path
import json


def main():
    from mpl_toolkits.basemap import Basemap
    from shapely.geometry import Polygon, mapping, box

    root = Path(__file__).resolve().parents[1]
    model = Basemap(projection='cyl', llcrnrlon=-14, llcrnrlat=47,
                    urcrnrlon=8, urcrnrlat=63, resolution='i', area_thresh=12)
    features = []
    for (xs, ys), kind in zip(model.coastpolygons, model.coastpolygontypes):
        if kind not in (1, 2):
            continue
        geometry = Polygon(zip(xs, ys)).buffer(0).intersection(box(-14, 47, 8, 63))
        if geometry.is_empty:
            continue
        geometry = geometry.simplify(0.005, preserve_topology=True)
        features.append({'type': 'Feature', 'properties': {'kind': 'land' if kind == 1 else 'water'},
                         'geometry': mapping(geometry)})
    data = {'type': 'FeatureCollection', 'features': features}
    # Rounding gives sufficient precision for a small-scale, non-navigational overview.
    def rounded(value):
        if isinstance(value, float): return round(value, 4)
        if isinstance(value, (list, tuple)): return [rounded(x) for x in value]
        if isinstance(value, dict): return {k: rounded(v) for k, v in value.items()}
        return value
    data = rounded(data)
    out = root / 'birding/assets/uk-context.geojson'
    out.write_text(json.dumps(data, separators=(',', ':')) + '\n', encoding='utf-8')
    js = root / 'birding/assets/uk-context.js'
    js.write_text('window.BIRDING_UK_CONTEXT = ' + json.dumps(data, separators=(',', ':')) + ';\n', encoding='utf-8')
    print(f'Wrote {out.name} ({out.stat().st_size:,} bytes) and {js.name} ({js.stat().st_size:,} bytes).')


if __name__ == '__main__': main()
