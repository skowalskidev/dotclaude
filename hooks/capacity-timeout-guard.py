#!/usr/bin/env python3
"""
Deny a capacity-gated `run_in_background` Bash task whose timeout ends before its queue and run can.

references/dev-server-hygiene.md § Waiting on a background job: a background task's `timeout` must
cover its summed `--wait-min` plus `--max-min` plus cleanup, and a command whose sum reaches the
2-hour background cap runs detached instead. Prose alone did not hold: capacity-queued native runs
started as background tasks on the 30-minute default were killed while still waiting for admission,
and each kill left a lease that blocked the owner's next run. This guard is the mechanical backstop.

WHAT IT JUDGES: a Bash call with `run_in_background: true` whose shell runs `local-capacity.py run`
or `native-slot.sh run` (also inside sh/bash -c, eval, $(...), chains). Each run counts its literal
`--wait-min` (default 5) plus `--max-min` (default 60); a chain sums them.

WHAT IT DENIES:
  - a summed budget of 120 minutes or more (the background cap): launch it detached and poll its log;
  - a `timeout` (default 30 minutes when absent) below the summed budget plus 2 minutes of cleanup;
  - a non-literal `--wait-min`/`--max-min` (`"$W"`) unless the timeout is the 2-hour cap.

WHAT IT ALLOWS: foreground calls, text that merely names a command (a quoted string, heredoc body,
echo or grep), other local-capacity verbs, and the detached `start_new_session=True` launcher, which
returns at once. Parsing is shared with hooks/secret-echo-guard.py. No override: setting the timeout
or detaching is always possible. Fails OPEN on anything malformed.
"""

import importlib.util
import json
import os
import re
import sys
from pathlib import Path

HERE = Path(__file__).resolve().parent
SCRIPTS = {"local-capacity.py": "local-capacity.py", "native-slot.sh": "native-slot.sh"}
DEFAULT_WAIT_MIN = 5    # bin/local-capacity.py WAIT_SECONDS / 60 and bin/native-slot.sh wait_min
DEFAULT_MAX_MIN = 60    # --max-min default in both
CLEANUP_MIN = 2         # supervisor cleanup retries for up to 30 s, plus simulator shutdown
CAP_MS = 2 * 60 * 60 * 1000   # the Bash tool's longest run_in_background timeout
DEFAULT_MS = 30 * 60 * 1000   # the Bash tool's background default when `timeout` is absent
GLOBAL_VALUE_OPTS = {"--root"}


def _load_parser():
    spec = importlib.util.spec_from_file_location("secret_echo_guard", HERE / "secret-echo-guard.py")
    mod = importlib.util.module_from_spec(spec)  # type: ignore[arg-type]
    spec.loader.exec_module(mod)  # type: ignore[union-attr]
    return mod


def run_budget(words):
    """(script, minutes or None when non-literal) for a capacity `run` in these words, else None."""
    for i, word in enumerate(words):
        if os.path.basename(word) not in SCRIPTS:
            continue
        j = i + 1
        while j < len(words) and words[j].startswith("--") and words[j] != "--":
            j += 2 if words[j] in GLOBAL_VALUE_OPTS else 1
        if j >= len(words) or words[j] != "run":
            return None
        budget = {"--wait-min": float(DEFAULT_WAIT_MIN), "--max-min": float(DEFAULT_MAX_MIN)}
        k, literal = j + 1, True
        while k < len(words) and words[k] != "--":
            name, _, inline = words[k].partition("=")
            if name in budget:
                value = inline if inline else (words[k + 1] if k + 1 < len(words) else "")
                k += 1 if inline else 2
                try:
                    budget[name] = float(value)
                except ValueError:
                    literal = False
                continue
            k += 1
        return os.path.basename(word), (sum(budget.values()) if literal else None)
    return None


def detached_launcher(words):
    return any("start_new_session" in w for w in words)


def collect(P, cmds, found, depth=0):
    if depth > 6:
        return
    for cmd in cmds:
        words, _ = P.effective(cmd.texts())
        if words and os.path.basename(words[0]) in P.ECHOERS | P.FILTERS:
            continue
        if detached_launcher(words):
            continue
        hit = run_budget(words)
        if hit:
            found.append(hit)
        body = P.shell_body(words)
        if body:
            collect(P, P.parse(body), found, depth + 1)
        for inner in cmd.substs:
            collect(P, inner, found, depth + 1)


def verdict(command, background, timeout):
    """The deny reason for this Bash call, else None."""
    if not background or not re.search(r"(local-capacity\.py|native-slot\.sh)", command):
        return None
    P = _load_parser()
    found = []
    collect(P, P.parse(command), found)
    if not found:
        return None
    explicit = isinstance(timeout, (int, float)) and not isinstance(timeout, bool) and timeout > 0
    timeout_ms = timeout if explicit else DEFAULT_MS
    named = "timeout %d ms" % timeout_ms if explicit else "no timeout (the 30-minute background default)"
    if any(minutes is None for _, minutes in found):
        if timeout_ms >= CAP_MS:
            return None
        return ("a capacity run with a non-literal --wait-min/--max-min runs as a background task with %s; "
                "set timeout to %d (the 2-hour cap), or pass literal minutes" % (named, CAP_MS))
    total = sum(minutes for _, minutes in found)
    runs = ", ".join("%s run" % script for script, _ in found)
    if total >= CAP_MS / 60000:
        return ("%s sums to %g minutes of --wait-min plus --max-min, at or past the 2-hour background cap; "
                "launch it detached (start_new_session) and poll its log in bounded foreground waits"
                % (runs, total))
    need = min(CAP_MS, int((total + CLEANUP_MIN) * 60000))
    if timeout_ms >= need:
        return None
    return ("%s needs up to %g minutes (--wait-min plus --max-min) plus %d of cleanup, but runs as a "
            "background task with %s, which kills it while it still queues for capacity and leaves its "
            "lease behind; set timeout to at least %d" % (runs, total, CLEANUP_MIN, named, need))


def main() -> int:
    try:
        payload = json.load(sys.stdin)
        if payload.get("tool_name") != "Bash":
            return 0
        tool_input = payload.get("tool_input", {})
        command = tool_input.get("command", "")
        if not isinstance(command, str) or not command.strip():
            return 0
        why = verdict(command, tool_input.get("run_in_background") is True, tool_input.get("timeout"))
    except Exception:
        return 0  # fail open
    if not why:
        return 0
    print(json.dumps({
        "hookSpecificOutput": {
            "hookEventName": "PreToolUse",
            "permissionDecision": "deny",
            "permissionDecisionReason": (
                f"Blocked: {why}. references/dev-server-hygiene.md § Waiting on a background job: a "
                "background task's timeout covers its summed --wait-min plus --max-min plus cleanup, at "
                "most the 2-hour cap (7200000 ms); a longer budget runs detached."
            ),
        }
    }))
    return 0


if __name__ == "__main__":
    sys.exit(main())
