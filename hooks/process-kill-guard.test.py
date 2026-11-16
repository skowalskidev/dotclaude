#!/usr/bin/env python3
"""
Both directions for hooks/process-kill-guard.py: a guard is assumed vacuous until it has been seen to
fail, and assumed harmful until it has been seen NOT to fire on an owned kill or on text that merely
names a command.

Drives the hook the way the harness does (a tool_use JSON payload on stdin). Nothing is run or
signalled: every command below is a string the guard only parses.
"""

import json
import os
import subprocess
import sys
from pathlib import Path

GUARD = Path(__file__).parent / "process-kill-guard.py"

MUST_FIRE = [
    # the incident and its spellings
    ("the incident", 'pkill -f "local-capacity.py run"'),
    ("incident with a shared bin path", "pkill -f ~/.claude/bin/local-capacity.py"),
    ("incident with an absolute shared bin path", "pkill -f /Users/me/.claude/bin/local-capacity.py"),
    ("shared bin tool by stem", "pkill -f bin/port-slot"),
    ("shared hooks dir", 'pkill -f "$HOME/.claude/hooks"'),
    # bare names and path-free patterns
    ("pkill node", "pkill node"),
    ("pkill -f vitest", "pkill -f vitest"),
    ("pkill -9 -f next", "pkill -9 -f next"),
    ("pkill -KILL node", "pkill -KILL node"),
    ("pkill -SIGTERM -f next-server", "pkill -SIGTERM -f next-server"),
    ("pkill clustered -fi", "pkill -fi Vitest"),
    ("pkill --signal TERM -f x", "pkill --signal TERM -f x"),
    ("pkill -f regex with one slash", 'pkill -f "node .*/vitest"'),
    ("pkill -f single segment", "pkill -f /node"),
    ("pkill without -f on a path", "pkill /tmp/run.1/server"),
    ("pkill -f system install path", "pkill -f /opt/homebrew/bin/node"),
    ("pkill -f usr path", "pkill -f /usr/local/bin/node"),
    ("pkill -f $HOME alone", 'pkill -f "$HOME"'),
    ("pkill -f $TMPDIR alone", 'pkill -f "$TMPDIR"'),
    ("pkill -u selects a whole user", "pkill -u me"),
    ("pkill absolute binary", "/usr/bin/pkill -f vitest"),
    # killall
    ("killall node", "killall node"),
    ("killall -9 node", "killall -9 node"),
    ("killall Simulator", "killall Simulator"),
    # wrappers, chains and nesting
    ("sudo pkill", "sudo pkill node"),
    ("sudo -u root pkill", "sudo -u root pkill -f vitest"),
    ("bash -c", "bash -c 'pkill -f vitest'"),
    ("bash -lc double-quoted", 'bash -lc "killall node"'),
    ("sh -c with chain inside", "sh -c 'cd /tmp && pkill node'"),
    ("eval", "eval 'pkill -f vitest'"),
    ("after &&", "cd /tmp && pkill -f vitest"),
    ("after ;", "echo stop; pkill node"),
    ("after ||", "false || killall node"),
    ("after a pipe", "echo x | pkill -f vitest"),
    ("in a subshell", "(pkill node)"),
    ("in a substitution", 'echo "$(pkill node)"'),
    ("timeout prefix", "timeout 5 pkill node"),
    ("env prefix", "FOO=1 env pkill node"),
    ("nohup prefix", "nohup killall node"),
    ("stderr silenced", "pkill -f vitest 2>/dev/null || true"),
    # pgrep feeding kill
    ("pgrep piped to xargs kill", 'pgrep -f "local-capacity.py run" | xargs kill'),
    ("pgrep piped to kill -9 via xargs", "pgrep node | xargs kill -9"),
    ("kill of a pgrep substitution", "kill $(pgrep -f vitest)"),
    ("kill -9 of a pgrep substitution", 'kill -9 "$(pgrep node)"'),
    # every process you own
    ("kill -9 -1", "kill -9 -1"),
    ("kill -- -1", "kill -- -1"),
    ("kill -s KILL -1", "kill -s KILL -1"),
]

