"""Shared, standard-library-only data validation and publishing for the birding site.

Authoring source of truth: birding/data/places/*.json.
Everything inside that directory is PUBLIC. Never put private GPS data there.
"""
from __future__ import annotations

import datetime as dt
import html
import json
import math
import os
from pathlib import Path, PurePosixPath
import re
import tempfile
from typing import Any

ROOT = Path(__file__).resolve().parents[1]
ID_RE = re.compile(r'^[a-z0-9][a-z0-9-]*$')
PLACE_FIELDS = {'schemaVersion', 'id', 'name', 'mapLabel', 'region', 'country', 'coordinates',
                'locationPrecision', 'habitats', 'summary', 'demo', 'visits'}
VISIT_FIELDS = {'id', 'date', 'notes', 'checklistUrl', 'observations'}
OBS_FIELDS = {'speciesId', 'nameEn', 'nameZh', 'scientificName', 'identified', 'count', 'notes', 'photos'}
PHOTO_FIELDS = {'src', 'thumb', 'width', 'height', 'alt', 'caption', 'camera', 'lens', 'settings'}


class ValidationError(ValueError):
    pass


def read_json(path: Path) -> Any:
    try:
        return json.loads(path.read_text(encoding='utf-8'))
    except (OSError, ValueError) as exc:
        raise ValidationError(f'{path}: {exc}') from exc


def atomic_text(path: Path, content: str) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    fd, temporary = tempfile.mkstemp(prefix='.' + path.name + '-', suffix='.tmp', dir=path.parent)
    try:
        with os.fdopen(fd, 'w', encoding='utf-8', newline='\n') as stream:
            stream.write(content)
            stream.flush()
            os.fsync(stream.fileno())
        os.replace(temporary, path)
    finally:
        if os.path.exists(temporary):
            os.unlink(temporary)


def json_text(value: Any) -> str:
    return json.dumps(value, ensure_ascii=False, indent=2, allow_nan=False) + '\n'


def js_assignment(name: str, value: Any) -> str:
    payload = json.dumps(value, ensure_ascii=False, separators=(',', ':'), allow_nan=False)
    return f'window.{name} = {payload};\n'


def load_places(root: Path = ROOT) -> list[dict]:
    result = []
    for path in sorted((root / 'birding/data/places').glob('*.json')):
        place = read_json(path)
        if not isinstance(place, dict) or place.get('id') != path.stem:
            raise ValidationError(f'{path.name}: filename must match the location id.')
        result.append(place)
    return result


def photo_path(root: Path, value: Any) -> Path:
    if not isinstance(value, str) or not value or '\\' in value or '%' in value or '?' in value or '#' in value or any(ord(c) < 32 for c in value):
        raise ValidationError(f'Invalid public image path: {value!r}')
    path = PurePosixPath(value)
    if path.is_absolute() or len(path.parts) < 2 or path.parts[0] != 'photos' or '..' in path.parts:
        raise ValidationError(f'Images must use a relative photos/... path: {value!r}')
    full = (root / 'birding' / path).resolve()
    base = (root / 'birding/photos').resolve()
    if not full.is_relative_to(base):
        raise ValidationError(f'Image escapes the public photo directory: {value}')
    if full.suffix.lower() not in {'.jpg', '.jpeg', '.png', '.webp', '.avif'}:
        raise ValidationError(f'Unsupported web image format: {value}')
    return full


