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
        bad = [k for k, ok in checks.items() if not ok]
        for k, ok in checks.items():
            print(("PASS " if ok else "FAIL ") + k)
        return 1 if bad else 0


if __name__ == "__main__":
    sys.exit(main())
