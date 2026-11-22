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
  - an installer that loads one itself: `session-auto-resume.py install`.

Override: CLAUDE_ALLOW_DAEMON=1 in the ENVIRONMENT the Claude session was started with, which only
the user sets. A `CLAUDE_ALLOW_DAEMON=1 ...` prefix inside the command does NOT pass: the agent types
the command, so an inline prefix would let it approve its own gated install (rules/self-healing-config.md
§ Safeguard changes). Fails OPEN on anything malformed — a guard that breaks the session gets switched off.
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
    # An installer that calls launchctl itself hides the verb from the patterns above, so it is named.
    (re.compile(r"\bsession-auto-resume\.py\s+install\b"),
     "installs the hourly auto-resume LaunchAgent (persistent scheduled job)"),
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
                        "specific persistent process, they run the command in their own terminal or "
                        "start the session with CLAUDE_ALLOW_DAEMON=1 in its environment; an inline "
                        "CLAUDE_ALLOW_DAEMON=1 prefix in the command is not accepted. Remove it AND its "
                        "registration when the task is done, unless they asked for it to stay installed."
                    ),
                }
            }))
            return 0
    return 0


if __name__ == "__main__":
    sys.exit(main())
