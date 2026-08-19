#!/usr/bin/env python3
"""
Deny THREE git mistakes Claude makes that no other layer catches:

  0. `gh pr merge` — merging a PR into the remote default branch. This is the action that once
     merged 8 PRs (two on red CI) into master off a general "merge everything, no loose ends".
     `git-commit-guard` covered `git push` to main/master, but `gh pr merge` contains neither "git"
     nor "push" so it slipped straight through. A general instruction ("merge everything" / "proceed"
     / "continue") is NEVER a yes for a SPECIFIC merge; confirm the PR and verify CI is actually
     green, or set CLAUDE_ALLOW_PR_MERGE=1 once the user has confirmed THIS merge.

  1. Committing or pushing on the default branch (main / master). rules/process.md: "If on the
     default branch, create a branch first", and feedback_no_master_commits: never commit/push to
     master without your confirmation. Branch first, or set CLAUDE_ALLOW_MAIN_COMMIT=1 — in the
     hook's env OR prefixed inline on the command — when you have confirmed this exact commit/push.

  2. `git commit -m` (or a heredoc). references/git-pr-deploy.md makes `git commit -F <file>` the
     ONLY sanctioned form: the shell interprets `-m "…"` and heredoc bodies — backticks run, $VAR
     expands, unmatched quotes break the parse — and it fails SILENTLY, committing with the content
     mangled. It is a recidivism rule (it happened a third time in one session on a message that
     "felt too short to bother with"), so this is a hard block, not a nudge.

WHY A PreToolUse BASH GUARD, NOT A git hook

A commit-msg hook sees only the final message, so it cannot tell `-m` from `-F` — the distinction
this rule turns on. And `Bash(git commit:*)` sub-matchers are known to misfire in Claude Code
(anthropics/claude-code#36389), so like the other guards here this matches the plain "Bash" tool and
parses the command itself. It fails OPEN on anything malformed: a guard that breaks the session gets
switched off.
"""

import json
import os
import re
import subprocess
import sys

# Split on shell separators so each command is judged on its own.
SEGMENT_RE = re.compile(r"(?:\|\||&&|;|\||\n)")

DEFAULT_BRANCHES = {"main", "master"}

# Inline-message flags on `git commit`. Written to NOT match `--amend` / `--no-edit` (no `-m`):
#  - a short-flag cluster containing m: -m, -am, -sm  (single dash, m among the letters)
#  - the long form --message
INLINE_M_RE = re.compile(r"(?:^|\s)-[a-zA-Z]*m[a-zA-Z]*(?:[\s=]|$)|--message\b")
HEREDOC_RE = re.compile(r"<<-?\s*['\"]?\w")


def segments(command: str):
    return [s.strip() for s in SEGMENT_RE.split(command) if s.strip()]


def _git(cwd: str, *args: str) -> str:
    try:
        r = subprocess.run(
            ["git", *args], cwd=cwd or None,
            capture_output=True, text=True, timeout=5,
        )
        return r.stdout.strip() if r.returncode == 0 else ""
    except Exception:
        return ""


def current_branch(cwd: str) -> str:
    return _git(cwd, "rev-parse", "--abbrev-ref", "HEAD")


def is_config_repo(cwd: str) -> bool:
    """The ~/.claude config repo commits to main by design (via /sk:claude-config-sync), so the
    default-branch protection does not apply there."""
    top = _git(cwd, "rev-parse", "--show-toplevel")
    if not top:
        return False
    try:
        return os.path.realpath(top) == os.path.realpath(os.path.expanduser("~/.claude"))
    except Exception:
        return False


def deny(reason: str) -> int:
    print(json.dumps({
        "hookSpecificOutput": {
            "hookEventName": "PreToolUse",
            "permissionDecision": "deny",
            "permissionDecisionReason": reason,
        }
    }))
    return 0


