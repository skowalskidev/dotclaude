#!/usr/bin/env python3
"""Regression tests for completion, concurrent updates and portable evidence."""
import copy
import importlib.util
import json
import html
import os
import signal
import socket
import subprocess
import sys
import threading
import unittest.mock
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
import tempfile
import unittest

DASHBOARD_SCRIPT = Path(__file__).with_name('workflow-dashboard.py').resolve()
spec = importlib.util.spec_from_file_location('dashboard', DASHBOARD_SCRIPT)
d = importlib.util.module_from_spec(spec)
spec.loader.exec_module(d)

try:
    from playwright.sync_api import sync_playwright
    HAVE_PLAYWRIGHT = True
except ImportError:
    HAVE_PLAYWRIGHT = False


def fixture():
    return {'schemaVersion': 1, 'title': 'Test task', 'engine': 'current', 'gauntlet': True,
            'referenceMode': 'none', 'inspiration': '', 'optionsConfirmedAt': d.now(),
            'revision': 1, 'updatedAt': d.now(), 'phase': 'running', 'iteration': 0,
            'maxIterations': 10, 'sections': [{'id': 'one', 'title': 'One', 'status': 'todo',
            'artifactRevision': 1, 'criteria': [{'id': 'c1', 'text': 'Outcome', 'passed': False}]}]}


def passed():
    s = fixture()
    section = s['sections'][0]
    section['status'] = 'done'
    section['criteria'][0].update(passed=True, evidence='test.log: pass')
    section['judge'] = {'agentId': 'critic', 'builderId': 'builder', 'verdict': 'pass',
                        'artifactRevision': 1, 'reference': 'Approved target', 'evidence': 'judge.json'}
    return s


def free_port():
    with socket.socket() as s:
        s.bind(('127.0.0.1', 0))
        return s.getsockname()[1]


class FakeGauntletApp(BaseHTTPRequestHandler):
    """Stands in for the Next.js app's /api/health and /api/projects contract."""

    def do_GET(self):
        if self.path == '/api/health':
            self._json(200, {'ok': True, 'pid': self.server.app_pid,
                              'port': self.server.server_port, 'app': 'gauntlet'})
        elif self.path == '/api/projects':
            self._json(200, list(self.server.plans))
        else:
            self.send_error(404)

    def do_POST(self):
        plan = self._body().get('plan')
        if plan and not any(row['plan'] == plan for row in self.server.plans):
            self.server.plans.append({'plan': plan, 'title': 't', 'phase': 'running',
                                      'revision': 1, 'updatedAt': d.now(), 'root': '/'})
        self._json(200, {'plans': self.server.plans})

    def do_DELETE(self):
        plan = self._body().get('plan')
        self.server.plans = [row for row in self.server.plans if row['plan'] != plan]
        self._json(200, {'plans': self.server.plans})

    def _body(self):
        length = int(self.headers.get('Content-Length', 0))
        return json.loads(self.rfile.read(length)) if length else {}

    def _json(self, code, payload):
        body = json.dumps(payload).encode()
        self.send_response(code)
        self.send_header('Content-Type', 'application/json')
        self.send_header('Content-Length', str(len(body)))
        self.end_headers()
        self.wfile.write(body)

    def log_message(self, *_):
        pass


def start_fake_app(pid):
    server = ThreadingHTTPServer(('127.0.0.1', 0), FakeGauntletApp)
    server.plans = []
    server.app_pid = pid
    thread = threading.Thread(target=server.serve_forever, daemon=True)
    thread.start()
    return server, thread


def stop_fake_app(server, thread):
    server.shutdown()
    server.server_close()
    thread.join()


