#!/usr/bin/env python3
"""Interactive local editor. Prompts are in Chinese; the published website stays English.

Run: python3 tools/add_birding_record.py
Install photo dependency once: python3 -m pip install -r tools/requirements.txt
Original images are read, never modified or copied into the public repository.
"""
from __future__ import annotations

import argparse
import copy
import datetime as dt
import io
import json
import math
import os
from pathlib import Path
import re
import shlex
import shutil
import sys
import tempfile
import time
import unicodedata
import urllib.error
import urllib.parse
import urllib.request
import uuid

from birding_common import (ROOT, ID_RE, ValidationError, atomic_text, json_text, load_places,
                            validate_places, output_texts, photo_path)


class Cancelled(Exception):
    pass


def ask(label: str, default: str = '', required: bool = False) -> str:
    while True:
        suffix = f' [{default}]' if default else ''
        value = input(f'{label}{suffix}: ').strip()
        if not value: value = default
        if value or not required: return value
        print('此项不能为空。')


def yes(label: str, default: bool = False) -> bool:
    return ask(label + (' (Y/n)' if default else ' (y/N)'), 'y' if default else 'n').casefold() in {'y', 'yes', '是'}


def slugify(value: str) -> str:
    value = unicodedata.normalize('NFKD', value).encode('ascii', 'ignore').decode().lower()
    return re.sub(r'[^a-z0-9]+', '-', value).strip('-')


def ask_date() -> str:
    while True:
        value = ask('观鸟日期 YYYY-MM-DD', dt.date.today().isoformat())
        try:
            date = dt.date.fromisoformat(value)
            if not re.fullmatch(r'\d{4}-\d{2}-\d{2}', value): raise ValueError()
            if date > dt.date.today() and not yes('日期在未来，仍使用这个日期吗？'): continue
            return value
        except ValueError: print('请输入有效日期，例如 2026-09-08。')


def ask_number(label: str, limit: float) -> float:
    while True:
        try:
            value = float(ask(label, required=True))
            if not math.isfinite(value) or abs(value) > limit: raise ValueError()
            return value
        except ValueError: print(f'请输入 -{limit:g} 到 {limit:g} 之间的数字。')


def geocode(name: str, country: str, root: Path = ROOT) -> list[dict]:
    """Explicit one-shot search, cached locally and throttled to < 1 request/second.

    No autocomplete, no bulk operations, no browser geocoding.
    .birding-local/ MUST remain outside Git/public deployment.
    """
    cache_path = root / '.birding-local/geocoding.json'
    try:
        cache = json.loads(cache_path.read_text(encoding='utf-8'))
        if not isinstance(cache.get('results'), dict): raise ValueError()
    except (OSError, ValueError, AttributeError): cache = {'results': {}, 'lastRequest': 0}
    key = country.upper() + ':' + name.casefold().strip()
    if key in cache['results']: return cache['results'][key]
    delay = 1.1 - (time.time() - float(cache.get('lastRequest', 0)))
    if delay > 0: time.sleep(min(delay, 1.1))
    endpoint = os.environ.get('BIRDING_GEOCODER_URL', 'https://nominatim.openstreetmap.org/search')
    params = urllib.parse.urlencode({'q': name, 'format': 'jsonv2', 'countrycodes': country.lower(), 'limit': 5})
    contact = os.environ.get('BIRDING_GEOCODER_CONTACT', 'https://github.com/IzayoiYuuki')
    request = urllib.request.Request(endpoint + '?' + params, headers={
        'User-Agent': f'YuqiLiuBirdingNotebook/0.1 (local personal-site editor; {contact})',
        'Accept': 'application/json', 'Accept-Language': 'en'
    })
    cache['lastRequest'] = time.time()
    atomic_text(cache_path, json_text(cache))
    with urllib.request.urlopen(request, timeout=15) as response:
        data = json.load(response)
    if not isinstance(data, list): raise ValueError('Unexpected geocoder response.')
    candidates = []
    for row in data:
        lat, lng = float(row['lat']), float(row['lon'])
        if not (math.isfinite(lat) and math.isfinite(lng) and abs(lat) <= 90 and abs(lng) <= 180): continue
        candidates.append({'name': str(row.get('display_name', name)), 'lat': lat, 'lng': lng})
    cache['results'][key] = candidates
    atomic_text(cache_path, json_text(cache))
    return candidates


