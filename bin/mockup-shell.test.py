#!/usr/bin/env python3
"""Behavioral contracts for the shared frame and mockup/decision adapters.

Run after the edit batch converges and resource capacity is admitted. Requires
Python Playwright/Chromium. No network or service credentials are used.
"""
import copy
import importlib.util
import json
import subprocess
import sys
import tempfile
from pathlib import Path

HERE = Path(__file__).resolve().parent


def load(name, path):
    spec = importlib.util.spec_from_file_location(name, path)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def main():
    from playwright.sync_api import sync_playwright
    from presentation_build import extract
    fixture = json.loads((HERE / 'mockup-synthetic-spec.json').read_text())
    fixture['designTokens']['fontFamily'] = '"system-ui"'
    fixture['variants']['legacy']=copy.deepcopy(fixture['variants']['gamma'])
    fixture['variants']['legacy']['label']='Before — superseded: An older proposal'
    fixture['manifest']['variantIds'].append('legacy')
    fixture['versions'][0]['variantIds'].append('legacy')
    fixture['versions'][0]['variantLabelOverrides']['legacy']='Friendly earlier label'

    fixture['variants']['beta']['flashSelector'] = '#state-label, h1'
    for persona, capture in fixture['variants']['beta']['captures'].items():
        fixture['variants']['beta']['captures'][persona]=capture.replace('State: base', 'State: undeclared-initial')
    phone = next(p for p in fixture['personas'] if p['id'] == 'mobile')
    phone['label']=f'Mobile {phone["w"]}×{phone["h"]}'
    fixture['personas'].append({**phone, 'id': 'duplicate', 'label': 'Duplicate'})
    fixture['personas'].append({**phone, 'id': 'native', 'label': 'Native'})
    for variant in fixture['variants'].values():
        variant['captures']['duplicate'] = variant['captures']['mobile']
        variant['captures']['native'] = variant['captures']['mobile'].replace('</body>', '<p>Native content</p></body>')
    with tempfile.TemporaryDirectory() as tmp:
        path = Path(tmp)
        source, built = path / 'spec.json', path / 'mockup.html'
        source.write_text(json.dumps(fixture))
        subprocess.run([sys.executable, str(HERE / 'mockup-build.py'), str(source), str(built)], check=True)
        assert extract(built.read_text()) == fixture, 'exact spec roundtrip'
        again = path / 'again.html'
        back = path / 'back.json'; back.write_text(json.dumps(extract(built.read_text())))
        subprocess.run([sys.executable, str(HERE / 'mockup-build.py'), str(back), str(again)], check=True)
        assert built.read_bytes() == again.read_bytes(), 'deterministic roundtrip'
        decision = load('decision', HERE / 'decision-artifact.py')
        decision_spec=copy.deepcopy(decision.EXAMPLE)
        decision_spec['sections'][0]['cards'][0]['control']={'type':'radio','group':'scope','default':True}
        decision_spec['runtime']={'comments':{'small':'Preserve this prior note'},'included':{'docs':False}}
        decision_path = path / 'decision.html'; decision_path.write_text(decision.build(decision_spec))
        assert extract(decision_path.read_text())==decision_spec, 'legacy decision metadata roundtrips unchanged'
        assert decision.build(extract(decision_path.read_text()))==decision_path.read_text(), 'decision rebuild is deterministic'
        decision.build(decision.EXAMPLE)  # New read-only specs need no control schema.

        with sync_playwright() as pw:
            browser = pw.chromium.launch()
            page = browser.new_page(viewport={'width': 1440, 'height': 900})
            errors=[]; page.on('pageerror', lambda error: errors.append(str(error)))
            page.goto(built.as_uri()); page.wait_for_timeout(150)
            def active():
                return page.locator('#mock-stage iframe').first
            def state_label():
                return active().content_frame.locator('#state-label').inner_text()
            def fits():
                return page.evaluate('''() => {const s=document.getElementById('mock-stage').getBoundingClientRect();return [...document.querySelectorAll('.mock-frame-wrap')].every(h=>{const r=h.getBoundingClientRect(),f=h.querySelector('iframe').getBoundingClientRect();return f.left>=s.left-.5&&f.top>=s.top-.5&&f.right<=s.right+.5&&f.bottom<=s.bottom+.5&&f.right<=r.right+.5&&f.bottom<=r.bottom+.5})}''')
            assert 'system-ui' in page.locator('body').evaluate('(el)=>getComputedStyle(el).fontFamily')
            assert page.locator('[data-pick-persona="duplicate"]').count()==0
            assert page.locator('[data-pick-persona="native"]').count()==1
            assert page.locator('[data-pick-persona="mobile"]').inner_text().count(f'{phone["w"]}×{phone["h"]}')==1
            assert page.locator('#history-diff').count()==0, 'no implementation field-diff UI'
            assert page.locator('[data-history-variant="legacy"]').count()==1, 'friendly override retains superseded base status'
            assert page.locator('[data-pick-variant="legacy"]').count()==0, 'legacy round is absent from current variants'

            assert page.locator('#mock-highlight').get_attribute('aria-checked')=='false'
            page.click('#show-before'); page.click('[data-goto-state="modal"]');page.wait_for_timeout(100)
            assert 'modal' in state_label()
            page.click('#show-after');page.wait_for_timeout(100)
            assert state_label()=='State: base', 'overlay teardown on variant switch'
            assert page.locator('#mock-stage iframe').count()==1
            page.click('[data-goto-state="bottom_sheet"]');page.wait_for_timeout(100)
            page.click('[data-pick-persona="mobile"]');page.wait_for_timeout(100)
            assert 'bottom_sheet' in state_label(), 'device retains valid state'
            assert active().evaluate('(el)=>el.clientWidth')==phone['w']
            page.click('[data-goto-state="base"]');page.wait_for_timeout(100)
            assert active().content_frame.locator('.is-open').count()==0, 'state teardown'
            page.click('#mock-highlight');page.click('#mock-highlight');page.wait_for_timeout(1300)
            assert active().content_frame.locator('html').get_attribute('class') in ('',None), 'highlight stays off after prior timer interval'
            assert active().content_frame.locator('h1').evaluate('(el)=>getComputedStyle(el).outlineStyle')=='none', 'comma selector does not escape highlight class'
            page.click('#mock-highlight');page.click('[data-goto-state="bottom_sheet"]');page.click('#mock-highlight');page.wait_for_timeout(150)
            assert active().content_frame.locator('html.presentation-highlight').count()==0, 'load reads latest highlight state'
            page.evaluate("document.querySelector('#mock-stage iframe').dataset.marker='kept'")
            page.select_option('#frame-theme','dark');page.click('#mock-rail-toggle-btn');page.click('#open-controls')
            assert active().get_attribute('data-marker')=='kept', 'theme and sidebar never remount'
            assert active().evaluate('(el)=>getComputedStyle(el).colorScheme')=='light'
            assert fits()
            page.click('#mock-view-compare');page.wait_for_timeout(120)
            assert page.locator('.mock-pane').evaluate_all('(els)=>els.map(e=>e.dataset.variant)')==['alpha','beta']
            assert fits(), 'two current panes fit both axes'
            page.evaluate("document.querySelectorAll('#mock-stage iframe').forEach(f=>f.dataset.marker='compare')")
            page.set_viewport_size({'width':1024,'height':520});page.wait_for_timeout(100)
            assert fits() and active().get_attribute('data-marker')=='compare', 'resize refits without reload'
            page.click('#mock-history summary');page.click('[data-history-variant="gamma"]');page.wait_for_timeout(100)
            assert page.locator('#mock-stage iframe').count()==1 and page.locator('.history-banner').count()==1
            assert page.locator('#mock-view-compare').is_disabled()
            page.goto(built.as_uri()+'#v=v1&variant=legacy&persona=mobile&view=compare');page.wait_for_timeout(100)
            assert page.locator('.mock-pane').count()==1 and page.locator('.history-banner').count()==1, 'friendly legacy label cannot enter current Compare'
            assert page.locator('[data-pick-variant="legacy"]').count()==0

            page.click('#back-current');page.wait_for_timeout(100)
            assert page.locator('.history-banner').count()==0
            page.evaluate("document.body.appendChild(Object.assign(document.createElement('div'),{id:'escaped-overlay'}))")
            page.wait_for_timeout(30);assert page.locator('#escaped-overlay').count()==0
            page.goto(built.as_uri()+'#v=missing&variant=missing&persona=missing&state=missing');page.wait_for_timeout(100)
            assert 'variant=alpha' in page.url and 'state=base' in page.url and 'missing' not in page.url, 'stale route validated and declared default state selected'
            page.goto(built.as_uri()+'#v=v1&variant=beta&persona=mobile&state=bottom_sheet');page.wait_for_timeout(150)
            assert 'bottom_sheet' in state_label(), 'reviewed route restored'
            page.set_viewport_size({'width':390,'height':844});page.wait_for_timeout(100)
            if page.locator('#open-controls').is_visible():page.click('#open-controls')
            assert page.locator('#mock-rail').evaluate('(el)=>el.scrollWidth<=el.clientWidth'), 'narrow sidebar no overflow'
            page.click('#mock-rail-toggle-btn');assert fits(), 'phone fits on mobile'
            # Earlier versions remain viewable; field-diff metadata stays hidden.
            multi=copy.deepcopy(fixture)
            multi['variants']['delta']=copy.deepcopy(multi['variants']['beta'])
            multi['variants']['delta']['label']='Another current proposal'
            multi['versions'].append({**copy.deepcopy(multi['versions'][0]),'id':'v2','diffData':{'changed':True}})
            multi['versions'][-1]['variantIds'].append('delta')
            source.write_text(json.dumps(multi));subprocess.run([sys.executable,str(HERE/'mockup-build.py'),str(source),str(again)],check=True)
            page.set_viewport_size({'width':1440,'height':900});page.goto(again.as_uri())
            if page.locator('#open-controls').is_visible(): page.click('#open-controls')
            page.click('#mock-history summary')
            assert page.locator('#history-diff,#mock-diff-from,#mock-diff-to').count()==0, 'history only views designs'
            assert extract(again.read_text())['versions'][-1]['diffData']=={'changed':True}, 'field metadata retained for CLI extraction'
            page.click('[data-history-version="v1"]');page.wait_for_timeout(100)
            assert page.locator('.history-banner').count()==1 and page.locator('#mock-stage iframe').count()==1
            page.goto(again.as_uri()+'#v=v2&variant=delta&persona=mobile&view=compare');page.wait_for_timeout(100)
            assert page.locator('.mock-pane').evaluate_all('(els)=>els.map(e=>e.dataset.variant)')==['alpha','delta'], 'deep link selects current After for Compare'
            page.goto(again.as_uri()+'#v=v2&variant=beta&persona=mobile');page.wait_for_timeout(100)
            page.keyboard.press('ArrowDown');page.click('#mock-view-compare');page.wait_for_timeout(100)
            assert page.locator('.mock-pane').evaluate_all('(els)=>els.map(e=>e.dataset.variant)')==['alpha','delta'], 'arrow navigation selects current After for Compare'
            page.goto(again.as_uri()+'#v=v1&variant=alpha&persona=mobile');page.wait_for_timeout(100)
            page.keyboard.press('ArrowDown');page.wait_for_timeout(100)
            assert page.locator('.history-banner').count()==1, 'old version stays labelled after arrow navigation'
            active().content_frame.locator('body').evaluate("el=>parent.postMessage({type:'mockup:navigate-variant',variantId:'alpha'},'*')")
            page.wait_for_timeout(100)
            assert page.locator('.history-banner').count()==1, 'old capture navigation stays labelled history'
            no_baseline=copy.deepcopy(fixture)
            no_baseline['variants']={'beta':no_baseline['variants']['beta']}
            no_baseline['manifest']['variantIds']=['beta'];no_baseline['manifest']['defaultVariant']='beta'
            no_baseline['versions']=[{'id':'v1','variantIds':['beta'],'defaultVariant':'beta'}]
            source.write_text(json.dumps(no_baseline));single=path/'no-baseline.html'
            subprocess.run([sys.executable,str(HERE/'mockup-build.py'),str(source),str(single)],check=True)
            page.goto(single.as_uri());page.wait_for_timeout(100);page.keyboard.press('b')
            assert page.locator('.mock-pane').get_attribute('data-variant')=='beta', 'B is safe with no baseline'

            # Pure viewers keep old interaction metadata inert in #spec.
            for artifact in (built,decision_path):
                page.goto(artifact.as_uri());page.wait_for_timeout(100)
                assert page.locator('textarea,input[type="radio"],input[type="checkbox"]').count()==0
                assert page.locator('#copy-spec,#save-html,#copy-response,#generate-response,[data-select-all],[data-count]').count()==0
            assert page.locator('.decision-card').count()==3
            assert 'Small update' in page.locator('.decision-doc').inner_text()
            assert 'Preserve this prior note' not in page.locator('body').inner_text()
            if page.locator('#open-controls').is_visible():page.click('#open-controls')
            page.evaluate("document.querySelector('.decision-card').dataset.marker='same-card'")
            page.select_option('#frame-theme','light');page.click('#mock-rail-toggle-btn');page.click('#open-controls')
            assert page.locator('.decision-card').first.get_attribute('data-marker')=='same-card'
            page.set_viewport_size({'width':390,'height':844});page.reload();page.wait_for_timeout(100)
            assert page.locator('#presentation-app').evaluate("el=>el.classList.contains('is-collapsed')")
            assert page.locator('.decision-card').first.is_visible()
            assert page.locator('textarea,input').count()==0, 'phone design viewer has no response or choice inputs'
            assert json.loads(page.locator('#spec').text_content())==decision_spec, 'viewing never mutates retained metadata'
            page.click('#open-controls');page.click('[data-jump="direction"]')
            assert page.locator('#presentation-app').evaluate("el=>el.classList.contains('is-collapsed')"), 'section navigation closes the phone sheet'

            # Proposal feedback is explicit and isolated from pure viewers.
            proposal=copy.deepcopy(decision_spec);proposal['feedback']=True
            proposal['sections'][0]['cards'][0]['detail']='Supporting evidence stays collapsed.'
            long_detail=' '.join(['Preserve every meaningful detail.']*9)
            proposal['sections'][0]['cards'][1].pop('tradeoff')
            proposal['sections'][0]['cards'][1]['explainer']=long_detail
            proposal['sections'][0]['cards'][2].pop('tradeoff')
            proposal['sections'][0]['cards'][2].update(explainer=long_detail,verdict='Clarifies the flow; leaves the product unchanged.')
            proposal_path=path/'proposal.html';proposal_path.write_text(decision.build(proposal))
            page.goto(proposal_path.as_uri())
            page.evaluate("Object.defineProperty(navigator,'clipboard',{configurable:true,value:{writeText:async text=>{window.copied=text}}})")
            first=page.locator('.decision-card').first
            assert page.locator('.decision-card').nth(1).locator(':scope > p').count()==0, 'long legacy prose is not a visible summary'
            assert page.locator('.decision-card').nth(1).locator('.decision-details p').text_content()==long_detail, 'long prose is preserved intact'
            legacy=page.locator('.decision-card').nth(1)
            assert not legacy.locator('.decision-details p').is_visible()
            legacy.locator('.decision-details summary').click()
            assert legacy.locator('.decision-details p').is_visible()
            legacy.locator('.decision-details summary').click()
            assert page.locator('.decision-card').nth(2).locator(':scope > p').inner_text()=='Clarifies the flow; leaves the product unchanged.'
            assert not page.locator('.decision-card').nth(2).locator('.decision-details p').is_visible()
            assert first.locator('.decision-details').get_attribute('open') is None
            assert not first.get_by_text('Supporting evidence stays collapsed.').is_visible()
            first.locator('.decision-details summary').click()
            assert first.get_by_text('Supporting evidence stays collapsed.').is_visible()
            first.locator('[data-choice]').select_option('Revise')
            first.locator('.decision-feedback summary').click()
            first.locator('[data-comment]').fill('Keep the existing navigation.')
            page.locator('#generate-copy').focus();page.keyboard.press('Enter')
            page.wait_for_function("document.getElementById('generate-copy').textContent==='Copied'")
            assert 'Small update: Revise\n  Keep the existing navigation.' in page.evaluate('window.copied')
            first.locator('[data-choice]').select_option('Accept')
            first.locator('[data-comment]').fill('Use the latest notes.')
            page.click('#generate-copy')
            page.wait_for_function("document.getElementById('generate-copy').textContent==='Copied'")
            assert 'Small update: Accept\n  Use the latest notes.' in page.evaluate('window.copied')
            assert 'Keep the existing navigation.' not in page.evaluate('window.copied')
            assert page.locator('#response-fallback').is_hidden()
            page.evaluate("() => { navigator.clipboard.writeText=async()=>{throw new DOMException('Denied','NotAllowedError')}; }")
            page.click('#generate-copy')
            page.wait_for_function("!document.querySelector('.decision-fallback').hidden")
            assert 'Use the latest notes.' in page.locator('#response-fallback').input_value()
            assert page.locator('#generate-copy').inner_text()!='Copied'
            assert page.locator('#response-fallback').evaluate('(e)=>e.selectionEnd===e.value.length && e.selectionStart===0')
            first.locator('[data-comment]').fill('Changed after denial.')
            assert page.locator('#response-fallback').is_hidden()
            page.evaluate("Object.defineProperty(navigator,'clipboard',{configurable:true,value:undefined})")
            page.click('#generate-copy')
            assert 'Changed after denial.' in page.locator('#response-fallback').input_value()
            # A pending clipboard operation cannot label newer edits as copied.
            page.evaluate("Object.defineProperty(navigator,'clipboard',{configurable:true,value:{writeText:()=>new Promise(resolve=>window.finishCopy=resolve)}})")
            page.click('#generate-copy')
            first.locator('[data-comment]').fill('Edited while copying.')
            page.evaluate('window.finishCopy()')
            page.wait_for_function("!document.getElementById('generate-copy').disabled")
            assert page.locator('#generate-copy').inner_text()=='Generate & copy'
            assert 'Earlier response copied' in page.locator('#frame-status').inner_text()
            for width in (1440,390,320):
                page.set_viewport_size({'width':width,'height':844})
                page.evaluate("document.querySelector('.decision-doc').scrollTop=0")
                assert page.locator('#mock-stage').evaluate('(e)=>e.scrollWidth<=e.clientWidth'), 'proposal fits phone width'
                assert page.locator('#generate-copy').evaluate("e=>getComputedStyle(e.parentElement).position==='static'")
                assert page.locator('#generate-copy').bounding_box()['height']>=44
                assert page.evaluate("document.querySelector('#generate-copy').getBoundingClientRect().bottom <= document.querySelector('.decision-section').getBoundingClientRect().top"), 'corner action never covers cards'
            before_button=page.locator('#generate-copy').bounding_box()
            page.evaluate("document.querySelector('.decision-doc').scrollTop=500")
            assert page.locator('#generate-copy').bounding_box()==before_button, 'action remains available while cards scroll'
            assert json.loads(page.locator('#spec').text_content())==proposal, 'feedback never mutates metadata'

            assert not errors, errors
            browser.close()
    print('ALL PASSED: shared frame, routes, teardown, highlights, fit, history, read-only viewers, metadata roundtrips')
    return 0


if __name__=='__main__':
    raise SystemExit(main())
