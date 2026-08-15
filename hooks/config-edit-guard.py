#!/usr/bin/env python3
"""
Deny ONE thing: an Edit/Write to a TRACKED config file under ~/.claude that is NOT running
inside the /sk:claude-config-update flow.

WHY THIS EXISTS

~/.claude is your config as instructions: rules, skills, hooks, references, contracts.
`/sk:claude-config-update` is the sanctioned way to change any of it — it routes the change
to the right home, previews it, gates on your yes, and keeps the contracts/routing tests
in step. A hand-edit skips all of that, which is exactly how a change lands with a missing
contract entry, a missing routing scenario, or an unverified figure in it. So this hook makes
the skill the ONLY path: it blocks a config Edit/Write unless the flow set its sentinel.

WHAT IS GATED, AND WHAT IS DELIBERATELY NOT

Gated: an Edit/Write whose target resolves under ~/.claude into one of the config roots
(rules, references, skills, work, hooks, bin, connectors, contracts, dotfiles) or a top-level
config file (CLAUDE.md, AGENTS.md, README.md, settings*.json, .gitignore, any top-level *.md).

NOT gated, on purpose: everything else under ~/.claude is RUNTIME STATE, not config-as-
instructions — `projects/` (Claude's own memory files and transcripts), `logs/`, `sessions/`,
`todos/`, `cache/`, and the rest. Blocking those would break the memory system, which writes
files under projects/ with the Write tool. Anything outside ~/.claude is never gated.

THE AUTHORIZATION

Allowed when EITHER holds:
  - the sentinel ~/.claude/.config-edit-authorized exists — the /sk:claude-config-update flow
    touches it right after your yes (Step 6) and removes it at the end (Step 7); or
  - CLAUDE_CONFIG_EDIT=1 is in the environment — the documented override for a deliberate
    direct edit you asked for, or a headless batch.

SEATBELT, NOT A WALL

A caller can `touch` the sentinel itself, so this does not stop a determined actor — it stops
the CASUAL hand-edit, the one that skips the gate without meaning to. That is the whole job.
It fails OPEN on any malformed input: a guard that breaks the session gets switched off, and a
guard that is off protects nothing.
"""

import json
import os
import sys
from pathlib import Path

EDIT_TOOLS = {"Edit", "Write", "MultiEdit", "NotebookEdit"}

# The config-as-instructions surface. First path component under ~/.claude.
GATED_ROOTS = {
    "rules", "references", "skills", "work",
    "hooks", "bin", "connectors", "contracts", "dotfiles",
}
# Top-level files that are config even though they sit at the root.
GATED_TOP_FILES = {"CLAUDE.md", "AGENTS.md", "README.md", ".gitignore"}

CLAUDE_DIR = Path(os.path.expanduser("~/.claude")).resolve()
SENTINEL = CLAUDE_DIR / ".config-edit-authorized"


def target_path(payload: dict):
    ti = payload.get("tool_input", {})
    if not isinstance(ti, dict):
        return None
    p = ti.get("file_path") or ti.get("notebook_path")
    if not isinstance(p, str) or not p:
        return None
    return p


def is_gated(raw: str) -> bool:
    """True when the target is a tracked config file under ~/.claude."""
    try:
        resolved = Path(os.path.expanduser(raw)).resolve()
    except Exception:
        return False
    try:
        rel = resolved.relative_to(CLAUDE_DIR)
    except ValueError:
        return False  # not under ~/.claude
    parts = rel.parts
    if not parts:
        return False
    if len(parts) == 1:  # a top-level file
        name = parts[0]
        return name in GATED_TOP_FILES or name.endswith(".md") or (
            name.startswith("settings") and name.endswith(".json"))
    return parts[0] in GATED_ROOTS


def authorized() -> bool:
    return SENTINEL.exists() or os.environ.get("CLAUDE_CONFIG_EDIT") == "1"


def main() -> int:
    try:
        payload = json.load(sys.stdin)
    except Exception:
        return 0  # Never break the session on a malformed payload.

    if payload.get("tool_name") not in EDIT_TOOLS:
        return 0
    raw = target_path(payload)
    if not raw or not is_gated(raw) or authorized():
        return 0

    print(
        json.dumps({
            "hookSpecificOutput": {
                "hookEventName": "PreToolUse",
                "permissionDecision": "deny",
                "permissionDecisionReason": (
                    f"Blocked: `{raw}` is a tracked ~/.claude config file, and config changes "
                    "must go through /sk:claude-config-update, not an ad-hoc edit.\n"
                    "That skill routes the change to its right home, previews it, gates on your "
                    "yes, and keeps the contract + routing tests in step — the steps a hand-edit "
                    "skips. Invoke /sk:claude-config-update and state the change; it sets the "
                    "authorization sentinel after you confirm.\n"
                    "For a deliberate one-off direct edit: `touch ~/.claude/.config-edit-authorized` "
                    "first (or set CLAUDE_CONFIG_EDIT=1), edit, then remove it — and say you did."
                ),
            }
        })
    )
    return 0


if __name__ == "__main__":
    sys.exit(main())
