#!/usr/bin/env python3
"""Pins bin/test-browser-tabs.py: the label survives the page rewriting its own title, and sweep
closes exactly the stale tabs (blank, unlabelled, ended or idle owner, own earlier task) while every
live walk's tab stays open. The label check runs in real Chromium through Node Playwright."""

import json
import os
import subprocess
import sys
import tempfile
import threading
import time
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path

HERE = Path(__file__).resolve().parent
TOOL = HERE / "test-browser-tabs.py"
sys.path.insert(0, str(HERE))
import node_playwright  # noqa: E402

FAILURES: list[str] = []


def check(ok: bool, msg: str) -> None:
    if not ok:
        FAILURES.append(msg)


def run(args, env=None, cwd=None):
    full = dict(os.environ, **(env or {}))
    return subprocess.run([sys.executable, str(TOOL), *args], capture_output=True, text=True,
                          timeout=60, env=full, cwd=cwd)


# ---------------------------------------------------------------- the label in a real browser

BROWSER_JS = r"""
const { chromium } = require(process.env.PW);
const keeper = process.env.KEEPER, relabel = process.env.RELABEL;
const html = "<!doctype html><html><head><title>Flight Search</title></head><body></body></html>";
(async () => {
  const browser = await chromium.launch();
  const page = await browser.newPage();
  await page.route("http://walk.test/**", r => r.fulfill({ contentType: "text/html", body: html }));
  await page.addInitScript(keeper);
  const seen = [];
  const step = async (js) => { if (js) await page.evaluate(js); seen.push(await page.title()); };
  await page.goto("http://walk.test/");
  await step("");
  await step('document.title = "Example App"');
  await step('history.pushState({}, "", "/next"); document.title = "Checkout"');
  await step('const t = document.createElement("title"); t.textContent = "Swapped"; document.querySelector("title").replaceWith(t)');
  await step('document.title = ""');
  await page.reload(); await step("");
  await step(relabel);
  await step(keeper);
  await browser.close();
  console.log(JSON.stringify(seen));
})().catch(e => { console.error(e); process.exit(1); });
"""


def check_label_survives_the_page() -> None:
    found, groups = node_playwright.find()
    if not found:
        FAILURES.append(node_playwright.not_found_message(groups))
        return
    keeper = run(["label", "--task", "PR 1272", "--persona", "SENDER 0107", "--owner", "auckland"],
                 env={"CLAUDE_TEST_BROWSER_WALKS_DIR": tempfile.mkdtemp()}).stdout
    relabel = run(["label", "--task", "PR 1272", "--persona", "FRIEND 0108", "--owner", "auckland"],
                  env={"CLAUDE_TEST_BROWSER_WALKS_DIR": tempfile.mkdtemp()}).stdout
    res = subprocess.run(["node", "-e", BROWSER_JS], capture_output=True, text=True, timeout=120,
                         env=dict(os.environ, PW=found[0], KEEPER=keeper, RELABEL=relabel))
    if res.returncode:
        FAILURES.append("browser label run failed: " + res.stderr[-800:])
        return
    seen = json.loads(res.stdout.strip().splitlines()[-1])
    s, f = "▶ PR 1272 · SENDER 0107", "▶ PR 1272 · FRIEND 0108"
    tail = " · @auckland"
    want = [s + " · Flight Search" + tail,   # first paint
            s + " · Example App" + tail,             # the app rewrote document.title
            s + " · Checkout" + tail,              # client-side navigation + new title
            s + " · Swapped" + tail,               # the <title> element replaced
            s + tail,                                   # the app cleared the title
            s + " · Flight Search" + tail,   # full reload: the init script re-ran
            f + " · Flight Search" + tail,   # re-labelled in place, no double prefix
            s + " · Flight Search" + tail]   # the same keeper again is idempotent
    check(seen == want, "label did not hold:\n  got  %r\n  want %r" % (seen, want))


# ---------------------------------------------------------------- classify and sweep

class FakeBrowser:
    def __init__(self, pages):
        self.pages = list(pages)
        self.closed: list[str] = []
        owner = self

        class Handler(BaseHTTPRequestHandler):
            def do_GET(self):
                if self.path == "/json/list":
                    body = json.dumps(owner.pages).encode()
                elif self.path.startswith("/json/close/"):
                    target = self.path.rsplit("/", 1)[1]
                    owner.closed.append(target)
                    owner.pages = [p for p in owner.pages if p["id"] != target]
                    body = b"Target is closing"
                else:
                    self.send_response(404)
                    self.end_headers()
                    return
                self.send_response(200)
                self.end_headers()
                self.wfile.write(body)

            def log_message(self, *_):
                pass

        self.server = ThreadingHTTPServer(("127.0.0.1", 0), Handler)
        self.port = self.server.server_port
        threading.Thread(target=self.server.serve_forever, daemon=True).start()

    def stop(self):
        self.server.shutdown()


def label(task, persona, title, owner):
    head = " · ".join(x for x in (task, persona) if x)
    return "▶ " + head + (" · " + title if title else "") + " · @" + owner


