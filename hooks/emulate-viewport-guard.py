#!/usr/bin/env python3
"""
Deny an emulated phone viewport taller than the test window can show.

references/browser-debugging.md § Fit the window: the emulated viewport must fit the visible content
area of the launched test window, or the page bottom falls below the window and the tester cannot
reach it. That prose rule was missed three times (402x874, then 390x844), so this is the backstop.

WHAT IT BLOCKS: mcp__chrome-devtools__emulate whose `viewport` ("<w>x<h>[x<dpr>][,mobile][,touch]
[,landscape]") has a vertical extent above the cap. The vertical extent is the height, or the width
when `landscape` is set. An absent viewport (clearing the override) passes.

THE CAP HAS ONE OWNER: MAX_VIEWPORT_H below. It is the default window (1280x900, launched by
bin/test-browser.sh --size) minus 150 px of browser chrome. For a taller launched window, set
CLAUDE_TEST_VIEWPORT_MAX_H (window height minus 150) in the session environment. Fails OPEN on
anything malformed: a guard that breaks the session gets switched off.
"""

import json
import os
import re
import sys

DEFAULT_WINDOW = "1280x900"
CHROME_PX = 150
MAX_VIEWPORT_H = int(DEFAULT_WINDOW.split("x")[1]) - CHROME_PX  # the one source of the cap
ENV_OVERRIDE = "CLAUDE_TEST_VIEWPORT_MAX_H"
SAFE_DEFAULT = f"402x{MAX_VIEWPORT_H}x3,mobile,touch"

VIEWPORT = re.compile(r"^\s*(\d+)\s*x\s*(\d+)(?:\s*x\s*[\d.]+)?\s*((?:,\s*[a-z]+\s*)*)$", re.I)


def cap() -> int:
    raw = os.environ.get(ENV_OVERRIDE, "").strip()
    return int(raw) if raw.isdigit() and int(raw) > 0 else MAX_VIEWPORT_H


def main() -> int:
    try:
        payload = json.load(sys.stdin)
    except Exception:
        return 0
    if not isinstance(payload, dict) or payload.get("tool_name") != "mcp__chrome-devtools__emulate":
        return 0
    tool_input = payload.get("tool_input") or {}
    viewport = tool_input.get("viewport") if isinstance(tool_input, dict) else None
    if not isinstance(viewport, str) or not viewport.strip():
        return 0
    m = VIEWPORT.match(viewport)
    if not m:
        return 0
    width, height = int(m.group(1)), int(m.group(2))
    flags = {f.strip().lower() for f in m.group(3).split(",") if f.strip()}
    landscape = "landscape" in flags
    vertical = width if landscape else height
    limit = cap()
    if vertical <= limit:
        return 0

    side = "width (landscape)" if landscape else "height"
    print(json.dumps({
        "hookSpecificOutput": {
            "hookEventName": "PreToolUse",
            "permissionDecision": "deny",
            "permissionDecisionReason": (
                f"Blocked: viewport {viewport!r} has a {side} of {vertical}px, above the {limit}px "
                f"cap, so the page bottom falls below the test window and the tester cannot reach it.\n"
                f"Fix: emulate viewport {SAFE_DEFAULT!r} (fits the default {DEFAULT_WINDOW} window). "
                f"Or relaunch the window taller with `~/.claude/bin/test-browser.sh launch --size WxH` "
                f"and raise the cap with {ENV_OVERRIDE}=<H minus {CHROME_PX}> in the session environment.\n"
                f"Rule: ~/.claude/references/browser-debugging.md § Fit the window."
            ),
        }
    }))
    return 0


if __name__ == "__main__":
    sys.exit(main())
