#!/usr/bin/env python3
"""Build / extract a shareable design board: many phone-frame mockups on one pan/zoom whiteboard.

The board is the exploration form (many variants, Figma-like); bin/mockup-build.py is the decision
form (one surface, before/after). Both are spec-driven shells; neither is hand-rolled per project.

Usage:
    design-board.py build <spec.json> <out.html>
    design-board.py extract <board.html> <spec.json>
    design-board.py example > spec.json

Spec (schemaVersion 1):
    {
      "title": "...", "lead": "...",
      "font": "/abs/path/Inter.woff2" | "data:font/woff2;base64,...",   # optional, embedded
      "phone": {"w": 393, "h": 852},                                   # optional, iPhone default
      "css": "...",                                                   # optional, project screen CSS
      "sections": [
        {"title": "...", "lead": "...", "frames": [
          {"id": "1", "label": "POINTSGPT · 01", "title": "...", "hypothesis": "...", "note": "...",
           "pick": true, "hidden": false, "night": false,
           "html": "<inner html of the phone>"  |  "image": "/abs/path/capture.png"}
        ]}
      ]
    }

Every frame carries `data-frame` and `data-measure` hooks. In a browser, `window.__measure()` returns
[{id, overflow, wrapped}] where `overflow` is how far the deepest element sits past the phone bottom
and `wrapped` lists elements marked `data-oneline` that broke onto a second line. No third-party
dependencies; Python 3.9+ (Pillow optional, for image frames).
"""
import base64
import html as html_mod
import io
import json
import pathlib
import sys

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


def frame_html(frame: dict, phone: dict) -> str:
    if frame.get("hidden"):
        return ""
    esc = html_mod.escape
    badge = '<span class="pick">Picked</span>' if frame.get("pick") else ""
    night = " night" if frame.get("night") else ""
    if "image" in frame:
        body = f'<div class="screen image{night}" data-frame="{esc(frame["id"])}"><img src="{image_uri(frame["image"], phone["w"] * 2)}" alt=""></div>'
    else:
        body = f'<div class="screen{night}" data-frame="{esc(frame["id"])}">{frame.get("html", "")}</div>'
    return (
        f'<div class="frame{" picked" if frame.get("pick") else ""}">'
        f'<p class="flabel">{esc(frame.get("label", ""))} {badge}</p>'
        f'<p class="ftitle">{esc(frame.get("title", ""))}</p>'
        f'<p class="fhyp">{esc(frame.get("hypothesis", ""))}</p>'
        f"{body}"
        f'<p class="fnote">{esc(frame.get("note", ""))}</p></div>'
    )


def build(spec: dict) -> str:
    phone = {"w": 393, "h": 852, **spec.get("phone", {})}
    esc = html_mod.escape
    sections = "".join(
        f'<section class="board"><h2>{esc(s.get("title", ""))}</h2><p class="slead">{esc(s.get("lead", ""))}</p>'
        f'<div class="row">{"".join(frame_html(f, phone) for f in s.get("frames", []))}</div></section>'
        for s in spec.get("sections", [])
    )
    font = spec.get("font")
    font_face = (
        f"@font-face{{font-family:'BoardFont';src:url({data_uri(font, 'font/woff2')}) format('woff2');font-weight:100 900}}"
        if font
        else ""
    )
    page = TEMPLATE.read_text()
    page = page.replace("/*FONT_FACE*/", font_face)
    page = page.replace("/*PHONE_W*/", str(phone["w"])).replace("/*PHONE_H*/", str(phone["h"]))
    page = page.replace("/*PROJECT_CSS*/", spec.get("css", ""))
    page = page.replace("<!--TITLE-->", esc(spec.get("title", "Design board")))
    page = page.replace("<!--LEAD-->", esc(spec.get("lead", "")))
    page = page.replace("<!--SECTIONS-->", sections)
    stored = {k: v for k, v in spec.items() if k != "font"}
    page = page.replace(
        "<!--SPEC-->", SPEC_TAG + json.dumps(stored).replace("</", "<\\/") + "</script>"
    )
    return page


def extract(page: str) -> dict:
    start = page.index(SPEC_TAG) + len(SPEC_TAG)
    end = page.index("</script>", start)
    return json.loads(page[start:end].replace("<\\/", "</"))


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
    print(__doc__)
    return 2


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))