MUST_NOT_FIRE = [
    # the owned-pid route
    ("kill a pid", "kill 12345"),
    ("kill -9 a pid", "kill -9 12345"),
    ("kill -TERM a pid", "kill -TERM 12345"),
    ("kill $!", "kill $!"),
    ("kill a pid variable", 'kill "$SERVER_PID"'),
    ("kill a process group", "kill -- -4321"),
    ("kill -s TERM pgid", "kill -s TERM -- -4321"),
    ("kill -1 as a signal to a pid", "kill -1 12345"),
    ("kill -l", "kill -l"),
    ("kill of a pidfile read", "kill $(cat /tmp/run.1/server.pid)"),
    # path-scoped pattern kills
    ("superspeed test teardown", 'pkill -f "$TMP" 2>/dev/null'),
    ("superspeed trap", "trap 'rm -rf \"$TMP\"; pkill -f \"$TMP\" 2>/dev/null || true' EXIT"),
    ("braced variable", 'pkill -f "${WORKDIR}"'),
    ("own temp dir literal", "pkill -f /tmp/superspeed-test.ab12/server"),
    ("own worktree path", "pkill -f /Users/me/dev/app/.claude/worktrees/fix-x/node_modules/.bin/next"),
    ("own path under $HOME", 'pkill -f "$HOME/dev/app/.next/server"'),
    ("own path variable plus suffix", 'pkill -9 -f "$WT/node_modules/.bin/vitest"'),
    ("path-scoped under bash -c", "bash -c 'pkill -f \"$TMP\"'"),
    ("path-scoped after &&", 'cd "$TMP" && pkill -f "$TMP"'),
    # pid-scoped selectors
    ("pkill -P own children", "pkill -P $$"),
    ("pkill -F pidfile", "pkill -F /tmp/run.1/server.pid"),
    ("pkill -g process group", "pkill -g 4321"),
    ("pkill --parent", "pkill --parent 4321"),
    # pgrep that kills nothing, or a scoped one that does
    ("pgrep alone", "pgrep -f vitest"),
    ("pgrep names", "pgrep -l node"),
    ("pgrep counted", "pgrep node | wc -l"),
    ("scoped pgrep feeding kill", 'pgrep -f "$TMP" | xargs kill'),
    ("killall -l lists signals", "killall -l"),
    # override, inline on that command
    ("inline override", "CLAUDE_ALLOW_PATTERN_KILL=1 pkill -f vitest"),
    # text that merely NAMES a command
    ("echo naming pkill", 'echo "never run pkill node"'),
    ("grep for pkill", 'grep -rn "pkill -f" bin'),
    ("heredoc naming killall", "cat > note.md <<'EOF'\nkillall node\npkill -f vitest\nEOF"),
    ("man page", "man pkill"),
    ("which", "which pkill"),
    ("python on the guard file", "python3 hooks/process-kill-guard.test.py"),
    ("a skill name containing kill", "bash ~/.claude/bin/kill-orphan-workers.sh --dry-run"),
    # robustness: fail open
    ("empty command", ""),
    ("malformed unterminated quote", "echo 'oops pkill"),
]


def run(command: str, env=None) -> str:
    payload = {"tool_name": "Bash", "tool_input": {"command": command}}
    p = subprocess.run([sys.executable, str(GUARD)], input=json.dumps(payload), text=True,
                       capture_output=True, env=env)
    if p.returncode != 0:
        return f"CRASH rc={p.returncode} {p.stderr[-200:]}"
    if not p.stdout.strip():
        return ""
    return json.loads(p.stdout)["hookSpecificOutput"]["permissionDecisionReason"]


def main() -> int:
    env = {k: v for k, v in os.environ.items() if k != "CLAUDE_ALLOW_PATTERN_KILL"}
    failures, passes = [], 0
    for label, cmd in MUST_FIRE:
        reason = run(cmd, env)
        ok = (reason and not reason.startswith("CRASH") and "kill <pid>" in reason
              and "dev-server-hygiene.md § Private process inspection" in reason
              and "CLAUDE_ALLOW_PATTERN_KILL=1" in reason)
        if ok:
            passes += 1
        else:
            failures.append(f"MUST FIRE: {label}: {cmd!r} -> {reason[:120]!r}")
    for label, cmd in MUST_NOT_FIRE:
        reason = run(cmd, env)
        if not reason:
            passes += 1
        else:
            failures.append(f"MUST NOT FIRE: {label}: {cmd!r} -> {reason[:120]!r}")
    # The environment override passes a command that would otherwise fire.
    if not run("pkill node", {**env, "CLAUDE_ALLOW_PATTERN_KILL": "1"}):
        passes += 1
    else:
        failures.append("ENV OVERRIDE: CLAUDE_ALLOW_PATTERN_KILL=1 did not allow pkill node")
    # Non-Bash tools and a garbage payload are never touched.
    for raw in ('{"tool_name": "Read", "tool_input": {"command": "pkill node"}}', "not json"):
        p = subprocess.run([sys.executable, str(GUARD)], input=raw, text=True, capture_output=True, env=env)
        if p.returncode == 0 and not p.stdout.strip():
            passes += 1
        else:
            failures.append(f"MUST FAIL OPEN: {raw[:40]!r} -> rc={p.returncode} out={p.stdout[:80]!r}")
    for f in failures:
        print(f)
    print(f"{passes} pass, {len(failures)} fail")
    return 1 if failures else 0


if __name__ == "__main__":
    sys.exit(main())
