#!/usr/bin/env python3
"""design-board.py self-test: the example spec builds, round-trips, carries the measurement hooks, and
stores each embedded payload once with a byte-identical extract -> build, `check` passes the example while failing a board whose phone frame renders blank or sits cut by an overflow-hidden ancestor (skipped without Node Playwright)."""
import base64
import importlib.util
import json
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
const { chromium } = require(process.env.PW_ROOT + '/playwright');
(async () => {
  const b = await chromium.launch(); const p = await b.newPage({ viewport: { width: 1440, height: 900 } });
  await p.goto('file://' + process.argv[2]); await p.waitForTimeout(800);
  const t = () => p.evaluate(() => document.getElementById('canvas').style.transform);
  const f = await (await p.$('.screen[data-frame] iframe')).boundingBox();
  const x = f.x + f.width / 2, y = f.y + f.height / 2, r = {};
  let a = await t(); await p.mouse.move(x, y); await p.mouse.wheel(0, 120); await p.waitForTimeout(100); r.wheel = (await t()) !== a;
  a = await t(); await p.mouse.down(); await p.mouse.move(x + 80, y + 40, { steps: 4 }); await p.mouse.up(); r.drag = (await t()) !== a;
  a = await t(); await p.keyboard.press('0'); await p.waitForTimeout(100); r.keys = (await t()) !== a;
  await p.click('[data-section="0"]'); await p.waitForTimeout(100);
  r.section = await p.evaluate(() => { const s = document.querySelector('.board').getBoundingClientRect(), v = document.getElementById('mock-stage').getBoundingClientRect(); return s.left >= v.left - 1 && s.right <= v.right + 1 && s.top >= v.top - 1 && s.bottom <= v.bottom + 1; });
  console.log(JSON.stringify(r)); await b.close();
})();
"""


def navigation_probe(board: pathlib.Path, tmp: str):
    """Drive the built board in Chromium; None when Node Playwright is unavailable (same skip as check)."""
    import os
    roots = [os.environ.get("MOCKUP_SHOTS_NODE_MODULES", ""), str(pathlib.Path.home() / ".claude/node_modules")]
    root = next((r for r in roots if r and pathlib.Path(r, "playwright").is_dir()), None)
    if not root:
        return None
    script = pathlib.Path(tmp, "nav.cjs")
    script.write_text(NAV_PROBE)
    res = subprocess.run(["node", str(script), str(board.resolve())], capture_output=True, text=True,
                         env={**os.environ, "PW_ROOT": root})
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
            checks["check writes a pass table"] = pathlib.Path(tmp, "shots", "pass-table.md").is_file()
            checks["check fails a blank frame"] = bad_run.returncode == 1 and "blank" in bad_run.stdout
            nav = navigation_probe(out, tmp)
            if nav is not None:
                checks["wheel over a phone pans"] = nav["wheel"]
                checks["drag over a phone pans"] = nav["drag"]
                checks["keys work after clicking a phone"] = nav["keys"]
                checks["section click fits that section"] = nav["section"]
        bad = [k for k, ok in checks.items() if not ok]
        for k, ok in checks.items():
            print(("PASS " if ok else "FAIL ") + k)
        return 1 if bad else 0


if __name__ == "__main__":
    sys.exit(main())
