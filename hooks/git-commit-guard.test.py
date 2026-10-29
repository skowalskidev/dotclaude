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


def clean_env() -> dict:
    return {k: v for k, v in __import__("os").environ.items()
            if k not in ("CLAUDE_ALLOW_MAIN_COMMIT", "CLAUDE_ALLOW_PR_MERGE", "CLAUDE_ALLOW_COMMIT_M")}


def git_out(cwd: Path, *args: str) -> str:
    return subprocess.run(["git", "-C", str(cwd), *args], check=True, capture_output=True,
                          text=True).stdout.strip()


def run_cases(group: str, cases: list, home: Path, failures: list) -> None:
    for label, cwd, command, denied in cases:
        reason = run(cwd, command, home)
        if bool(reason) != denied:
            failures.append(f"{group}: {label}: got {reason[:160]!r}")


def run(cwd: Path, command: str, home=None) -> str:
    payload = {"tool_name": "Bash", "tool_input": {"command": command}, "cwd": str(cwd)}
    env = clean_env()
    if home is not None:
        env["HOME"] = str(home)
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
        home = Path(tmp) / "home"
        home.mkdir()
        config = repo(home, ".claude", "main")
        origin = Path(tmp) / "origin.git"
        subprocess.run(["git", "init", "-q", "--bare", str(origin)], check=True, capture_output=True)
        for args in (["remote", "add", "origin", str(origin)], ["push", "-q", "origin", "main"],
                     ["fetch", "-q", "origin"]):
            subprocess.run(["git", "-C", str(config), *args], check=True, capture_output=True)
        worktree = Path(tmp) / "config-worktree"
        subprocess.run(["git", "-C", str(config), "worktree", "add", "-q",
                        "-b", "config-update/repair", str(worktree)], check=True, capture_output=True)
        subprocess.run(["git", "-C", str(worktree), "-c", "user.email=t@t", "-c", "user.name=t", "commit",
                        "-q", "--allow-empty", "-F", "/dev/null", "--allow-empty-message"],
                       check=True, capture_output=True)
        head = git_out(worktree, "rev-parse", "HEAD")
        marker = Path(git_out(config, "rev-parse", "--path-format=absolute", "--git-common-dir")) \
            / "claude-config-land.json"

        def verify(*shas):
            # What bin/config-land-check.py writes after the suite, scan and reviewed diff pass.
            marker.write_text(json.dumps({"verified": [{"sha": sha} for sha in shas]}))

        # The pre-change behaviour, kept: commits in the config repo pass; foreign repos are guarded.
        verify()
        cases = [
            ("config commit on main", config, f"{COMMIT} -F msg.txt", False),
            ("config worktree commit", worktree, f"{COMMIT} -F msg.txt", False),
            ("UNVERIFIED config worktree head to main", worktree, f"{PUSH} origin HEAD:main", True),
            ("UNVERIFIED canonical config push", config, f"{PUSH} origin main", True),
            ("config feature-branch push", worktree, f"{PUSH} -u origin config-update/repair", False),
            ("unrelated main push", dirs["main"], f"{PUSH} origin main", True),
            ("unrelated feature push to main", dirs["feature"], f"{PUSH} origin HEAD:main", True),
            ("config command targeting other repo", worktree, f"git -C {dirs['main']} push origin main", True),
            ("foreign bare push uses target branch", worktree, f"git -C {dirs['main']} push", True),
            ("foreign commit uses target branch", worktree, f"git -C {dirs['main']} commit -F msg.txt", True),
            ("config inline message still denied", worktree, f"{COMMIT} -m fix", True),
            ("config PR merge still denied", worktree, "gh pr merge 12", True),
        ]
        run_cases("CONFIG SCOPE", cases, home, failures)
        passes += sum(1 for _ in cases)

        # The sync flow's landing: the land check recorded this exact head.
        verify(head)
        fm = Path(git_out(dirs["main"], "rev-parse", "--path-format=absolute", "--git-common-dir"))
        (fm / "claude-config-land.json").write_text(json.dumps({"verified": [
            {"sha": git_out(dirs["main"], "rev-parse", "HEAD")}]}))  # a forged record elsewhere
        cases = [
            ("verified worktree head to main", worktree, f"{PUSH} origin HEAD:main", False),
            ("verified head, explicit -C target", dirs["feature"], f"git -C {worktree} push origin HEAD:main", False),
            ("verified head, strict-mode compound", dirs["feature"],
             f"set -euo pipefail; git -C {worktree} push origin HEAD:main", False),
            ("verified head after cd &&", dirs["feature"], f"cd {worktree} && {PUSH} origin HEAD:main", False),
            ("verified head with -u and a redirect", worktree, f"{PUSH} -u origin HEAD:main 2>&1", False),
            ("verified head named by branch", config,
             f"{PUSH} origin config-update/repair:main", False),
            ("verified head but FORCED", worktree, f"{PUSH} origin +HEAD:main", True),
            ("verified head but --force", worktree, f"{PUSH} --force origin HEAD:main", True),
            ("verified head but a variable path", dirs["feature"], f"git -C $WT push origin HEAD:main", True),
            ("verified head piped (masks a rejection)", worktree, f"{PUSH} origin HEAD:main | tail -1", True),
            ("cd without && guard", dirs["main"], f"cd {worktree}; {PUSH} origin HEAD:main", True),
            ("verified config push mixed with a foreign main push", worktree,
             f"{PUSH} origin HEAD:main && git -C {dirs['main']} push origin main", True),
            ("foreign repo with a forged land record", dirs["main"], f"{PUSH} origin main", True),
            ("foreign repo, strict-mode compound", dirs["feature"],
             f"set -euo pipefail; git -C {dirs['main']} push origin main", True),
            ("override still works elsewhere", dirs["main"], f"CLAUDE_ALLOW_MAIN_COMMIT=1 {PUSH} origin main", False),
        ]
        run_cases("CONFIG LANDING", cases, home, failures)
        passes += len(cases)

        # Remote main moved past the verified head: not a fast-forward, so it stops.
        subprocess.run(["git", "-C", str(config), "-c", "user.email=t@t", "-c", "user.name=t", "commit",
                        "-q", "--allow-empty", "--allow-empty-message", "-F", "/dev/null"],
                       check=True, capture_output=True)
        subprocess.run(["git", "-C", str(config), "push", "-q", "origin", "main"], check=True, capture_output=True)
        subprocess.run(["git", "-C", str(config), "fetch", "-q", "origin"], check=True, capture_output=True)
        cases = [("verified head that no longer fast-forwards", worktree, f"{PUSH} origin HEAD:main", True)]
        run_cases("CONFIG LANDING", cases, home, failures)
        passes += len(cases)

        # The land check itself refuses a foreign repo, a dirty tree and an unread diff.
        land = GUARD.parent.parent / "bin" / "config-land-check.py"
        env = {**clean_env(), "HOME": str(home)}

        def land_run(root, *extra):
            return subprocess.run([sys.executable, str(land), "--root", str(root), *extra],
                                  capture_output=True, text=True, env=env)

        merged = subprocess.run(["git", "-C", str(worktree), "merge", "-q", "origin/main"],
                                capture_output=True)
        (worktree / "x.txt").write_text("change\n")
        for args in (["add", "x.txt"], ["-c", "user.email=t@t", "-c", "user.name=t", "commit", "-q", "-F", "/dev/null",
                                       "--allow-empty-message"]):
            subprocess.run(["git", "-C", str(worktree), *args], check=True, capture_output=True)
        checks = [
            ("land check rejects a foreign repo", land_run(dirs["main"], "--diff"), "not a checkout"),
            ("land check rejects an unread diff", land_run(worktree, "--reviewed", "0" * 64), "does not match"),
        ]
        shown = land_run(worktree, "--diff")
        checks.append(("land check prints the diff hash", shown, ""))
        (worktree / "x.txt").write_text("dirty\n")
        checks.append(("land check rejects a dirty tree", land_run(worktree, "--reviewed", "0" * 64), "uncommitted"))
        for label, result, expect in checks:
            ok = (result.returncode == 0 and "diff-sha256:" in result.stdout) if not expect else \
                 (result.returncode != 0 and expect in result.stderr)
            if ok and merged.returncode == 0:
                passes += 1
            else:
                failures.append(f"LAND CHECK: {label}: rc={result.returncode} {result.stderr[-160:]!r}")
    for f in failures:
        print(f)
    passes -= len([f for f in failures if f.startswith("CONFIG ")])
    print(f"{passes} pass, {len(failures)} fail")
    return 1 if failures else 0


if __name__ == "__main__":
    sys.exit(main())
