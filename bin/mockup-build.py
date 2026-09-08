#!/usr/bin/env python3
"""Build / extract a self-contained mockup HTML file from the generic mockup-shell.

The shell (mockup-shell.html, in this same directory) renders entirely from a
single JSON "spec" embedded in a `<script type="application/json" id="spec">`
tag. This tool inlines a spec into the shell to produce a shareable, offline
`file://`-openable HTML document, and can pull the spec back out of a built
document for editing.

Usage:
    mockup-build.py <spec.json> <out.html>
    mockup-build.py --extract <mockup.html> <spec.json>

No third-party dependencies; Python 3.9+.
"""
import json
import sys
from pathlib import Path

SHELL_PATH = Path(__file__).resolve().parent / "mockup-shell.html"
PLACEHOLDER = "__MOCKUP_SPEC__"
SPEC_TAG_OPEN = '<script id="spec" type="application/json">'
SPEC_TAG_CLOSE = "</script>"


def _json_for_embed(spec: dict) -> str:
    # Compact, and escape sequences that would otherwise break out of the
    # surrounding <script> tag or get mangled by an HTML parser.
    text = json.dumps(spec, ensure_ascii=False, separators=(",", ":"))
    return text.replace("</", "<\\/")


def build(spec_path: str, out_path: str) -> None:
    spec = json.loads(Path(spec_path).read_text(encoding="utf-8"))
    shell = SHELL_PATH.read_text(encoding="utf-8")
    if PLACEHOLDER not in shell:
        raise SystemExit(f"shell is missing the {PLACEHOLDER} placeholder: {SHELL_PATH}")
    out = shell.replace(PLACEHOLDER, _json_for_embed(spec))
    Path(out_path).write_text(out, encoding="utf-8")
    size = Path(out_path).stat().st_size
    print(f"wrote {out_path} ({size / 1024 / 1024:.2f} MB)")


def extract(mockup_path: str, spec_out_path: str) -> None:
    html = Path(mockup_path).read_text(encoding="utf-8")
    start = html.find(SPEC_TAG_OPEN)
    if start == -1:
        raise SystemExit(f"no #spec script tag found in {mockup_path}")
    start += len(SPEC_TAG_OPEN)
    end = html.find(SPEC_TAG_CLOSE, start)
    if end == -1:
        raise SystemExit(f"unterminated #spec script tag in {mockup_path}")
    raw = html[start:end]
    spec = json.loads(raw)
    Path(spec_out_path).write_text(json.dumps(spec, indent=2, ensure_ascii=False), encoding="utf-8")
    print(f"wrote {spec_out_path}")


def main(argv):
    if len(argv) == 4 and argv[1] == "--extract":
        extract(argv[2], argv[3])
        return 0
    if len(argv) == 3:
        build(argv[1], argv[2])
        return 0
    print(__doc__)
    return 1


if __name__ == "__main__":
    raise SystemExit(main(sys.argv))
