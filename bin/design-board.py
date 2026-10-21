#!/usr/bin/env python3
"""Build / extract a shareable design board: many phone-frame mockups on one pan/zoom whiteboard.

The board is the exploration form (many variants, Figma-like); bin/mockup-build.py is the decision
form (one surface, before/after). Both are spec-driven shells; neither is hand-rolled per project.

Usage:
    design-board.py build <spec.json> <out.html>
    design-board.py extract <board.html> <spec.json>
    design-board.py example > spec.json
    design-board.py check <board.html> <outdir>     # exit 0 only when every board state passes

Spec (schemaVersion 1):
    {
      "title": "...", "lead": "...",
      "font": "/abs/path/Inter.woff2" | "data:font/woff2;base64,...",   # optional, embedded
      "phone": {"w": 393, "h": 852},                                   # optional, iPhone default
      "css": "...",                                                   # optional, project screen CSS
      "sections": [
        {"title": "...", "lead": "...", "frames": [
          {"id": "1", "label": "EXAMPLE · 01", "title": "...", "hypothesis": "...", "note": "...",
           "pick": true, "hidden": false, "night": false,
           "html": "<inner html of the phone>"  |  "image": "/abs/path/capture.png"}
        ]}
      ]
    }

Every embedded payload (image, font, capture html) is stored ONCE, in the #spec data island; the board
fills each frame's screen document from it on load. `build` moves each image into `spec.assets` under a
content hash and points the frame at it as `@@ASSET:<id>@@`, so frames sharing a capture share one
copy. That keeps a board small enough to share as a claude.ai artifact, and keeps `extract` -> `build`
byte-identical.

Every frame carries `data-frame` and `data-measure` hooks. In a browser, `window.__measure()` returns
[{id, overflow, wrapped}] where `overflow` is how far the deepest element sits past the phone bottom
and `wrapped` lists elements marked `data-oneline` that broke onto a second line. No third-party
dependencies; Python 3.9+ (Pillow optional, for image frames).

`check` runs bin/visual-check.py on the built file: fit, 100% zoom and flattened states at 1440x900, a
title per shown frame in the page text, and, in the flattened state, every phone frame and frame title
fully visible (not cut by an ancestor) with ink in each phone.
It prints the pass table and writes the screenshots to <outdir>; hand the table over with the board.
"""
import base64
import copy
import hashlib
import html as html_mod
import io
import json
import pathlib
import subprocess
import sys
from presentation_build import ASSET_RE, ASSET_TOKEN, compose, extract as extract_spec

HERE = pathlib.Path(__file__).resolve().parent
TEMPLATE = HERE / "design-board.html"
SPEC_TAG = '<script type="application/json" id="spec">'


def data_uri(path: str, mime: str) -> str:
    if path.startswith("data:"):
        return path
    return f"data:{mime};base64," + base64.b64encode(pathlib.Path(path).read_bytes()).decode()


def image_uri(path: str, width: int) -> str:
    if path.startswith("data:"):
        return path
    try:
        from PIL import Image  # type: ignore
    except ImportError:
        return data_uri(path, "image/png")
    im = Image.open(path).convert("RGB")
    im = im.resize((width, round(im.height * width / im.width)))
    buf = io.BytesIO()
    im.save(buf, "WEBP", quality=88)
    return "data:image/webp;base64," + base64.b64encode(buf.getvalue()).decode()


def frame_html(frame: dict) -> str:
    """Frame card only. The capture document is filled from #spec at runtime, so each image, font and
    capture html is stored once in the built file (the spec), never again inside an iframe srcdoc."""
    if frame.get("hidden"):
        return ""
    esc = html_mod.escape
    badge = '<span class="pick">Picked</span>' if frame.get("pick") else ""
    return (f'<div class="board-frame{" picked" if frame.get("pick") else ""}">'
            f'<p class="flabel">{esc(frame.get("label", ""))} {badge}</p>'
            f'<p class="ftitle">{esc(frame.get("title", ""))}</p>'
            f'<p class="fhyp">{esc(frame.get("hypothesis", ""))}</p>'
            f'<div class="screen" data-frame="{esc(frame["id"])}"><iframe title="{esc(frame.get("title", frame["id"]))}"></iframe></div>'
            f'<p class="fnote">{esc(frame.get("note", ""))}</p></div>')