def choose_coordinates(name: str, country: str, root: Path) -> dict:
    while True:
        coords = None
        method = ask('坐标输入方式：1 手填；2 按地点名在线搜索', '1')
        if method == '2':
            print('搜索会把地点名称发送给 OpenStreetMap / Nominatim。敏感地点请改为手填安全的公开位置。')
            query = ask('搜索公开地点', name)
            try:
                candidates = geocode(query, country, root)
                print('地点搜索 © OpenStreetMap contributors (ODbL).')
                for index, row in enumerate(candidates, 1):
                    print(f"  {index}. {row['name']}\n     {row['lat']:.6f}, {row['lng']:.6f}")
                if not candidates: print('没有找到候选位置，可以手填。')
                else:
                    choice = ask('选择候选编号；0 改为手填', '0')
                    if choice.isdigit() and 1 <= int(choice) <= len(candidates):
                        candidate = candidates[int(choice) - 1]
                        coords = {'lat': candidate['lat'], 'lng': candidate['lng']}
            except (OSError, ValueError, KeyError, urllib.error.URLError) as exc:
                print(f'在线搜索暂时不可用：{exc}\n可以继续手填坐标，不影响添加记录。')
        if coords is None:
            coords = {'lat': ask_number('公开纬度 latitude', 90), 'lng': ask_number('公开经度 longitude', 180)}
        print(f"将公开：纬度 {coords['lat']:.6f}，经度 {coords['lng']:.6f}。")
        print('approximate 标签不会自动模糊坐标。请使用保护区中心等安全位置，而不是巢址。')
        if yes('我已核对位置，并确认这些坐标可以公开'): return coords
        if not yes('重新输入坐标？', True): raise Cancelled()


def choose_place(places: list[dict], root: Path) -> dict:
    real = [place for place in places if not place['demo']]
    print('\n选择地点（演示记录不会被当成真实观鸟记录）：')
    print('  0. 新地点')
    for index, place in enumerate(real, 1): print(f'  {index}. {place["name"]} · {place["region"]}')
    while True:
        selection = ask('地点编号', '0')
        if selection.isdigit() and 0 <= int(selection) <= len(real): break
        print('请选择列表中的编号。')
    if int(selection): return copy.deepcopy(real[int(selection) - 1])
    name = ask('地点名称（公开显示）', required=True)
    matching = next((p for p in real if p['name'].casefold() == name.casefold()), None)
    if matching and yes('已存在同名地点，使用它？', True): return copy.deepcopy(matching)
    default_id = slugify(name) or 'place-' + uuid.uuid4().hex[:8]
    existing = {p['id'] for p in places}
    while True:
        identifier = ask('地点 ID（通常直接回车）', default_id)
        if ID_RE.fullmatch(identifier) and identifier not in existing: break
        print('ID 必须使用小写字母、数字和连字符，且不能与现有地点重复。')
    region = ask('地区，如 West Yorkshire', required=True)
    while True:
        country = ask('国家代码', 'GB').upper()
        if re.fullmatch(r'[A-Z]{2}', country): break
        print('请输入两位字母国家代码，英国使用 GB。')
    while True:
        precision = ask('公开位置：a 大致位置；e 精确公开位置；h 完全隐藏坐标', 'a').lower()
        if precision in {'a', 'e', 'h'}: break
    precision = {'a': 'approximate', 'e': 'exact', 'h': 'hidden'}[precision]
    coordinates = None if precision == 'hidden' else choose_coordinates(name, country, root)
    if precision == 'hidden': print('隐藏位置：不会记录任何经纬度。名称、地区、备注和照片内容仍会公开。')
    habitats = [h.strip() for h in re.split('[,，]', ask('栖息地（逗号分隔，如 Wetland, Woodland）')) if h.strip()]
    return {'schemaVersion': 1, 'id': identifier, 'name': name, 'mapLabel': name,
            'region': region, 'country': country, 'coordinates': coordinates,
            'locationPrecision': precision, 'habitats': list(dict.fromkeys(habitats)),
            'summary': ask('地点简介（可留空，公开显示）'), 'demo': False, 'visits': []}


def photo_metadata(image) -> dict:
    """Allowlist only model/lens/exposure: no GPS, serial number or owner metadata."""
    exif = image.getexif()
    def string(key): return str(exif.get(key, '')).strip()[:150]
    def number(key):
        try: return float(exif[key])
        except (KeyError, ValueError, TypeError, ZeroDivisionError): return None
    parts = []
    shutter, aperture, iso = number(33434), number(33437), number(34855)
    if shutter and shutter > 0: parts.append(f'1/{round(1 / shutter)} s' if shutter < 1 else f'{shutter:g} s')
    if aperture and aperture > 0: parts.append(f'f/{aperture:g}')
    if iso and iso > 0: parts.append(f'ISO {iso:g}')
    return {'camera': string(272), 'lens': string(42036), 'settings': ' · '.join(parts)}


