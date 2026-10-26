#!/usr/bin/env python3
"""visual-check.py self-test: --route with a missing file exits 2, --wait-for and --wait-timeout parse, a client-rendered
page that fetches its data after load fails without them and passes with --route and --wait-for, and a tall page whose later
region screenshots scroll earlier regions above the viewport still passes (browser part skipped without Node Playwright)."""
import functools
import http.server
import collections
import json
import pathlib
import runpy
import struct
import subprocess
import sys
import tempfile
import threading
import zlib

HERE = pathlib.Path(__file__).resolve().parent
TOOL = HERE / "visual-check.py"
PAGE = """<!doctype html><meta charset=utf-8><title>t</title><p>Loading</p>
<script>fetch('/data.json').then(r => r.json()).then(d => setTimeout(() => {
  document.body.insertAdjacentHTML('beforeend', '<div id=done style="width:300px;height:120px;background:repeating-linear-gradient(90deg,#c33 0 20px,#36c 20px 40px);color:#fff">' + d.label + '</div>');
}, 1500));</script>"""
# Every region sits inside the document; screenshotting the lower cards scrolls the header and early cards above the viewport.
TALL = """<!doctype html><meta charset=utf-8><title>tall</title><style>body{margin:0}
.head,.card{height:260px;margin:20px;background:repeating-linear-gradient(90deg,#c33 0 20px,#36c 20px 40px)}
.grid{display:flex;flex-wrap:wrap}.card{width:240px}</style>
<div class=head></div><div class=grid>""" + "<div class=card></div>" * 12 + "</div>"


def run(*args: str, cwd: str) -> subprocess.CompletedProcess:
    return subprocess.run([sys.executable, str(TOOL), *args], capture_output=True, text=True, cwd=cwd)


class Quiet(http.server.SimpleHTTPRequestHandler):
    def log_message(self, *args):
        pass


def write_png(path, width, bands):
    """Write exact RGBA fixtures without depending on Pillow or a browser-sized canvas."""
    height = sum(repeat for _, repeat in bands)
    compressor = zlib.compressobj()
    payload = []
    for row, repeat in bands:
        assert len(row) == width * 4
        for _ in range(repeat):
            payload.append(compressor.compress(b'\0' + row))
    payload.append(compressor.flush())
    def chunk(kind, data):
        return struct.pack('!I', len(data)) + kind + data + struct.pack('!I', zlib.crc32(kind + data))
    path.write_bytes(b'\x89PNG\r\n\x1a\n' + chunk(b'IHDR', struct.pack('!2I5B', width, height, 8, 6, 0, 0, 0))
                     + chunk(b'IDAT', b''.join(payload)) + chunk(b'IEND', b''))


def reference_ink(width, rows, inset):
    """Original full-image metric, computed independently for small opaque fixtures."""
    x0, y0 = int(width * inset), int(len(rows) * inset)
    cw, ch = max(1, width - 2 * x0), max(1, len(rows) - 2 * y0)
    pixels = [tuple(row[4*x:4*x+3]) for row in rows[y0:y0+ch] for x in range(x0, x0+cw)]
    mode = collections.Counter(pixels).most_common(1)[0][0]
    return sum(any(abs(a-b) > 8 for a, b in zip(pixel, mode)) for pixel in pixels) / len(pixels)


def ink_checks(root):
    """Exercise the production ink function in one browser, including canvas-limit regressions."""
    white, black = bytes((255, 255, 255, 255)), bytes((0, 0, 0, 255))
    cases = []
    def case(name, width, bands, inset, expected):
        path = root / (name + '.png')
        write_png(path, width, bands)
        cases.append(dict(name=name, file=str(path), inset=inset, expected=expected))
    height = 100259
    case('tall blank', 13, [(white * 13, height)], 0, 0)
    case('tall global mode', 13, [(white * 13, 50000), (black * 13, height-50000)], 0, 50000/height)
    inset = int(height * .12)
    case('tall inset', 13, [(white * 13, 50000), (black * 13, height-50000)], .12,
         (50000-inset)/(height-2*inset))
    case('wide global mode', height, [(white*50000 + black*(height-50000), 3)], 0, 50000/height)
    case('wide blank', height, [(bytes((127, 127, 127, 255))*height, 1)], 0, 0)
    case('single pixel', 1, [(white, 1)], .12, 0)
    # A colour seen in a later tile can precede another colour in row-major order.
    a, b, near, far = [bytes((r, 0, 0, 255)) for r in (0, 20, 8, 200)]
    tie_rows = [near*1024+a*1024, b*1024+a*1024, b*1024+far*1024]
    case('row-major mode tie', 2048, [(row, 1) for row in tie_rows], 0, .5)
    small = [b''.join(bytes(((x*7+y*11) % 31, (x+y) % 19, 100, 255))
                      if (x+y) % 5 == 0 else bytes((8, 8, 100, 255)) for x in range(37))
             for y in range(29)]
    for value in (0, .12):
        case('small equivalence ' + str(value), 37, [(row, 1) for row in small], value,
             reference_ink(37, small, value))
    # A reused canvas must clear the prior tile before drawing transparent pixels.
    case('transparent tile reset', 13, [(white*13, 1024), (bytes(4)*13, 1024)], 0, .5)
    prefix = runpy.run_path(str(TOOL))['NODE_RUNNER'].split('// Why an element', 1)[0]
    script = root / 'ink-tests.mjs'
    script.write_text(prefix + r'''
const results = {};
try {
  for (const test of job.cases) {
    const actual = await ink(readFileSync(test.file), test.inset);
    results[test.name] = Math.abs(actual - test.expected) < 1e-12;
    if (!results[test.name]) console.error(`${test.name}: expected ${test.expected}, got ${actual}`);
  }
  await probe.evaluate(() => {
    window.originalLost = CanvasRenderingContext2D.prototype.isContextLost;
    CanvasRenderingContext2D.prototype.isContextLost = () => true;
  });
  try { await ink(readFileSync(job.cases[5].file), 0); results['lost context is an error'] = false; }
  catch (e) { results['lost context is an error'] = e.message.includes('ink canvas read failed'); }
  finally { await probe.evaluate(() => { CanvasRenderingContext2D.prototype.isContextLost = window.originalLost; }); }
} finally { await browser.close(); }
console.log(JSON.stringify(results));
process.exit(Object.values(results).every(Boolean) ? 0 : 1);
''')
    job = root / 'ink-job.json'
    job.write_text(json.dumps(dict(outdir=str(root), cases=cases)))
    result = subprocess.run(['node', str(script), str(job)], capture_output=True, text=True, timeout=90)
    if result.returncode:
        print(result.stdout + result.stderr)
        return {'pixel metric regressions': False}
    return json.loads(result.stdout.strip().splitlines()[-1])


