#!/usr/bin/env python3
"""
Guard TWO wrong-checkout edits. ASK before an Edit/Write from inside a git WORKTREE that targets a
file in the MAIN checkout (or a DIFFERENT worktree) of the same repo. DENY an Edit/Write into a
tracked file of the live ~/.claude config checkout, from any session (second check, below).

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
  - a target outside the repo entirely — ~/.claude config (the second check below covers it), /tmp
    scratch, anything else;
  - reads, and any non-edit tool.

SECOND CHECK: THE LIVE CONFIG CHECKOUT (deny, from any session)

Several sessions repair ~/.claude at once. An Edit/Write straight into the live checkout's tracked
files puts their changes in one shared working tree, where they clash and one session's commit
sweeps up another's WIP. Every tracked config change goes through its own `config-update/<slug>`
worktree (skills/sk/skills/claude-config-update Step 5). So a target under the live checkout
(realpath of ~/.claude, or $CLAUDE_LIVE_CONFIG_ROOT for tests) that is NOT under its
`.claude/worktrees/` and NOT git-ignored there is denied, with the worktree command to run instead.
A deny, not an ask: the redirect is always available, so the agent re-routes with no prompt to Simon.
Ignored paths stay open (auto-memory under projects/, the untracked work/ and sk-work skills,
.context, plans, settings.local.json), and so does every worktree or Conductor workspace of the repo.

SEATBELT, NOT A WALL

"ask" surfaces the wrong-checkout edit to you; you allow the rare intentional one and redirect the
accidental one. It fails OPEN on any malformed input or when git/paths can't be resolved: a guard
that breaks the session gets switched off, and a guard that is off protects nothing.
"""

import json
import os
import re
import subprocess
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


def live_config_denial(fp: str):
    """The deny reason when `fp` is a tracked file in the live config checkout; None otherwise."""
    live = os.path.realpath(os.environ.get("CLAUDE_LIVE_CONFIG_ROOT") or os.path.expanduser("~/.claude"))
    real = os.path.realpath(fp)
    if not _under(real, live) or _under(real, os.path.join(live, ".claude", "worktrees")):
        return None
    rel = os.path.relpath(real, live)
    try:
        ignored = subprocess.run(["git", "-C", live, "check-ignore", "-q", "--", rel],
                                 capture_output=True, timeout=5)
    except Exception:
        return None  # Fail open when git can't answer.
    if ignored.returncode != 1:
        return None  # 0 = ignored (personal/untracked area), 128 = not a git repo or git error.
    return (
        f"This edit targets a tracked file in the LIVE config checkout:\n  {real}\n\n"
        "Parallel sessions share that working tree, so direct edits there clash. Make the change "
        "in this task's own config worktree instead (claude-config-update Step 5):\n"
        "  git -C ~/.claude fetch origin\n"
        "  git -C ~/.claude worktree add ~/.claude/.claude/worktrees/config-update-<slug> "
        "-b config-update/<slug> origin/main\n"
        f"then edit  ~/.claude/.claude/worktrees/config-update-<slug>/{rel}  and land it with "
        "/sk:claude-config-sync."
    )


def main() -> int:
    try:
        payload = json.load(sys.stdin)
    except Exception:
        return 0  # Never break the session on a malformed payload.

    if payload.get("tool_name") not in EDIT_TOOLS:
        return 0

    cwd = payload.get("cwd") or os.getcwd()
    raw = target_path(payload)
    if raw:
        fp0 = os.path.normpath(raw if os.path.isabs(raw) else os.path.join(cwd, raw))
        reason = live_config_denial(fp0)
        if reason:
            print(json.dumps({"hookSpecificOutput": {"hookEventName": "PreToolUse",
                                                     "permissionDecision": "deny",
                                                     "permissionDecisionReason": reason}}))
            return 0
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
