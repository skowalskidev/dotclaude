#!/usr/bin/env python3
"""Read-only git facts for a skill's dynamic-context (`!`) lines, one plain command per fact.

Claude Code refuses a dynamic-context line in a worktree-isolated agent when it names git in a compound
form (command substitution, `||` chains, pipes, variables in git's arguments): "names git in a form too
complex to verify that it stays inside the worktree". A skill then fails to load at all. Each fact here
is one subcommand, so the skill line names no git and stays a single literal command:

    !`python3 ~/.claude/bin/skill-context.py origin`
    !`python3 ~/.claude/bin/skill-context.py diff-scope`

Every git call runs in the current directory, reads only, and never writes a ref or config.
hooks/config-contract.test.py (skill-context-lines-load-in-isolated-worktrees) holds every sk skill's
`!` lines to this shape and runs each one inside a linked worktree.
"""

from __future__ import annotations

import subprocess
import sys


def git(*args: str) -> str | None:
    try:
        result = subprocess.run(["git", *args], capture_output=True, text=True, timeout=10, check=False)
    except (OSError, subprocess.TimeoutExpired):
        return None
    return result.stdout.strip() if result.returncode == 0 else None


def origin() -> str:
    return git("remote", "get-url", "origin") or "(no git remote)"


def diff_scope() -> str:
    base = None
    for ref in ("origin/master", "origin/main"):
        base = git("merge-base", ref, "HEAD")
        if base:
            break
    base = base or "HEAD~1"
    stat = git("diff", "--stat", base + "...HEAD")
    if stat is None:
        return "(no diff scope)"
    lines = stat.splitlines()
    return lines[-1].strip() if lines else "(no changes against %s)" % base[:12]


FACTS = {"origin": origin, "diff-scope": diff_scope}


def main(argv: list[str]) -> int:
    if len(argv) != 1 or argv[0] not in FACTS:
        print("usage: skill-context.py {%s}" % "|".join(FACTS), file=sys.stderr)
        return 2
    print(FACTS[argv[0]]())
    return 0


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))
