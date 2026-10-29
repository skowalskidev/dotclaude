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
     The ~/.claude config repo is the one exception, and it is narrow: a commit there passes (it
     lives on main by design), and a push to its main passes only when every pushed head was
     verified by bin/config-land-check.py (contract suite, secret scan and a hash-bound diff review
     for that exact sha) and fast-forwards the remote main. That is how a validated config repair
     lands with no question under rules/self-healing-config.md, while an unverified head still stops.

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
import shlex
import subprocess
import sys

# Split on shell separators so each command is judged on its own. Runs on the MASKED command, so a
# separator inside quotes or a heredoc body never splits it.
SEGMENT_RE = re.compile(r"(?:\|\||&&|;|\||\n)")

# Tokens that can precede the real command word: `VAR=1 git push`, `sudo git …`, `( git … )`.
PREFIX_WORDS = {"sudo", "env", "command", "time", "nohup", "exec", "(", "{", "!", "then", "do", "else"}
ASSIGN_RE = re.compile(r"^[A-Za-z_][A-Za-z0-9_]*=")
# git global options that take a separate value: `git -C <path> push`.
GIT_OPTS_WITH_VALUE = {"-C", "-c", "--git-dir", "--work-tree", "--namespace", "--exec-path"}
HEREDOC_START_RE = re.compile(r"<<-?\s*(['\"]?)(\w+)\1")

DEFAULT_BRANCHES = {"main", "master"}

# Written by bin/config-land-check.py into the config repo's shared Git directory, so every worktree
# of that repo reads the same record. It lists head shas that passed the land checks.
LAND_MARKER = "claude-config-land.json"
# Push options that cannot change WHAT lands. Anything else (force, delete, mirror, all, tags,
# no-verify, a push option) leaves the config push on the ordinary confirmation path.
SAFE_PUSH_OPTS = {"-u", "--set-upstream", "-q", "--quiet", "-v", "--verbose", "--porcelain",
                  "--atomic", "--no-progress", "--progress"}
SHELL_SEPARATORS = {";", "&&", "||", "\n"}

# Inline-message flags on `git commit`. Written to NOT match `--amend` / `--no-edit` (no `-m`):
#  - a short-flag cluster containing m: -m, -am, -sm  (single dash, m among the letters)
#  - the long form --message
INLINE_M_RE = re.compile(r"(?:^|\s)-[a-zA-Z]*m[a-zA-Z]*(?:[\s=]|$)|--message\b")
# Matches the masked form too: mask() turns a quoted marker `<<'EOF'` into `<<''`.
HEREDOC_RE = re.compile(r"<<-?\s*(?:['\"]?\w|''|\"\")")


def mask(command: str) -> str:
    """Blank out quoted strings and heredoc bodies, keeping the quote marks and heredoc markers.

    The guard judges what the shell RUNS, not text a command carries: a printf writing a note that
    quotes a push command is a printf, and a heredoc body naming `git commit -m` is data. Matching
    the raw text blocked exactly that (a ledger note quoting a push). Fails open: an unterminated
    quote masks to the end, which can only hide a match, never invent one.
    """
    # Heredoc bodies first: everything after the marker's line up to the closing delimiter line.
    out, i = [], 0
    for m in HEREDOC_START_RE.finditer(command):
        if m.start() < i:
            continue
        nl = command.find("\n", m.end())
        if nl == -1:
            break
        end = re.compile(rf"^\s*{re.escape(m.group(2))}\s*$", re.M).search(command, nl + 1)
        out.append(command[i:nl + 1])
        i = end.start() if end else len(command)
    out.append(command[i:])
    text = "".join(out)

    res, quote, esc = [], None, False
    for ch in text:
        if quote:
            if quote == '"' and esc:
                esc = False
            elif quote == '"' and ch == "\\":
                esc = True
            elif ch == quote:
                quote = None
                res.append(ch)
            continue
        if ch in ("'", '"'):
            quote = ch
        res.append(ch)
    return "".join(res)


