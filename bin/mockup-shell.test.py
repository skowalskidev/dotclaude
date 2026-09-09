#!/usr/bin/env python3
"""Regression test: a variant switch is a full teardown in mockup-shell.html.

Reproduces the bug Simon hit — open an overlay (a modal, a bottom sheet, a
kebab menu, a popover) in one variant, switch to another, and the overlay
used to survive because the shell only cleared #mock-stage's innerHTML and
never removed listeners/timers it had accumulated, and never remounted
presentation mode or handled a capture escaping its own iframe.

This builds mockup-synthetic-spec.json (which has a `modal` state on `alpha` and a
`bottom_sheet` state on `beta`) through mockup-build.py into a throwaway
file://-openable HTML, drives it with Playwright, and asserts:
  1. Opening alpha's modal, then switching to beta, leaves 0 overlay traces
     from alpha and beta mounts at its own DEFAULT state (not `bottom_sheet`).
  2. Opening beta's bottom sheet, then switching back to alpha, leaves 0
     overlay traces from beta and alpha mounts at its own DEFAULT state.
  3. Exactly one <iframe> ever lives in #mock-stage at a time in focus view
     (never two stacked from a torn-down + newly-mounted variant).
  4. The same clean teardown holds across entering AND exiting presentation
     mode with an overlay open.
  5. Walking states within ONE variant (a rail click, e.g. modal -> base) is
     ALSO a full teardown+remount, not a live postMessage into the mounted
     iframe — so a state's own overlay/bookkeeping can never leak into the
     next state. Exactly one "Walk the states" row carries `is-active` at a
     time, before and after every step.
  6. Presentation-mode arrow keys step through the active variant's STATES
     (not its sibling variants), each step a clean teardown+remount, and the
     HUD + rail active-row track every keyboard step too.
  7. A capture that reaches out and appends a node directly to the shell's
     own <body> (escaping its iframe) gets removed by the shell's guard.
  8. Reproduces the bug Simon hit embedding a built mockup in a wide-but-short
     host frame (a modal iframe ~1900x1010, stage ~1600x940 next to the rail):
     the focus iframe fits within the stage on both axes (never clipped, top-
     aligned rather than centred), a later resize of the STAGE alone (no page
     reload) re-fits the same mounted iframe via the ResizeObserver, resizing
     back to a standalone-sized viewport reproduces the same fit a fresh load
     would, and the mobile persona keeps its centred layout throughout.

Usage:
    python3 ~/.claude/bin/mockup-shell.test.py

Exits 0 and prints "ALL PASSED" on success; exits 1 and prints the first
failing assertion otherwise. No third-party dependency beyond `playwright`
(pip install playwright; a Chromium build already cached under
~/Library/Caches/ms-playwright is reused automatically if the version matches).
"""
import json
import subprocess
import sys
import tempfile
from pathlib import Path

SHELL_DIR = Path(__file__).resolve().parent
SPEC_PATH = SHELL_DIR / "mockup-synthetic-spec.json"
BUILD_SCRIPT = SHELL_DIR / "mockup-build.py"

FAILURES = []


def check(label, condition, detail=""):
    status = "PASS" if condition else "FAIL"
    print(f"[{status}] {label}" + (f" — {detail}" if detail and not condition else ""))
    if not condition:
        FAILURES.append(label)


def overlay_signal(page):
    """Count live iframes in the stage, and 'is-open' overlay nodes inside the
    currently-focused iframe's own document."""
    return page.evaluate(
        """() => {
            const iframes = document.querySelectorAll('#mock-stage iframe');
            let openOverlays = 0;
            let stateLabel = null;
            const f = document.querySelector('#mock-stage iframe');
            if (f) {
                try {
                    const doc = f.contentDocument;
                    openOverlays = doc.querySelectorAll('.is-open').length;
                    const lbl = doc.getElementById('state-label');
                    stateLabel = lbl ? lbl.textContent : null;
                } catch (e) { /* cross-origin, shouldn't happen for srcdoc */ }
            }
            return { iframeCount: iframes.length, openOverlays, stateLabel };
        }"""
    )