PAGES = [
    {"id": "blank", "type": "page", "url": "about:blank", "title": "about:blank"},
    {"id": "unlabelled", "type": "page", "url": "http://100.64.0.1:10002/app", "title": "Flight Search"},
    {"id": "own", "type": "page", "url": "http://127.0.0.1:3010/app", "title": label("PR 1272", "SENDER 0107", "Invite", "auckland")},
    {"id": "own-old", "type": "page", "url": "http://127.0.0.1:3010/app", "title": label("PR 1270", "", "Checkout", "auckland")},
    {"id": "live", "type": "page", "url": "http://127.0.0.1:3020/app", "title": label("POI-1662", "", "Settings", "tokyo")},
    {"id": "idle", "type": "page", "url": "http://127.0.0.1:3030/app", "title": label("PR 1201", "", "Home", "daegu")},
    {"id": "ended", "type": "page", "url": "http://127.0.0.1:3040/app", "title": label("PR 1199", "", "Home", "lusaka")},
    {"id": "worker", "type": "service_worker", "url": "chrome-extension://x/bg.js", "title": "Service Worker"},
]


def check_sweep_closes_only_stale_tabs() -> None:
    walks = Path(tempfile.mkdtemp())
    for owner in ("tokyo", "daegu"):
        (walks / owner).write_text("{}\n")
    old = time.time() - 45 * 60
    os.utime(walks / "daegu", (old, old))
    env = {"CLAUDE_TEST_BROWSER_WALKS_DIR": str(walks), "CLAUDE_TEST_BROWSER_TABS_ANY_BROWSER": "1",
           "CLAUDE_TEST_BROWSER_TABS_SESSIONS": "/w/project/auckland\n/w/project/tokyo\n/w/project/daegu"}
    fake = FakeBrowser(PAGES)
    try:
        base = ["--port", str(fake.port), "--owner", "auckland", "--task", "PR 1272"]
        listed = run(["list", *base, "--json"], env=env)
        rows = {r["id"]: r["class"] for r in json.loads(listed.stdout)}
        want = {"blank": "stale", "unlabelled": "stale", "own": "own", "own-old": "stale",
                "live": "live", "idle": "stale", "ended": "stale"}
        check(rows == want, f"list classes: got {rows}, want {want}")
        check(fake.closed == [], "list must never close a tab")
        dry = run(["sweep", *base, "--dry-run"], env=env)
        check(dry.returncode == 0 and fake.closed == [], "sweep --dry-run closed a tab")
        swept = run(["sweep", *base], env=env)
        check(swept.returncode == 0, "sweep failed: " + swept.stderr)
        check(sorted(fake.closed) == sorted(k for k, v in want.items() if v == "stale"),
              f"sweep closed {sorted(fake.closed)}")
        check((walks / "auckland").is_file(), "sweep must record this owner's heartbeat")
        # Without --task, every own tab is kept.
        fake.pages = list(PAGES)
        fake.closed = []
        rows = {r["id"]: r["class"] for r in json.loads(
            run(["list", "--port", str(fake.port), "--owner", "auckland", "--json"], env=env).stdout)}
        check(rows["own-old"] == "own", "own tab of another task must be kept when no --task is given")
        # A failed session probe keeps every other owner's tab.
        rows = {r["id"]: r["class"] for r in json.loads(run(
            ["list", *base, "--json"], env=dict(env, CLAUDE_TEST_BROWSER_TABS_SESSIONS="!fail")).stdout)}
        check(rows["live"] == rows["idle"] == rows["ended"] == "unknown",
              f"failed probe must keep other owners' tabs: {rows}")
        # A port that is not Chrome for Testing is refused before anything closes.
        strict = {k: v for k, v in env.items() if k != "CLAUDE_TEST_BROWSER_TABS_ANY_BROWSER"}
        refused = run(["sweep", *base], env=strict)
        check(refused.returncode == 5 and fake.closed == [],
              f"non-test browser: exit {refused.returncode}, closed {fake.closed}")
    finally:
        fake.stop()
    nothing = run(["list", "--port", "1", "--owner", "auckland"], env=env)
    check(nothing.returncode == 3, f"no browser on the port must exit 3, got {nothing.returncode}")


def check_label_cli() -> None:
    walks = tempfile.mkdtemp()
    res = run(["label", "--task", "  "], env={"CLAUDE_TEST_BROWSER_WALKS_DIR": walks})
    check(res.returncode == 2, "an empty --task must be a usage error")
    out = Path(walks) / "keeper.js"
    res = run(["label", "--task", "PR 9", "--owner", "my space", "--out", str(out)],
              env={"CLAUDE_TEST_BROWSER_WALKS_DIR": walks})
    check(res.returncode == 0 and out.read_text().strip() == res.stdout.strip(),
          "--out must write the same script it prints")
    check("@my-space" in res.stdout and "__claudeTabLabel" in res.stdout,
          "owner names are slugged and the keeper carries the guard's marker")
    check((Path(walks) / "my-space").is_file(), "label must record the owner's heartbeat")


def main() -> int:
    for fn in (check_label_cli, check_sweep_closes_only_stale_tabs, check_label_survives_the_page):
        fn()
    for msg in FAILURES:
        print("FAIL", msg)
    print("test-browser-tabs: " + ("OK" if not FAILURES else f"{len(FAILURES)} failure(s)"))
    return 1 if FAILURES else 0


if __name__ == "__main__":
    sys.exit(main())
