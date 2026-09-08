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
  5. A capture that reaches out and appends a node directly to the shell's
     own <body> (escaping its iframe) gets removed by the shell's guard.

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


def main():
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

            # --- 4. The shell's own guard removes a node a capture appends to its <body> ---
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

            browser.close()

    print()
    if FAILURES:
        print(f"{len(FAILURES)} FAILED: " + "; ".join(FAILURES))
        return 1
    print("ALL PASSED")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