def segments(command: str):
    return [s.strip() for s in SEGMENT_RE.split(mask(command)) if s.strip()]


def command_words(seg: str) -> list:
    """The segment's words from the command word on, skipping env assignments and prefixes."""
    words = seg.split()
    while words and (words[0] in PREFIX_WORDS or ASSIGN_RE.match(words[0])):
        words = words[1:]
    return words


def git_subcommand(words: list) -> str:
    """`git -C x push origin main` -> 'push'. Empty when the command word is not git."""
    if not words or os.path.basename(words[0]) != "git":
        return ""
    rest = words[1:]
    while rest:
        w = rest.pop(0)
        if w in GIT_OPTS_WITH_VALUE:
            if rest:
                rest.pop(0)
        elif not w.startswith("-"):
            return w
    return ""


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
    """Recognize the canonical config and its worktrees by shared Git storage, not directory name."""
    canonical = os.path.expanduser("~/.claude")
    common = _git(cwd, "rev-parse", "--path-format=absolute", "--git-common-dir")
    config_common = _git(canonical, "rev-parse", "--path-format=absolute", "--git-common-dir")
    return bool(common and config_common and
                os.path.realpath(common) == os.path.realpath(config_common))



def command_cwd(command: str, cwd: str) -> str:
    """Resolve the repository targeted by a simple Git command.

    Unknown shell expansion, compound commands and Git environment selectors keep the guard.
    This prevents `git -C <other-repo>` inheriting the caller's config exemption.
    """
    if any(os.environ.get(key) for key in ("GIT_DIR", "GIT_WORK_TREE", "GIT_COMMON_DIR")):
        return ""
    try:
        lexer = shlex.shlex(command, posix=True, punctuation_chars=True)
        lexer.whitespace_split = True
        words = list(lexer)
    except ValueError:
        return ""
    if any(any(ch in word for ch in "$`\n") or word in (";", "&&", "||", "|", "&", "(", ")")
           for word in words):
        return ""
    if not words or os.path.basename(words.pop(0)) != "git":
        return ""
    target = cwd
    while words:
        word = words.pop(0)
        if word == "-C":
            if not words:
                return ""
            path = os.path.expanduser(words.pop(0))
            target = os.path.abspath(os.path.join(target, path))
        elif word.startswith("-C"):
            target = os.path.abspath(os.path.join(target, os.path.expanduser(word[2:])))
        elif word.startswith("-"):
            return ""
        else:
            return target
    return ""


