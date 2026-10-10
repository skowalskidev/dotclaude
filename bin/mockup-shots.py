#!/usr/bin/env python3
"""Screenshot a built mockup with JavaScript running: every variant x persona x state.

The built-in browser pane cannot open file:// and a scratch-dir file renders as a static
snapshot, so a clipped dropdown or a toast covering a button never shows. This renders each
capture in headless Chromium, jumps to the state, waits for entrance animations, and writes
one PNG per capture plus one of the whole shell.

Usage:
    mockup-shots.py <mockup.html> <outdir> [--filter SUBSTR]

Output: <outdir>/shell.png and <outdir>/<variant>-<persona>-<state>.png at the persona's w x h.
Exit code: 0 clean, 1 when any page error occurred, 2 on a usage or setup error.

Python 3.9+, standard library only. Playwright for Python is not assumed: the browser work
runs in Node Playwright (resolved from NODE_PATH, the global npm root, ./node_modules,
~/.claude/node_modules, or MOCKUP_SHOTS_NODE_MODULES), with the spec extracted here.
"""
import json
import os
import re
import subprocess
import sys
import tempfile
from pathlib import Path

SPEC_TAG_OPEN = '<script id="spec" type="application/json">'
SPEC_TAG_CLOSE = "</script>"
ASSET_RE = re.compile(r"@@ASSET:([a-f0-9]+)@@")
SETTLE_MS = 1500

NODE_RUNNER = r"""
import { createRequire } from "node:module";
import { readFileSync, mkdirSync } from "node:fs";
import { execSync } from "node:child_process";
import { join } from "node:path";
const job = JSON.parse(readFileSync(process.argv[2], "utf8"));
const roots = [];
if (process.env.MOCKUP_SHOTS_NODE_MODULES) roots.push(process.env.MOCKUP_SHOTS_NODE_MODULES);
for (const p of (process.env.NODE_PATH || "").split(":")) if (p) roots.push(p);
try { roots.push(execSync("npm root -g", { encoding: "utf8" }).trim()); } catch {}
roots.push(join(process.cwd(), "node_modules"), join(process.env.HOME || "", ".claude", "node_modules"));
let chromium = null;
for (const r of roots) {
  try { chromium = createRequire(join(r, "_"))("playwright").chromium; if (chromium) break; } catch {}
}
if (!chromium) { console.error("SETUP: node 'playwright' not found. Set MOCKUP_SHOTS_NODE_MODULES to a node_modules dir containing it."); process.exit(2); }
mkdirSync(job.outdir, { recursive: true });
const browser = await chromium.launch();
const errors = [];
const shell = await browser.newPage({ viewport: { width: 1440, height: 900 } });
shell.on("pageerror", (e) => errors.push("shell: " + e.message));
await shell.goto("file://" + job.mockup);
await shell.waitForTimeout(2500);
await shell.screenshot({ path: join(job.outdir, "shell.png") });
await shell.close();
let count = 1;
for (const c of job.captures) {
  const page = await browser.newPage({ viewport: { width: c.w, height: c.h }, deviceScaleFactor: 1 });
  page.on("pageerror", (e) => errors.push(c.name + ": " + e.message));
  await page.setContent(c.html, { waitUntil: "domcontentloaded" });
  await page.evaluate((id) => window.postMessage({ type: "mockup:goto-state", stateId: id }, "*"), c.stateId);
  await page.waitForTimeout(job.settleMs);
  await page.screenshot({ path: join(job.outdir, c.name + ".png") });
  await page.close();
  count++;
}
await browser.close();
console.log(JSON.stringify({ count, errors }));
process.exit(errors.length ? 1 : 0);
"""


def extract_spec(mockup_path: Path) -> dict:
    html = mockup_path.read_text(encoding="utf-8")
    start = html.find(SPEC_TAG_OPEN)
    if start == -1:
        raise SystemExit(f"no #spec script tag found in {mockup_path}")
    start += len(SPEC_TAG_OPEN)
    end = html.find(SPEC_TAG_CLOSE, start)
    if end == -1:
        raise SystemExit(f"unterminated #spec script tag in {mockup_path}")
    return json.loads(html[start:end])


def build_job(spec: dict, mockup: Path, outdir: Path, needle: str) -> dict:
    assets = spec.get("assets", {})

    def fill(h: str) -> str:
        return ASSET_RE.sub(lambda m: assets.get(m.group(1), m.group(0)), h)

    captures = []
    for vid, v in spec["variants"].items():
        for p in spec["personas"]:
            html = v["captures"].get(p["id"])
            if html is None:
                continue
            filled = fill(html)
            for s in v["states"]:
                name = f"{vid}-{p['id']}-{s['id']}"
                if needle and needle not in name:
                    continue
                captures.append({"name": name, "w": p["w"], "h": p["h"], "html": filled, "stateId": s["id"]})
    return {"mockup": str(mockup), "outdir": str(outdir), "settleMs": SETTLE_MS, "captures": captures}


def main(argv):
    args = argv[1:]
    needle = ""
    if "--filter" in args:
        i = args.index("--filter")
        if i + 1 >= len(args):
            print(__doc__, file=sys.stderr)
            return 2
        needle = args[i + 1]
        del args[i : i + 2]
    if len(args) != 2:
        print(__doc__, file=sys.stderr)
        return 2
    mockup = Path(args[0]).resolve()
    outdir = Path(args[1]).resolve()
    if not mockup.is_file():
        print(f"not a file: {mockup}", file=sys.stderr)
        return 2
    job = build_job(extract_spec(mockup), mockup, outdir, needle)
    with tempfile.TemporaryDirectory() as tmp:
        job_path = Path(tmp) / "job.json"
        run_path = Path(tmp) / "run.mjs"
        job_path.write_text(json.dumps(job), encoding="utf-8")
        run_path.write_text(NODE_RUNNER, encoding="utf-8")
        proc = subprocess.run(["node", str(run_path), str(job_path)], capture_output=True, text=True)
    if proc.returncode == 2:
        print(proc.stderr.strip(), file=sys.stderr)
        return 2
    try:
        result = json.loads(proc.stdout.strip().splitlines()[-1])
    except (IndexError, ValueError):
        print(proc.stdout + proc.stderr, file=sys.stderr)
        return 2
    for e in result["errors"]:
        print("page error:", e)
    print(f"{result['count']} PNGs in {outdir} ({len(result['errors'])} page errors)")
    return 1 if result["errors"] else 0


if __name__ == "__main__":
    sys.exit(main(sys.argv))
