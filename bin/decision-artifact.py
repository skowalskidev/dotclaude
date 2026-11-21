#!/usr/bin/env python3
"""Build/extract compact proposal cards using the shared presentation frame.

Usage: decision-artifact.py build <spec.json> <out.html>
       decision-artifact.py extract <out.html> <spec.json>
       decision-artifact.py example

sections[].cards[]: id, title, tradeoff, optional detail, before, after, research.
research: {verdict: recommended|not-recommended|mixed|unverified, tldr: one line,
details: [paragraphs], sources: [{title, url}]}; every verdict but unverified needs
at least one http(s) source. It renders as a stamp, a visible TLDR and collapsed Research.
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
    {"id": "small", "title": "Small update", "tradeoff": "Ships sooner; keeps the existing layout.",
     "research": {"verdict": "recommended", "tldr": "Native disclosure is the documented default for optional detail.",
                  "details": ["The details element opens and closes with a click or the keyboard, with no script.",
                              "Status labels pair colour with text, so the meaning survives without colour."],
                  "sources": [{"title": "MDN: the details element", "url": "https://developer.mozilla.org/en-US/docs/Web/HTML/Reference/Elements/details"},
                              {"title": "WCAG 2.2: Use of Color", "url": "https://www.w3.org/WAI/WCAG22/Understanding/use-of-color.html"}]}},
    {"id": "large", "title": "Full redesign", "tradeoff": "Changes the whole flow; takes longer to build."},
    {"id": "docs", "title": "Update the guide", "tradeoff": "Clarifies the flow; leaves the product unchanged.", "before": {"text": "Existing instructions"}, "after": {"text": "Updated instructions"}}
]}]}


VERDICTS = ("recommended", "not-recommended", "mixed", "unverified")


def check_research(card):
    research = card.get("research")
    if research is None:
        return
    where = f"Card {card['id']} research"
    if not isinstance(research, dict) or research.get("verdict") not in VERDICTS:
        raise ValueError(f"{where} needs a verdict: {', '.join(VERDICTS)}")
    if not isinstance(research.get("tldr"), str) or not research["tldr"].strip():
        raise ValueError(f"{where} needs a one-line tldr")
    details, sources = research.get("details", []), research.get("sources", [])
    if not isinstance(details, list) or not all(isinstance(text, str) for text in details):
        raise ValueError(f"{where} details must be a list of strings")
    if not isinstance(sources, list) or not all(
            isinstance(source, dict) and isinstance(source.get("title"), str)
            and str(source.get("url", "")).lower().startswith(("https://", "http://")) for source in sources):
        raise ValueError(f"{where} sources must be [{{title, url}}] with http(s) urls")
    if research["verdict"] != "unverified" and not sources:
        raise ValueError(f"{where} needs a source link, or verdict unverified")


def build(spec):
    seen = set()
    for section in spec.get("sections", []):
        for item in [section, *section.get("cards", [])]:
            if not item.get("id") or item["id"] in seen:
                raise ValueError("Every section and card needs a unique id")
            seen.add(item["id"])
        for card in section.get("cards", []):
            check_research(card)
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
