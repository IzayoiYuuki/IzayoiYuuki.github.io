#!/usr/bin/env python3
"""Validate records, image paths, privacy fields and generated-file freshness."""
import argparse
from pathlib import Path
import sys
from birding_common import ROOT, ValidationError, load_places, validate_places, output_texts, audit_images


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--root', type=Path, default=ROOT)
    parser.add_argument('--images', action='store_true', help='Also decode photographs and reject EXIF/XMP; requires Pillow')
    args = parser.parse_args()
    try:
        places = load_places(args.root); validate_places(places, args.root)
        for relative, expected in output_texts(places).items():
            path = args.root / relative
            if not path.is_file() or path.read_text(encoding='utf-8') != expected:
                raise ValidationError(f'{relative} is missing or outdated. Run python3 tools/build_birding_data.py')
        if args.images: print(f'Photo audit passed: {audit_images(places, args.root)} distinct image files.')
        print(f'Validation passed: {len(places)} locations; generated files are up to date.')
        return 0
    except (ValidationError, OSError) as exc:
        print(f'ERROR: {exc}', file=sys.stderr); return 1


if __name__ == '__main__': raise SystemExit(main())
