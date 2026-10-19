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
        self.case = dict(id='empty-small', point='Items: empty list', column='web-mobile', surface='Items', route='/items', account='fixture',
                         variant='after', conditions=['Zero items'], steps=['Open items'],
                         expected='Empty visible; rows absent', observed='Empty visible',
                         nextAction='Review', browser='Chromium', theme='light', locale='en',
                         deviceMode='emulated', viewport=dict(width=390, height=844, dpr=1),
                         captureStatus='captured', reviewStatus='not-reviewed', image='shots/one.png')
        self.doc = dict(schemaVersion=1, title='Review', scope='Items', coverageStrategy='All declared cases',
                        columns=[dict(id='web-desktop', label='Web desktop'), dict(id='web-mobile', label='Web mobile')],
                        exclusions=[], run=dict(revision='abc', dirtyFingerprint='clean', timestamp='now',
                                                environment='local', dataMode='fixture'), cases=[self.case])
        self.desktop = dict(self.case, id='empty-wide', column='web-desktop', viewport=dict(width=1440, height=900, dpr=1),
                            captureStatus='not-applicable', reason='Layout identical to mobile here',
                            image=None)
        self.desktop.pop('image')
        self.doc['cases'].append(self.desktop)

    def test_portable_exact_bytes_and_conditions_before_image(self):
        html = report.render(self.doc, self.root)
        self.assertIn('data:image/png;base64,' + base64.b64encode(PNG).decode(), html)
        self.assertLess(html.index('Zero items'), html.index('<img '))
        self.assertIn('height:auto', html)
        self.assertIn('1 captured', html)
        self.assertIn('0 pass', html)
        
    def test_image_context_visible_before_collapsed_details(self):
        html = report.render(self.doc, self.root)
        section = html.split('<section id="empty-small" class="case">', 1)[1].split('</section>', 1)[0]
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
        for text in ('5 cases', '1 blocked', '1 not-run', '2 not-applicable', '5 not-reviewed', '0 pass'):
            self.assertIn(text, html)
        self.assertEqual(html.count('Evidence gap:'), 4)
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
        self.assertIn('<video class="narrow" controls', html)
        self.assertIn('data:video/webm;base64,', html)
        self.assertIn('download="empty-small-trace.zip"', html)

    def test_one_heading_and_table_per_point_with_fixed_columns_and_stacked_variants(self):
        (self.root / 'shots' / 'wide.png').write_bytes(PNG)
        self.desktop.update(captureStatus='captured', reviewStatus='not-reviewed', image='shots/wide.png')
        self.desktop.pop('reason')
        before = dict(self.desktop, id='empty-wide-before', variant='before')
        other = dict(self.case, id='full-small', point='Items: full list')
        other_wide = dict(self.desktop, id='full-wide', point='Items: full list')
        self.doc['cases'] = [other, self.case, before, self.desktop, other_wide]
        html = report.render(self.doc, self.root)
        self.assertIn('2 points', html)
        rows = html.split('class="point-block">')[1:]
        self.assertEqual(html.count('<table class="gallery"'), 2)
        self.assertEqual(len(rows), 2)
        self.assertIn('Items: full list', rows[0])
        self.assertIn('Items: empty list', rows[1])
        for row in rows:
            heading, table = row.split('<table class="gallery"', 1)
            self.assertIn('<h2>', heading)
            self.assertNotIn('class="point"', table)
            self.assertEqual(table.count('<td>'), 2)
            self.assertEqual(table.count('<th>'), 2)
            self.assertLess(table.index('Web desktop'), table.index('Web mobile'))
            self.assertLess(row.index('id="empty-wide') if 'empty-wide' in row else row.index('id="full-wide"'),
                            row.index('id="empty-small"') if 'empty-small' in row else row.index('id="full-small"'))
        self.assertLess(rows[1].index('id="empty-wide-before"'), rows[1].index('id="empty-wide"'))
        self.assertEqual(rows[1].count('<img'), 3)
        self.assertIn('<img class="narrow"', rows[1])
        self.assertIn('<img src=', rows[1])

    def test_missing_cell_unknown_column_and_bad_columns_rejected(self):
        self.doc['cases'].remove(self.desktop)
        with self.assertRaisesRegex(ValueError, 'no case for column web-desktop'):
            report.render(self.doc, self.root)
        self.doc['cases'].append(self.desktop)
        self.desktop['column'] = 'ios'
        with self.assertRaisesRegex(ValueError, 'declared column ids'):
            report.render(self.doc, self.root)
        self.desktop['column'] = 'web-desktop'
        for columns in ([], [dict(id='a', label='A'), dict(id='a', label='B')], [dict(id='a')]):
            with self.subTest(columns=columns):
                doc = copy.deepcopy(self.doc)
                doc['columns'] = columns
                with self.assertRaises(ValueError):
                    report.render(doc, self.root)
        del self.case['point']
        with self.assertRaisesRegex(ValueError, 'point'):
            report.render(self.doc, self.root)

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
