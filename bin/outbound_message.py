#!/usr/bin/env python3
"""
The one owner of the shape check for a message to someone else (a teammate DM, a Slack reply, an
email, a PR comment, a draft Simon sends as himself).

rules/communication.md § Answer first: line 1 is the ask or the verdict, then one fact per bullet,
at most 5 lines; references/tldr-report-formats.md § Message for someone else holds the shape.
hooks/outbound-message-guard.py imports this for Slack and Gmail sends; every route the hook cannot
see (a codex-app Slack run, `gh pr comment`, `gh api .../replies`) runs the CLI on the draft first:

  python3 ~/.claude/bin/outbound_message.py check <file|->

prints `ok` and exits 0 when the draft fits; prints each problem and the Fix shape and exits 1.

WHAT IT MEASURES, after dropping a leading greeting line ("Hi there,"), a trailing sign-off ("Thanks,"
alone or followed by a name line), quoted reply lines ("> ...") and code fences:
- at most MAX_LINES non-blank lines and MAX_WORDS words in all;
- at most MAX_LINE_WORDS words on any one line, its bullet marker excluded; a URL-only line is exempt;
- a message of BULLETS_FROM_LINES lines or more carries its facts on bullets or numbered steps.
"""

from __future__ import annotations

import re
import sys
from pathlib import Path

MAX_LINES = 5  # mirrors rules/communication.md § Answer first
MAX_WORDS = 100  # 5 lines of at most 20 words
MAX_LINE_WORDS = 25  # the rule says 20 per line; 5 words of slack before a deny
BULLETS_FROM_LINES = 3  # line 1 plus two or more facts: the facts go on bullets
RULE = "references/tldr-report-formats.md § Message for someone else"

SIGNOFF = re.compile(r"^(thanks|thank you|cheers|best|regards|kind regards|best regards|ta|thx)\b[\s\w]{0,12}[,.!]?$", re.I)
GREETING = re.compile(r"^(hi|hey|hello|dear|morning|good (morning|afternoon|evening))\b", re.I)
BULLET = re.compile(r"^([-*•‣◦]|\d{1,2}[.)])\s+")
URL_ONLY = re.compile(r"^(<?https?://\S+>?|<https?://[^>]+>|\[[^\]]*\]\(\S+\))$")

FIX = ("Fix: line 1 is the ask or the verdict; then one fact per bullet (\"- \"), each at most 20 "
       "words, a figure in its own bullet rather than in parentheses; at most 5 lines in all. e.g.\n"
       "  Suggest variant B for every new visitor; it earns more per visitor.\n"
       "  - 7-day revenue per visitor: B $2.20, A $1.30, after refunds\n"
       "  - Gap $0.90, 95% range $0.10 to $1.80\n"
       "  - At 14 days the gap is $0.50, not yet clear of zero\n"
       "Cut it; do not split it into several messages.")


def counted_lines(text: str) -> list[str]:
    lines = [ln.strip() for ln in text.splitlines()]
    lines = [ln for ln in lines if ln and not ln.startswith(">") and not ln.startswith("```")]
    if lines and GREETING.match(lines[0]) and len(lines[0].split()) <= 5:
        lines = lines[1:]
    if len(lines) > 2 and SIGNOFF.match(lines[-2]) and len(lines[-1].split()) <= 4:
        lines = lines[:-2]  # "Thanks," then a name
    elif len(lines) > 1 and SIGNOFF.match(lines[-1]):
        lines = lines[:-1]
    return lines


def line_words(line: str) -> int:
    body = BULLET.sub("", line, count=1)
    return 0 if URL_ONLY.match(body) else len(body.split())


def problems(text: str) -> list[str]:
    lines = counted_lines(text)
    found = []
    n_words = sum(len(ln.split()) for ln in lines)
    if len(lines) > MAX_LINES or n_words > MAX_WORDS:
        found.append(f"{len(lines)} lines and {n_words} words, over the cap of {MAX_LINES} lines "
                     f"and {MAX_WORDS} words")
    long = [(i, line_words(ln)) for i, ln in enumerate(lines, 1) if line_words(ln) > MAX_LINE_WORDS]
    if long:
        found.append("line " + ", line ".join(f"{i} has {n} words" for i, n in long)
                     + f", over {MAX_LINE_WORDS} per line")
    if len(lines) >= BULLETS_FROM_LINES and not any(BULLET.match(ln) for ln in lines[1:]):
        found.append(f"{len(lines)} lines with no bullets; put each fact after line 1 on its own bullet")
    return found


def main(argv: list[str]) -> int:
    if len(argv) != 2 or argv[0] != "check":
        print("usage: outbound_message.py check <file|->", file=sys.stderr)
        return 2
    text = sys.stdin.read() if argv[1] == "-" else Path(argv[1]).read_text()
    found = problems(text)
    if not found:
        print("ok")
        return 0
    print("over: " + "; ".join(found) + f".\n{FIX}\nShape: {RULE}.")
    return 1


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))
