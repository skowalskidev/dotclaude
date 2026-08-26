#!/usr/bin/env python3
"""
Deny AUTO-launching a browser to verify a frontend change, unless you authorized it.

rules/process.md: "Do NOT automatically spin up a dev server / preview and verify every frontend or
UI change in the browser ... when you're done working, ask me whether I want it verified." Only
launch the browser if the user says yes, if they explicitly asked for browser verification /
screenshots, or if the running skill carries their standing authorization (today only the
ship-report test phase).

WHAT IT BLOCKS

The two chrome-devtools tools that OPEN or DRIVE a page — `new_page` and `navigate_page`. Gating the
entry points is enough: the other tools (screenshot, click, snapshot) are inert without a page open,
so blocking the launch enforces the rule without carpet-blocking the whole server (a Lighthouse audit
or a read-only page inspection you asked for still needs the override, which is one env var).

Override: CLAUDE_ALLOW_BROWSER=1 — set it when the user said yes, when they asked for browser
verification / screenshots, or inside a skill that carries their standing authorization. Fails OPEN on
anything malformed — a guard that breaks the session gets switched off.
"""

import json
import os
import sys

# The chrome-devtools tools that open or navigate a page. Suffixes, matched against the tool name.
LAUNCH_TOOLS = ("new_page", "navigate_page")


def main() -> int:
    try:
        payload = json.load(sys.stdin)
    except Exception:
        return 0

    tool = payload.get("tool_name", "")
    if not isinstance(tool, str) or "chrome-devtools" not in tool:
        return 0
    if not tool.endswith(LAUNCH_TOOLS):
        return 0
    if os.environ.get("CLAUDE_ALLOW_BROWSER") == "1":
        return 0
    # An authorized browser skill (/sk:ship-screenshot-changes, /sk:test-eyeball) drops this sentinel
    # when it takes its port lane and removes it at teardown, so a user-approved browser run is allowed
    # without a manual env var. Mirrors hooks/config-edit-guard.py's authorization sentinel.
    if os.path.exists(os.path.expanduser("~/.claude/.browser-authorized")):
        return 0

    print(json.dumps({
        "hookSpecificOutput": {
            "hookEventName": "PreToolUse",
            "permissionDecision": "deny",
            "permissionDecisionReason": (
                f"Blocked: {tool} would launch a browser to verify a change. rules/process.md says "
                "don't auto-verify a frontend change in the browser — ask the user first when the "
                "work is done.\n"
                "If they said yes, asked for screenshots / browser verification, or a skill carries "
                "their standing authorization (e.g. the ship-report test phase), set "
                "CLAUDE_ALLOW_BROWSER=1 for the session, or touch ~/.claude/.browser-authorized (the "
                "sentinel an authorized browser skill sets). Static checks (grep, reading rendered "
                "output, layout math) never need this."
            ),
        }
    }))
    return 0


if __name__ == "__main__":
    sys.exit(main())
