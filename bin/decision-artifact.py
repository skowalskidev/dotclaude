#!/usr/bin/env python3
"""Build/extract compact proposal cards using the shared presentation frame.

Usage: decision-artifact.py build <spec.json> <out.html>
       decision-artifact.py extract <out.html> <spec.json>
       decision-artifact.py example

sections[].cards[]: id, title, tradeoff, accept, decline, before, after, optional detail, research.
One card = ONE proposed change; the shape rules live in references/tldr-report-formats.md
§ Before/after unit. `tradeoff` is the card's one-line context TLDR (what changes, who sees it,
the consequence), shown visibly; `accept` / `decline` say what each choice does.
before/after map viewport labels to data-URI images or {text: ...} with the real values.
research: {verdict: recommended|not-recommended|mixed|unverified, tldr: one line,
details: [paragraphs], sources: [{title, url}]}; every verdict but unverified needs
at least one http(s) source. It renders as a stamp, a visible TLDR and collapsed Research.
Set feedback: true only when collecting proposal decisions and comments. With feedback on, build
refuses a card without a context TLDR of at most 25 words, accept, decline, a 2-6 word title,
or both before and after; before equal to after, and two cards with the same before/after
(mirror cards of one decision), fail too. Any card titled with an option label fails.
Legacy control/runtime metadata is retained unchanged and never rendered as inputs.
"""
import json
import re
import sys
from pathlib import Path
from presentation_build import compose, extract

HERE = Path(__file__).resolve().parent
EXAMPLE = {"title": "Streak rules proposal", "feedback": True, "sections": [{"id": "streaks", "title": "Streaks", "cards": [
    {"id": "rules-details", "title": "Streak rules fold under Details",
     "tradeoff": "Every member sees the streak count first; the four rule lines move under a closed Details toggle.",
     "accept": "The rules text collapses behind a Details toggle.", "decline": "The four rule lines stay open under the count.",
     "before": {"text": "Streak screen: count, then 4 lines of rules"},
     "after": {"text": "Streak screen: count, then a closed Details toggle holding the rules"},
     "research": {"verdict": "recommended", "tldr": "Native disclosure is the documented default for optional detail.",
                  "details": ["The details element opens and closes with a click or the keyboard, with no script."],
                  "sources": [{"title": "MDN: the details element", "url": "https://developer.mozilla.org/en-US/docs/Web/HTML/Reference/Elements/details"}]}},
    {"id": "rest-days", "title": "Rest days keep the streak",
     "tradeoff": "Members with a scheduled rest day keep their streak that day instead of dropping to zero.",
     "accept": "A scheduled rest day holds the streak.", "decline": "A rest day still resets the streak to 0.",
     "before": {"text": "Scheduled rest day: streak resets to 0"},
     "after": {"text": "Scheduled rest day: streak holds, no increment"}},
    {"id": "outside-workouts", "title": "Outside workouts count for streaks",
     "tradeoff": "Members logging a 20+ minute outside workout keep their streak; plan-only members see no change.",
     "accept": "A 20+ minute outside workout counts as the day's workout.", "decline": "Only a plan workout counts.",
     "before": {"text": "Streak day: plan workout + calorie goal"},
     "after": {"text": "Streak day: plan workout OR a 20+ min outside workout, + calorie goal"},
     "research": {"verdict": "unverified", "tldr": "No platform page settles streak rules; the call rests on product data."}}
]}]}


VERDICTS = ("recommended", "not-recommended", "mixed", "unverified")
TLDR_WORDS = 25  # the renderer shows the first of tradeoff/verdict/explainer within this many words
TITLE_WORDS = (2, 6)
# A title that is a choice, not a change: "Option B", "Streaks: ship as built", "Suggest to <person>".
OPTION_LABEL = re.compile(r"""(?:^|:\s*)(?:
    (?:option|variant|alternative|choice|proposal|suggestion)(?:\s+\w{1,3})?
  | (?:suggest|propose|recommend|pitch|escalate)(?:ed)?\s+to\b.*
  | (?:ship|keep|leave|defer|park|skip|accept|decline|reject|build|merge)
    (?:\s+(?:it|this|that|them))?(?:\s+(?:as[- ]built|as[- ]is|unchanged|for\s+now|later|now|current|anyway))?
  | do\s+nothing|status\s+quo|no\s+change|as[- ]is|as[- ]built|recommended|preferred|current
)\s*$""", re.I | re.X)
UNIT = "references/tldr-report-formats.md § Before/after unit"


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


