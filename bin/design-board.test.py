#!/usr/bin/env python3
"""design-board.py self-test: the example spec builds, round-trips, and carries the measurement hooks."""
import json
import pathlib
import subprocess
import sys
import tempfile

HERE = pathlib.Path(__file__).resolve().parent
TOOL = HERE / "design-board.py"


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
            "self-contained": "http://" not in page and "https://" not in page,
        }
        run("extract", str(out), str(back))
        checks["round-trip"] = json.loads(back.read_text()) == json.loads(spec.read_text())
        bad = [k for k, ok in checks.items() if not ok]
        for k, ok in checks.items():
            print(("PASS " if ok else "FAIL ") + k)
        return 1 if bad else 0


if __name__ == "__main__":
    sys.exit(main())
