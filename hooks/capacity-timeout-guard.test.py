#!/usr/bin/env python3
"""
Both directions for hooks/capacity-timeout-guard.py: it must deny a capacity-gated background task
whose timeout ends before its queue and run can, and a foreground call whose timeout passes the 10-minute foreground cap, and must stay silent on
other foreground calls, adequate
timeouts, the detached launcher and text that merely names the command.

Drives the hook the way the harness does (a tool_use JSON payload on stdin). Nothing is run.
"""

import json
import subprocess
import sys
from pathlib import Path

GUARD = Path(__file__).parent / "capacity-timeout-guard.py"
LC = "python3 ~/.claude/bin/local-capacity.py"
NS = "~/.claude/bin/native-slot.sh"
HOUR = 3600000

# (label, command, run_in_background, timeout, reason fragment)
MUST_FIRE = [
    ("a foreground run expecting more than the 10-minute foreground cap is moved to a 30-minute background",
     f"{LC} run --owner s -- npm run build", False, HOUR, "set run_in_background"),
    ("the incident: default budget on the 30-minute default",
     f"{LC} run --owner s -- xcodebuild test", True, None, "set timeout to at least 4020000"),
    ("simulator test with --wait-min 60 --max-min 30 under a 60-minute timeout",
     f"{LC} run --owner s --simulator X --wait-min 60 --max-min 30 -- make test", True, HOUR,
     "set timeout to at least 5520000"),
    ("native-slot wrapper", f"{NS} run --for ui -- xcodebuild test", True, None, "native-slot.sh run"),
    ("equals form", f"{LC} run --owner s --wait-min=20 --max-min=20 -- x", True, 1800000, "at least 2520000"),
    ("global --root before run", f"{LC} --root /tmp/c run --owner s -- x", True, None, "at least 4020000"),
    ("a chain at the 2-hour cap", f"{LC} run --owner s --wait-min 30 --max-min 30 -- a && "
     f"{LC} run --owner s --wait-min 30 --max-min 30 -- b", True, 2 * HOUR, "launch it detached"),
    ("single run at the cap", f"{LC} run --owner s --wait-min 60 --max-min 60 -- x", True, 2 * HOUR,
     "launch it detached"),
    ("inside bash -c", f"bash -c '{LC} run --owner s -- x'", True, None, "set timeout"),
    ("after cd &&", f"cd /w && {LC} run --owner s --max-min 45 -- x", True, 1800000, "at least 3120000"),
    ("non-literal minutes", f'{LC} run --owner s --wait-min "$W" -- x', True, HOUR, "non-literal"),
]

MUST_PASS = [
    ("foreground run", f"{LC} run --owner s -- x", False, None),
    ("foreground run within the 10-minute foreground cap", f"{LC} run --owner s -- x", False, 600000),
    ("adequate timeout", f"{LC} run --owner s -- x", True, 4020000),
    ("adequate timeout, wrapper", f"{NS} run --for ui --wait-min 10 --max-min 40 -- x", True, 3120000),
    ("non-literal at the cap", f'{LC} run --owner s --max-min "$M" -- x', True, 2 * HOUR),
    ("status verb", f"{LC} status", True, None),
    ("echo names it", f'echo "{LC} run --owner s -- x"', True, None),
    ("grep names it", f'grep -n "local-capacity.py run" notes.md', True, None),
    ("detached launcher",
     "python3 -c 'import subprocess,sys; print(subprocess.Popen(sys.argv[2:], stdout=open(sys.argv[1],\"w\"), "
     "start_new_session=True).pid)' /tmp/log " + f"{LC} run --owner s --wait-min 60 --max-min 90 -- x", True, None),
    ("unrelated background command", "npm run dev", True, None),
]


def decide(command, background, timeout):
    tool_input = {"command": command, "run_in_background": background}
    if timeout is not None:
        tool_input["timeout"] = timeout
    out = subprocess.run([sys.executable, str(GUARD)], input=json.dumps({"tool_name": "Bash", "tool_input": tool_input}),
                         capture_output=True, text=True, timeout=10)
    if out.returncode != 0:
        return "error", out.stderr
    if not out.stdout.strip():
        return "allow", ""
    hook = json.loads(out.stdout)["hookSpecificOutput"]
    return hook["permissionDecision"], hook["permissionDecisionReason"]


def main() -> int:
    failures = []
    for label, command, background, timeout, fragment in MUST_FIRE:
        decision, reason = decide(command, background, timeout)
        if decision != "deny" or fragment not in reason:
            failures.append(f"MUST FIRE [{label}]: got {decision}: {reason}")
    for label, command, background, timeout in MUST_PASS:
        decision, reason = decide(command, background, timeout)
        if decision != "allow":
            failures.append(f"MUST PASS [{label}]: got {decision}: {reason}")
    malformed = subprocess.run([sys.executable, str(GUARD)], input="not json", capture_output=True, text=True)
    if malformed.returncode != 0 or malformed.stdout.strip():
        failures.append("malformed payload must fail open")
    for line in failures:
        print(line)
    print(f"capacity-timeout-guard: {len(MUST_FIRE) + len(MUST_PASS) + 1 - len(failures)} passed, "
          f"{len(failures)} failed")
    return 1 if failures else 0


if __name__ == "__main__":
    sys.exit(main())