def stage_fit_signal(page):
    """Geometry + alignment + overflow-fallback state for the mounted focus iframe, plus a
    marker attribute so a caller can tell whether a later resize remounted a NEW iframe
    (a reload) or re-fit the SAME one (the ResizeObserver/resize-listener path)."""
    return page.evaluate(
        """() => {
            const stage = document.getElementById('mock-stage');
            const iframe = document.querySelector('#mock-stage iframe');
            if (!iframe) return null;
            const stageRect = stage.getBoundingClientRect();
            const iframeRect = iframe.getBoundingClientRect();
            const m = iframe.style.transform.match(/scale\\(([-0-9.eE]+)\\)/);
            return {
                stageW: stage.clientWidth, stageH: stage.clientHeight,
                stageBottom: stageRect.bottom, iframeTop: iframeRect.top, iframeBottom: iframeRect.bottom,
                scale: m ? parseFloat(m[1]) : null,
                isCentered: stage.classList.contains('is-centered'),
                overflow: getComputedStyle(stage).overflow,
                marker: iframe.getAttribute('data-test-marker')
            };
        }"""
    )


def source_contract_checks():
    """Keep the portable deep-link and exact What’s-new target contract durable."""
    source = (SHELL_DIR / "mockup-shell.html").read_text()
    check("shell URL route validates version, variant, persona and state",
          all(token in source for token in ("readShellRoute", "stateExists", "applyShellRoute",
                                             "new URLSearchParams(location.hash")))
    check("What’s new uses the declared variant and state target",
          "function goToWhatsNew()" in source
          and "version.whatsNewVariantId" in source
          and "version.whatsNewStateId" in source
          and "stateExists(targetVariant, version.whatsNewStateId)" in source)
    check("flash follows the selected state with variant fallback",
          "currentFlashSelector()" in source
          and "currentState && currentState.flashSelector" in source
          and "def.flashSelector" in source)


