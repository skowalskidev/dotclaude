#!/usr/bin/env python3
"""
Deny AUTO-launching a browser to verify a frontend change, unless you authorized it.

rules/process.md: "Do NOT automatically spin up a dev server / preview and verify every frontend or
UI change in the browser ... when you're done working, ask me whether I want it verified." Only
launch the browser if the user says yes, if they explicitly asked for browser verification /
screenshots, or if the running skill carries their standing authorization (today only the
ship-report test phase).

WHAT IT BLOCKS

The two chrome-devtools tools that OPEN or DRIVE a page — `new_page` and `navigate_page` — but ONLY
when the target URL is the LOCAL app under verification. That is the whole rule: "verify a frontend
change" means opening the app you just edited (the local dev server / preview), not browsing the web.
So the gate is scoped by URL:

  - LOCAL app URL (localhost / 127.0.0.1 / 0.0.0.0 / [::1] / *.localhost) → GATED. Opening it is
    auto-verifying the frontend, which is the ask-first case.
  - Any other URL (github.com, external docs, a vendor dashboard, a remote dev deploy, any site) →
    ALLOWED. Ordinary browsing is not frontend verification, so it must not be blocked (the over-block
    that made this guard too restrictive: posting screenshots to a PR on github.com was denied). A
    remote deploy needs a deploy first, so it is browsing, not a silent local auto-verify.
  - `navigate_page` back / forward / reload (no URL) → ALLOWED. It re-navigates an already-open page,
    never a fresh launch of the local app.

Gating the launch entry points is enough: the other tools (screenshot, click, snapshot) are inert
without a page open, so blocking the local-app launch enforces the rule without carpet-blocking the
whole server or the whole web.

Override (for the LOCAL-app case): CLAUDE_ALLOW_BROWSER=1 — set it when the user said yes, when they
asked for browser verification / screenshots, or inside a skill that carries their standing
authorization; or the ~/.claude/.browser-authorized sentinel an authorized browser skill drops and
removes at teardown. Fails OPEN on anything malformed — a guard that breaks the session gets switched
off.
"""

import json
import os
import sys
from urllib.parse import urlparse

# The chrome-devtools tools that open or navigate a page. Suffixes, matched against the tool name.
LAUNCH_TOOLS = ("new_page", "navigate_page")


def _is_local_app_url(url: str) -> bool:
    """True when the URL is the local app under verification — the only thing this guard gates.

    Matches the hosts a locally-run or dev-previewed frontend is reached on. Everything else is
    ordinary browsing (github.com, docs, dashboards) and is never gated.
    """
    try:
        host = (urlparse(url).hostname or "").lower()
    except Exception:
        return False
    if not host:
        return False
    if host in ("localhost", "127.0.0.1", "0.0.0.0", "::1"):
        return True
    # A subdomained localhost (foo.localhost). A remote dev-deploy preview is a normal URL, not the
    # local app, so it is treated as browsing and never gated here.
    if host.endswith(".localhost"):
        return True
    return False


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

    tool_input = payload.get("tool_input") or {}
    url = tool_input.get("url") if isinstance(tool_input, dict) else None
    # No URL (a back/forward/reload) or a non-local URL (browsing the web) is not frontend
    # verification — allow it. Only a launch/navigate to the LOCAL app is gated below.
    if not isinstance(url, str) or not _is_local_app_url(url):
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
                f"Blocked: {tool} would open the LOCAL app ({url}) to verify a frontend change. "
                "rules/process.md says don't auto-verify a frontend change in the browser — ask the "
                "user first when the work is done.\n"
                "If they said yes, asked for screenshots / browser verification, or a skill carries "
                "their standing authorization (e.g. the ship-report test phase), set "
                "CLAUDE_ALLOW_BROWSER=1 for the session, or touch ~/.claude/.browser-authorized (the "
                "sentinel an authorized browser skill sets). Browsing a non-local URL (github.com, "
                "docs) is never gated; static checks (grep, reading rendered output, layout math) "
                "never need this."
            ),
        }
    }))
    return 0


if __name__ == "__main__":
    sys.exit(main())
