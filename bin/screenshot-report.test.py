#!/usr/bin/env python3
"""Observable report guarantees; fixtures are synthetic bytes, not app evidence."""
import base64
import copy
import importlib.util
from pathlib import Path
import tempfile
import unittest
from unittest.mock import patch

spec = importlib.util.spec_from_file_location('report', Path(__file__).with_name('screenshot-report.py'))
report = importlib.util.module_from_spec(spec)
spec.loader.exec_module(report)
PNG = base64.b64decode('iVBORw0KGgoAAAANSUhEUgAAAAEAAAABCAQAAAC1HAwCAAAAC0lEQVR42mP8/x8AAusB9Y9Zl1sAAAAASUVORK5CYII=')


class ReportTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.root = Path(self.temp.name)
        (self.root / 'shots').mkdir()
        (self.root / 'shots' / 'one.png').write_bytes(PNG)
        self.case = dict(id='empty-small', surface='Items', route='/items', account='fixture',
                         variant='after', conditions=['Zero items'], steps=['Open items'],
                         expected='Empty visible; rows absent', observed='Empty visible',
                         nextAction='Review', browser='Chromium', theme='light', locale='en',
                         deviceMode='emulated', viewport=dict(width=390, height=844, dpr=1),
                         captureStatus='captured', reviewStatus='not-reviewed', image='shots/one.png')
        self.doc = dict(schemaVersion=1, title='Review', scope='Items', coverageStrategy='All declared cases',
                        exclusions=[], run=dict(revision='abc', dirtyFingerprint='clean', timestamp='now',
                                                environment='local', dataMode='fixture'), cases=[self.case])

    def test_portable_exact_bytes_and_conditions_before_image(self):
        html = report.render(self.doc, self.root)
        self.assertIn('data:image/png;base64,' + base64.b64encode(PNG).decode(), html)
        self.assertLess(html.index('Zero items'), html.index('<img '))
        self.assertIn('height:auto', html)
        self.assertIn('1 captured', html)
        self.assertIn('0 pass', html)
        self.assertIn('/items<br>fixture<br>Zero items', html)

    def test_image_context_visible_before_collapsed_details(self):
        html = report.render(self.doc, self.root)
        section = html.split('<section id="empty-small">', 1)[1].split('</section>', 1)[0]
        visible, details = section.split('<details>', 1)
        for label, value in (('Where', '/items'), ('Account', 'fixture'),
                             ('Viewport', '390 × 844 @ 1'), ('Variant', 'after')):
            self.assertIn(f'<b>{label}:</b> {value}', visible)
            self.assertNotIn(f'<b>{label}:</b>', details)
        self.assertIn('browser: Chromium', details)
        self.assertIn('<li>Open items</li>', details)
        self.assertLess(section.index('</details>'), section.index('<img '))

    def test_escapes_metadata_and_has_no_executable_input(self):
        attack = '<script>alert("x")</script>'
        self.doc['title'] = attack
        self.case['conditions'] = [attack]
        self.case['nextAction'] = attack
        html = report.render(self.doc, self.root)
        self.assertNotIn('<script>', html)
        self.assertIn('&lt;script&gt;', html)
        self.assertIn("default-src 'none'", html)

    def test_gaps_and_review_counts_are_derived(self):
        self.doc['coveragePercent'] = 100
        for status in ('blocked', 'not-run', 'not-applicable'):
            c = copy.deepcopy(self.case)
            c.update(id=status, captureStatus=status, reason='Unavailable')
            c.pop('image')
            self.doc['cases'].append(c)
        html = report.render(self.doc, self.root)
        for text in ('4 cases', '1 blocked', '1 not-run', '1 not-applicable', '4 not-reviewed', '0 pass'):
            self.assertIn(text, html)
        self.assertEqual(html.count('Evidence gap:'), 3)
        self.doc.pop('coveragePercent')
        self.assertEqual(html, report.render(self.doc, self.root))

    def test_invalid_statuses_duplicates_and_missing_image(self):
        for field, value in (('captureStatus', 'done'), ('reviewStatus', 'approved'), ('reviewStatus', []), ('image', None)):
            with self.subTest(field=field):
                doc = copy.deepcopy(self.doc)
                doc['cases'][0][field] = value
                with self.assertRaises(ValueError):
                    report.render(doc, self.root)
        self.doc['cases'].append(copy.deepcopy(self.case))
        with self.assertRaisesRegex(ValueError, 'duplicate'):
            report.render(self.doc, self.root)

    def test_no_pass_without_capture(self):
        self.case.update(captureStatus='blocked', reviewStatus='pass', reason='No access')
        self.case.pop('image')
        with self.assertRaisesRegex(ValueError, 'uncaptured'):
            report.render(self.doc, self.root)

    def test_missing_remote_traversal_and_active_assets_rejected(self):
        (self.root / 'active.svg').write_text('<svg onload="alert(1)"></svg>')
        for name in ('missing.png', 'https://example.invalid/x.png', '../outside.png', '/tmp/one.png', 'active.svg'):
            with self.subTest(name=name):
                self.case['image'] = name
                with self.assertRaises(ValueError):
                    report.render(self.doc, self.root)

    def test_symlink_cannot_escape_manifest_directory(self):
        with tempfile.TemporaryDirectory() as outside:
            path = Path(outside) / 'one.png'
            path.write_bytes(PNG)
            (self.root / 'escape.png').symlink_to(path)
            self.case['image'] = 'escape.png'
            with self.assertRaises(ValueError):
                report.render(self.doc, self.root)

    def test_aggregate_budget_is_enforced_before_read(self):
        budget = [256 * 1024 * 1024]
        with patch.object(Path, 'read_bytes', side_effect=AssertionError('must not read')):
            with self.assertRaisesRegex(ValueError, 'aggregate'):
                report.asset(self.root, 'shots/one.png', 'image', budget)

    def test_optional_video_and_trace_are_embedded(self):
        (self.root / 'demo.webm').write_bytes(b'\x1aE\xdf\xa3synthetic')
        (self.root / 'trace.zip').write_bytes(b'PK\x03\x04synthetic')
        self.case.update(video='demo.webm', trace='trace.zip')
        html = report.render(self.doc, self.root)
        self.assertIn('<video controls', html)
        self.assertIn('data:video/webm;base64,', html)
        self.assertIn('download="empty-small-trace.zip"', html)

    def test_required_conditions_and_viewport(self):
        for key, value in (('conditions', []), ('viewport', dict(width=True, height=844, dpr=1)),
                           ('viewport', dict(width=float('nan'), height=844, dpr=1))):
            with self.subTest(key=key):
                doc = copy.deepcopy(self.doc)
                doc['cases'][0][key] = value
                with self.assertRaises(ValueError):
                    report.render(doc, self.root)


if __name__ == '__main__':
    unittest.main()