def validate_places(places: list[dict], root: Path = ROOT, check_files: bool = True) -> None:
    errors: list[str] = []
    def require(condition: bool, message: str) -> None:
        if not condition: errors.append(message)
    def fields(obj: dict, allowed: set[str], where: str) -> None:
        extra = set(obj) - allowed
        require(not extra, f'{where}: unknown fields {sorted(extra)}. This is public data; remove private metadata.')
    def text(obj: dict, keys: list[str], where: str, required: set[str] | None = None) -> None:
        for key in keys:
            value = obj.get(key, '')
            require(isinstance(value, str), f'{where}.{key}: must be text.')
            if required and key in required:
                require(isinstance(value, str) and bool(value.strip()), f'{where}.{key}: cannot be empty.')
    ids = set()
    for place in places:
        if not isinstance(place, dict): errors.append('Every location must be an object.'); continue
        where = str(place.get('id', '<unnamed>'))
        fields(place, PLACE_FIELDS, where)
        require(place.get('schemaVersion') == 1, f'{where}: schemaVersion must be 1.')
        identifier = place.get('id')
        require(isinstance(identifier, str) and bool(ID_RE.fullmatch(identifier)), f'{where}: use a lowercase ASCII slug as id.')
        if isinstance(identifier, str):
            require(identifier not in ids, f'Duplicate location id: {identifier}'); ids.add(identifier)
        text(place, ['name', 'mapLabel', 'region', 'country', 'summary'], where, {'name', 'country'})
        require(isinstance(place.get('demo'), bool), f'{where}.demo: true or false is required.')
        country = place.get('country')
        require(isinstance(country, str) and bool(re.fullmatch(r'[A-Z]{2}', country)), f'{where}.country: use a two-letter country code, e.g. GB.')
        precision = place.get('locationPrecision')
        require(isinstance(precision, str) and precision in {'exact', 'approximate', 'hidden'}, f'{where}: invalid locationPrecision.')
        coordinates = place.get('coordinates')
        if precision == 'hidden':
            require(coordinates is None, f'{where}: hidden locations MUST have coordinates: null, not secretly stored coordinates.')
        elif not isinstance(coordinates, dict):
            errors.append(f'{where}: visible locations require coordinates.lat and coordinates.lng.')
        else:
            require(set(coordinates) == {'lat', 'lng'}, f'{where}: coordinates must contain only lat and lng.')
            for key, limit in [('lat', 90), ('lng', 180)]:
                value = coordinates.get(key)
                require(isinstance(value, (int, float)) and not isinstance(value, bool) and math.isfinite(value) and abs(value) <= limit,
                        f'{where}: invalid {key}.')
        habitats = place.get('habitats')
        require(isinstance(habitats, list) and all(isinstance(x, str) and x.strip() for x in habitats), f'{where}.habitats: use an array of non-empty strings.')
        visits = place.get('visits')
        if not isinstance(visits, list): errors.append(f'{where}.visits: must be an array.'); continue
        visit_ids: set[str] = set()
        photo_ids: set[str] = set()
        for visit in visits:
            if not isinstance(visit, dict): errors.append(f'{where}: visit must be an object.'); continue
            vw = f"{where}/{visit.get('id', '<visit>')}"
            fields(visit, VISIT_FIELDS, vw)
            vid = visit.get('id')
            require(isinstance(vid, str) and bool(ID_RE.fullmatch(vid)), f'{vw}: invalid visit id.')
            if isinstance(vid, str):
                require(vid not in visit_ids, f'{vw}: duplicate visit id.'); visit_ids.add(vid)
            text(visit, ['notes', 'checklistUrl'], vw)
            if visit.get('checklistUrl'):
                require(str(visit['checklistUrl']).startswith('https://'), f'{vw}: checklist URL must start with https://.')
            date = visit.get('date')
            try:
                if date is None and place.get('demo') is True: pass
                elif isinstance(date, str) and re.fullmatch(r'\d{4}-\d{2}-\d{2}', date): dt.date.fromisoformat(date)
                else: raise ValueError()
            except ValueError: errors.append(f'{vw}: use a valid YYYY-MM-DD date. Only demo visits may use null.')
            observations = visit.get('observations')
            if not isinstance(observations, list): errors.append(f'{vw}.observations: must be an array.'); continue
            for obs in observations:
                if not isinstance(obs, dict): errors.append(f'{vw}: observation must be an object.'); continue
                fields(obs, OBS_FIELDS, vw)
                text(obs, ['speciesId', 'nameEn', 'nameZh', 'scientificName', 'notes'], vw, {'speciesId'})
                sid = obs.get('speciesId')
                require(isinstance(sid, str) and bool(ID_RE.fullmatch(sid)), f'{vw}: speciesId must be a slug.')
                require(bool(obs.get('nameEn') or obs.get('nameZh')), f'{vw}: provide an English or Chinese bird name.')
                require(isinstance(obs.get('identified'), bool), f'{vw}.identified: true or false is required.')
                require(not obs.get('identified') or (isinstance(sid, str) and sid not in {'unknown', 'unidentified'}), f'{vw}: an unidentified observation cannot be marked identified.')
                count = obs.get('count')
                require(count is None or isinstance(count, int) and not isinstance(count, bool) and count >= 0, f'{vw}.count: use a non-negative integer or null.')
                photos = obs.get('photos')
                if not isinstance(photos, list): errors.append(f'{vw}.photos: must be an array.'); continue
                for photo in photos:
                    if not isinstance(photo, dict): errors.append(f'{vw}: photo must be an object.'); continue
                    fields(photo, PHOTO_FIELDS, vw)
                    text(photo, ['alt', 'caption', 'camera', 'lens', 'settings'], vw, {'alt'})
                    for dimension in ('width', 'height'):
                        value = photo.get(dimension)
                        require(isinstance(value, int) and not isinstance(value, bool) and value > 0, f'{vw}: photo {dimension} must be a positive integer.')
                    src = photo.get('src')
                    if isinstance(src, str):
                        require(src not in photo_ids, f'{vw}: duplicate photograph {src} in the same place.'); photo_ids.add(src)
                    for key in ('src', 'thumb'):
                        try:
                            path = photo_path(root, photo.get(key))
                            if check_files: require(path.is_file(), f'{vw}: missing image {photo.get(key)}')
                        except ValidationError as exc: errors.append(str(exc))
    if errors:
        raise ValidationError('\n'.join(errors))


