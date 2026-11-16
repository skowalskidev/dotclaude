#!/usr/bin/env python3
"""design-board.py self-test: the example spec builds, round-trips, carries the measurement hooks, and
stores each embedded payload once with a byte-identical extract -> build, `check` passes the example while failing a board whose phone frame renders blank or sits cut by an overflow-hidden ancestor (skipped without Node Playwright),
and the flattened-size estimate warns on a board too large for one screenshot, naming its long flow row and the split fix (matched to Chromium's measured size when Node Playwright is available)."""
import base64
import importlib.util
import json
import os
import pathlib
import subprocess
import sys
import tempfile

HERE = pathlib.Path(__file__).resolve().parent
TOOL = HERE / "design-board.py"


def load_tool():
    spec = importlib.util.spec_from_file_location("design_board", TOOL)
    module = importlib.util.module_from_spec(spec)
    sys.path.insert(0, str(HERE))
    spec.loader.exec_module(module)
    return module


def run(*args: str) -> str:
    return subprocess.run([sys.executable, str(TOOL), *args], check=True, capture_output=True, text=True).stdout


NAV_PROBE = r"""
const { chromium } = require(process.env.PW_PKG);
(async () => {
  const b = await chromium.launch();
  try {
  const p = await b.newPage({ viewport: { width: 1440, height: 900 } });
  await p.goto('file://' + process.argv[2]); await p.waitForTimeout(800);
  const t = () => p.evaluate(() => document.getElementById('canvas').style.transform);
  const f = await (await p.$('.screen[data-frame] iframe')).boundingBox();
  const x = f.x + f.width / 2, y = f.y + f.height / 2, r = {};
  let a = await t(); await p.mouse.move(x, y); await p.mouse.wheel(0, 120); await p.waitForTimeout(100); r.wheel = (await t()) !== a;
  a = await t(); await p.mouse.down(); await p.mouse.move(x + 80, y + 40, { steps: 4 }); await p.mouse.up(); r.drag = (await t()) !== a;
  a = await t(); await p.keyboard.press('0'); await p.waitForTimeout(100); r.keys = (await t()) !== a;
  await p.click('[data-section="0"]'); await p.waitForTimeout(100);
  r.section = await p.evaluate(() => { const s = document.querySelector('.board').getBoundingClientRect(), v = document.getElementById('mock-stage').getBoundingClientRect(); return s.left >= v.left - 1 && s.right <= v.right + 1 && s.top >= v.top - 1 && s.bottom <= v.bottom + 1; });
  r.horizontal = await p.evaluate(() => {
    const screen = document.querySelector('.screen[data-frame]');
    const doc = screen.querySelector('iframe').contentDocument;
    const width = screen.clientWidth;
    const measure = html => { doc.body.innerHTML = html; return window.__measure()[0].overflow; };
    const wide = '<div style="width:' + (width + 80) + 'px;height:80px">Scrollable content</div>';
    return {
      popover: measure('<div style="position:absolute;left:' + (width - 30) + 'px;top:100px;width:100px;height:40px">Popover</div>') === 70,
      auto: measure('<div style="overflow-x:auto;height:100px">' + wide + '</div>') === 0,
      scroll: measure('<div style="overflow-x:scroll;height:100px"><div>' + wide + '</div></div>') === 0,
      oversized: measure('<div style="overflow-x:auto;width:' + (width + 20) + 'px;height:100px">' + wide + '</div>') === 20,
      hidden: measure('<div style="overflow-x:hidden;height:100px">' + wide + '</div>') === 80,
      fixed: measure('<div style="overflow-x:auto;height:100px"><div style="position:fixed;left:' + (width - 30) + 'px;top:100px;width:100px;height:40px">Overlay</div></div>') === 70,
      bottom: measure('<div style="position:absolute;top:840px;height:40px">Below phone</div>') === 28,
      invisible: measure('<div style="display:none;width:1000px">Hidden</div>') === 0,
    };
  });
  console.log(JSON.stringify(r));
  } finally { await b.close(); }
})();
"""


FLAT_PROBE = r"""
const { chromium } = require(process.env.PW_PKG);
(async () => {
  const b = await chromium.launch();
  try {
    const p = await b.newPage({ viewport: { width: 1440, height: 900 } });
    await p.goto('file://' + process.argv[2]); await p.waitForTimeout(500);
    console.log(JSON.stringify(await p.evaluate(() => { window.__flatten(); const d = document.documentElement; return [d.scrollWidth, d.scrollHeight]; })));
  } finally { await b.close(); }
})();
"""


def frames(prefix: str, n: int) -> list:
    return [{"id": f"{prefix}{i}", "label": "L", "title": f"{prefix} {i}", "hypothesis": "h", "note": "n",
             "html": "<p>x</p>"} for i in range(n)]


