#!/usr/bin/env python3
"""PreToolUse Bash: no polling of background output, and no identical check on identical inputs.

KPIS.md speed metrics, from the 2026-11-27 transcript audit (26 sessions, 894 requests):
  - 487 Bash calls looped on a background task's output file (until/while/sleep over
    .../tasks/<id>.output). The harness already re-invokes the session when the task ends, so the
    loop only burns a turn and a timeout: DENY it, naming the notification.
  - in 168 of 230 requests that ran checks, the same check ran again with no edit in between. A check
    on unchanged inputs repeats its answer. As Nx and Turborepo cache a task by the hash of its inputs,
    this hook keys a check by (command, repo HEAD, hash of the working-tree diff and untracked files)
    and DENIES the second run in the same session. A changed file is a new key, so a rerun after a fix
    passes. A flaky check is rerun with CLAUDE_RERUN_OK=1 in front of the command.

State: state/check-cache/<session>.json, the keys seen this session (pruned after 2 days).
Fails OPEN on anything malformed: a guard that blocks legitimate work costs more than a repeat run.
"""
import hashlib
import json
import os
import re
import subprocess
import sys
import time
from pathlib import Path

STATE = Path(os.environ.get("CLAUDE_CHECK_CACHE_DIR") or Path.home() / ".claude" / "state" / "check-cache")
KEEP_S = 2 * 86400
CHECK = re.compile(r"\.test\.(py|ts|js|sh)\b|\bvitest\b|deno (task )?test|\bplaywright\b|\bpytest\b|\bjest\b"
                   r"|(npm|pnpm|yarn|bun) (run )?test\b|xcodebuild\b[^|;&]*\btest|test-without-building"
                   r"|swift test|go test|cargo test|\btsc\b|typecheck|deno (check|lint)|\beslint\b")
TASK_OUTPUT = re.compile(r"/tasks/[A-Za-z0-9_-]+\.output")
WAIT_LOOP = re.compile(r"\b(until|while)\b|\bsleep\b")
OVERRIDE = re.compile(r"(^|[\s;&|(])CLAUDE_RERUN_OK=1\b")


def deny(reason):
    print(json.dumps({"hookSpecificOutput": {"hookEventName": "PreToolUse", "permissionDecision": "deny",
                                             "permissionDecisionReason": reason}}))
    return 0


def git(cwd, *args):
    r = subprocess.run(["git", "-C", cwd, *args], capture_output=True, timeout=10)
    return r.stdout if r.returncode == 0 else None


def fingerprint(cwd):
    """(repo top, HEAD, sha of tracked diff + untracked names and sizes), or None outside a repo."""
    top = git(cwd, "rev-parse", "--show-toplevel")
    if not top:
        return None
    top = top.decode().strip()
    head = (git(top, "rev-parse", "HEAD") or b"").strip()
    diff = git(top, "diff", "HEAD", "--binary") or b""
    untracked = git(top, "ls-files", "--others", "--exclude-standard", "-z") or b""
    parts = []
    for name in filter(None, untracked.split(b"\0")):
        full = os.path.join(top, name.decode(errors="replace"))
        parts.append(name + b"\0" + str(os.path.getsize(full) if os.path.isfile(full) else 0).encode())
    sizes = b"\0".join(parts)
    return top, hashlib.sha256(head + b"\0" + diff + b"\0" + sizes).hexdigest()


def main():
    try:
        payload = json.loads(sys.stdin.read() or "{}")
    except ValueError:
        return 0
    if payload.get("tool_name") != "Bash":
        return 0
    cmd = str((payload.get("tool_input") or {}).get("command", ""))
    if TASK_OUTPUT.search(cmd) and WAIT_LOOP.search(cmd):
        return deny("Polling a background task's output file is refused: the harness re-invokes this "
                    "session when the task finishes (KPIS.md: polls of background output = 0). End the "
                    "turn or do other work; read the output file once after the notification.")
    if not CHECK.search(cmd) or OVERRIDE.search(cmd):
        return 0
    session = re.sub(r"[^A-Za-z0-9._-]", "", str(payload.get("session_id", ""))) or ""
    cwd = str(payload.get("cwd") or os.getcwd())
    if not session:
        return 0
    try:
        found = fingerprint(cwd)
    except (OSError, subprocess.SubprocessError):
        return 0
    if not found:
        return 0
    top, inputs = found
    normalized = re.sub(r"\s+", " ", cmd.strip())
    key = hashlib.sha256("\0".join((top, normalized, inputs)).encode()).hexdigest()
    STATE.mkdir(parents=True, exist_ok=True)
    path = STATE / f"{session}.json"
    now = time.time()
    try:
        seen = json.loads(path.read_text())
    except (OSError, ValueError):
        seen = {}
    if key in seen:
        ago = int((now - seen[key]) / 60)
        return deny(f"This exact check already ran {ago} min ago on identical inputs (same HEAD, same "
                    "working-tree diff): its result still stands, so reuse it (KPIS.md: repeated identical "
                    "checks = 0). Change a file first, or prefix CLAUDE_RERUN_OK=1 to rerun a flaky check.")
    seen = {k: v for k, v in seen.items() if now - v < KEEP_S}
    seen[key] = now
    tmp = path.with_suffix(f".{os.getpid()}.tmp")
    tmp.write_text(json.dumps(seen))
    os.replace(tmp, path)
    for old in STATE.glob("*.json"):  # other sessions' stale files
        try:
            if now - old.stat().st_mtime > KEEP_S:
                old.unlink()
        except OSError:
            pass
    return 0


if __name__ == "__main__":
    try:
        sys.exit(main())
    except Exception:  # noqa: BLE001 - fail open
        sys.exit(0)