def git_segments(command: str, cwd: str):
    """[(repo, subcommand, args)] for every git command in a compound command, or None.

    Resolves `cd <literal> && git ...` and `git -C <literal> ...` the way the shell would, so a
    sync flow written as `set -euo pipefail; git -C ~/.claude/... push ...` is judged against the
    repository it really targets. Anything not statically certain returns None, which keeps the
    ordinary default-branch guard: a variable or command substitution, a pipe, a subshell, a
    background job, a heredoc, a Git environment selector or a git global option other than -C.
    """
    if "<<" in command or any(ch in command for ch in "$`"):
        return None
    if any(os.environ.get(key) for key in ("GIT_DIR", "GIT_WORK_TREE", "GIT_COMMON_DIR")):
        return None
    try:
        lexer = shlex.shlex(command, posix=True, punctuation_chars=";&|()<>\n")
        lexer.whitespace = " \t\r"
        lexer.whitespace_split = True
        tokens = list(lexer)
    except ValueError:
        return None
    groups, current = [], []
    for tok in tokens:
        bare = tok.replace("\n", "")
        if "\n" in tok and bare in ("", ";", "&&", "||") or tok in SHELL_SEPARATORS:
            # shlex joins adjacent punctuation, so `;` then a newline arrives as one token.
            groups.append((current, bare or "\n"))
            current = []
        elif set(bare) & set(";&|()") and not (set(bare) <= set("<>&") and set(bare) & set("<>")):
            return None
        else:
            current.append(tok)
    groups.append((current, ""))

    found, here, errexit = [], cwd, False
    for words, sep in groups:
        # Drop redirections (`2>&1`, `> log`): they never change the repository a command targets.
        kept, i = [], 0
        while i < len(words):
            w = words[i]
            if set(w) <= set("<>&") and ("<" in w or ">" in w):
                if kept and kept[-1].isdigit():
                    kept.pop()
                i += 2
                continue
            kept.append(w)
            i += 1
        words = kept
        while words and (words[0] in PREFIX_WORDS or ASSIGN_RE.match(words[0])):
            if ASSIGN_RE.match(words[0]) and words[0].startswith("GIT_"):
                return None
            words = words[1:]
        if not words:
            continue
        head = os.path.basename(words[0])
        if head == "set":
            errexit = errexit or any(w.startswith("-") and "e" in w for w in words[1:])
            continue
        if head in ("pushd", "popd", "eval", "source", ".", "exec"):
            return None
        if head == "cd":
            # A later command runs in that directory only when a failed cd stops the line.
            if len(words) != 2 or words[1] == "-" or not (sep == "&&" or (errexit and sep in (";", "\n"))):
                return None
            here = os.path.abspath(os.path.join(here, os.path.expanduser(words[1])))
            continue
        if head != "git":
            continue
        rest, repo = words[1:], here
        while rest and rest[0].startswith("-"):
            opt = rest.pop(0)
            if opt == "-C" and rest:
                repo = os.path.abspath(os.path.join(repo, os.path.expanduser(rest.pop(0))))
            elif opt.startswith("-C") and len(opt) > 2:
                repo = os.path.abspath(os.path.join(repo, os.path.expanduser(opt[2:])))
            else:
                return None
        if not rest:
            continue
        found.append((repo, rest[0], rest[1:]))
    return found


def land_verified(repo: str) -> set:
    common = _git(repo, "rev-parse", "--path-format=absolute", "--git-common-dir")
    if not common:
        return set()
    try:
        with open(os.path.join(common, LAND_MARKER), encoding="utf-8") as f:
            record = json.load(f)
        return {e["sha"] for e in record.get("verified", []) if isinstance(e, dict) and e.get("sha")}
    except Exception:
        return set()


