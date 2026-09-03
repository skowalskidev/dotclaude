#!/usr/bin/env python3
"""
ASK before ONE thing: an Edit/Write from inside a git WORKTREE that targets a file in the
MAIN checkout (or a DIFFERENT worktree) of the same repo, instead of this worktree's copy.

WHY THIS EXISTS

rules/process.md § "Git worktree discipline" says: when operating in a worktree, use the
WORKTREE path prefix for every file op — exploration agents and tool results often report the
MAIN repo's absolute paths, and using those silently edits the wrong checkout. That is a written
rule with nothing mechanical behind it, and it bit a real session: fixes were written to the main
checkout by its absolute path, passed a build+test run in the worktree (which never saw them), and
had to be moved back. This hook is the backstop — it catches the wrong-checkout edit at the moment
it happens, before the edit lands, so the agent re-issues it against the worktree path.

WHAT IS FLAGGED, AND WHAT IS DELIBERATELY NOT

Flagged (permissionDecision "ask", NOT a hard deny — occasionally a main-checkout edit from a
worktree IS intentional): the session cwd is under `<main>/.claude/worktrees/<name>/`, and the
target resolves under the MAIN checkout root but OUTSIDE this worktree — i.e. into the main
checkout's own tree, or into a sibling worktree.

NOT flagged, on purpose:
  - not in a worktree at all (cwd has no `/.claude/worktrees/<name>`): the main checkout IS the
    workspace, so every edit is correct;
  - a target under THIS worktree (the correct case);
  - a target outside the repo entirely — ~/.claude config (its own guard covers it), /tmp
    scratch, anything else;
  - reads, and any non-edit tool.

SEATBELT, NOT A WALL

"ask" surfaces the wrong-checkout edit to you; you allow the rare intentional one and redirect the
accidental one. It fails OPEN on any malformed input or when git/paths can't be resolved: a guard
that breaks the session gets switched off, and a guard that is off protects nothing.
"""

import json
import os
import re
import sys

EDIT_TOOLS = {"Edit", "Write", "MultiEdit", "NotebookEdit"}

# `<main>/.claude/worktrees/<name>` — capture the main checkout root and this worktree's root.
WORKTREE_RE = re.compile(r"^(?P<main>.*?)/\.claude/worktrees/(?P<name>[^/]+)")


def target_path(payload: dict):
    ti = payload.get("tool_input", {})
    if not isinstance(ti, dict):
        return None
    p = ti.get("file_path") or ti.get("notebook_path")
    if not isinstance(p, str) or not p:
        return None
    return p


def _under(path: str, root: str) -> bool:
    """True when `path` is `root` or sits beneath it (prefix match on a path boundary)."""
    if path == root:
        return True
    return path.startswith(root.rstrip("/") + "/")


def main() -> int:
    try:
        payload = json.load(sys.stdin)
    except Exception:
        return 0  # Never break the session on a malformed payload.

    if payload.get("tool_name") not in EDIT_TOOLS:
        return 0

    cwd = payload.get("cwd") or os.getcwd()
    m = WORKTREE_RE.match(cwd)
    if not m:
        return 0  # Not operating inside a worktree — every checkout edit is the right one.
    worktree_root = m.group(0)          # <main>/.claude/worktrees/<name>
    main_root = m.group("main")         # the main checkout root

    raw = target_path(payload)
    if not raw:
        return 0
    # Resolve relative targets against the session cwd (those already point INTO the worktree, the
    # correct case). abspath, not realpath: don't chase a worktree's symlinked node_modules etc.
    fp = raw if os.path.isabs(raw) else os.path.join(cwd, raw)
    fp = os.path.normpath(fp)

    if _under(fp, worktree_root):
        return 0  # Correct: editing this worktree.
    if not _under(fp, main_root):
        return 0  # Outside the repo (~/.claude, /tmp, …) — not this guard's business.

    # Under the main root but not this worktree → the wrong checkout (main tree or a sibling worktree).
    print(
        json.dumps({
            "hookSpecificOutput": {
                "hookEventName": "PreToolUse",
                "permissionDecision": "ask",
                "permissionDecisionReason": (
                    f"This session runs inside the worktree:\n  {worktree_root}\n"
                    f"but this edit targets a file OUTSIDE it, in the main checkout (or a sibling "
                    f"worktree):\n  {fp}\n\n"
                    "That is the wrong-checkout trap (rules/process.md § Git worktree discipline): "
                    "tool results report the MAIN repo's absolute paths, so an edit meant for the "
                    "worktree silently lands in the main checkout and the worktree's build/tests "
                    "never see it. Re-issue the edit against the worktree path:\n"
                    f"  {worktree_root}/<same relative path>\n\n"
                    "Allow only if you truly mean to edit that other checkout."
                ),
            }
        })
    )
    return 0


if __name__ == "__main__":
    sys.exit(main())