def process_photo(source: Path, stage: Path, relative: str, *, alt: str, caption: str) -> dict:
    from PIL import Image, ImageOps, ImageCms, UnidentifiedImageError
    if source.suffix.lower() not in {'.jpg', '.jpeg', '.png', '.webp', '.tif', '.tiff'}:
        raise ValidationError(f'{source.name}: 请先导出 JPEG/PNG/TIFF/WebP。第一版不直接读取 CR3、HEIC 或其他 RAW 文件。')
    try:
        with Image.open(source) as original:
            original.load()
            metadata = photo_metadata(original)
            image = ImageOps.exif_transpose(original)
            if image.info.get('icc_profile'):
                try:
                    image = ImageCms.profileToProfile(image, ImageCms.ImageCmsProfile(io.BytesIO(image.info['icc_profile'])), ImageCms.createProfile('sRGB'), outputMode='RGB')
                except (ValueError, OSError, ImageCms.PyCMSError): image = image.convert('RGB')
            elif image.mode in ('RGBA', 'LA'):
                rgba = image.convert('RGBA'); white = Image.new('RGBA', rgba.size, 'white'); white.alpha_composite(rgba); image = white.convert('RGB')
            else: image = image.convert('RGB')
            # Fresh pixel-only canvases ensure that no source EXIF/XMP/GPS metadata survives.
            clean = Image.new('RGB', image.size); clean.paste(image)
            clean.thumbnail((1920, 1920), Image.Resampling.LANCZOS)
            destination = stage / relative; destination.parent.mkdir(parents=True, exist_ok=True)
            clean.save(destination, 'WEBP', quality=84, method=6)
            thumb = str(Path(relative).parent / 'thumbs' / Path(relative).name).replace(os.sep, '/')
            thumb_image = clean.copy(); thumb_image.thumbnail((720, 720), Image.Resampling.LANCZOS)
            thumb_path = stage / thumb; thumb_path.parent.mkdir(parents=True, exist_ok=True)
            thumb_image.save(thumb_path, 'WEBP', quality=78, method=6)
            for path in (destination, thumb_path):
                with Image.open(path) as exported:
                    if exported.getexif() or exported.info.get('xmp'): raise ValidationError('Metadata stripping failed; no record was committed.')
            return {'src': relative, 'thumb': thumb, 'width': clean.width, 'height': clean.height,
                    'alt': alt, 'caption': caption, **metadata}
    except (OSError, UnidentifiedImageError) as exc:
        raise ValidationError(f'无法读取图片 {source}: {exc}') from exc


def input_photos() -> list[Path]:
    print('输入图片路径（可从 Finder 拖入终端；可一次输入多个路径）。输入空行结束。')
    paths = []
    while True:
        value = input('图片路径: ').strip()
        if not value: return paths
        if Path(value).expanduser().is_file(): candidates = [value]
        else:
            try: candidates = shlex.split(value)
            except ValueError as exc: print(f'路径引号不完整：{exc}'); continue
        for candidate in candidates:
            path = Path(candidate).expanduser().resolve()
            if not path.is_file(): print(f'文件不存在：{path}'); continue
            if path.suffix.lower() not in {'.jpg', '.jpeg', '.png', '.webp', '.tif', '.tiff'}:
                print(f'{path.name}: 请先导出 JPEG、PNG、TIFF 或 WebP；不支持直接导入 RAW/CR3/HEIC。'); continue
            if path not in paths: paths.append(path)


