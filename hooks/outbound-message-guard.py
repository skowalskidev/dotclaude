#!/usr/bin/env python3
"""
Deny a Slack or Gmail send/draft whose message is over the TLDR cap for a message to someone else.

rules/communication.md § Answer first: a message for anyone but Simon, or a draft he sends as
himself, is at most 5 lines with no preamble. That rule existed and drafts to teammates still ran
long until Simon asked for TLDR again, so this is the backstop on the send path. Shape and override:
references/tldr-report-formats.md § Message for someone else.

WHAT IT BLOCKS: a PreToolUse call to a Slack or Gmail MCP tool that sends, replies, posts,
schedules, forwards or saves a draft, whose message text has more than MAX_LINES non-blank lines or
MAX_WORDS words. A leading greeting line ("Hi there,") and a trailing sign-off ("Thanks," alone or
followed by a name line) are not counted, nor are quoted lines ("> ...") in an email reply.
Reads, searches, canvases, labels and deletes pass.

OVERRIDE, one send at a time: when Simon's own message asked for the length, write his words into
`.context/long-message-ok` under the call's working directory. The guard allows the next over-cap
send and deletes the file.

CLI, for routes this hook cannot see (a codex-app run, `gh pr comment`, `gh api .../replies`):
  python3 ~/.claude/hooks/outbound-message-guard.py --check <file|->
prints `ok` and exits 0 within the cap; prints the counts and exits 1 over it.

Fails OPEN on anything malformed: a guard that breaks the session gets switched off.
"""

from __future__ import annotations

import json
import re
import sys
from pathlib import Path

MAX_LINES = 5  # the one source of the cap; mirrors rules/communication.md § Answer first
MAX_WORDS = 100  # 5 lines of at most 20 words
OVERRIDE = Path(".context") / "long-message-ok"
RULE = "references/tldr-report-formats.md § Message for someone else"

SERVICE = re.compile(r"slack|gmail", re.I)
SENDS = re.compile(r"send|reply|post|schedule|draft|forward", re.I)
NOT_A_SEND = re.compile(r"canvas|(^|_)(read|search|list|get|label|unlabel|trash|untrash|spam|delete)(_|$)", re.I)
TEXT_KEYS = ("text", "message", "body", "forwardText", "content", "markdown", "plain_text", "draft")
HTML_KEYS = ("htmlBody", "html")
HTML_BREAK = re.compile(r"<\s*(br|/p|/li|/div|/h\d)\b[^>]*>", re.I)
HTML_TAG = re.compile(r"<[^>]+>")
SIGNOFF = re.compile(r"^(thanks|thank you|cheers|best|regards|kind regards|best regards|ta|thx)\b[\s\w]{0,12}[,.!]?$", re.I)
GREETING = re.compile(r"^(hi|hey|hello|dear|morning|good (morning|afternoon|evening))\b", re.I)


def counted_lines(text: str) -> list[str]:
    lines = [ln.strip() for ln in text.splitlines()]
    lines = [ln for ln in lines if ln and not ln.startswith(">") and not ln.startswith("```")]
    if lines and GREETING.match(lines[0]) and len(lines[0].split()) <= 5:
        lines = lines[1:]
    if len(lines) > 2 and SIGNOFF.match(lines[-2]) and len(lines[-1].split()) <= 2:
        lines = lines[:-2]  # "Thanks," then a name
    elif len(lines) > 1 and SIGNOFF.match(lines[-1]):
        lines = lines[:-1]
    return lines


def measure(text: str) -> tuple[int, int]:
    lines = counted_lines(text)
    return len(lines), sum(len(ln.split()) for ln in lines)


def over(text: str) -> str | None:
    n_lines, n_words = measure(text)
    if n_lines <= MAX_LINES and n_words <= MAX_WORDS:
        return None
    return (f"{n_lines} lines and {n_words} words, over the cap of {MAX_LINES} lines and "
            f"{MAX_WORDS} words")


def message_text(tool_input: dict) -> str | None:
    for key in TEXT_KEYS:
        value = tool_input.get(key)
        if isinstance(value, str) and value.strip():
            return value
    for key in HTML_KEYS:
        value = tool_input.get(key)
        if isinstance(value, str) and value.strip():
            return HTML_TAG.sub("", HTML_BREAK.sub("\n", value))
    return None


def is_send(tool_name: str) -> bool:
    action = tool_name.split("__")[-1]
    return bool(SERVICE.search(tool_name) and SENDS.search(action) and not NOT_A_SEND.search(action))


def check_cli(arg: str) -> int:
    text = sys.stdin.read() if arg == "-" else Path(arg).read_text()
    problem = over(text)
    if problem is None:
        print("ok")
        return 0
    print(f"over: {problem}. Cut to the ask on line 1 and at most {MAX_LINES} lines; see {RULE}.")
    return 1


def main() -> int:
    if len(sys.argv) == 3 and sys.argv[1] == "--check":
        return check_cli(sys.argv[2])
    try:
        payload = json.load(sys.stdin)
    except Exception:
        return 0
    if not isinstance(payload, dict):
        return 0
    tool_name = payload.get("tool_name")
    tool_input = payload.get("tool_input")
    if not isinstance(tool_name, str) or not isinstance(tool_input, dict) or not is_send(tool_name):
        return 0
    text = message_text(tool_input)
    if text is None:
        return 0
    problem = over(text)
    if problem is None:
        return 0

    cwd = payload.get("cwd")
    override = Path(cwd) / OVERRIDE if isinstance(cwd, str) and cwd else None
    try:
        if override is not None and override.is_file() and override.read_text().strip():
            override.unlink()
            return 0
    except OSError:
        return 0

    print(json.dumps({
        "hookSpecificOutput": {
            "hookEventName": "PreToolUse",
            "permissionDecision": "deny",
            "permissionDecisionReason": (
                f"Blocked: this message is {problem} for a message to someone else.\n"
                f"Fix: put the ask or fact on line 1, keep at most {MAX_LINES} lines, drop the "
                f"preamble, recap and closer, and offer detail on request. Cut it; do not split it "
                f"into several messages.\n"
                f"Only if Simon's own message asked for this length: write his words into "
                f"{OVERRIDE} in the working directory and send again (allows one send).\n"
                f"Rule: rules/communication.md § Answer first; shape: {RULE}."
            ),
        }
    }))
    return 0


if __name__ == "__main__":
    sys.exit(main())
