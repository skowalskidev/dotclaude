#!/usr/bin/env python3
"""Ownership records for config-update/* branches, so a drafted change cannot be lost.

A drafting session owns its branch until it lands. This module keeps one JSON record per branch in
<git-common-dir>/claude-config-branches/ (shared by every worktree) and answers three questions:

  stop-gate   which unlanded branches this session owns with no recorded blocker (the Stop hook blocks
              hand-back on them, the way the ship gate blocks an unrecorded PR head);
  adoptable   which unlanded branches have no live owner (idle longer than ADOPT_AFTER_HOURS), for the
              SessionStart note and the next config-touching session to adopt;
  records     claim, block (a blocker AND its next action), supersede (evidence) and adopt.

A branch counts as landed when origin/main contains it. Activity is the newer of the last commit and the
owner's last heartbeat; the Stop hook refreshes the heartbeat on every turn of the owning session.
"""
import argparse
import json
import os
import re
import subprocess
import sys
import time
from pathlib import Path

# 4 h: past the longest leased suite run plus its queue (65 min) with margin, and the cadence of the
# config repo's own fetch stamp; a live session's Stop hook refreshes the heartbeat every turn, so only a
# session idle for the whole window loses the claim, and adopting is a merge plus a validated landing.
ADOPT_AFTER_HOURS = 4
PREFIX = "config-update/"
RECORDS = "claude-config-branches"


def git(root, *args):
    r = subprocess.run(["git", "-C", str(root), *args], capture_output=True, text=True)
    return r.stdout.strip() if r.returncode == 0 else ""


def records_dir(root):
    common = git(root, "rev-parse", "--path-format=absolute", "--git-common-dir")
    return Path(common) / RECORDS


def record_path(root, branch):
    return records_dir(root) / (branch.replace("/", "__") + ".json")


def load(root, branch):
    try:
        return json.loads(record_path(root, branch).read_text())
    except (OSError, ValueError):
        return {}


def save(root, branch, data):
    path = record_path(root, branch)
    path.parent.mkdir(parents=True, exist_ok=True)
    tmp = path.with_suffix(".tmp")
    tmp.write_text(json.dumps(dict(data, branch=branch), indent=1))
    os.replace(tmp, path)


def unlanded(root):
    """config-update/* branches origin/main does not contain."""
    out = git(root, "for-each-ref", "--no-merged", "origin/main", "--format=%(refname:short)",
              f"refs/heads/{PREFIX}")
    return [b for b in out.splitlines() if b]


def last_activity(root, branch, now=None):
    committed = git(root, "log", "-1", "--format=%ct", branch)
    beat = load(root, branch).get("heartbeat", 0)
    return max(float(committed or 0), float(beat or 0))


def claim(root, branch, session, now=None, how="claimed"):
    now = now or time.time()
    data = load(root, branch)
    save(root, branch, {"session": session, "claimed_at": data.get("claimed_at", now), "heartbeat": now,
                        "status": "owned", "note": how})


def heartbeat(root, session, now=None):
    now = now or time.time()
    for branch in unlanded(root):
        data = load(root, branch)
        if data.get("session") == session:
            save(root, branch, dict(data, heartbeat=now))


def block(root, branch, session, reason, now=None):
    if len(reason.split()) < 4:
        raise ValueError("a blocker needs the blocker AND its next action, in at least 4 words")
    data = load(root, branch)
    save(root, branch, dict(data, session=data.get("session") or session, heartbeat=now or time.time(),
                            status="blocked", note=reason))


def supersede(root, branch, evidence, now=None):
    if len(evidence.split()) < 4:
        raise ValueError("superseding needs the evidence (the landed sha or PR that replaces it)")
    save(root, branch, dict(load(root, branch), heartbeat=now or time.time(), status="superseded",
                            note=evidence))


def stop_gate(root, session):
    """Branches this session owns that are unlanded and carry no blocker or supersede record."""
    return [b for b in unlanded(root)
            if load(root, b).get("session") == session and load(root, b).get("status", "owned") == "owned"]


def adoptable(root, hours=ADOPT_AFTER_HOURS, now=None, exclude_session=""):
    now = now or time.time()
    rows = []
    for branch in unlanded(root):
        data = load(root, branch)
        if data.get("status") == "superseded":
            continue
        if exclude_session and data.get("session") == exclude_session:
            continue
        idle = now - last_activity(root, branch)
        if idle > hours * 3600:
            rows.append((branch, idle / 3600.0, data.get("session", "none"), data.get("note", "")))
    return rows


def session_from_env():
    return re.sub(r"[^A-Za-z0-9._-]", "", os.environ.get("CLAUDE_CODE_SESSION_ID", ""))


def main(argv=None):
    ap = argparse.ArgumentParser(description=__doc__.split("\n")[0])
    ap.add_argument("--root", default=str(Path.home() / ".claude"))
    sub = ap.add_subparsers(dest="cmd", required=True)
    for name in ("claim", "adopt"):
        p = sub.add_parser(name)
        p.add_argument("branch")
        p.add_argument("--session", default="")
    for name in ("block", "supersede"):
        p = sub.add_parser(name)
        p.add_argument("branch")
        p.add_argument("text")
        p.add_argument("--session", default="")
    p = sub.add_parser("adoptable")
    p.add_argument("--hours", type=float, default=ADOPT_AFTER_HOURS)
    p.add_argument("--session", default="")
    sub.add_parser("status")
    a = ap.parse_args(argv)
    session = getattr(a, "session", "") or session_from_env() or "unknown"
    root = a.root
    try:
        if a.cmd in ("claim", "adopt"):
            claim(root, a.branch, session, how="adopted" if a.cmd == "adopt" else "claimed")
        elif a.cmd == "block":
            block(root, a.branch, session, a.text)
        elif a.cmd == "supersede":
            supersede(root, a.branch, a.text)
        elif a.cmd == "adoptable":
            for branch, idle, owner, note in adoptable(root, a.hours, exclude_session=a.session):
                print(f"{branch}\tidle {idle:.0f} h\towner {owner}\t{note}")
        else:
            for branch in unlanded(root):
                d = load(root, branch)
                print(f"{branch}\t{d.get('status', 'unclaimed')}\towner {d.get('session', 'none')}\t{d.get('note', '')}")
    except ValueError as error:
        print(f"config_branches: {error}", file=sys.stderr)
        return 2
    return 0


if __name__ == "__main__":
    sys.exit(main())