def commit_record(place: dict, places: list[dict], stage: Path, root: Path) -> None:
    """Validate before replacing records; roll back newly copied assets/files on failure."""
    new_images: list[Path] = []
    old_text: dict[Path, str | None] = {}
    try:
        for source in (stage / 'photos').rglob('*') if (stage / 'photos').exists() else []:
            if not source.is_file(): continue
            relative = source.relative_to(stage).as_posix()
            destination = photo_path(root, relative)
            if destination.exists(): raise ValidationError(f'Image collision: {relative}')
            destination.parent.mkdir(parents=True, exist_ok=True)
            shutil.copyfile(source, destination); new_images.append(destination)
        merged = [p for p in places if p['id'] != place['id']] + [place]
        validate_places(merged, root)
        outputs = output_texts(merged)
        outputs['birding/data/places/' + place['id'] + '.json'] = json_text(place)
        for relative in outputs:
            path = root / relative
            old_text[path] = path.read_text(encoding='utf-8') if path.exists() else None
        for relative, content in outputs.items(): atomic_text(root / relative, content)
    except Exception:
        for path, content in old_text.items():
            if content is None: path.unlink(missing_ok=True)
            else: atomic_text(path, content)
        for path in new_images: path.unlink(missing_ok=True)
        raise


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--root', type=Path, default=ROOT)
    args = parser.parse_args(); root = args.root.resolve()
    try:
        import PIL  # noqa: F401
    except ImportError:
        print('缺少 Pillow。请先运行：python3 -m pip install -r tools/requirements.txt', file=sys.stderr); return 1
    try:
        if not (root / 'index.html').is_file(): raise ValidationError('指定目录不是主页根目录。')
        places = load_places(root); validate_places(places, root)
        print('添加观鸟记录\n原片不会修改；公开副本会缩小并去除 EXIF/XMP。地点、日期和文字都会公开。')
        place = choose_place(places, root)
        date = ask_date()
        existing = next((v for v in place['visits'] if v['date'] == date), None)
        if existing and yes('这一天已有访问记录，新鸟种/照片加到同一次访问？', True): visit = existing
        else:
            visit = {'id': f'visit-{date}-{uuid.uuid4().hex[:6]}', 'date': date, 'notes': '', 'checklistUrl': '', 'observations': []}
            place['visits'].append(visit)
        visit['notes'] = ask('本次访问备注（留空保留已有内容）', visit.get('notes', ''))
        known = [o for p in places for v in p['visits'] for o in v['observations'] if o['identified']]
        with tempfile.TemporaryDirectory(prefix='birding-import-') as temporary:
            stage = Path(temporary)
            while True:
                print('\n添加一个鸟种：')
                en = ask('英文名（不确定可保持默认）', 'Unidentified bird')
                zh = ask('中文名（可留空）')
                scientific = ask('学名（可留空）')
                identified = yes('鸟种已经确认？确认后才计入鸟种数', bool(scientific))
                matching = next((o for o in known if (scientific and o['scientificName'].casefold() == scientific.casefold()) or
                                 (en != 'Unidentified bird' and o['nameEn'].casefold() == en.casefold()) or (zh and o['nameZh'] == zh)), None)
                species_id = matching['speciesId'] if matching else (slugify(scientific or en or zh) or 'bird-' + uuid.uuid4().hex[:8])
                if not identified and en == 'Unidentified bird': species_id = 'unidentified'
                while True:
                    count_text = ask('数量（不知道就留空）')
                    if not count_text: count = None; break
                    if count_text.isdigit(): count = int(count_text); break
                    print('请输入非负整数，或留空。')
                obs = {'speciesId': species_id, 'nameEn': en, 'nameZh': zh, 'scientificName': scientific,
                       'identified': identified, 'count': count, 'notes': ask('鸟种备注（可留空）'), 'photos': []}
                sources = input_photos()
                caption = ask('这一组照片的说明（可留空）') if sources else ''
                for source in sources:
                    stem = species_id[:45] + '-' + uuid.uuid4().hex[:10] + '.webp'
                    relative = f'photos/{place["id"]}/{date}/{stem}'
                    print('处理图片：', source.name)
                    obs['photos'].append(process_photo(source, stage, relative,
                        alt=f'{en or zh}, photographed at {place["name"]}.', caption=caption))
                previous = next((o for o in visit['observations'] if o['speciesId'] == species_id), None)
                if previous and yes('同次访问已有该鸟种，合并新照片？', True):
                    previous['photos'].extend(obs['photos'])
                    if obs['notes']: previous['notes'] = '\n'.join(x for x in [previous.get('notes', ''), obs['notes']] if x)
                    if count is not None: previous['count'] = count
                else: visit['observations'].append(obs)
                if not yes('继续添加另一个鸟种？'): break
            place['visits'].sort(key=lambda v: v['date'] or '', reverse=True)
            print(f'\n准备更新：{place["name"]} · {date} · 本次 {len(visit["observations"])} 条鸟类记录。')
            if not yes('确认保存公开记录及网页照片？'): raise Cancelled()
            commit_record(place, places, stage, root)
        print('\n已保存并重建地图索引、照片目录。原片保持不变。')
        print('本地预览：python3 tools/preview.py')
        print('完整检查：python3 tools/validate_birding_data.py --images')
        print('检查 git diff 后，再按原来的方式提交和推送主页。')
        return 0
    except (Cancelled, KeyboardInterrupt, EOFError):
        print('\n已取消；没有提交观鸟记录。'); return 130
    except (OSError, ValueError, ValidationError) as exc:
        print(f'ERROR: {exc}', file=sys.stderr); return 1


if __name__ == '__main__': raise SystemExit(main())
