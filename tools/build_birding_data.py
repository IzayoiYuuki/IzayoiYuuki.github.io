#!/usr/bin/env python3
"""Rebuild the map index, file:// data bundle, and JavaScript-free photo catalogue."""
import argparse
from pathlib import Path
import sys
from birding_common import ROOT, ValidationError, build_site, load_places


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--root', type=Path, default=ROOT, help='Homepage root (normally detected automatically)')
    parser.add_argument('--remove-demos', action='store_true', help='Delete ONLY demo:true source JSON entries, then rebuild. Use after checking your Git backup.')
    args = parser.parse_args()
    try:
        if args.remove_demos:
            places = load_places(args.root)
            for place in places:
                if place.get('demo') is True:
                    (args.root / 'birding/data/places' / (place['id'] + '.json')).unlink()
                    print('Removed example:', place['id'])
        count, photos = build_site(args.root)
        print(f'Built locations.geojson, birding-data.js and catalogue.html: {count} locations, {photos} photo entries.')
        return 0
    except (ValidationError, OSError) as exc:
        print(f'ERROR: {exc}', file=sys.stderr); return 1


if __name__ == '__main__': raise SystemExit(main())
