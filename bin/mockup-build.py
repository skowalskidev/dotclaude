#!/usr/bin/env python3
"""Build / extract an offline mockup using the shared presentation frame.

The mockup-shell.html adapter renders captured product content from the complete
#spec JSON. presentation-shell.html owns shared controls, typography and theme.
Extraction preserves every field, including metadata hidden from the frame.

Usage:
    mockup-build.py <spec.json> <out.html>
    mockup-build.py --extract <mockup.html> <spec.json>

No third-party dependencies; Python 3.9+.
"""
import json
import sys
from presentation_build import compose, extract as extract_spec
from pathlib import Path

SHELL_PATH = Path(__file__).resolve().parent / "mockup-shell.html"

def validate(spec: dict) -> None:
    personas = spec.get("personas", [])
    defaults = {"desktop": (1440, 900), "mobile": (390, 844)}
    if not personas:
        unknown = {key for variant in spec.get("variants", {}).values()
                   for key in variant.get("captures", {})} - defaults.keys()
        if unknown:
            raise ValueError("Declare exact personas w/h for capture IDs: " + ", ".join(sorted(unknown)))
    ids = set()
    for persona in personas:
        if not persona.get("id") or persona["id"] in ids:
            raise ValueError("Each persona needs a unique id")
        ids.add(persona["id"])
        for dimension in ("w", "h"):
            value = persona.get(dimension)
            if not isinstance(value, (int, float)) or isinstance(value, bool) or value <= 0:
                raise ValueError("Persona " + persona["id"] + " needs a positive " + dimension)


def build(spec_path: str, out_path: str) -> None:
    spec = json.loads(Path(spec_path).read_text(encoding="utf-8"))
    validate(spec)
    shell = SHELL_PATH.read_text(encoding="utf-8")
    out = compose("mockup", spec, shell, title=spec.get("manifest", {}).get("title", "Mockup"))
    Path(out_path).write_text(out, encoding="utf-8")
    size = Path(out_path).stat().st_size
    print(f"wrote {out_path} ({size / 1024 / 1024:.2f} MB)")


def extract(mockup_path: str, spec_out_path: str) -> None:
    html = Path(mockup_path).read_text(encoding="utf-8")
    spec = extract_spec(html)
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
