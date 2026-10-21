#!/usr/bin/env python3
"""visual-check.py self-test: --route with a missing file exits 2, --wait-for and --wait-timeout parse, a client-rendered
page that fetches its data after load fails without them and passes with --route and --wait-for, and a tall page whose later
region screenshots scroll earlier regions above the viewport still passes (browser part skipped without Node Playwright)."""
import functools
import http.server
import pathlib
import subprocess
import sys
import tempfile
import threading

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
            if gap.returncode == 2:
                print("SKIP browser checks (Node Playwright unavailable): " + gap.stderr.strip())
            else:
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
        finally:
            server.shutdown()
    bad = [k for k, ok in checks.items() if not ok]
    for k, ok in checks.items():
        print(("PASS " if ok else "FAIL ") + k)
    return 1 if bad else 0


if __name__ == "__main__":
    sys.exit(main())