def main() -> int:
    checks = {}
    with tempfile.TemporaryDirectory() as tmp:
        root = pathlib.Path(tmp)
        (root / "index.html").write_text(PAGE)
        (root / "data.json").write_text('{"label": "loaded"}')
        usage = run(str(root / "index.html"), "--out", str(root / "o1"), "--route", "**/data.json=missing.json", cwd=tmp)
        checks["missing route file exits 2"] = usage.returncode == 2 and "fixture file not found" in usage.stderr
        usage = run(str(root / "index.html"), "--out", str(root / "o2"), "--route", "nofile", cwd=tmp)
        checks["route without = exits 2"] = usage.returncode == 2 and "GLOB=FILE" in usage.stderr
        # Served from a directory without data.json so the page's fetch only succeeds through --route.
        site = root / "site"
        site.mkdir()
        (site / "index.html").write_text(PAGE)
        fixture = root / "fixture.json"
        fixture.write_text('{"label": "loaded"}')
        handler = functools.partial(Quiet, directory=str(site))
        server = http.server.ThreadingHTTPServer(("127.0.0.1", 0), handler)
        threading.Thread(target=server.serve_forever, daemon=True).start()
        url = f"http://127.0.0.1:{server.server_address[1]}/"
        try:
            base = ["--region", "#done", "--expect", "loaded"]
            gap = run(url, "--out", str(root / "o3"), *base, cwd=tmp)
            if gap.returncode == 2 and "SETUP: node 'playwright' not found" in gap.stderr:
                print("SKIP browser checks (Node Playwright unavailable): " + gap.stderr.strip())
            else:
                checks.update(ink_checks(root))
                checks["fails without --route and --wait-for"] = gap.returncode == 1
                ok = run(url, "--out", str(root / "o4"), "--route", "**/data.json=fixture.json", "--wait-for", "#done", *base, cwd=tmp)
                checks["passes with --route and --wait-for"] = ok.returncode == 0 and "| PASS" in ok.stdout
                late = run(url, "--out", str(root / "o5"), "--route", "**/data.json=fixture.json", *base, cwd=tmp)
                checks["fails with --route alone (data renders after load)"] = late.returncode == 1
                miss = run(url, "--out", str(root / "o6"), "--wait-for", "#never", "--wait-timeout", "500", cwd=tmp)
                checks["wait-for timeout fails the row, no crash"] = miss.returncode == 1 and "wait-for timed out: #never" in miss.stdout
                (root / "tall.html").write_text(TALL)
                tall = run(str(root / "tall.html"), "--out", str(root / "o7"), "--viewport", "600x400", "--region", ".card", "--region", ".head", "--visible", ".card", cwd=tmp)
                checks["regions scrolled above the viewport still count as inside the document"] = tall.returncode == 0 and "outside the document" not in tall.stdout
                huge = root / 'huge.html'
                huge.write_text('<style>body{margin:0;height:100259px;background:#777}i{position:absolute;'
                                'top:90000px;width:16px;height:10259px;background:white}</style><i></i>')
                visible = run(str(huge), '--out', str(root / 'huge-visible'), '--viewport', '16x200', cwd=tmp)
                checks['canvas-limit height with ink passes the page gate'] = visible.returncode == 0
                huge.write_text('<style>body{margin:0;height:100259px;background:#777}</style>')
                blank = run(str(huge), '--out', str(root / 'huge-blank'), '--viewport', '16x200', cwd=tmp)
                checks['canvas-limit height without ink fails the page gate'] = blank.returncode == 1 and 'page blank' in blank.stdout
        finally:
            server.shutdown()
    bad = [k for k, ok in checks.items() if not ok]
    for k, ok in checks.items():
        print(("PASS " if ok else "FAIL ") + k)
    return 1 if bad else 0


if __name__ == "__main__":
    sys.exit(main())