def config_push_problem(repo: str, args: list) -> str:
    """Why this config-repo push may NOT land on main without a confirmation; "" when it may."""
    positional = []
    for a in args:
        if a.startswith("-"):
            if a not in SAFE_PUSH_OPTS:
                return f"push option {a} is outside the automatic landing path"
        else:
            positional.append(a)
    remote = positional[0] if positional else ""
    pairs = []
    if len(positional) <= 1:
        # A bare push sends the current branch to its push destination, which may be main.
        dest = _git(repo, "rev-parse", "--abbrev-ref", "--symbolic-full-name", "@{push}")
        branch = dest.split("/", 1)[1] if "/" in dest else current_branch(repo)
        remote = remote or (dest.split("/", 1)[0] if "/" in dest else "origin")
        pairs.append(("HEAD", branch))
    else:
        for spec in positional[1:]:
            if spec.startswith("+"):
                return f"forced refspec {spec}"
            src, _, dst = spec.partition(":")
            dst = dst or src
            if not src:
                return f"deleting refspec {spec}"
            pairs.append((src, dst))
    verified = None
    for src, dst in pairs:
        dst = dst[len("refs/heads/"):] if dst.startswith("refs/heads/") else dst
        if dst not in DEFAULT_BRANCHES:
            continue
        sha = _git(repo, "rev-parse", "--verify", "--quiet", src + "^{commit}")
        if not sha:
            return f"cannot resolve {src}"
        verified = land_verified(repo) if verified is None else verified
        if sha not in verified:
            return (f"head {sha[:12]} has not passed bin/config-land-check.py "
                    "(contract suite, secret scan, reviewed diff)")
        tracking = _git(repo, "rev-parse", "--verify", "--quiet", f"refs/remotes/{remote}/{dst}")
        if tracking and subprocess.run(
                ["git", "merge-base", "--is-ancestor", tracking, sha], cwd=repo,
                capture_output=True, timeout=5).returncode != 0:
            return f"head {sha[:12]} does not fast-forward {remote}/{dst}"
    return ""


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

    masked = mask(command)
    target_cwd = command_cwd(command, cwd)
    allow_main = os.environ.get("CLAUDE_ALLOW_MAIN_COMMIT") == "1" or bool(
        re.search(r"\bCLAUDE_ALLOW_MAIN_COMMIT=1\b", masked)
    )
    # Config-repo landing: decided once for the whole command, and only when every commit or push in
    # it statically targets the config repo. A mixed or unresolvable command keeps the ordinary guard.
    config_scope = False
    resolved = git_segments(command, cwd)
    landing = [r for r in (resolved or []) if r[1] in ("commit", "push")]
    if landing and all(is_config_repo(repo) for repo, _, _ in landing):
        config_scope = True
        for repo, sub, args in landing:
            problem = config_push_problem(repo, args) if sub == "push" else ""
            if problem and not allow_main:
                return deny(
                    f"Blocked: push to the config repo's main: {problem}. A validated config repair "
                    "lands automatically, with no question to the user: run "
                    f"`/usr/bin/python3 ~/.claude/bin/config-land-check.py --root {repo} --diff`, read "
                    "the whole diff, then rerun with `--reviewed <diff-sha256>` and push the head it "
                    "verified with a literal `git -C <path> push origin HEAD:main`. Ask the user only "
                    "for an excluded decision (rules/self-healing-config.md)."
                )
    for seg in segments(command):
        words = command_words(seg)
        sub = git_subcommand(words)
        is_commit = sub == "commit"
        is_push = sub == "push"
        is_gh_merge = bool(words) and os.path.basename(words[0]) == "gh" and words[1:3] == ["pr", "merge"]
        if not (is_commit or is_push or is_gh_merge):
            continue

        # 0. `gh pr merge` merges into the remote default branch — the action that once merged 8 PRs
        # (two on red CI) into master off a general "merge everything". A general instruction is never
        # a yes for a specific merge, so block unless the user confirmed THIS merge (the flag in the
        # hook's env OR prefixed inline). The deny message is what tells Claude to get that yes.
        if is_gh_merge:
            allow_merge = os.environ.get("CLAUDE_ALLOW_PR_MERGE") == "1" or bool(
                re.search(r"\bCLAUDE_ALLOW_PR_MERGE=1\b", masked)
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

        # 1. Default-branch protection. The override counts whether the flag is in the hook's OWN env
        # OR prefixed inline on the command (`CLAUDE_ALLOW_MAIN_COMMIT=1 git push …`). Claude only
        # adds it once the user has confirmed THIS push; a bare push with no flag stays blocked. The
        # config repo was judged above: its commits pass, and its main pushes need a verified head.
        # A config commit the resolver could not parse keeps its old exemption; a config push never
        # does, so an unverified head reaching main still stops here.
        config_commit = is_commit and bool(target_cwd) and is_config_repo(target_cwd)
        if not allow_main and not config_scope and not config_commit:
            branch = current_branch(target_cwd or cwd)
            target = re.search(r"(?:^|\s|:)(main|master)\b", seg)
            if branch in DEFAULT_BRANCHES or (is_push and target):
                verb = "push to" if is_push else "commit on"
                # Name the branch being pushed TO when the command names one; the checkout's own
                # branch is only the target for a bare push or a commit.
                where = (target.group(1) if is_push and target else branch) or "main/master"
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
