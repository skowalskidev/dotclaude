#!/usr/bin/env python3
"""
Deny a Slack or Gmail send/draft whose message breaks the TLDR shape for a message to someone else.

rules/communication.md § Answer first: a message for anyone but Simon, or a draft he sends as
himself, is line 1 the ask or verdict, then one fact per bullet, at most 5 lines. That rule existed
and drafts to teammates still ran long and dense until Simon asked again, so this is the backstop on
the send path. The measure lives in ONE owner, bin/outbound_message.py, which every route the hook
cannot see (a codex-app run, `gh pr comment`, `gh api .../replies`) runs as
`python3 ~/.claude/bin/outbound_message.py check <file|->`.

WHAT IT BLOCKS: a PreToolUse call to a Slack or Gmail MCP tool that sends, replies, posts,
schedules, forwards or saves a draft, whose message text fails bin/outbound_message.py problems():
over 5 lines or 100 words, a line over 25 words (a URL-only line exempt), or 3+ lines with no
bullets. Reads, searches, canvases, labels and deletes pass.

OVERRIDE, one send at a time: when Simon's own message asked for the length, write his words into
`.context/long-message-ok` under the call's working directory. The guard allows the next failing
send and deletes the file.

Fails OPEN on anything malformed: a guard that breaks the session gets switched off.
"""

from __future__ import annotations

import json
import os
import re
import sys
from pathlib import Path

sys.path.insert(0, os.path.join(os.path.dirname(os.path.realpath(__file__)), "..", "bin"))
try:
    import outbound_message  # noqa: E402  the one owner of the measure
except Exception:  # fail open: a broken import must not block every send
    outbound_message = None

OVERRIDE = Path(".context") / "long-message-ok"

SERVICE = re.compile(r"slack|gmail", re.I)
SENDS = re.compile(r"send|reply|post|schedule|draft|forward", re.I)
NOT_A_SEND = re.compile(r"canvas|(^|_)(read|search|list|get|label|unlabel|trash|untrash|spam|delete)(_|$)", re.I)
TEXT_KEYS = ("text", "message", "body", "forwardText", "content", "markdown", "plain_text", "draft")
HTML_KEYS = ("htmlBody", "html")
HTML_BREAK = re.compile(r"<\s*(br|/p|/li|/div|/h\d)\b[^>]*>", re.I)
HTML_ITEM = re.compile(r"<\s*li\b[^>]*>", re.I)  # a list item keeps its bullet
HTML_TAG = re.compile(r"<[^>]+>")


def message_text(tool_input: dict) -> str | None:
    for key in TEXT_KEYS:
        value = tool_input.get(key)
        if isinstance(value, str) and value.strip():
            return value
    for key in HTML_KEYS:
        value = tool_input.get(key)
        if isinstance(value, str) and value.strip():
            return HTML_TAG.sub("", HTML_ITEM.sub("\n- ", HTML_BREAK.sub("\n", value)))
    return None


def is_send(tool_name: str) -> bool:
    action = tool_name.split("__")[-1]
    return bool(SERVICE.search(tool_name) and SENDS.search(action) and not NOT_A_SEND.search(action))


def main() -> int:
    if len(sys.argv) > 1:
        print("This is a PreToolUse hook; measure a draft with "
              "python3 ~/.claude/bin/outbound_message.py check <file|->", file=sys.stderr)
        return 2
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
    if text is None or outbound_message is None:
        return 0
    found = outbound_message.problems(text)
    if not found:
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
                f"Blocked: a message to someone else with " + "; ".join(found) + ".\n"
                f"{outbound_message.FIX}\n"
                f"Only if Simon's own message asked for this length: write his words into "
                f"{OVERRIDE} in the working directory and send again (allows one send).\n"
                f"Rule: rules/communication.md § Answer first; shape: {outbound_message.RULE}."
            ),
        }
    }))
    return 0


if __name__ == "__main__":
    sys.exit(main())
