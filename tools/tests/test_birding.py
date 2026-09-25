"""Run from the Homepage root: python3 -m unittest discover -s tools/tests -v"""
import copy
import io
import json
from pathlib import Path
import shutil
import subprocess
import sys
import tempfile
import unittest
from unittest.mock import patch

TOOLS = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(TOOLS))
from birding_common import (ValidationError, validate_places, build_index, build_catalogue,
                            audit_images, load_places, photo_path)
from add_birding_record import process_photo, geocode, commit_record
from PIL import Image, TiffImagePlugin


def example():
    return {'schemaVersion': 1, 'id': 'test-pond', 'name': 'Test pond', 'mapLabel': 'Test pond',
            'region': 'Test region', 'country': 'GB', 'coordinates': {'lat': 53.7, 'lng': -1.4},
            'locationPrecision': 'approximate', 'habitats': ['Wetland'], 'summary': '', 'demo': False,
            'visits': [{'id': 'visit-one', 'date': '2026-09-07', 'notes': '', 'checklistUrl': '',
                        'observations': [{'speciesId': 'mallard', 'nameEn': 'Mallard', 'nameZh': '绿头鸭',
                                          'scientificName': 'Anas platyrhynchos', 'identified': True,
                                          'count': None, 'notes': '', 'photos': []}]}]}


class ValidationTests(unittest.TestCase):
    def test_valid_record(self): validate_places([example()], check_files=False)

    def test_hidden_rejects_coordinates(self):
        record = example(); record['locationPrecision'] = 'hidden'
        with self.assertRaisesRegex(ValidationError, 'MUST have coordinates: null'):
            validate_places([record], check_files=False)

    def test_hidden_null_is_valid(self):
        record = example(); record.update(locationPrecision='hidden', coordinates=None)
        validate_places([record], check_files=False)
        self.assertIsNone(build_index([record])['features'][0]['geometry'])

    def test_geojson_coordinate_order(self):
        geometry = build_index([example()])['features'][0]['geometry']
        self.assertEqual(geometry['coordinates'], [-1.4, 53.7])

    def test_private_extra_fields_rejected(self):
        record = example(); record['privateCoordinates'] = {'lat': 53, 'lng': -1}
        with self.assertRaisesRegex(ValidationError, 'unknown fields'): validate_places([record], check_files=False)

    def test_nan_coordinates_rejected(self):
        record = example(); record['coordinates']['lat'] = float('nan')
        with self.assertRaisesRegex(ValidationError, 'invalid lat'): validate_places([record], check_files=False)

    def test_real_date_required(self):
        record = example(); record['visits'][0]['date'] = None
        with self.assertRaises(ValidationError): validate_places([record], check_files=False)
        record['demo'] = True; validate_places([record], check_files=False)

    def test_invalid_date_rejected(self):
        record = example(); record['visits'][0]['date'] = '2026-02-30'
        with self.assertRaises(ValidationError): validate_places([record], check_files=False)

    def test_duplicate_id(self):
        with self.assertRaisesRegex(ValidationError, 'Duplicate location id'): validate_places([example(), example()], check_files=False)

    def test_image_traversal(self):
        with tempfile.TemporaryDirectory() as tmp:
            for value in ['../secret.jpg', 'photos/../../secret.jpg', 'https://example.org/bird.jpg', 'photos/%2e%2e/bird.jpg']:
                with self.assertRaises(ValidationError): photo_path(Path(tmp), value)

    def test_catalogue_escapes_text(self):
        record = example(); record['summary'] = '<script>alert(1)</script>'
        result = build_catalogue([record]); self.assertNotIn('<script>', result); self.assertIn('&lt;script&gt;', result)

    def test_demo_hidden_when_real_exists(self):
        demo = example(); demo.update(id='demo-record', name='DemonstrationOnly', demo=True)
        result = build_catalogue([demo, example()]); self.assertNotIn('DemonstrationOnly', result)

    def test_distinct_species_across_visits(self):
        record = example(); v = copy.deepcopy(record['visits'][0]); v['id'] = 'visit-two'; record['visits'].append(v)
        self.assertEqual(build_index([record])['features'][0]['properties']['speciesCount'], 1)


