#!/usr/bin/env python3
"""Regression tests for hooks/worktree-path-guard.py. Run by hooks/config-contract.test.py."""
import json
import os
import subprocess
import sys
import tempfile
from pathlib import Path

GUARD = Path(__file__).resolve().parent / "worktree-path-guard.py"
FAILS = []


def decide(tool, file_path, cwd, live):
    env = dict(os.environ, CLAUDE_LIVE_CONFIG_ROOT=str(live))
    p = subprocess.run([sys.executable, str(GUARD)], input=json.dumps(
        {"tool_name": tool, "tool_input": {"file_path": str(file_path)}, "cwd": str(cwd)}),
        capture_output=True, text=True, env=env)
    if p.returncode != 0:
        FAILS.append(f"guard exited {p.returncode}: {p.stderr}")
    out = p.stdout.strip()
    return json.loads(out)["hookSpecificOutput"]["permissionDecision"] if out else "allow"


def expect(label, got, want):
    if got != want:
        FAILS.append(f"{label}: expected {want}, got {got}")


with tempfile.TemporaryDirectory() as tmp:
    live = Path(tmp) / "live"
    (live / "rules").mkdir(parents=True)
    (live / "work").mkdir()
    (live / ".gitignore").write_text("work/\nprojects/\n.claude/\n")
    subprocess.run(["git", "init", "-q", str(live)], check=True)
    other = Path(tmp) / "elsewhere"
    other.mkdir()

    expect("tracked live file, outside session", decide("Edit", live / "rules/a.md", other, live), "deny")
    expect("new tracked live file", decide("Write", live / "skills/x/SKILL.md", other, live), "deny")
    expect("relative path from the live cwd", decide("Edit", "rules/a.md", live, live), "deny")
    expect("ignored work/ area", decide("Write", live / "work/sk-work/a.md", other, live), "allow")
    expect("ignored auto-memory", decide("Write", live / "projects/p/memory/m.md", other, live), "allow")
    expect("config worktree under live", decide(
        "Edit", live / ".claude/worktrees/config-update-x/rules/a.md", other, live), "allow")
    expect("outside the live checkout", decide("Edit", other / "rules/a.md", other, live), "allow")
    expect("non-edit tool", decide("Read", live / "rules/a.md", other, live), "allow")
    link = Path(tmp) / "link"
    link.symlink_to(live)
    expect("symlinked path into live", decide("Edit", link / "rules/a.md", other, live), "deny")

    # The original check still asks for a main-checkout edit from a project worktree.
    repo = Path(tmp) / "repo"
    wt = repo / ".claude/worktrees/w"
    wt.mkdir(parents=True)
    expect("main checkout from worktree", decide("Edit", repo / "src/a.ts", wt, live), "ask")
    expect("own worktree", decide("Edit", wt / "src/a.ts", wt, live), "allow")

    p = subprocess.run([sys.executable, str(GUARD)], input="not json", capture_output=True, text=True)
    expect("malformed payload fails open", p.stdout.strip() or "allow", "allow")

if FAILS:
    print("\n".join(FAILS))
    sys.exit(1)
print("worktree-path-guard: all cases pass")