def all_photos(place: dict) -> list[dict]:
    return [photo for visit in place['visits'] for obs in visit['observations'] for photo in obs['photos']]


def build_index(places: list[dict]) -> dict:
    features = []
    for place in sorted(places, key=lambda p: (p.get('demo', False), p['name'].casefold())):
        photos = all_photos(place)
        observations = [o for v in place['visits'] for o in v['observations']]
        dates = [v['date'] for v in place['visits'] if v.get('date')]
        identified = sorted({o['speciesId'] for o in observations if o['identified']})
        coords = place['coordinates']
        properties = {key: place.get(key, '') for key in ['id', 'name', 'mapLabel', 'region', 'country', 'summary', 'locationPrecision', 'habitats', 'demo']}
        properties.update({
            'cover': photos[0]['thumb'] if photos else None,
            'speciesIds': identified, 'speciesCount': len(identified),
            'photoPaths': sorted({p['src'] for p in photos}), 'photoCount': len(photos),
            'visitCount': len(place['visits']), 'latestVisit': max(dates, default=None),
            'years': sorted({date[:4] for date in dates}, reverse=True),
            'searchText': ' '.join(' '.join(o.get(key, '') for key in ('nameEn', 'nameZh', 'scientificName')) for o in observations),
        })
        features.append({'type': 'Feature', 'geometry': None if coords is None else {'type': 'Point', 'coordinates': [coords['lng'], coords['lat']]}, 'properties': properties})
    return {'type': 'FeatureCollection', 'schemaVersion': 1, 'features': features}


def visible_places(places: list[dict]) -> list[dict]:
    real = [p for p in places if not p['demo']]
    return sorted(real or places, key=lambda p: p['name'].casefold())


