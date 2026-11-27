#!/usr/bin/env python3
"""Offline regression tests for bin/design-type-match.py: synthetic boards, macOS system fonts.

Each board is a 390 pt frame rendered at 1.5x with a string in one known face of a family that
ships adjacent weights (Medium, DemiBold, Bold); the tool must name that face from the three,
dark-on-light and light-on-dark, and name the family when the faces differ in family. Needs
Pillow, the engine's own dependency.
"""
import importlib.util
import json
import subprocess
import sys
import tempfile
from pathlib import Path

HERE = Path(__file__).resolve().parent
SCRIPT = HERE / "design-type-match.py"
FAILS: list[str] = []

try:
    from PIL import Image, ImageDraw, ImageFont
except ImportError:
    sys.exit("design-type-match.test: Pillow missing for " + sys.executable + " (brew install pillow)")

AVENIR = "/System/Library/Fonts/Avenir Next.ttc"
WEIGHTS = {"Medium": f"{AVENIR}#5", "DemiBold": f"{AVENIR}#2", "Bold": f"{AVENIR}#0"}
SUPP = "/System/Library/Fonts/Supplemental"
FAMILIES = {"Georgia": f"{SUPP}/Georgia Bold.ttf", "Verdana": f"{SUPP}/Verdana Bold.ttf",
            "Trebuchet": f"{SUPP}/Trebuchet MS Bold.ttf"}
SCALE, SIZE, TEXT = 1.5, 62, "8,114"
BOX = (16, 190, 200, 80)  # pt


def check(ok, msg):
    if not ok:
        FAILS.append(msg)


def board(path, font_spec, fg=(17, 17, 17), bg=(255, 255, 255)):
    """A 390x844 pt frame at 1.5x with TEXT drawn at SIZE pt inside BOX."""
    file, _, index = font_spec.partition("#")
    font = ImageFont.truetype(file, round(SIZE * SCALE), index=int(index or 0))
    img = Image.new("RGB", (round(390 * SCALE), round(844 * SCALE)), bg)
    ImageDraw.Draw(img).text((round((BOX[0] + 8) * SCALE), round((BOX[1] + 4) * SCALE)), TEXT, font=font,
                             fill=fg, anchor="lt")
    img.save(path)


def run(*args):
    return subprocess.run([sys.executable, str(SCRIPT), *map(str, args)], capture_output=True, text=True)


def match(path, fonts):
    args = [path, "--box", ",".join(map(str, BOX)), "--scale", SCALE, "--text", TEXT, "--size", SIZE, "--json"]
    for spec in fonts:
        args += ["--font", spec]
    r = run(*args)
    return r, json.loads(r.stdout or "{}")


def main():
    missing = [p for p in (AVENIR, *FAMILIES.values()) if not Path(p).is_file()]
    if missing:
        sys.exit("design-type-match.test: system fonts missing: " + ", ".join(missing))
    with tempfile.TemporaryDirectory() as tmp:
        t = Path(tmp)
        # Each adjacent weight is identified from the three, dark on light.
        for name, spec in WEIGHTS.items():
            board(t / f"{name}.png", spec)
            r, rep = match(t / f"{name}.png", WEIGHTS.values())
            check(r.returncode == 0 and rep.get("closest") == spec,
                  f"{name} board matched {rep.get('closest')}: {r.stdout} {r.stderr}")
            strokes = [f["stroke"] for f in sorted(rep.get("fonts", []), key=lambda f: f["stroke"])]
            check(len(strokes) == 3 and strokes[0] < strokes[1] < strokes[2],
                  f"per-weight strokes not strictly ordered for {name}: {strokes}")

        # Light text on a dark board (the ink polarity flips) still names the weight.
        board(t / "dark.png", WEIGHTS["DemiBold"], fg=(250, 250, 250), bg=(20, 24, 40))
        r, rep = match(t / "dark.png", WEIGHTS.values())
        check(r.returncode == 0 and rep.get("closest") == WEIGHTS["DemiBold"],
              f"light-on-dark DemiBold matched {rep.get('closest')}: {r.stderr}")

        # Family: the board's family wins over the same weight in other families.
        for name, spec in FAMILIES.items():
            board(t / f"fam-{name}.png", spec)
            r, rep = match(t / f"fam-{name}.png", FAMILIES.values())
            check(r.returncode == 0 and rep.get("closest") == spec,
                  f"{name} family board matched {rep.get('closest')}: {r.stderr}")

        # A wrong family is flagged by ink width even when it is the only candidate.
        r, rep = match(t / "fam-Verdana.png", [FAMILIES["Georgia"]])
        check(r.returncode == 0 and rep["fonts"][0]["width_mismatch"],
              f"Georgia against a Verdana board not flagged as a width mismatch: {r.stdout}")

        # Human output names the closest font and every candidate's stroke.
        r = run(t / "Bold.png", "--box", ",".join(map(str, BOX)), "--scale", SCALE, "--text", TEXT,
                "--size", SIZE, *[a for s in WEIGHTS.values() for a in ("--font", s)])
        check(r.returncode == 0 and f"closest: {WEIGHTS['Bold']}" in r.stdout and r.stdout.count("stroke") == 4,
              f"text report missing the closest line or a stroke: {r.stdout}")

        # Empty box: exit 1. Bad arguments or files: exit 2.
        r = run(t / "Bold.png", "--box", "300,700,40,40", "--scale", SCALE, "--text", TEXT, "--size", SIZE,
                "--font", WEIGHTS["Bold"])
        check(r.returncode == 1, f"empty box should exit 1, got {r.returncode}: {r.stderr}")
        for bad in (["--box", "1,2,3"], ["--box", "1,2,3,4", "--font", str(t / "nope.otf")]):
            args = [t / "Bold.png", "--scale", SCALE, "--text", TEXT, "--size", SIZE, *bad]
            if "--font" not in bad:
                args += ["--font", WEIGHTS["Bold"]]
            r = run(*args)
            check(r.returncode == 2, f"bad input {bad} should exit 2, got {r.returncode}")
        r = run(t / "missing.png", "--box", "1,2,3,4", "--scale", SCALE, "--text", TEXT, "--size", SIZE,
                "--font", WEIGHTS["Bold"])
        check(r.returncode == 2, f"unreadable board should exit 2, got {r.returncode}")

    if FAILS:
        print("design-type-match.test: FAIL")
        for f in FAILS:
            print("  - " + f)
        return 1
    print("design-type-match.test: ok")
    return 0


if __name__ == "__main__":
    sys.exit(main())