def main() -> int:
    try:
        payload = json.load(sys.stdin)
    except Exception:
        return 0

    if payload.get("tool_name") != "Bash":
        return 0
    command = payload.get("tool_input", {}).get("command", "")
    if not isinstance(command, str) or ("git" not in command and "gh " not in command):
        return 0
    cwd = payload.get("cwd") or os.getcwd()

    for seg in segments(command):
        is_commit = re.search(r"\bgit\b.*\bcommit\b", seg) is not None
        is_push = re.search(r"\bgit\b.*\bpush\b", seg) is not None
        is_gh_merge = re.search(r"\bgh\s+pr\s+merge\b", seg) is not None
        if not (is_commit or is_push or is_gh_merge):
            continue

        # 0. `gh pr merge` merges into the remote default branch — the action that once merged 8 PRs
        # (two on red CI) into master off a general "merge everything". A general instruction is never
        # a yes for a specific merge, so block unless the user confirmed THIS merge (the flag in the
        # hook's env OR prefixed inline). The deny message is what tells Claude to get that yes.
        if is_gh_merge:
            allow_merge = os.environ.get("CLAUDE_ALLOW_PR_MERGE") == "1" or bool(
                re.search(r"\bCLAUDE_ALLOW_PR_MERGE=1\b", command)
            )
            if not allow_merge:
                return deny(
                    "Blocked: `gh pr merge` merges a PR into the remote default branch. A general "
                    "'merge everything' / 'proceed' / 'continue' is NEVER authorization for a "
                    "specific merge — get the user's explicit yes naming THIS PR, and verify CI is "
                    "genuinely green first (`gh pr view <n> --json statusCheckRollup`: every required "
                    "check SUCCESS, none FAILURE/PENDING — never a truncated summary). Never "
                    "admin-override a required review; prefer handing the merge to the user. If the "
                    "user confirmed THIS merge, prefix CLAUDE_ALLOW_PR_MERGE=1."
                )

        # 1. Default-branch protection (the config repo is exempt — it lives on main by design).
        # The override counts whether the flag is in the hook's OWN env OR prefixed inline on the
        # command (`CLAUDE_ALLOW_MAIN_COMMIT=1 git push …`). The inline form is what the deny message
        # tells the user to use, and Claude only adds it once the user has confirmed THIS push; a bare
        # push with no flag stays blocked, so accidental default-branch pushes are still caught.
        allow_main = os.environ.get("CLAUDE_ALLOW_MAIN_COMMIT") == "1" or bool(
            re.search(r"\bCLAUDE_ALLOW_MAIN_COMMIT=1\b", command)
        )
        if not allow_main and not is_config_repo(cwd):
            branch = current_branch(cwd)
            names_default = re.search(r"(?:^|\s|:)(main|master)\b", seg) is not None
            if branch in DEFAULT_BRANCHES or (is_push and names_default):
                verb = "push to" if is_push else "commit on"
                where = branch or "main/master"
                return deny(
                    f"Blocked: {verb} the default branch ({where}). "
                    "rules/process.md says branch first; never commit or push to main/master "
                    "without the user's confirmation.\n"
                    "Create a feature branch (git switch -c <branch>) and redo it there. If the user "
                    "confirmed this exact commit/push to the default branch, prefix the command with "
                    "CLAUDE_ALLOW_MAIN_COMMIT=1 (e.g. `CLAUDE_ALLOW_MAIN_COMMIT=1 git push origin main`)."
                )

        # 2. Commit must use -F <file>, never -m or a heredoc.
        if is_commit and os.environ.get("CLAUDE_ALLOW_COMMIT_M") != "1":
            if INLINE_M_RE.search(seg) or HEREDOC_RE.search(seg):
                return deny(
                    "Blocked: `git commit` with -m or a heredoc. references/git-pr-deploy.md makes "
                    "`git commit -F <file>` the only sanctioned form — the shell interprets -m and "
                    "heredoc bodies (backticks, $VAR, quotes) and mangles the message SILENTLY.\n"
                    "Write the message to a file with the Write tool, then `git commit -F <file>`. "
                    "This is a recidivism rule; override only with CLAUDE_ALLOW_COMMIT_M=1 if the user "
                    "explicitly asked for -m here."
                )
    return 0


if __name__ == "__main__":
    sys.exit(main())