def main():
    source_contract_checks()
    with tempfile.TemporaryDirectory() as tmp:
        out_html = Path(tmp) / "shell-switch-test.html"
        subprocess.run(
            [sys.executable, str(BUILD_SCRIPT), str(SPEC_PATH), str(out_html)],
            check=True,
        )

        try:
            from playwright.sync_api import sync_playwright
        except ImportError:
            print("Python 'playwright' package not installed. Run:")
            print("  python3 -m venv /tmp/pw-venv && /tmp/pw-venv/bin/pip install playwright==1.58.0")
            print("  /tmp/pw-venv/bin/python " + str(Path(__file__).resolve()))
            return 1

        with sync_playwright() as p:
            browser = p.chromium.launch()
            page = browser.new_page(viewport={"width": 1200, "height": 800})
            dialogs = []
            page.on("dialog", lambda d: (dialogs.append(d.message), d.dismiss()))
            page.goto(out_html.as_uri())
            page.wait_for_timeout(300)

            # --- 1. Open alpha's modal, switch to beta ---
            page.click('[data-pick-variant="alpha"]')
            page.wait_for_timeout(150)
            page.click('[data-goto-state="modal"]')
            page.wait_for_timeout(150)
            sig = overlay_signal(page)
            check(
                "alpha's modal is open before switching",
                sig["iframeCount"] == 1 and sig["openOverlays"] == 1,
                json.dumps(sig),
            )

            page.click('[data-pick-variant="beta"]')
            page.wait_for_timeout(200)
            sig = overlay_signal(page)
            check(
                "switching alpha(modal)->beta leaves exactly 1 iframe",
                sig["iframeCount"] == 1,
                json.dumps(sig),
            )
            check(
                "beta mounts at its own DEFAULT state (no overlay open, not bottom_sheet)",
                sig["openOverlays"] == 0 and sig["stateLabel"] == "State: base",
                json.dumps(sig),
            )

            # --- 2. Open beta's bottom sheet, switch back to alpha ---
            page.click('[data-goto-state="bottom_sheet"]')
            page.wait_for_timeout(150)
            sig = overlay_signal(page)
            check(
                "beta's bottom sheet is open before switching back",
                sig["iframeCount"] == 1 and sig["openOverlays"] == 1,
                json.dumps(sig),
            )

            page.click('[data-pick-variant="alpha"]')
            page.wait_for_timeout(200)
            sig = overlay_signal(page)
            check(
                "switching beta(sheet)->alpha leaves exactly 1 iframe",
                sig["iframeCount"] == 1,
                json.dumps(sig),
            )
            check(
                "alpha mounts back at its own DEFAULT state (modal closed, not re-opened)",
                sig["openOverlays"] == 0 and sig["stateLabel"] == "State: base",
                json.dumps(sig),
            )

            # --- 3. Same teardown through presentation mode entry/exit ---
            page.click('[data-goto-state="modal"]')
            page.wait_for_timeout(150)
            sig_before = overlay_signal(page)
            check(
                "alpha's modal is open before entering presentation",
                sig_before["openOverlays"] == 1,
                json.dumps(sig_before),
            )

            page.click("#mock-present-btn")  # -> enterPresentation()
            page.wait_for_timeout(200)
            sig_presenting = overlay_signal(page)
            check(
                "entering presentation tears down the open modal (clean default mount)",
                sig_presenting["iframeCount"] == 1 and sig_presenting["openOverlays"] == 0,
                json.dumps(sig_presenting),
            )

            page.keyboard.press("Escape")  # -> exitPresentation()
            page.wait_for_timeout(200)
            sig_after = overlay_signal(page)
            check(
                "exiting presentation stays clean (still exactly 1 iframe, no overlay)",
                sig_after["iframeCount"] == 1 and sig_after["openOverlays"] == 0,
                json.dumps(sig_after),
            )

            # --- 5. Walking states within ONE variant is a full teardown+remount, not a
            #        live postMessage: modal -> base leaves 0 overlay traces, 1 iframe. ---
            page.click('[data-pick-variant="alpha"]')
            page.wait_for_timeout(150)
            active_rows = page.evaluate(
                "() => Array.from(document.querySelectorAll('.mock-walk-btn.is-active'))"
                ".map(b => b.getAttribute('data-goto-state'))"
            )
            check(
                "alpha's default walk-state row (base) is the sole is-active row on load",
                active_rows == ["base"],
                json.dumps(active_rows),
            )

            page.click('[data-goto-state="modal"]')
            page.wait_for_timeout(150)
            sig = overlay_signal(page)
            active_rows = page.evaluate(
                "() => Array.from(document.querySelectorAll('.mock-walk-btn.is-active'))"
                ".map(b => b.getAttribute('data-goto-state'))"
            )
            check(
                "walking to alpha's modal state opens exactly one overlay in a single iframe",
                sig["iframeCount"] == 1 and sig["openOverlays"] == 1,
                json.dumps(sig),
            )
            check(
                "the modal walk-state row becomes the sole is-active row",
                active_rows == ["modal"],
                json.dumps(active_rows),
            )

            page.click('[data-goto-state="base"]')
            page.wait_for_timeout(150)
            sig = overlay_signal(page)
            active_rows = page.evaluate(
                "() => Array.from(document.querySelectorAll('.mock-walk-btn.is-active'))"
                ".map(b => b.getAttribute('data-goto-state'))"
            )
            check(
                "walking a state back to base is a full remount: 0 overlay traces, 1 iframe",
                sig["iframeCount"] == 1 and sig["openOverlays"] == 0 and sig["stateLabel"] == "State: base",
                json.dumps(sig),
            )
            check(
                "the base walk-state row is once again the sole is-active row",
                active_rows == ["base"],
                json.dumps(active_rows),
            )

            # --- 6. Presentation-mode arrow keys step through STATES (not sibling
            #        variants), each step a clean teardown+remount. ---
            page.click("#mock-present-btn")  # -> enterPresentation(), resets to alpha's base
            page.wait_for_timeout(200)
            sig = overlay_signal(page)
            check(
                "entering presentation from alpha resets to its base state, cleanly mounted",
                sig["iframeCount"] == 1 and sig["openOverlays"] == 0 and sig["stateLabel"] == "State: base",
                json.dumps(sig),
            )

            page.keyboard.press("ArrowRight")  # base -> loading
            page.wait_for_timeout(150)
            sig = overlay_signal(page)
            check(
                "ArrowRight while presenting steps to the next STATE (loading), one clean iframe",
                sig["iframeCount"] == 1 and sig["openOverlays"] == 0 and sig["stateLabel"] == "State: loading",
                json.dumps(sig),
            )

            page.keyboard.press("ArrowRight")  # loading -> modal
            page.wait_for_timeout(150)
            sig = overlay_signal(page)
            hud_text = page.evaluate("() => document.getElementById('mock-hud').textContent")
            active_rows = page.evaluate(
                "() => Array.from(document.querySelectorAll('.mock-walk-btn.is-active'))"
                ".map(b => b.getAttribute('data-goto-state'))"
            )
            check(
                "ArrowRight again reaches the modal state cleanly (fresh mount, exactly 1 overlay)",
                sig["iframeCount"] == 1 and sig["openOverlays"] == 1 and sig["stateLabel"] == "State: modal",
                json.dumps(sig),
            )
            check(
                "the HUD reflects the active state while presenting",
                "Modal open" in hud_text,
                hud_text,
            )
            check(
                "the rail's active row tracks a keyboard state step too (queryable even though hidden)",
                active_rows == ["modal"],
                json.dumps(active_rows),
            )

            page.keyboard.press("ArrowRight")  # modal -> wraps back to base
            page.wait_for_timeout(150)
            sig = overlay_signal(page)
            check(
                "ArrowRight wraps back to base; the earlier modal does not survive the remount",
                sig["iframeCount"] == 1 and sig["openOverlays"] == 0 and sig["stateLabel"] == "State: base",
                json.dumps(sig),
            )

            page.keyboard.press("Escape")  # -> exitPresentation()
            page.wait_for_timeout(150)

            # --- 7. The shell's own guard removes a node a capture appends to its <body> ---
            page.evaluate(
                """() => {
                    const stray = document.createElement('div');
                    stray.id = 'stray-escaped-overlay';
                    stray.textContent = 'I escaped my iframe';
                    document.body.appendChild(stray);
                }"""
            )
            page.wait_for_timeout(150)
            stray_gone = page.evaluate("() => !document.getElementById('stray-escaped-overlay')")
            check(
                "a node appended directly to the shell body is removed by the MutationObserver guard",
                stray_gone,
            )

            # --- 9. Round grouping: exactly one Before row, superseded rows collapsed into
            #        "Earlier rounds" until opened, arrow-key stepping skips them, and a
            #        legacy "Before — superseded: ..." label loses its prefix on display.
            #        synthetic-spec.json: alpha carries role:"before", gamma is marked
            #        superseded via a v1 variantLabelOverrides entry using the legacy prefix.
            page.click('[data-pick-variant="alpha"]')
            page.wait_for_timeout(150)

            before_badges = page.eval_on_selector_all(
                ".mock-badge-before",
                "els => els.map(e => e.closest('.mock-variant-item').getAttribute('data-pick-variant'))",
            )
            check(
                "exactly one Before row, on alpha (spec's role:\"before\" variant)",
                before_badges == ["alpha"],
                json.dumps(before_badges),
            )

            gamma_visible_before_open = page.eval_on_selector(
                '[data-pick-variant="gamma"]', "e => e.offsetParent !== null"
            )
            check(
                "gamma (superseded) is hidden in the rail before the disclosure opens",
                gamma_visible_before_open is False,
            )

            summary_text = page.eval_on_selector(".mock-earlier-rounds summary", "e => e.textContent")
            check(
                "the collapsed disclosure names the superseded count",
                summary_text == "Earlier rounds (1)",
                summary_text,
            )

            arrow_order = []
            for _ in range(3):
                arrow_order.append(
                    page.eval_on_selector(".mock-variant-item.active", "e => e.getAttribute('data-pick-variant')")
                )
                page.keyboard.press("ArrowRight")
                page.wait_for_timeout(120)
            check(
                "←/→ stepping cycles Before + current variants only, never gamma while collapsed",
                arrow_order == ["alpha", "beta", "alpha"],
                json.dumps(arrow_order),
            )

            page.click(".mock-earlier-rounds summary")
            page.wait_for_timeout(150)
            gamma_visible_after_open = page.eval_on_selector(
                '[data-pick-variant="gamma"]', "e => e.offsetParent !== null"
            )
            check(
                "opening the disclosure reveals gamma",
                gamma_visible_after_open is True,
            )

            gamma_label = page.eval_on_selector('[data-pick-variant="gamma"] .lbl', "e => e.textContent.trim()")
            check(
                "gamma's legacy 'Before — superseded: ...' override displays with the prefix stripped",
                gamma_label == "Gamma — earlier round two",
                gamma_label,
            )

            page.click('[data-pick-variant="gamma"]')
            page.wait_for_timeout(150)
            active_after_pick = page.eval_on_selector(".mock-variant-item.active", "e => e.getAttribute('data-pick-variant')")
            check(
                "a superseded variant is still selectable from the open disclosure",
                active_after_pick == "gamma",
                active_after_pick,
            )

            page.keyboard.press("ArrowRight")
            page.wait_for_timeout(150)
            active_after_step_away = page.eval_on_selector(
                ".mock-variant-item.active", "e => e.getAttribute('data-pick-variant')"
            )
            check(
                "stepping away from an already-selected superseded variant lands on Before, not another superseded row",
                active_after_step_away == "alpha",
                active_after_step_away,
            )

            compare_order = page.evaluate(
                """() => {
                    document.getElementById('mock-view-compare').click();
                    return Array.from(document.querySelectorAll('[data-compare-toggle]'))
                        .map(e => e.getAttribute('data-compare-toggle'));
                }"""
            )
            check(
                "the Compare picker lists current variants first, superseded (gamma) last under the same list",
                compare_order == ["alpha", "beta", "gamma"],
                json.dumps(compare_order),
            )
            page.click("#mock-view-focus")
            page.wait_for_timeout(150)

            page.reload()
            page.wait_for_timeout(300)
            default_after_reload = page.evaluate(
                "() => document.querySelector('.mock-variant-item.active').getAttribute('data-pick-variant')"
            )
            check(
                "the default variant on open is the manifest default (alpha), never a superseded one",
                default_after_reload == "alpha",
                default_after_reload,
            )

            # --- 8. Fit never clips a wide-short host frame; refits the mounted iframe on a
            #        stage-only resize (no reload); resizing back matches a fresh load. ---
            DESKTOP_W, DESKTOP_H = 1440, 900  # the desktop persona's natural size (synthetic-spec.json)

            def expected_fit_scale(stage_w, stage_h):
                return min(stage_w / DESKTOP_W, stage_h / DESKTOP_H, 1)

            fit_page = browser.new_page(viewport={"width": 1900, "height": 1010})
            fit_page.goto(out_html.as_uri())
            fit_page.wait_for_timeout(300)
            fit_page.evaluate(
                "() => document.querySelector('#mock-stage iframe').setAttribute('data-test-marker', 'm1')"
            )
            sig_a = stage_fit_signal(fit_page)
            check(
                "wide-short host (1900x1010, stage ~1600x940): focus iframe never overruns the stage bottom",
                sig_a is not None and sig_a["iframeBottom"] <= sig_a["stageBottom"] + 0.5,
                json.dumps(sig_a),
            )
            check(
                "the fitted frame's full natural height is visible without scrolling (min(w,h) fit, not width-only)",
                abs(sig_a["scale"] - expected_fit_scale(sig_a["stageW"], sig_a["stageH"])) < 0.01
                and DESKTOP_H * sig_a["scale"] <= sig_a["stageH"] + 0.5,
                json.dumps(sig_a),
            )
            check(
                "the desktop persona top-aligns (not vertically centred) so overflow always trails at the bottom",
                sig_a["isCentered"] is False,
                json.dumps(sig_a),
            )
            check(
                "#mock-stage keeps overflow:auto as the never-clip fallback even when fit already fits",
                sig_a["overflow"] == "auto",
                json.dumps(sig_a),
            )

            fit_page.set_viewport_size({"width": 1200, "height": 700})
            fit_page.wait_for_timeout(400)
            sig_b = stage_fit_signal(fit_page)
            check(
                "shrinking the STAGE alone (no navigation) re-fits via the ResizeObserver, without a reload",
                sig_b is not None and sig_b["marker"] == "m1" and sig_b["scale"] != sig_a["scale"],
                json.dumps({"before": sig_a, "after": sig_b}),
            )
            check(
                "the re-fit scale after shrinking matches min(w,h) for the new stage size",
                abs(sig_b["scale"] - expected_fit_scale(sig_b["stageW"], sig_b["stageH"])) < 0.01
                and sig_b["iframeBottom"] <= sig_b["stageBottom"] + 0.5,
                json.dumps(sig_b),
            )

            fit_page.set_viewport_size({"width": 1440, "height": 900})
            fit_page.wait_for_timeout(400)
            sig_c = stage_fit_signal(fit_page)
            check(
                "resizing back to a standalone-sized viewport still re-fits the SAME iframe (no reload)",
                sig_c is not None and sig_c["marker"] == "m1",
                json.dumps(sig_c),
            )
            check(
                "…and reproduces exactly the fit a fresh load at that size would compute (regression guard)",
                abs(sig_c["scale"] - expected_fit_scale(sig_c["stageW"], sig_c["stageH"])) < 0.01
                and sig_c["iframeBottom"] <= sig_c["stageBottom"] + 0.5,
                json.dumps(sig_c),
            )

            # Collapsing the rail changes #mock-stage's own box (width grows) WITHOUT any
            # window resize at all — the one case a plain window 'resize' listener structurally
            # cannot catch, and the reason the ResizeObserver is on the stage element itself.
            sig_before_collapse = stage_fit_signal(fit_page)
            fit_page.click("#mock-rail-toggle-btn")
            fit_page.wait_for_timeout(300)
            sig_collapsed = stage_fit_signal(fit_page)
            check(
                "collapsing the rail (no window resize) still re-fits, via the ResizeObserver alone",
                sig_collapsed is not None
                and sig_collapsed["marker"] == "m1"
                and sig_collapsed["stageW"] > sig_before_collapse["stageW"]
                and sig_collapsed["scale"] != sig_before_collapse["scale"]
                and abs(sig_collapsed["scale"] - expected_fit_scale(sig_collapsed["stageW"], sig_collapsed["stageH"])) < 0.01,
                json.dumps({"before": sig_before_collapse, "after": sig_collapsed}),
            )
            fit_page.click("#mock-rail-toggle-btn")  # restore, tidy for the persona switch below
            fit_page.wait_for_timeout(200)

            fit_page.click('[data-pick-persona="mobile"]')
            fit_page.wait_for_timeout(200)
            sig_mobile = stage_fit_signal(fit_page)
            check(
                "the mobile persona keeps its centred layout (unaffected by the desktop top-align change)",
                sig_mobile is not None and sig_mobile["isCentered"] is True,
                json.dumps(sig_mobile),
            )

            fit_page.close()

            browser.close()

    print()
    if FAILURES:
        print(f"{len(FAILURES)} FAILED: " + "; ".join(FAILURES))
        return 1
    print("ALL PASSED")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
