#!/usr/bin/env python3
"""Bash guard: no polling of background output, and no identical check on identical inputs.

KPIS.md speed SLIs, from the 2026-11-27 transcript audit (26 sessions, 894 requests):
  - 487 Bash calls looped on a background task's output file. The harness re-invokes the session when
    the task ends, so the loop only burns a turn: PreToolUse DENIES it.
  - checks reran with no edit in between. As Turborepo and Nx cache a task by the hash of its inputs,
    a check is keyed by (command segment, directory, HEAD, hash of the working-tree diff and the
    CONTENTS of untracked files). PreToolUse records the key as pending; PostToolUse marks it complete
    only when the call finished uninterrupted in the foreground. A second run of a COMPLETED key in the
    same session is denied, so an interrupted, timed-out or refused run never blocks its rerun.
    Stateful checks (browser, simulator, e2e) are never cached, as Turborepo's `cache: false`.
    CLAUDE_RERUN_OK=1 in front of a command reruns a flaky check.

What counts as a check, a poll and a stateful check is bin/kpi.py's (check_segments, is_poll,
STATEFUL), so the guard and the KPI metric cannot disagree. State: state/check-cache/<session>.json,
pruned after 2 days. Fails OPEN on anything malformed.
"""
import hashlib
import importlib.util
import json
import os
import re
import subprocess
import sys
import time
from pathlib import Path

STATE = Path(os.environ.get("CLAUDE_CHECK_CACHE_DIR") or Path.home() / ".claude" / "state" / "check-cache")
KEEP_S = 2 * 86400
MAX_HASHED = 1 << 20  # untracked files above 1 MB are keyed by size and mtime
OVERRIDE = re.compile(r"(^|[\s;&|(])CLAUDE_RERUN_OK=1\b")
_spec = importlib.util.spec_from_file_location("_kpi", Path(__file__).resolve().parents[1] / "bin" / "kpi.py")
kpi = importlib.util.module_from_spec(_spec)
_spec.loader.exec_module(kpi)


def deny(reason):
    print(json.dumps({"hookSpecificOutput": {"hookEventName": "PreToolUse", "permissionDecision": "deny",
                                             "permissionDecisionReason": reason}}))
    return 0


def git(cwd, *args):
    r = subprocess.run(["git", "-C", cwd, *args], capture_output=True, timeout=10)
    return r.stdout if r.returncode == 0 else None


def fingerprint(cwd):
    """(repo top, sha of HEAD + tracked diff + untracked contents), or None outside a repo."""
    top = git(cwd, "rev-parse", "--show-toplevel")
    if not top:
        return None
    top = top.decode().strip()
    h = hashlib.sha256((git(top, "rev-parse", "HEAD") or b"").strip())
    h.update(b"\0" + (git(top, "diff", "HEAD", "--binary") or b""))
    for name in filter(None, (git(top, "ls-files", "--others", "--exclude-standard", "-z") or b"").split(b"\0")):
        full = os.path.join(top, name.decode(errors="replace"))
        h.update(b"\0" + name)
        try:
            st = os.stat(full)
            if st.st_size <= MAX_HASHED:
                with open(full, "rb") as f:
                    h.update(hashlib.sha256(f.read()).digest())
            else:
                h.update(f"{st.st_size}:{st.st_mtime_ns}".encode())
        except OSError:
            pass
    return top, h.hexdigest()


def keys_for(cmd, cwd):
    out = []
    for seg_cwd, seg in kpi.check_segments(cmd):
        if kpi.STATEFUL.search(seg):
            continue
        where = os.path.normpath(os.path.join(cwd, os.path.expanduser(seg_cwd))) if seg_cwd else cwd
        found = fingerprint(where)
        if found:
            out.append(hashlib.sha256("\0".join((found[0], where, seg, found[1])).encode()).hexdigest())
    return out


def load(path):
    try:
        data = json.loads(path.read_text())
        return data if isinstance(data, dict) and "done" in data else {"done": {}, "pending": {}}
    except (OSError, ValueError):
        return {"done": {}, "pending": {}}


def save(path, data, now):
    data["done"] = {k: v for k, v in data["done"].items() if now - v < KEEP_S}
    data["pending"] = {k: v for k, v in data["pending"].items() if now - v.get("at", 0) < KEEP_S}
    tmp = path.with_suffix(f".{os.getpid()}.tmp")
    tmp.write_text(json.dumps(data))
    os.replace(tmp, path)


def main():
    try:
        payload = json.loads(sys.stdin.read() or "{}")
    except ValueError:
        return 0
    if payload.get("tool_name") != "Bash":
        return 0
    tin = payload.get("tool_input") or {}
    cmd = str(tin.get("command", ""))
    post = payload.get("hook_event_name") == "PostToolUse" or "tool_response" in payload
    if not post and kpi.is_poll(cmd):
        return deny("Polling a background task's output file is refused: the harness re-invokes this "
                    "session when the task finishes (KPIS.md: polls of background output = 0). End the "
                    "turn or do other work; read the output file once after the notification.")
    session = re.sub(r"[^A-Za-z0-9._-]", "", str(payload.get("session_id", "")))
    call = str(payload.get("tool_use_id", ""))
    if not session or OVERRIDE.search(cmd) or not kpi.check_segments(cmd):
        return 0
    STATE.mkdir(parents=True, exist_ok=True)
    path, now = STATE / f"{session}.json", time.time()
    data = load(path)
    if post:
        entry = data["pending"].pop(call, None) if call else None
        response = payload.get("tool_response") or {}
        if entry and not tin.get("run_in_background") and not (isinstance(response, dict) and response.get("interrupted")):
            for key in entry.get("keys", []):
                data["done"][key] = now
        save(path, data, now)
        return 0
    try:
        keys = keys_for(cmd, str(payload.get("cwd") or os.getcwd()))
    except (OSError, subprocess.SubprocessError):
        return 0
    if not keys:
        return 0
    if all(key in data["done"] for key in keys):
        ago = int((now - max(data["done"][k] for k in keys)) / 60)
        return deny(f"This exact check finished {ago} min ago on identical inputs (same HEAD, same working "
                    "tree, same untracked contents): its result still stands, so reuse it (KPIS.md: repeated "
                    "identical checks = 0). Change a file first, or prefix CLAUDE_RERUN_OK=1 to rerun a flaky check.")
    if call:
        data["pending"][call] = {"at": now, "keys": keys}
    save(path, data, now)
    for old in STATE.glob("*.json"):
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
