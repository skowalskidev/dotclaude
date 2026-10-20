#!/usr/bin/env python3
"""Build/extract compact proposal cards using the shared presentation frame.

Usage: decision-artifact.py build <spec.json> <out.html>
       decision-artifact.py extract <out.html> <spec.json>
       decision-artifact.py example

sections[].cards[]: id, title, tradeoff, optional detail, before, after.
Set feedback: true only when collecting proposal decisions and comments.
before/after map viewport labels to data-URI images or {text: ...}.
Legacy control/runtime metadata is retained unchanged and never rendered as inputs.
"""
import json
import sys
from pathlib import Path
from presentation_build import compose, extract

HERE = Path(__file__).resolve().parent
EXAMPLE = {"title": "Choose the next step", "sections": [{"id": "direction", "title": "Direction", "cards": [
    {"id": "small", "title": "Small update", "tradeoff": "Ships sooner; keeps the existing layout."},
    {"id": "large", "title": "Full redesign", "tradeoff": "Changes the whole flow; takes longer to build."},
    {"id": "docs", "title": "Update the guide", "tradeoff": "Clarifies the flow; leaves the product unchanged.", "before": {"text": "Existing instructions"}, "after": {"text": "Updated instructions"}}
]}]}


def build(spec):
    seen = set()
    for section in spec.get("sections", []):
        for item in [section, *section.get("cards", [])]:
            if not item.get("id") or item["id"] in seen:
                raise ValueError("Every section and card needs a unique id")
            seen.add(item["id"])
    return compose("decision", spec, (HERE / "decision-artifact.html").read_text(), title=spec.get("title", "Decision"))


def main(argv):
    if argv == ["example"]:
        print(json.dumps(EXAMPLE, indent=2)); return 0
    if len(argv) == 3 and argv[0] in ("build", "extract"):
        source = Path(argv[1]).read_text()
        result = build(json.loads(source)) if argv[0] == "build" else json.dumps(extract(source), indent=2, ensure_ascii=False)
        Path(argv[2]).write_text(result); return 0
    print(__doc__); return 2


if __name__ == "__main__":
    raise SystemExit(main(sys.argv[1:]))
