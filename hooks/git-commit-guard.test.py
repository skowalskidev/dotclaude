#!/usr/bin/env python3
"""
Both directions for hooks/git-commit-guard.py: a guard is assumed vacuous until it has been seen to
fail, and assumed harmful until it has been seen NOT to fire on text that merely names a command.

Drives the hook the way the harness does (a tool_use JSON payload on stdin) from two throwaway git
repos, one on a feature branch and one on main. Nothing real is touched.

The MUST-NOT-FIRE block is the important half. The guard once matched the raw command text, so a
printf writing a note that quoted a push to main, and `python3 -m py_compile git-commit-guard.py`,
were both blocked. The guard judges what the shell RUNS: the command word, with quoted strings and
heredoc bodies masked. Widen it back into a text match and these fail first.
"""

import json
import subprocess
import sys
import tempfile
from pathlib import Path

GUARD = Path(__file__).parent / "git-commit-guard.py"
PUSH = "git " + "push"            # assembled so this file's own source is never a test case
COMMIT = "git " + "commit"

# (label, "feature"|"main", command, substring the deny reason must contain)
MUST_FIRE = [
    ("push to main from a feature branch", "feature", f"{PUSH} origin main", "push to the default branch (main)"),
    ("push names master", "feature", f"{PUSH} origin master", "(master)"),
    ("git -C <path> push to main", "feature", f"git -C /tmp/x push origin main", "(main)"),
    ("push after cd &&", "feature", f"cd /tmp && {PUSH} origin HEAD:main", "(main)"),
    ("env prefix that is not the override", "feature", f"FOO=1 {PUSH} origin main", "(main)"),
    ("commit on main", "main", f"{COMMIT} -F msg.txt", "commit on the default branch (main)"),
    ("bare push on main", "main", f"{PUSH}", "push to the default branch (main)"),
    ("gh pr merge", "feature", "gh pr merge 12 --squash", "gh pr merge"),
    ("commit -m", "feature", f'{COMMIT} -m "fix: thing"', "-m or a heredoc"),
    ("commit -am", "feature", f'{COMMIT} -am "fix"', "-m or a heredoc"),
    ("commit from a heredoc", "feature", f"{COMMIT} -F - <<'EOF'\nfix: thing\nEOF", "-m or a heredoc"),
]

MUST_NOT_FIRE = [
    ("a quoted note naming a push to main", "feature",
     f"printf -- '- next: Simon runs {PUSH} origin main; then verify\\n' > note.md"),
    ("a double-quoted echo naming commit -m", "feature", f'echo "use {COMMIT} -m never" > x'),
    ("a heredoc body naming a push to main", "feature",
     f"cat > note.md <<'EOF'\n{PUSH} origin main\n{COMMIT} -m x\nEOF"),
    ("python -m on a file named after the guard", "feature",
     "python3 -m py_compile ~/.claude/hooks/git-commit-guard.py"),
    ("grep for the merge command", "feature", 'grep -rn "gh pr merge" docs'),
    ("git log mentioning push and main", "feature", "git log --grep push main"),
    ("push to the feature branch", "feature", f"{PUSH} -u origin feature"),
    ("commit -F on a feature branch", "feature", f"{COMMIT} -F msg.txt"),
    ("amend no-edit", "feature", f"{COMMIT} --amend --no-edit"),
    ("confirmed push with the inline override", "feature", f"CLAUDE_ALLOW_MAIN_COMMIT=1 {PUSH} origin main"),
    ("confirmed merge with the inline override", "feature", "CLAUDE_ALLOW_PR_MERGE=1 gh pr merge 12"),
    ("malformed unterminated quote fails open", "feature", f"echo 'oops {PUSH} origin main"),
]


def repo(root: Path, name: str, branch: str) -> Path:
    d = root / name
    d.mkdir()
    for args in (["init", "-q", "-b", branch], ["-c", "user.email=t@t", "-c", "user.name=t",
                                                  "commit", "-q", "--allow-empty", "--allow-empty-message", "-F", "/dev/null"]):
        subprocess.run(["git", *args], cwd=d, check=True, capture_output=True)
    return d


def run(cwd: Path, command: str) -> str:
    payload = {"tool_name": "Bash", "tool_input": {"command": command}, "cwd": str(cwd)}
    env = {k: v for k, v in __import__("os").environ.items()
           if k not in ("CLAUDE_ALLOW_MAIN_COMMIT", "CLAUDE_ALLOW_PR_MERGE", "CLAUDE_ALLOW_COMMIT_M")}
    p = subprocess.run([sys.executable, str(GUARD)], input=json.dumps(payload), text=True,
                       capture_output=True, cwd=cwd, env=env)
    if not p.stdout.strip():
        return ""
    return json.loads(p.stdout)["hookSpecificOutput"]["permissionDecisionReason"]


def main() -> int:
    failures, passes = [], 0
    with tempfile.TemporaryDirectory() as tmp:
        dirs = {"feature": repo(Path(tmp), "f", "feature"), "main": repo(Path(tmp), "m", "main")}
        for label, where, cmd, expect in MUST_FIRE:
            reason = run(dirs[where], cmd)
            if reason and expect in reason:
                passes += 1
            else:
                failures.append(f"MUST FIRE: {label}: got {reason!r}")
        for label, where, cmd in MUST_NOT_FIRE:
            reason = run(dirs[where], cmd)
            if not reason:
                passes += 1
            else:
                failures.append(f"MUST NOT FIRE: {label}: {reason[:90]!r}")
    for f in failures:
        print(f)
    print(f"{passes} pass, {len(failures)} fail")
    return 1 if failures else 0


if __name__ == "__main__":
    sys.exit(main())
