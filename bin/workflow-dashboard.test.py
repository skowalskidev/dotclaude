#!/usr/bin/env python3
"""Regression tests for completion, concurrent updates and portable evidence."""
import copy
import importlib.util
import json
import html
import threading
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
import tempfile
import unittest

spec = importlib.util.spec_from_file_location('dashboard', Path(__file__).with_name('workflow-dashboard.py'))
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


class DashboardTests(unittest.TestCase):
    def test_mockup_route_bridge_contract_is_present(self):
        source = Path(__file__).with_name('workflow-dashboard.html').read_text()
        for token in ('cleanMockupRoute', 'dashboard-mockup-route', 'mockup:route',
                      'assetTabUrl(sectionId,key,route=', 'writeRoute(sectionId,key,\'mock\',false,cleanMockupRoute(readRoute()))'):
            self.assertIn(token, source)

    def test_run_waits_for_options_and_names_need_platforms(self):
        s = fixture(); s['optionsConfirmedAt'] = None
        with self.assertRaisesRegex(ValueError, 'Select run options'): d.validate(s)
        s['phase'] = 'planning'; d.validate(s)
        s['optionsConfirmedAt'] = d.now(); s['referenceMode'] = 'names'
        with self.assertRaisesRegex(ValueError, 'Name the selected platforms'): d.validate(s)
        s['inspiration'] = 'Linear, Stripe'; s['phase'] = 'running'; d.validate(s)

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
            s = passed(); p.write_text('UNCHANGED NARRATIVE\n```dashboard-state\n'+json.dumps(s)+'\n```\n')
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