def size_checks(tool, tmp: str) -> dict:
    """The flattened-size estimate, the build warning, and the split hint check passes on (estimate vs Chromium when available)."""
    import contextlib
    import io
    import node_playwright
    checks = {}
    small = {"title": "s", "phone": {"w": 414, "h": 896}, "sections": [
        {"title": "grid", "lead": "wraps", "frames": frames("g", 10)},
        {"title": "flow", "lead": "one row", "flow": True, "frames": frames("f", 5)}]}
    # The shape that failed: one 45-frame flow row makes every one of 23 sections that wide.
    big = {"title": "b", "phone": {"w": 414, "h": 896},
           "sections": [{"title": f"s{i}", "lead": "l", "flow": True, "frames": frames(f"s{i}-", 8)} for i in range(22)]
           + [{"title": "long flow", "lead": "l", "flow": True, "frames": frames("long", 45)}]}
    checks["example fits one screenshot (no warning)"] = tool.size_warnings(json.loads(run("example"))) == []
    w, h, widest = tool.flat_size(big)
    warned = tool.size_warnings(big)
    checks["oversized board estimate is over the budget"] = w * h > node_playwright.BUDGET_PIXELS and widest == 22
    checks["warning names the size, the long flow row and the fix"] = (
        len(warned) == 1 and f"{w}x{h} px" in warned[0] and '"long flow" with 45 frames' in warned[0]
        and f"rows of about {tool.FLOW_ROW_CHUNK}" in warned[0] and "several boards" in warned[0])
    big_spec, big_out = pathlib.Path(tmp, "big.json"), pathlib.Path(tmp, "big.html")
    big_spec.write_text(json.dumps(big))
    built = subprocess.run([sys.executable, str(TOOL), "build", str(big_spec), str(big_out)], capture_output=True, text=True)
    checks["build warns on stderr and still writes the board"] = built.returncode == 0 and "WARNING: the flattened board" in built.stderr and big_out.is_file()
    calls = []
    real_run = tool.subprocess.run
    tool.subprocess.run = lambda args, **kw: calls.append(args) or subprocess.CompletedProcess(args, 0)
    try:
        err = io.StringIO()
        with contextlib.redirect_stderr(err):
            tool.check(big_out, pathlib.Path(tmp, "unused"))
    finally:
        tool.subprocess.run = real_run
    args = calls[0] if calls else []
    checks["check passes the board split hint to visual-check"] = "--split-hint" in args and args[args.index("--split-hint") + 1] == tool.SPLIT_HINT
    checks["check prints the size warning first"] = "WARNING: the flattened board" in err.getvalue()
    found, _ = node_playwright.find()
    if found:
        small_out = pathlib.Path(tmp, "small.html")
        small_out.write_text(tool.build(small))
        script = pathlib.Path(tmp, "flat.cjs")
        script.write_text(FLAT_PROBE)
        for name, spec, out in (("small", small, small_out), ("oversized", big, big_out)):
            res = subprocess.run(["node", str(script), str(out)], capture_output=True, text=True, env={**os.environ, "PW_PKG": found[0]})
            mw, mh = json.loads(res.stdout) if res.returncode == 0 else (0, 0)
            ew, eh, _ = tool.flat_size(spec)
            checks[f"estimate within 3% of the measured flattened {name} board"] = abs(ew - mw) <= 0.03 * mw and abs(eh - mh) <= 0.03 * mh
    return checks


def navigation_probe(board: pathlib.Path, tmp: str):
    """Drive the built board in Chromium; None when Node Playwright is unavailable (same skip as check)."""
    import node_playwright
    found, _ = node_playwright.find()
    if not found:
        return None
    script = pathlib.Path(tmp, "nav.cjs")
    script.write_text(NAV_PROBE)
    res = subprocess.run(["node", str(script), str(board.resolve())], capture_output=True, text=True,
                         env={**os.environ, "PW_PKG": found[0]})
    return json.loads(res.stdout) if res.returncode == 0 else {"wheel": False, "drag": False, "keys": False, "section": False}