class ImportTests(unittest.TestCase):
    def test_pixels_only_export_and_orientation(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp); source = root / 'source.jpg'
            image = Image.new('RGB', (200, 120), 'blue'); exif = Image.Exif()
            exif[274] = 6; exif[272] = 'Test camera'; exif[270] = 'Private description'
            exif[34853] = {1: 'N', 2: (TiffImagePlugin.IFDRational(53, 1), TiffImagePlugin.IFDRational(1, 1), TiffImagePlugin.IFDRational(0, 1))}
            image.save(source, exif=exif)
            original = source.read_bytes()
            photo = process_photo(source, root / 'birding', 'photos/test/image.webp', alt='A test image', caption='Test')
            self.assertEqual((photo['width'], photo['height']), (120, 200))
            self.assertEqual(photo['camera'], 'Test camera')
            self.assertEqual(source.read_bytes(), original)
            record = example(); record['visits'][0]['observations'][0]['photos'] = [photo]
            validate_places([record], root); self.assertEqual(audit_images([record], root), 2)

    def test_reject_raw(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            with self.assertRaises(ValidationError): process_photo(root/'image.CR3', root, 'photos/image.webp', alt='Test', caption='')

    def test_failed_commit_leaves_no_public_record_or_image(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp); stage = root/'stage'; source = root/'source.jpg'
            Image.new('RGB', (100, 80)).save(source)
            photo = process_photo(source, stage, 'photos/test/image.webp', alt='Test image', caption='')
            record = example(); record['privateCoordinates'] = [1, 2]
            record['visits'][0]['observations'][0]['photos'] = [photo]
            with self.assertRaises(ValidationError): commit_record(record, [], stage, root)
            self.assertFalse((root/'birding/data/places/test-pond.json').exists())
            self.assertFalse((root/'birding/photos/test/image.webp').exists())

    def test_geocoder_cache_and_identification(self):
        with tempfile.TemporaryDirectory() as tmp:
            payload = '[{"display_name":"Example reserve","lat":"53.7","lon":"-1.4"}]'
            with patch('urllib.request.urlopen', return_value=io.StringIO(payload)) as opened:
                first = geocode('Example reserve', 'GB', Path(tmp))
                second = geocode('Example reserve', 'GB', Path(tmp))
                self.assertEqual(first, second); self.assertEqual(opened.call_count, 1)
                request = opened.call_args.args[0]
                self.assertIn('YuqiLiuBirdingNotebook', request.get_header('User-agent'))
                self.assertIn('countrycodes=gb', request.full_url)

    def test_interactive_add_and_repeat_visit(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp); (root/'index.html').write_text('<html></html>')
            source = root/'test photo.jpg'; Image.new('RGB', (240, 160), 'green').save(source)
            answers = ['0', 'Integration Test Pond', '', 'Test region', '', 'h', 'Wetland', 'Testing only.',
                       '2026-09-07', 'First visit', 'Mallard', '绿头鸭', 'Anas platyrhynchos', 'y', '2', 'Test note',
                       str(source), '', 'First caption', 'n', 'y']
            script = TOOLS/'add_birding_record.py'
            run = subprocess.run([sys.executable, str(script), '--root', str(root)], input='\n'.join(answers)+'\n', text=True, capture_output=True)
            self.assertEqual(run.returncode, 0, run.stdout + run.stderr)
            first = load_places(root)[0]
            self.assertIsNone(first['coordinates']); self.assertEqual(len(first['visits']), 1)
            self.assertEqual(first['visits'][0]['observations'][0]['count'], 2)
            self.assertNotIn(str(source), json.dumps(first))
            answers = ['1', '2026-09-06', 'Earlier visit', 'Robin', '知更鸟', 'Erithacus rubecula', 'y', '1', '', '', 'n', 'y']
            run = subprocess.run([sys.executable, str(script), '--root', str(root)], input='\n'.join(answers)+'\n', text=True, capture_output=True)
            self.assertEqual(run.returncode, 0, run.stdout + run.stderr)
            places = load_places(root); self.assertEqual(len(places), 1); self.assertEqual(len(places[0]['visits']), 2)
            validate_places(places, root); audit_images(places, root)
            props = build_index(places)['features'][0]['properties']
            self.assertEqual(props['speciesCount'], 2); self.assertEqual(props['visitCount'], 2)
            self.assertIn('Integration Test Pond', (root/'birding/catalogue.html').read_text())


if __name__ == '__main__': unittest.main()