class DashboardTests(unittest.TestCase):
    def test_preview_url_validation_and_export_preserve_assets(self):
        state = fixture()
        for value in (None, 'http://localhost:3000/settings?tab=one#details',
                      'https://preview.example.com/app', 'http://[::1]:3060/'):
            with self.subTest(value=value):
                state['sections'][0]['previewUrl'] = value
                d.validate(state)
        for value in ('', 'javascript:alert(1)', 'data:text/html,hello', '/relative',
                      '//example.com', 'https://', 'https://user:pass@example.com',
                      'http://localhost:0/', 'http://localhost:99999/',
                      'http://localhost/has space', 'https://example.com\\path',
                      'https://example.com/\npath', 42):
            with self.subTest(value=value):
                state['sections'][0]['previewUrl'] = value
                with self.assertRaisesRegex(ValueError, 'previewUrl'):
                    d.validate(state)
        with tempfile.TemporaryDirectory() as tmp:
            base = Path(tmp)
            (base / 'capture.png').write_bytes(b'capture fixture')
            (base / 'target.html').write_text('<p>Approved target</p>')
            section = state['sections'][0]
            section.update(previewUrl='http://localhost:3000/settings',
                           current={'kind': 'image', 'label': 'Capture', 'path': 'capture.png', 'source': 'Browser'},
                           target={'kind': 'html', 'label': 'Target', 'path': 'target.html', 'source': 'Review'})
            plan = base / 'task-plan.md'
            plan.write_text('```dashboard-state\n' + json.dumps(state) + '\n```\n')
            public = d.public_spec(plan)['sections'][0]
            self.assertEqual(public['previewUrl'], section['previewUrl'])
            self.assertTrue(public['current']['data'].startswith('data:image/png;base64,'))
            self.assertEqual(public['target']['html'], '<p>Approved target</p>')
            output = d.export_dashboard(plan)
            data = output.read_text().split('<script id="spec" type="application/json">')[1].split('</script>')[0]
            self.assertEqual(json.loads(data)['sections'][0], public)

    def test_review_section_requires_html_or_image_target(self):
        state = fixture()
        state['sections'][0]['status'] = 'review'
        with self.assertRaisesRegex(ValueError, 'A review section needs its proposal embedded'):
            d.validate(state)
        with tempfile.TemporaryDirectory() as tmp:
            base = Path(tmp)
            (base / 'm.html').write_text('<p>Mock</p>')
            state['sections'][0]['target'] = {'kind': 'html', 'label': 'Mock', 'path': 'mockups/m.html', 'source': 'x'}
            (base / 'mockups').mkdir()
            (base / 'mockups' / 'm.html').write_text('<p>Mock</p>')
            d.validate(state)

    def test_export_refuses_unreferenced_mockup_then_succeeds_once_referenced(self):
        with tempfile.TemporaryDirectory() as tmp:
            base = Path(tmp)
            plan = base / 'task-plan.md'
            state = fixture()
            state['sections'][0].update(
                status='review',
                target={'kind': 'html', 'label': 'Mock', 'path': 'mockups/m.html', 'source': 'x'},
            )
            (base / 'mockups').mkdir()
            (base / 'mockups' / 'm.html').write_text('<p>Referenced</p>')
            (base / 'mockups' / 'extra.html').write_text('<p>Orphan</p>')
            plan.write_text('```dashboard-state\n' + json.dumps(state) + '\n```\n')
            with self.assertRaisesRegex(ValueError, 'Unreferenced mockup/preview: mockups/extra.html'):
                d.export_dashboard(plan)
            state['sections'].append({'id': 'two', 'title': 'Two', 'status': 'todo', 'artifactRevision': 1,
                                      'criteria': [{'id': 'c2', 'text': 'Second', 'passed': False}],
                                      'current': {'kind': 'html', 'label': 'Extra', 'path': 'mockups/extra.html', 'source': 'x'}})
            plan.write_text('```dashboard-state\n' + json.dumps(state) + '\n```\n')
            output = d.export_dashboard(plan)
            self.assertTrue(output.is_file())

    @unittest.skipUnless(HAVE_PLAYWRIGHT, 'playwright not installed')
    def test_current_preview_is_visible_live_and_in_saved_html(self):
        state = fixture()
        state['sections'][0]['current'] = {
            'kind': 'image', 'label': 'Current capture',
            'data': 'data:image/png;base64,iVBORw0KGgoAAAANSUhEUgAAAAEAAAABCAQAAAC1HAwCAAAAC0lEQVR42mP8/x8AAwMCAO+/l9sAAAAASUVORK5CYII=',
        }
        second = copy.deepcopy(state['sections'][0])
        second.update(id='two', title='No capture')
        second.pop('current')
        state['sections'].append(second)

        class Handler(BaseHTTPRequestHandler):
            def do_GET(self):
                payload = (json.dumps(state) if self.path == '/state' else
                           '<!doctype html><title>Preview</title><p>Live preview</p>' if self.path.startswith('/preview') else
                           d.render_spec(state))
                self.send_response(200)
                self.send_header('Content-Type', 'application/json' if self.path == '/state' else 'text/html')
                self.end_headers()
                self.wfile.write(payload.encode())

            def log_message(self, *_):
                pass

        server = ThreadingHTTPServer(('127.0.0.1', 0), Handler)
        thread = threading.Thread(target=server.serve_forever, daemon=True)
        thread.start()
        origin = f'http://127.0.0.1:{server.server_port}'
        preview = origin + '/preview?tab=one#details'
        for section in state['sections']:
            section['previewUrl'] = preview
        try:
            with tempfile.TemporaryDirectory() as tmp, sync_playwright() as pw:
                browser = pw.chromium.launch()
                page = browser.new_page()
                page.goto(origin + '/#section=one')
                with page.expect_download() as download:
                    page.locator('#download').click()
                saved = Path(tmp) / 'saved.html'
                download.value.save_as(saved)
                for source in (origin + '/', saved.as_uri()):
                    page.goto(source)
                    for index in (0, 1):
                        page.locator('#sections button').nth(index).click()
                        link = page.locator('.panel').nth(2).locator('.panel-head .open-preview')
                        self.assertTrue(link.is_visible())
                        self.assertEqual(link.inner_text(), 'Open preview ↗')
                        self.assertEqual(link.get_attribute('href'), preview)
                        with page.context.expect_page() as opened:
                            link.click()
                        tab = opened.value
                        tab.wait_for_load_state()
                        self.assertEqual(tab.url, preview)
                        self.assertEqual(tab.title(), 'Preview')
                        self.assertTrue(tab.evaluate('window.opener === null'))
                        tab.close()
                        if index == 0:
                            page.locator('.panel').nth(2).locator('img').click()
                            self.assertTrue(page.locator('#image-dialog').is_visible())
                            page.locator('#close-image').click()
                    for value in (None, 'javascript:alert(1)', '//example.com', 'https://user:pass@example.com'):
                        page.evaluate('(value) => { spec.sections[1].previewUrl=value; render(); }', value)
                        self.assertEqual(page.locator('.open-preview').count(), 0)
                browser.close()
        finally:
            server.shutdown()
            server.server_close()
            thread.join()

    def test_mockup_route_bridge_contract_is_present(self):
        source = Path(__file__).with_name('workflow-dashboard.html').read_text()
        for token in ('cleanMockupRoute', 'dashboard-mockup-route', 'mockup:route',
                      'assetTabUrl(sectionId,key,route=', 'writeRoute(sectionId,key,\'mock\',false,cleanMockupRoute(readRoute()))',
                      'Session record', 'renderRecord', "r.modal==='record'"):
            self.assertIn(token, source)

    def test_run_waits_for_options_and_names_need_platforms(self):
        s = fixture(); s['optionsConfirmedAt'] = None
        with self.assertRaisesRegex(ValueError, 'Select run options'): d.validate(s)
        s['phase'] = 'planning'; d.validate(s)
        s['optionsConfirmedAt'] = d.now(); s['referenceMode'] = 'names'
        with self.assertRaisesRegex(ValueError, 'Name the selected platforms'): d.validate(s)
        s['inspiration'] = 'Linear, Stripe'; s['phase'] = 'running'; d.validate(s)

    def test_ordinary_running_task_needs_no_loop_options(self):
        s = fixture()
        s.update(gauntlet=False, engine='current', optionsConfirmedAt=None)
        d.validate(s)
        s['engine'] = 'ralph'
        with self.assertRaisesRegex(ValueError, 'Select run options'):
            d.validate(s)

    def test_automatic_intake_creates_one_dashboard_without_loop_options(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            (root / '.git').mkdir()
            barrier = threading.Barrier(4)
            results = []

            def initialize(index):
                barrier.wait()
                results.append(d.initialize(root, slug='session-' + str(index)))

            threads = [threading.Thread(target=initialize, args=(index,)) for index in range(4)]
            for thread in threads:
                thread.start()
            for thread in threads:
                thread.join()

            self.assertEqual(sum(created for _, _, created in results), 1)
            first_plan, first_dashboard, _ = results[0]
            self.assertTrue(all(plan == first_plan for plan, _, _ in results))
            self.assertTrue(all(dashboard == first_dashboard for _, dashboard, _ in results))
            self.assertEqual(len(list((root / '.context').glob('*-plan.md'))), 1)
            self.assertEqual(len(list((root / '.context').glob('*-dashboard.html'))), 1)
            state = d.read_plan(first_plan)[2]
            self.assertEqual((state['engine'], state['gauntlet'], state['optionsConfirmedAt']),
                             ('current', False, None))
            d.validate(state)

    def test_done_needs_all_criteria_and_judge(self):
        s = fixture()
        s['sections'][0]['status'] = 'done'
        with self.assertRaisesRegex(ValueError, 'every criterion'): d.validate(s)
        s['sections'][0]['criteria'][0].update(passed=True, evidence='test.log')
        with self.assertRaisesRegex(ValueError, 'judge pass'): d.validate(s)
        s['gauntlet'] = False
        d.validate(s)

    def test_no_self_judging_or_stale_pass(self):
        for key, value in [('agentId', 'builder'), ('artifactRevision', 0), ('reference', '')]:
            s = passed()
            s['sections'][0]['judge'][key] = value
            with self.assertRaises(ValueError): d.validate(s)

    def test_missing_evidence_and_loose_ends(self):
        s = passed(); s['sections'][0]['criteria'][0]['evidence'] = ''
        with self.assertRaises(ValueError): d.validate(s)
        s = fixture(); s['phase'] = 'complete'
        with self.assertRaisesRegex(ValueError, 'every section done'): d.validate(s)
        s['phase'] = 'paused'; d.validate(s)

    def test_generated_target_requires_current_user_approval(self):
        s = passed()
        s['sections'][0]['target'] = {'kind': 'text', 'label': 'AI target', 'text': 'Draft', 'origin': 'generated', 'targetRevision': 2}
        with self.assertRaisesRegex(ValueError, 'explicit approval'): d.validate(s)
        s['sections'][0]['target']['approval'] = {'by': 'user', 'targetRevision': 1, 'evidence': 'User confirmed v1'}
        with self.assertRaisesRegex(ValueError, 'explicit approval'): d.validate(s)
        s['sections'][0]['target']['approval']['targetRevision'] = 2
        d.validate(s)

    def test_reject_duplicates_and_bad_schema(self):
        s = fixture(); s['sections'].append(copy.deepcopy(s['sections'][0]))
        with self.assertRaises(ValueError): d.validate(s)
        s = fixture(); s['schemaVersion'] = 2
        with self.assertRaises(ValueError): d.validate(s)

    def test_atomic_revision_conflict_and_judge_invalidation(self):
        with tempfile.TemporaryDirectory() as tmp:
            p = Path(tmp) / 'task-plan.md'
            s = passed()
            (Path(tmp) / 'target.png').write_bytes(b'fake-png-bytes')
            s['sections'][0]['target'] = {'kind': 'image', 'label': 'Target', 'path': 'target.png', 'source': 'Review'}
            p.write_text('UNCHANGED NARRATIVE\n```dashboard-state\n'+json.dumps(s)+'\n```\n')
            new = copy.deepcopy(s); new['sections'][0]['artifactRevision'] = 2
            result, _ = d.update(p, new, 1)
            self.assertEqual(result['sections'][0]['status'], 'review')
            self.assertEqual(result['sections'][0]['judge']['verdict'], 'pending')
            self.assertTrue(p.read_text().startswith('UNCHANGED NARRATIVE\n'))
            with self.assertRaisesRegex(ValueError, 'Revision conflict'): d.update(p, new, 1)
            self.assertEqual(d.read_plan(p)[2]['revision'], 2)

    def test_modes_preserve_plan_identity_and_evidence(self):
        with tempfile.TemporaryDirectory() as tmp:
            p = Path(tmp) / 'task-plan.md'; s = passed()
            p.write_text('```dashboard-state\n'+json.dumps(s)+'\n```\n')
            new = copy.deepcopy(s); new['engine'] = 'ralph'
            result, _ = d.update(p, new, 1)
            self.assertEqual(result['sections'], s['sections'])
            self.assertEqual(len(list(Path(tmp).glob('*-plan.md'))), 1)

    def test_assets_inline_and_no_script_breakout(self):
        with tempfile.TemporaryDirectory() as tmp:
            base = Path(tmp); p = base / 'task-plan.md'; s = fixture()
            s['title'] = '</script><script>alert(1)</script>'
            (base/'mock.html').write_text('<h1>v1</h1><script id="spec" type="application/json">{"versions":[1,2]}</script>')
            s['sections'][0]['target'] = {'kind': 'html', 'label': 'Mock', 'path': 'mock.html', 'source': 'Capture'}
            p.write_text('```dashboard-state\n'+json.dumps(s)+'\n```\n')
            rendered = d.render(p)
            self.assertNotIn(s['title'], rendered)
            public = d.public_spec(p)
            self.assertIn('"versions":[1,2]', public['sections'][0]['target']['html'])
            self.assertIn('sha256', public['sections'][0]['target'])
            s['sections'][0]['target']['path'] = '../outside.html'
            p.write_text('```dashboard-state\n'+json.dumps(s)+'\n```\n')
            with self.assertRaisesRegex(ValueError, 'inside'): d.render(p)

    def test_session_record_derives_sources_decisions_artifacts_and_remaining(self):
        with tempfile.TemporaryDirectory() as tmp:
            base = Path(tmp)
            p = base / 'task-plan.md'
            (base / 'mock.html').write_text('<!doctype html><p>Mockup</p>')
            s = fixture()
            s.update(gauntlet=False, optionsConfirmedAt=None)
            s['sections'][0].update(
                title='Build surface',
                next='Implement the approved target.',
                target={'kind': 'html', 'label': 'Approved mockup', 'path': 'mock.html', 'source': 'Design review'},
            )
            p.write_text(
                '# Task\n\n## Goal & user journey (current trajectory)\n\nOpen the finished surface.\n\n'
                '## System journey (current trajectory)\n\nRender the current plan.\n\n'
                '## Tasks\n\n- Build the surface.\n\n'
                '## Decisions & rationale\n\n- Keep one viewer.\n\n'
                '## Risks & assumptions\n\n- The plan remains present.\n\n'
                '## Sources\n\n- [Ticket](https://example.com/ticket)\n\n'
                '## Execution notes\n\n- Runtime verified.\n\n'
                '## Out of scope\n\n- Hosted storage.\n\n'
                '## Changelog\n\n- Added the record.\n\n'
                '## Dashboard state\n\n```dashboard-state\n' + json.dumps(s) + '\n```\n'
            )
            public = d.public_spec(p)
            record = public['record']
            self.assertEqual([entry['label'] for entry in record['sections']],
                             ['User journey', 'System journey', 'Tasks', 'Decisions', 'Risks',
                              'Sources', 'Execution notes', 'Out of scope', 'Changelog'])
            self.assertEqual(record['artifacts'][0]['label'], 'Approved mockup')
            self.assertEqual(record['remaining'][0]['next'], 'Implement the approved target.')
            rendered = d.render(p)
            self.assertIn('https://example.com/ticket', rendered)
            self.assertIn('Approved mockup', rendered)
            result, _ = d.update(p, public, 1)
            self.assertNotIn('record', result)
            self.assertNotIn('"record"', p.read_text())

    def test_link_regenerates_one_canonical_dashboard_and_rejects_ambiguity(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            context = root / '.context'
            context.mkdir()

            def write_plan(name, phase):
                state = fixture()
                state.update(gauntlet=False, optionsConfirmedAt=None, phase=phase)
                if phase == 'complete':
                    state['sections'][0]['status'] = 'done'
                    state['sections'][0]['criteria'][0].update(passed=True, evidence='verified')
                path = context / name
                path.write_text('```dashboard-state\n' + json.dumps(state) + '\n```\n')
                return path

            completed = write_plan('old-plan.md', 'complete')
            active = write_plan('current-plan.md', 'running')
            self.assertEqual(d.discover_plan(root), active.resolve())
            (context / 'current-dashboard.html').write_text('stale')
            output = d.export_dashboard(d.discover_plan(root))
            self.assertEqual(output, (context / 'current-dashboard.html').resolve())
            self.assertTrue(output.is_file())
            self.assertNotEqual(output.read_text(), 'stale')
            cli = subprocess.run(
                [sys.executable, str(DASHBOARD_SCRIPT), 'link', '--root', str(root)],
                capture_output=True, text=True,
            )
            self.assertEqual(cli.returncode, 0, cli.stderr)
            self.assertIn('DASHBOARD_PATH=' + str(output), cli.stdout)
            custom = subprocess.run(
                [sys.executable, str(DASHBOARD_SCRIPT), 'link', '--root', str(root),
                 '--output', str(context / 'not-canonical.html')],
                capture_output=True, text=True,
            )
            self.assertNotEqual(custom.returncode, 0)
            self.assertIn('link discovers the workspace plan', custom.stderr)
            self.assertFalse((context / 'not-canonical.html').exists())
            other = write_plan('other-plan.md', 'planning')
            with self.assertRaisesRegex(ValueError, 'Multiple active dashboard plans'):
                d.discover_plan(root)
            positional = subprocess.run(
                [sys.executable, str(DASHBOARD_SCRIPT), 'link', str(active), '--root', str(root)],
                capture_output=True, text=True,
            )
            self.assertNotEqual(positional.returncode, 0)
            self.assertIn('link discovers the workspace plan', positional.stderr)
            other.unlink()
            active.unlink()
            self.assertEqual(d.discover_plan(root), completed.resolve())

    def test_serve_attaches_when_healthy_registers_and_writes_receipt(self):
        with tempfile.TemporaryDirectory() as tmp:
            base = Path(tmp)
            plan = base / 'task-plan.md'
            state = fixture()
            state.update(gauntlet=False, optionsConfirmedAt=None)
            plan.write_text('```dashboard-state\n' + json.dumps(state) + '\n```\n')

            server, thread = start_fake_app(pid=4242)
            try:
                port = server.server_port
                called = []

                def fake_start_app(p):
                    called.append(p)
                    raise AssertionError('start_app should not run when already healthy')

                original_start_app = d.start_app
                d.start_app = fake_start_app
                try:
                    d.serve(plan, d.canonical_dashboard_path(plan), port)
                finally:
                    d.start_app = original_start_app
                self.assertEqual(called, [])

                plan_r = str(plan.resolve())
                self.assertIn(plan_r, [row['plan'] for row in server.plans])

                receipt = json.loads(d.runtime_receipt_path(plan).read_text())
                self.assertEqual(receipt['pid'], 4242)
                self.assertEqual(receipt['port'], port)
                self.assertEqual(receipt['plan'], plan_r)
                self.assertEqual(receipt['app'], 'gauntlet')
                self.assertEqual(receipt['url'], 'http://127.0.0.1:%d/p?plan=%s' % (port, d.quote(plan_r, safe='')))
                self.assertTrue(d.canonical_dashboard_path(plan).is_file())
            finally:
                stop_fake_app(server, thread)

    def test_serve_starts_app_when_not_healthy(self):
        with tempfile.TemporaryDirectory() as tmp:
            base = Path(tmp)
            plan = base / 'task-plan.md'
            state = fixture()
            state.update(gauntlet=False, optionsConfirmedAt=None)
            plan.write_text('```dashboard-state\n' + json.dumps(state) + '\n```\n')

            port = free_port()
            spawned = {}

            def fake_start_app(p):
                self.assertEqual(p, port)
                server = ThreadingHTTPServer(('127.0.0.1', port), FakeGauntletApp)
                server.plans = []
                server.app_pid = 777
                thread = threading.Thread(target=server.serve_forever, daemon=True)
                thread.start()
                spawned['server'], spawned['thread'] = server, thread
                return d.app_health(port)

            original_start_app = d.start_app
            d.start_app = fake_start_app
            try:
                d.serve(plan, d.canonical_dashboard_path(plan), port)
            finally:
                d.start_app = original_start_app
                if 'server' in spawned:
                    stop_fake_app(spawned['server'], spawned['thread'])

            receipt = json.loads(d.runtime_receipt_path(plan).read_text())
            self.assertEqual(receipt['pid'], 777)
            self.assertEqual(receipt['port'], port)

    def test_link_prints_dashboard_url_only_when_healthy_and_registered(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            (root / '.git').mkdir()
            context = root / '.context'
            context.mkdir()
            plan = context / 'demo-plan.md'
            state = fixture()
            state.update(gauntlet=False, optionsConfirmedAt=None)
            plan.write_text('```dashboard-state\n' + json.dumps(state) + '\n```\n')

            cli = lambda: subprocess.run(
                [sys.executable, str(DASHBOARD_SCRIPT), 'link', '--root', str(root)],
                capture_output=True, text=True,
            )

            # No receipt at all: only the file path line.
            no_receipt = cli()
            self.assertEqual(no_receipt.returncode, 0, no_receipt.stderr)
            self.assertNotIn('DASHBOARD_URL=', no_receipt.stdout)

            server, thread = start_fake_app(pid=999)
            try:
                port = server.server_port
                plan_r = str(plan.resolve())
                url = 'http://127.0.0.1:%d/p?plan=%s' % (port, d.quote(plan_r, safe=''))
                d.atomic_write(d.runtime_receipt_path(plan), json.dumps({
                    'pid': 999, 'port': port, 'url': url, 'plan': plan_r,
                    'app': 'gauntlet', 'startedAt': d.now(),
                }))

                # Receipt exists but plan is not registered yet: still no URL.
                unregistered = cli()
                self.assertEqual(unregistered.returncode, 0, unregistered.stderr)
                self.assertNotIn('DASHBOARD_URL=', unregistered.stdout)

                server.plans.append({'plan': plan_r, 'title': 't', 'phase': 'running',
                                      'revision': 1, 'updatedAt': d.now(), 'root': str(root)})
                registered = cli()
                self.assertEqual(registered.returncode, 0, registered.stderr)
                self.assertIn('DASHBOARD_URL=' + url, registered.stdout)
            finally:
                stop_fake_app(server, thread)

    def test_stop_unregisters_without_killing_when_other_plans_remain(self):
        with tempfile.TemporaryDirectory() as tmp:
            base = Path(tmp)
            plan = base / 'task-plan.md'
            state = fixture()
            state.update(gauntlet=False, optionsConfirmedAt=None)
            plan.write_text('```dashboard-state\n' + json.dumps(state) + '\n```\n')

            server, thread = start_fake_app(pid=4242)
            original_app_receipt = d.APP_RECEIPT
            d.APP_RECEIPT = base / 'gauntlet-server.json'
            try:
                port = server.server_port
                plan_r = str(plan.resolve())
                other_r = str((base / 'other-plan.md').resolve())
                server.plans.extend([
                    {'plan': plan_r, 'title': 't', 'phase': 'running', 'revision': 1,
                     'updatedAt': d.now(), 'root': str(base)},
                    {'plan': other_r, 'title': 'o', 'phase': 'running', 'revision': 1,
                     'updatedAt': d.now(), 'root': str(base)},
                ])
                d.atomic_write(d.runtime_receipt_path(plan), json.dumps({
                    'pid': 4242, 'port': port, 'url': 'http://x', 'plan': plan_r,
                    'app': 'gauntlet', 'startedAt': d.now(),
                }))
                d.atomic_write(d.APP_RECEIPT, json.dumps({'pid': 4242, 'port': port, 'startedAt': d.now()}))

                killed = []
                with unittest.mock.patch('os.kill', lambda pid, sig: killed.append((pid, sig))):
                    result = d.stop_runtime(plan, 4242)

                self.assertEqual(killed, [])
                self.assertEqual(result['pid'], 4242)
                self.assertFalse(d.runtime_receipt_path(plan).is_file())
                self.assertTrue(d.APP_RECEIPT.is_file())
                self.assertNotIn(plan_r, [row['plan'] for row in server.plans])
                self.assertIn(other_r, [row['plan'] for row in server.plans])
            finally:
                d.APP_RECEIPT = original_app_receipt
                stop_fake_app(server, thread)

    def test_stop_kills_app_when_no_plans_remain_and_pid_command_matches(self):
        with tempfile.TemporaryDirectory() as tmp:
            base = Path(tmp)
            plan = base / 'task-plan.md'
            state = fixture()
            state.update(gauntlet=False, optionsConfirmedAt=None)
            plan.write_text('```dashboard-state\n' + json.dumps(state) + '\n```\n')

            server, thread = start_fake_app(pid=4242)
            original_app_receipt = d.APP_RECEIPT
            d.APP_RECEIPT = base / 'gauntlet-server.json'
            try:
                port = server.server_port
                plan_r = str(plan.resolve())
                server.plans.append({'plan': plan_r, 'title': 't', 'phase': 'running',
                                      'revision': 1, 'updatedAt': d.now(), 'root': str(base)})
                d.atomic_write(d.runtime_receipt_path(plan), json.dumps({
                    'pid': 4242, 'port': port, 'url': 'http://x', 'plan': plan_r,
                    'app': 'gauntlet', 'startedAt': d.now(),
                }))
                d.atomic_write(d.APP_RECEIPT, json.dumps({'pid': 4242, 'port': port, 'startedAt': d.now()}))

                killed = []
                original_pid_command_and_cwd = d.pid_command_and_cwd
                original_pid_exited = d.pid_exited
                d.pid_command_and_cwd = lambda pid: ('npm run dev -- -p 4747 (gauntlet)', base)
                d.pid_exited = lambda pid: True
                try:
                    with unittest.mock.patch('os.kill', lambda pid, sig: killed.append((pid, sig))):
                        d.stop_runtime(plan, 4242)
                finally:
                    d.pid_command_and_cwd = original_pid_command_and_cwd
                    d.pid_exited = original_pid_exited

                self.assertEqual(killed, [(4242, signal.SIGTERM)])
                self.assertFalse(d.APP_RECEIPT.is_file())
                self.assertEqual(server.plans, [])
            finally:
                d.APP_RECEIPT = original_app_receipt
                stop_fake_app(server, thread)

    def test_handoff_stamps_manifest_and_resolves_back_same_machine(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            (root / '.git').mkdir()
            context = root / '.context'
            context.mkdir()
            plan = context / 'demo-plan.md'
            state = fixture()
            state.update(engine='ralph', gauntlet=True, phase='running', iteration=3)
            plan.write_text('SOURCE NARRATIVE\n```dashboard-state\n' + json.dumps(state) + '\n```\n')

            def cli(*args):
                return subprocess.run([sys.executable, str(DASHBOARD_SCRIPT), *args],
                                      capture_output=True, text=True)

            first = cli('handoff', str(plan), '--by', 'agent-A', '--note', 'quota wall')
            self.assertEqual(first.returncode, 0, first.stderr)
            self.assertIn('HANDOFF_HOP=1', first.stdout)
            info = d.read_plan(plan)[2]['handoff']
            self.assertEqual((info['hop'], info['by'], info['note']), (1, 'agent-A', 'quota wall'))
            self.assertEqual(Path(info['plan']).resolve(), plan.resolve())
            # Chainable: a second handoff advances the hop from the one living plan.
            second = cli('handoff', str(plan), '--by', 'agent-B')
            self.assertIn('HANDOFF_HOP=2', second.stdout)
            self.assertEqual(d.read_plan(plan)[2]['handoff']['hop'], 2)
            # Banner is self-evident in the rendered dashboard.
            self.assertIn('Handed off', d.canonical_dashboard_path(plan).read_text())

            dashboard = d.canonical_dashboard_path(plan).resolve()
            for target in (str(plan), 'file://' + str(dashboard), str(dashboard)):
                with self.subTest(target=target):
                    resolved = cli('resolve', '--target', target)
                    self.assertEqual(resolved.returncode, 0, resolved.stderr)
                    self.assertIn('PLAN_PATH=' + str(plan.resolve()), resolved.stdout)
                    self.assertIn('ENGINE=ralph', resolved.stdout)
                    self.assertIn('GAUNTLET=true', resolved.stdout)
                    self.assertIn('ITERATION=3', resolved.stdout)
                    self.assertIn('HANDOFF_HOP=2', resolved.stdout)
            missing = cli('resolve', '--target', str(context / 'nope-plan.md'))
            self.assertNotEqual(missing.returncode, 0)
            plain = cli('resolve', '--target', str(context / 'notes.txt'))
            self.assertNotEqual(plain.returncode, 0)

    def test_invalid_update_does_not_advance_plan(self):
        with tempfile.TemporaryDirectory() as tmp:
            p = Path(tmp)/'task-plan.md'; s = fixture()
            p.write_text('```dashboard-state\n'+json.dumps(s)+'\n```\n')
            original = p.read_bytes()
            s['sections'][0]['current'] = {'kind': 'image', 'label': 'Missing', 'path': 'no.png', 'source': 'Capture'}
            with self.assertRaisesRegex(ValueError, 'Missing asset'): d.update(p, s, 1)
            self.assertEqual(p.read_bytes(), original)

    def test_missing_asset_and_multiple_blocks_fail(self):
        with tempfile.TemporaryDirectory() as tmp:
            p = Path(tmp)/'task-plan.md'; s = fixture()
            s['sections'][0]['target'] = {'kind': 'image','label': 'Missing','path': 'missing.png','source': 'Capture'}
            block = '```dashboard-state\n'+json.dumps(s)+'\n```\n'
            p.write_text(block)
            with self.assertRaisesRegex(ValueError, 'Missing asset'): d.render(p)
            p.write_text(block+block)
            with self.assertRaisesRegex(ValueError, 'exactly one'): d.read_plan(p)

    @unittest.skipUnless(HAVE_PLAYWRIGHT, 'playwright not installed')
    def test_mock_dialog_open_in_new_tab_shows_the_same_html(self):
        """An html asset is inlined (srcdoc), so the viewer had no way to open it outside the
        modal. "Open in new tab" must open a fresh tab whose document is the asset's own html,
        from the modal's header and from the panel caption."""
        with tempfile.TemporaryDirectory() as tmp:
            base = Path(tmp)
            (base / 'mock.html').write_text('<!doctype html><html><head><title>Mock tab</title></head><body><main id="mock-root">Mock content</main></body></html>')
            p = base / 'task-plan.md'
            s = fixture()
            s['sections'][0]['target'] = {'kind': 'html', 'label': 'Mock', 'path': 'mock.html',
                                           'source': 'Capture', 'viewport': {'width': 1440, 'height': 900}}
            p.write_text('```dashboard-state\n' + json.dumps(s) + '\n```\n')
            out = base / 'dashboard.html'
            out.write_text(d.render(p))
            with sync_playwright() as pw:
                browser = pw.chromium.launch()
                context = browser.new_context(viewport={'width': 1440, 'height': 900})
                page = context.new_page()
                page.goto(out.as_uri())
                page.wait_for_timeout(200)
                for opener in ('.panel-caption .open-mock-tab', '#open-mock-tab'):
                    if opener == '#open-mock-tab':
                        page.click('.open-mock')
                        page.wait_for_timeout(200)
                    with context.expect_page() as new_page_info:
                        page.click(opener)
                    tab = new_page_info.value
                    tab.wait_for_load_state()
                    self.assertEqual(tab.title(), 'Mock tab', opener)
                    self.assertEqual(tab.locator('#mock-root').inner_text(), 'Mock content', opener)
                    tab.close()
                browser.close()

    @unittest.skipUnless(HAVE_PLAYWRIGHT, 'playwright not installed')
    def test_mock_dialog_iframe_fills_visible_area_without_clipping(self):
        """Regression: the mock-dialog's iframe used to be CSS-scaled (transform) to a fixed
        design viewport, so its own contentWindow.innerHeight lied about how much room it had
        and the dialog's overflow:hidden clipped whatever an embedded self-fitting page (the
        mockup shell) rendered past that lie. The iframe must now fill its bounded flex
        container at true 1:1 size on any modal size, so its innerHeight is never a lie."""
        with tempfile.TemporaryDirectory() as tmp:
            base = Path(tmp)
            (base / 'mock.html').write_text('<!doctype html><html><body>Mock content</body></html>')
            p = base / 'task-plan.md'
            s = fixture()
            s['sections'][0]['target'] = {'kind': 'html', 'label': 'Mock', 'path': 'mock.html',
                                           'source': 'Capture', 'viewport': {'width': 1440, 'height': 900}}
            p.write_text('```dashboard-state\n' + json.dumps(s) + '\n```\n')
            out = base / 'dashboard.html'
            out.write_text(d.render(p))

            with sync_playwright() as pw:
                browser = pw.chromium.launch()
                for width, height in [(1900, 1010), (1440, 900)]:
                    page = browser.new_page(viewport={'width': width, 'height': height})
                    page.goto(out.as_uri())
                    page.wait_for_timeout(200)
                    page.click('.open-mock')
                    page.wait_for_timeout(200)
                    geo = page.evaluate(
                        """() => {
                            const dialog = document.getElementById('mock-dialog');
                            const iframe = dialog.querySelector('iframe');
                            const dr = dialog.getBoundingClientRect();
                            const ir = iframe.getBoundingClientRect();
                            return {
                                dialogBottom: dr.bottom,
                                iframeBottom: ir.bottom,
                                iframeHeight: ir.height,
                                contentInnerHeight: iframe.contentWindow.innerHeight,
                            };
                        }"""
                    )
                    self.assertLessEqual(
                        geo['iframeBottom'], geo['dialogBottom'] + 0.5,
                        f"at {width}x{height}: iframe bottom {geo['iframeBottom']} overruns "
                        f"the modal's visible bottom {geo['dialogBottom']} — {geo}",
                    )
                    self.assertAlmostEqual(
                        geo['contentInnerHeight'], geo['iframeHeight'], delta=1,
                        msg=f"at {width}x{height}: iframe.contentWindow.innerHeight "
                            f"({geo['contentInnerHeight']}) must equal the iframe's own "
                            f"rendered height ({geo['iframeHeight']}) — {geo}",
                    )
                    page.close()
                browser.close()

    @unittest.skipUnless(HAVE_PLAYWRIGHT, 'playwright not installed')
    def test_live_routes_nested_escape_and_feedback_survive_refresh(self):
        inner = ('<!doctype html><button id="open" onclick="document.querySelector(\'dialog\').showModal()">Open</button>'
                 '<input id="feedback" value="original"><dialog><input id="inside"></dialog>')
        asset = '<!doctype html><iframe srcdoc="' + html.escape(inner, quote=True) + '"></iframe>'
        state = fixture()
        state['sections'][0]['target'] = {'kind': 'html', 'label': 'Mock', 'html': asset, 'sha256': 'old'}
        state['sections'].append({'id': 'two', 'title': 'Two', 'status': 'todo', 'artifactRevision': 1,
                                  'criteria': [{'id': 'c2', 'text': 'Second', 'passed': False}]})

        class Handler(BaseHTTPRequestHandler):
            def do_GET(self):
                payload = json.dumps(state) if self.path == '/state' else d.render_spec(state)
                self.send_response(200)
                self.send_header('Content-Type', 'application/json' if self.path == '/state' else 'text/html')
                self.end_headers()
                self.wfile.write(payload.encode())

            def log_message(self, *_):
                pass

        server = ThreadingHTTPServer(('127.0.0.1', 0), Handler)
        thread = threading.Thread(target=server.serve_forever, daemon=True)
        thread.start()
        route = f'http://127.0.0.1:{server.server_port}/#section=one&asset=target&modal=mock'
        try:
            with sync_playwright() as pw:
                browser = pw.chromium.launch()
                page = browser.new_page()
                errors = []
                page.on('pageerror', lambda e: errors.append(str(e)))
                page.goto(route)
                nested = page.frame_locator('#mock-dialog iframe').frame_locator('iframe')
                nested.locator('#open').click()
                nested.locator('#inside').press('Escape')
                self.assertFalse(nested.locator('dialog').evaluate('(d) => d.open'))
                self.assertTrue(page.locator('#mock-dialog').evaluate('(d) => d.open'))
                nested.locator('#feedback').press('Escape')
                page.wait_for_function('() => !document.querySelector("#mock-dialog").open')
                self.assertFalse(page.locator('#mock-dialog').is_visible())
                page.locator('#sections button').nth(1).click()
                page.go_back()
                page.wait_for_function('() => document.querySelector("#title").textContent === "One"')
                page.go_forward()
                page.wait_for_function('() => document.querySelector("#title").textContent === "Two"')
                page.goto(route)
                page.reload()
                page.wait_for_function('() => document.querySelector("#mock-dialog").open')
                self.assertEqual(page.locator('#open-mock-tab').get_attribute('href'), route)
                with page.context.expect_page() as opened:
                    page.locator('#open-mock-tab').click()
                tab = opened.value
                tab.wait_for_load_state()
                self.assertEqual(tab.url, route)
                tab.close()
                nested.locator('#feedback').fill('retained feedback')
                state['revision'] = 2
                page.wait_for_function('() => document.querySelector("#updated").textContent.includes("v2")')
                self.assertEqual(nested.locator('#feedback').input_value(), 'retained feedback')
                state['sections'][0]['target'].update(sha256='new', html=asset.replace('original', 'new revision'))
                state['revision'] = 3
                page.wait_for_function('() => document.querySelector("#updated").textContent.includes("v3")')
                self.assertEqual(nested.locator('#feedback').input_value(), 'new revision')
                self.assertTrue(page.evaluate('Object.values(spec.feedbackDrafts).some(d => d.html.includes("retained feedback"))'))
                self.assertEqual(page.url, route)
                self.assertEqual(errors, [])
                browser.close()
        finally:
            server.shutdown()
            server.server_close()
            thread.join()


if __name__ == '__main__': unittest.main()