def main() -> int:
    with tempfile.TemporaryDirectory() as tmp:
        spec = pathlib.Path(tmp, "spec.json")
        out = pathlib.Path(tmp, "board.html")
        back = pathlib.Path(tmp, "back.json")
        spec.write_text(run("example"))
        run("build", str(spec), str(out))
        page = out.read_text()
        checks = {
            "two frames": page.count('data-frame="') == 2,
            "pick badge": 'class="pick"' in page,
            "measure hook": "window.__measure=" in page,
            "flatten hook": "window.__flatten=" in page,
            "pan/zoom": "zoomAt" in page,
            "viewer-only controls": all(token not in page for token in ('id="copy-spec"', 'id="save-html"', 'id="generate-response"', '<textarea')),
            "self-contained": "http://" not in page and "https://" not in page,
            # The frame reset sits in a first-declared layer, so project CSS in layers (Tailwind v4) still wins.
            "phones never swallow gestures": ".screen iframe{pointer-events:none}" in page,
            "reset is layered": "@layer board-reset{*{box-sizing:border-box;margin:0;padding:0}}" in page and "<style>*{" not in page,
        }
        run("extract", str(out), str(back))
        checks["round-trip"] = json.loads(back.read_text()) == json.loads(spec.read_text())
        # Each image is stored once (in #spec), and extract -> build reproduces the board byte for byte.
        images = []
        multi = json.loads(spec.read_text())
        multi["font"] = "data:font/woff2;base64," + base64.b64encode(b"board-font-bytes").decode()
        for n in range(3):
            payload = base64.b64encode(f"image-{n}-bytes".encode() * 7).decode()
            images.append(payload)
            multi["sections"][0]["frames"].append({"id": f"img{n}", "title": f"Image {n}", "image": "data:image/png;base64," + payload})
        multi["sections"][0]["frames"].append({"id": "img-shared", "title": "Shared", "image": "data:image/png;base64," + images[0]})
        built = load_tool().build(multi)
        checks["each image embedded once"] = all(built.count(p) == 1 for p in images)
        checks["shared image frames all shown"] = built.count('data-frame="img') == 4
        checks["font embedded once"] = built.count(multi["font"].split(",", 1)[1]) == 1
        checks["capture html embedded once"] = built.count("kept on this seat") == 1
        flow = json.loads(spec.read_text())
        flow["sections"][0]["flow"] = True
        flow_page = load_tool().build(flow)
        checks["flow section keeps one row"] = '<section class="board flow">' in flow_page and ".board.flow .row{flex-wrap:nowrap}" in flow_page
        checks["build(extract(build)) byte-identical"] = load_tool().build(load_tool().extract(built)) == built
        blank = json.loads(spec.read_text())
        blank["sections"][0]["frames"][1]["html"] = ""
        blank_spec, blank_out = pathlib.Path(tmp, "blank.json"), pathlib.Path(tmp, "blank.html")
        blank_spec.write_text(json.dumps(blank))
        run("build", str(blank_spec), str(blank_out))
        cut = json.loads(spec.read_text())
        cut["sections"][0]["frames"][0]["html"] = '<div style="height:300px;overflow:hidden"><div style="height:600px">Clipped content</div></div>'
        cut_spec, cut_out = pathlib.Path(tmp, "cut.json"), pathlib.Path(tmp, "cut.html")
        cut_spec.write_text(json.dumps(cut))
        run("build", str(cut_spec), str(cut_out))
        right = json.loads(spec.read_text())
        right["sections"][0]["frames"][0]["html"] = '<div style="position:absolute;left:350px;top:100px;width:120px;height:60px">Right-clipped popover</div>'
        right_out = pathlib.Path(tmp, "right.html")
        right_out.write_text(load_tool().build(right))
        good = subprocess.run([sys.executable, str(TOOL), "check", str(out), str(pathlib.Path(tmp, "shots"))],
                              capture_output=True, text=True)
        if good.returncode == 2:
            print("SKIP check (Node Playwright unavailable): " + good.stderr.strip())
        else:
            bad_run = subprocess.run([sys.executable, str(TOOL), "check", str(blank_out), str(pathlib.Path(tmp, "blank-shots"))],
                                     capture_output=True, text=True)
            cut_run = subprocess.run([sys.executable, str(TOOL), "check", str(cut_out), str(pathlib.Path(tmp, "cut-shots"))],
                                     capture_output=True, text=True)
            checks["check passes the example"] = good.returncode == 0 and good.stdout.count("| PASS") == 3
            checks["check fails a cut frame"] = cut_run.returncode == 1 and "cut by" in cut_run.stdout
            right_run = subprocess.run([sys.executable, str(TOOL), "check", str(right_out), str(pathlib.Path(tmp, "right-shots"))],
                                       capture_output=True, text=True)
            checks["check fails a right-clipped popover"] = right_run.returncode == 1 and "cut by" in right_run.stdout
            checks["check writes a pass table"] = pathlib.Path(tmp, "shots", "pass-table.md").is_file()
            checks["check fails a blank frame"] = bad_run.returncode == 1 and "blank" in bad_run.stdout
            nav = navigation_probe(out, tmp)
            if nav is not None:
                checks["wheel over a phone pans"] = nav["wheel"]
                checks["drag over a phone pans"] = nav["drag"]
                checks["keys work after clicking a phone"] = nav["keys"]
                checks["section click fits that section"] = nav["section"]
                for case, passed in nav.get("horizontal", {"probe": False}).items():
                    checks["overflow measurement: " + case] = passed
        checks.update(size_checks(load_tool(), tmp))
        bad = [k for k, ok in checks.items() if not ok]
        for k, ok in checks.items():
            print(("PASS " if ok else "FAIL ") + k)
        return 1 if bad else 0


if __name__ == "__main__":
    sys.exit(main())