def build_catalogue(places: list[dict]) -> str:
    esc = lambda value: html.escape(str(value), quote=True)
    output = ['''<!doctype html><html lang="en"><head><meta charset="utf-8"><meta name="viewport" content="width=device-width, initial-scale=1"><title>Birding photo catalogue · Yuqi Liu</title><link rel="stylesheet" href="birding.css"></head><body><header class="site-header wrap"><a class="brand" href="../index.html"><strong>Yuqi Liu</strong></a><nav><a href="index.html">Interactive map ↗</a></nav></header><main class="wrap catalogue"><h1>The photo notebook.</h1><p>All published places, photographs and visit notes. This page works without JavaScript.</p>''']
    displayed = visible_places(places)
    if displayed and all(p['demo'] for p in displayed):
        output.append('<aside class="notice"><strong>Preview edition.</strong> These are example locations, not personal birding records. The same homepage photograph is reused; its location and species are unverified.</aside>')
    if not displayed: output.append('<p>No birding records have been published yet.</p>')
    for place in displayed:
        output.append(f'<article id="{esc(place["id"])}"><h2>{esc(place["name"])}</h2>')
        output.append(f'<p>{esc(place["region"])} · {esc(place["locationPrecision"])} public location</p>')
        output.append(f'<p>{esc(place["summary"])}</p>')
        if place['habitats']: output.append('<p>Habitat: ' + esc(', '.join(place['habitats'])) + '</p>')
        for visit in sorted(place['visits'], key=lambda v: v['date'] or '', reverse=True):
            output.append(f'<section><h3>{esc(visit["date"] or "Example visit · date not supplied")}</h3><p style="white-space:pre-line">{esc(visit.get("notes", ""))}</p>')
            for obs in visit['observations']:
                output.append(f'<h4>{esc(obs["nameEn"])} {esc(obs.get("nameZh", ""))}</h4>')
                if obs.get('scientificName'): output.append(f'<p><em>{esc(obs["scientificName"])}</em></p>')
                if not obs['identified']: output.append('<p>Identification unconfirmed; excluded from the species count.</p>')
                if obs.get('count') is not None: output.append(f'<p>Count: {obs["count"]}</p>')
                if obs.get('notes'): output.append(f'<p>{esc(obs["notes"])}</p>')
                for photo in obs['photos']:
                    output.append(f'<figure><a href="{esc(photo["src"])}"><img class="catalogue-photo" src="{esc(photo["thumb"])}" alt="{esc(photo["alt"])}" width="{photo["width"]}" height="{photo["height"]}" style="height:auto" loading="lazy"></a><figcaption>{esc(photo.get("caption", ""))}</figcaption>')
                    if place['demo']: output.append('<p>Sample image; not assigned to this location.</p>')
                    metadata = ' · '.join(photo.get(k, '') for k in ('camera', 'lens', 'settings') if photo.get(k))
                    if metadata: output.append(f'<p>{esc(metadata)}</p>')
                    output.append('</figure>')
            if visit.get('checklistUrl'): output.append(f'<p><a href="{esc(visit["checklistUrl"])}" rel="noopener noreferrer">Open checklist ↗</a></p>')
            output.append('</section>')
        output.append(f'<a href="index.html#{esc(place["id"])}">View on the interactive map ↗</a></article>')
    output.append('</main><footer class="site-footer wrap"><a href="credits.html">Map credits &amp; privacy</a><a href="../index.html">Homepage ↗</a></footer></body></html>\n')
    return '\n'.join(output)


def output_texts(places: list[dict]) -> dict[str, str]:
    index = build_index(places)
    bundle = {'index': index, 'places': {place['id']: place for place in places}}
    return {
        'birding/data/locations.geojson': json_text(index),
        'birding/data/birding-data.js': js_assignment('BIRDING_DATA', bundle),
        'birding/catalogue.html': build_catalogue(places),
    }


def build_site(root: Path = ROOT) -> tuple[int, int]:
    places = load_places(root)
    validate_places(places, root)
    for path, content in output_texts(places).items(): atomic_text(root / path, content)
    return len(places), sum(len(all_photos(p)) for p in places)


def audit_images(places: list[dict], root: Path = ROOT) -> int:
    try:
        from PIL import Image
    except ImportError as exc:
        raise ValidationError('Photo audit requires Pillow: python3 -m pip install -r tools/requirements.txt') from exc
    checked: set[Path] = set()
    errors = []
    for place in places:
        for photo in all_photos(place):
            for key in ('src', 'thumb'):
                path = photo_path(root, photo[key])
                if path in checked: continue
                checked.add(path)
                try:
                    with Image.open(path) as image:
                        image.load()
                        if image.getexif() or image.info.get('xmp'):
                            errors.append(f'{path.name}: EXIF/XMP metadata present. Re-export with the photo tool.')
                        if key == 'src' and image.size != (photo['width'], photo['height']):
                            errors.append(f'{path.name}: stored dimensions do not match the image.')
                except OSError as exc: errors.append(f'{path.name}: {exc}')
    if errors: raise ValidationError('\n'.join(errors))
    return len(checked)
