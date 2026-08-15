#!/usr/bin/env python3
"""
Deny installing a PERSISTENT background process without asking.

rules/process.md: "Never install a persistent background process (login item, LaunchAgent/
LaunchDaemon, cron, always-on watcher) without asking first." An idle daemon burning a core, or a
login item pointing at a deleted script, is exactly the residue that rule exists to prevent — and it
is the kind of change Claude makes reaching for "keep it running", not something you asked for.

WHAT IT BLOCKS (the install/enable verbs only — listing and removing stay allowed):
  - crontab installing a table (crontab <file>, crontab -, crontab -e); `crontab -l` passes.
  - launchctl load / bootstrap / enable / kickstart / start.
  - systemctl [--user] enable / start.
  - writing a plist into ~/Library/LaunchAgents or /Library/LaunchDaemons.

Override: CLAUDE_ALLOW_DAEMON=1 when you have asked for that specific persistent process. Fails
OPEN on anything malformed — a guard that breaks the session gets switched off.
"""

import json
import os
import re
import sys

# Each pattern is an INSTALL/ENABLE action. Deliberately not matching list/status/remove verbs.
PATTERNS = [
    (re.compile(r"\bcrontab\b(?!\s+-l\b)(?:\s+-|\s+\S)"),
     "installs a crontab (persistent scheduled job)"),
    (re.compile(r"\blaunchctl\s+(?:load|bootstrap|enable|kickstart|start)\b"),
     "loads a launchd service (persistent background process)"),
    (re.compile(r"\bsystemctl\s+(?:--user\s+)?(?:enable|start)\b"),
     "enables a systemd unit (persistent background process)"),
    (re.compile(r"(?:>|>>|\bcp\b|\bmv\b|\btee\b|\bln\b|\binstall\b|\bcat\b)[^\n]*Library/Launch(?:Agents|Daemons)"),
     "writes a plist into a LaunchAgents/LaunchDaemons directory"),
]


def main() -> int:
    try:
        payload = json.load(sys.stdin)
    except Exception:
        return 0

    if payload.get("tool_name") != "Bash":
        return 0
    command = payload.get("tool_input", {}).get("command", "")
    if not isinstance(command, str):
        return 0
    if os.environ.get("CLAUDE_ALLOW_DAEMON") == "1":
        return 0

    for rx, what in PATTERNS:
        if rx.search(command):
            print(json.dumps({
                "hookSpecificOutput": {
                    "hookEventName": "PreToolUse",
                    "permissionDecision": "deny",
                    "permissionDecisionReason": (
                        f"Blocked: this {what}. rules/process.md forbids installing a persistent "
                        "background process without asking the user first, and prefers on-demand / "
                        "event-driven over always-on.\n"
                        "Ask the user first, with what it would run and why. If they asked for this "
                        "specific persistent process, set CLAUDE_ALLOW_DAEMON=1 — and remove it AND "
                        "its registration when the task is done."
                    ),
                }
            }))
            return 0
    return 0


if __name__ == "__main__":
    sys.exit(main())