def context_line(card):
    """The visible TLDR, chosen exactly as decision-artifact.html chooses it."""
    return next((text for text in (card.get(key) for key in ("tradeoff", "verdict", "explainer"))
                 if isinstance(text, str) and text.strip() and len(text.split()) <= TLDR_WORDS), "")


def filled(value):
    return isinstance(value, dict) and any(isinstance(v, str) and v.strip() for v in value.values())


def check_unit(card, feedback, pairs):
    """One card = one decidable change: a change title, a context TLDR, Accept/Decline, BEFORE and AFTER."""
    where, title = f"Card {card['id']} ({card.get('title', '')!r})", str(card.get("title", "")).strip()
    if OPTION_LABEL.search(title):
        raise ValueError(f"{where}: the title is an option label; name the change itself in 2-6 words, "
                         f"e.g. 'Outside workouts count for streaks' ({UNIT})")
    if not feedback:
        return
    if not TITLE_WORDS[0] <= len(title.split()) <= TITLE_WORDS[1]:
        raise ValueError(f"{where}: the title names the change in 2-6 words, never a bare topic ({UNIT})")
    if not context_line(card):
        raise ValueError(f"{where} needs tradeoff: a one-line context TLDR of at most {TLDR_WORDS} words "
                         f"(what changes, who sees it, the consequence) ({UNIT})")
    for key in ("accept", "decline"):
        if not isinstance(card.get(key), str) or not card[key].strip():
            raise ValueError(f"{where} needs {key}: one line saying what {key.title()} does ({UNIT})")
    missing = [key for key in ("before", "after") if not filled(card.get(key))]
    if missing:
        raise ValueError(f"{where} needs both before and after (missing {', '.join(missing)}): the exact current "
                         f"state and the exact state if accepted; use {{\"text\": ...}} with real values "
                         f"when nothing visible changes ({UNIT})")
    if card["before"] == card["after"]:
        raise ValueError(f"{where}: before and after are identical, so nothing changes; a keep-as-is option "
                         f"is another card's Decline ({UNIT})")
    pair = json.dumps([card["before"], card["after"]], sort_keys=True)
    if pair in pairs:
        raise ValueError(f"{where} shows the same before/after as card {pairs[pair]}: one decision is one card, "
                         f"decided by its Accept/Decline control ({UNIT})")
    pairs[pair] = card["id"]


def build(spec):
    seen, pairs, feedback = set(), {}, spec.get("feedback") is True
    for section in spec.get("sections", []):
        for item in [section, *section.get("cards", [])]:
            if not item.get("id") or item["id"] in seen:
                raise ValueError("Every section and card needs a unique id")
            seen.add(item["id"])
        for card in section.get("cards", []):
            check_research(card)
            check_unit(card, feedback, pairs)
    return compose("decision", spec, (HERE / "decision-artifact.html").read_text(), title=spec.get("title", "Decision"))


def main(argv):
    if argv == ["example"]:
        print(json.dumps(EXAMPLE, indent=2)); return 0
    if len(argv) == 3 and argv[0] in ("build", "extract"):
        source = Path(argv[1]).read_text()
        try:
            result = build(json.loads(source)) if argv[0] == "build" else json.dumps(extract(source), indent=2, ensure_ascii=False)
        except ValueError as error:
            print(f"decision-artifact: {error}", file=sys.stderr); return 1
        Path(argv[2]).write_text(result); return 0
    print(__doc__); return 2


if __name__ == "__main__":
    raise SystemExit(main(sys.argv[1:]))