def build(spec: dict) -> str:
    spec = copy.deepcopy(spec)
    phone = {"w": 393, "h": 852, **spec.get("phone", {})}
    if spec.get("font") and not spec["font"].startswith("data:"):
        spec.setdefault("sourceAssets", {})["font"] = spec["font"]
        spec["font"] = data_uri(spec["font"], "font/woff2")
    for section in spec.get("sections", []):
        for frame in section.get("frames", []):
            image = frame.get("image")
            if not image or ASSET_RE.fullmatch(image):
                continue
            if not image.startswith("data:"):
                spec.setdefault("sourceAssets", {}).setdefault("images", {})[frame["id"]] = image
                image = image_uri(image, phone["w"] * 2)
            # Content-addressed, so frames sharing one capture share one stored copy.
            key = "img_" + hashlib.sha256(image.encode()).hexdigest()[:16]
            spec.setdefault("assets", {})[key] = image
            frame["image"] = f"@@ASSET:{key}@@"
    esc = html_mod.escape
    sections = "".join(
        f'<section class="board"><h2>{esc(section.get("title", ""))}</h2><p class="slead">{esc(section.get("lead", ""))}</p>'
        f'<div class="row">{"".join(frame_html(f) for f in section.get("frames", []))}</div></section>'
        for section in spec.get("sections", [])
    )
    adapter = TEMPLATE.read_text().replace("/*PHONE_W*/", str(phone["w"])).replace("/*PHONE_H*/", str(phone["h"])).replace("/*ASSET_TOKEN*/", ASSET_TOKEN)
    return compose("board", spec, adapter, content='<div id="canvas"><h1 class="board-export-title">' + esc(spec.get("title", "Design board")) + '</h1>' + sections + '</div>', title=spec.get("title", "Design board"))


def extract(page: str) -> dict:
    return extract_spec(page)


EXAMPLE = {
    "schemaVersion": 1,
    "title": "Example board",
    "lead": "Two frames on one whiteboard.",
    "sections": [
        {
            "title": "01 · Direction",
            "lead": "What each frame tests.",
            "frames": [
                {
                    "id": "a",
                    "label": "EXAMPLE · 01",
                    "title": "Alpha",
                    "hypothesis": "A big number carries the claim.",
                    "note": "Pairs with 02.",
                    "pick": True,
                    "html": '<div style="padding:120px 24px;font:700 44px/1.1 BoardFont,system-ui">$3,460<p data-oneline style="font:500 14px/1.4 system-ui;margin-top:8px">kept on this seat</p></div>',
                },
                {
                    "id": "b",
                    "label": "EXAMPLE · 02",
                    "title": "Beta",
                    "hypothesis": "Two bars carry the claim.",
                    "note": "Pairs with 01.",
                    "html": '<div style="padding:120px 24px;font:500 16px system-ui">Two bars here.</div>',
                },
            ],
        }
    ],
}


def check(board: pathlib.Path, outdir: pathlib.Path) -> int:
    spec = extract(board.read_text())
    args = [sys.executable, str(HERE / "visual-check.py"), str(board), "--out", str(outdir),
            "--viewport", "1440x900",
            "--state", "zoom100=document.getElementById('one').click()",
            "--state", "flat=window.__flatten();if(window.__measure().some(f=>f.overflow>0||f.cut.length))throw Error('capture cut by overflow')",
            "--region", ".screen[data-frame]", "--visible", ".ftitle", "--regions-in", "flat"]
    shown = [f for s in spec.get("sections", []) for f in s.get("frames", []) if not f.get("hidden")]
    for text in [spec.get("title", ""), *[f.get("title", "") for f in shown]]:
        if text:
            args += ["--expect", text]
    return subprocess.run(args).returncode


def main(argv: list) -> int:
    if len(argv) >= 1 and argv[0] == "example":
        print(json.dumps(EXAMPLE, indent=2))
        return 0
    if len(argv) == 3 and argv[0] == "build":
        spec = json.loads(pathlib.Path(argv[1]).read_text())
        out = pathlib.Path(argv[2])
        out.write_text(build(spec))
        print(f"{out} {out.stat().st_size // 1024} KB")
        return 0
    if len(argv) == 3 and argv[0] == "extract":
        pathlib.Path(argv[2]).write_text(json.dumps(extract(pathlib.Path(argv[1]).read_text()), indent=2))
        return 0
    if len(argv) == 3 and argv[0] == "check":
        return check(pathlib.Path(argv[1]).resolve(), pathlib.Path(argv[2]))
    print(__doc__)
    return 2


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))
