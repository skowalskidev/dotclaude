#!/usr/bin/env python3
"""Read-only git facts a skill asks its worker to run from the PR checkout, one plain command per fact.

    cd <PR checkout> && python3 ~/.claude/bin/skill-context.py origin
    cd <PR checkout> && python3 ~/.claude/bin/skill-context.py diff-scope

sk skills carry no dynamic-context (`!`) line: Claude Code refused any of them in a worktree-isolated
agent ("names git in a form too complex", reproduced 26 Nov 2026 with a plain python3 line), and a `!`
line runs in the session cwd, not the PR checkout. Every git call runs in the current directory, reads
only, and never writes a ref or config. hooks/config-contract.test.py
(skill-context-lines-load-in-isolated-worktrees) holds that.
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
