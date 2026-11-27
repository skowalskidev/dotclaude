#!/usr/bin/env python3
"""Stop and PostToolUse hook: the drafting session owns landing its config-update/* branch.

PostToolUse (Bash): a `git worktree add ... -b config-update/<slug>` claims the branch for this session.
Stop: when the session ends (its last message gives the archive line) while it owns an unlanded
config-update/* branch with no recorded blocker, the end is blocked; a normal task turn never is,
because config work belongs to the end-of-session learning. The block is naming the exact commands that end it (land with bin/config-land-check.py, or record a blocker
with its next action, or a supersede with evidence). Loop safety: at most MAX_BLOCKS blocks per set of
owned branches, then it lets the turn end. Delegated workers return results and are never blocked.
"""
import json
import os
import re
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "bin"))
import config_branches as cb  # noqa: E402

MAX_BLOCKS = 3
ARCHIVE_LINE = "You can archive this session"
WORKTREE_ADD = re.compile(r"git\b[^\n;&|]*\bworktree\s+add\b[^\n;&|]*?\s-b\s+(config-update/[A-Za-z0-9._-]+)")


def state_file(session):
    root = Path(os.environ.get("CLAUDE_CONFIG_STATE", str(Path.home() / ".claude" / "state"))) / "config-branch-gate"
    root.mkdir(parents=True, exist_ok=True)
    return root / re.sub(r"[^A-Za-z0-9._-]", "", session)


def main():
    payload = json.loads(sys.stdin.read() or "{}")
    session = re.sub(r"[^A-Za-z0-9._-]", "", str(payload.get("session_id", ""))) or "unknown"
    root = os.environ.get("CLAUDE_CONFIG_ROOT", str(Path.home() / ".claude"))
    if payload.get("hook_event_name") == "PostToolUse" or payload.get("tool_name"):
        found = WORKTREE_ADD.search(str((payload.get("tool_input") or {}).get("command", "")))
        if found and session != "unknown":
            cb.claim(root, found.group(1), session)
        return 0
    if os.environ.get("AGENT_DELEGATED_WORKER") == "1" or session == "unknown":
        return 0
    cb.heartbeat(root, session)
    if ARCHIVE_LINE not in str(payload.get("last_assistant_message") or ""):
        return 0  # a task turn: config landing waits for the session's end
    owned = cb.stop_gate(root, session)
    marker = state_file(session)
    if not owned:
        marker.unlink(missing_ok=True)
        return 0
    key = ",".join(sorted(owned))
    count = 0
    if marker.exists():
        old_key, _, old_count = marker.read_text().partition("\t")
        count = int(old_count or 0) if old_key == key else 0
    if count >= MAX_BLOCKS:
        return 0
    marker.write_text(f"{key}\t{count + 1}")
    names = "\n".join(f"  {b}" for b in owned)
    reason = (
        "This session drafted config-update branches that are not on origin/main, and a drafted rule that "
        "never lands never takes effect:\n" + names + "\nLand each now, before the archive line: "
        "then `python3 ~/.claude/bin/config-land-check.py --root <worktree> --diff`, read it, `--reviewed <sha256>`. "
        "If something outside your control blocks it, record the blocker and its next action:\n"
        "  python3 ~/.claude/bin/config_branches.py block <branch> \"<blocker; next action>\"\n"
        "or, when a landed change replaces it:\n"
        "  python3 ~/.claude/bin/config_branches.py supersede <branch> \"<evidence: landed sha or PR>\"\n"
        "Another session adopts an unlanded branch after " + str(cb.ADOPT_AFTER_HOURS) + " h idle."
    )
    print(json.dumps({"decision": "block", "reason": reason}))
    return 0


if __name__ == "__main__":
    sys.exit(main())
