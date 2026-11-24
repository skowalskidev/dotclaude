#!/usr/bin/env python3
"""
Deny THREE git mistakes Claude makes that no other layer catches:

  0. `gh pr merge` — merging a PR into the remote default branch. This is the action that once
     merged 8 PRs (two on red CI) into master off a general "merge everything, no loose ends".
     `git-commit-guard` covered `git push` to main/master, but `gh pr merge` contains neither "git"
     nor "push" so it slipped straight through. A general instruction ("merge everything" / "proceed"
     / "continue") is NEVER a yes for a SPECIFIC merge; confirm the PR and verify CI is actually
     green, and it runs only when the user's OWN words this turn (every ask hooks/intent-ledger.sh
     recorded since his newest typed turn-opening prompt, queued mid-turn ones included) say "merge"
     with no later halt, and name the PR's number, or cover it as an open PR this session pushed, or
     say all/both/them in answer to a hand-back whose "Merge list:" line names it. A
     standing instruction earlier in the session ("merge and deploy all when they're ready", "merge
     12 once CI is green", "when it's safe then merge", or a plain "merge all"; never a question)
     also covers it, with no later halt, but only while
     the PR is open, not a draft, mergeable and every check has passed at the moment of the merge. There
     is no override flag: a flag the model sets itself let two PRs merge off a model-written "Merge
     #N?" answered "1 yes" and off "this is priority, finish it". `gh api` merge/enqueue/auto-merge
     calls are denied outright. Every merge deny leads with `Cause:`, the one check that failed
     (merge_deny_cause), so a `$n` selector is never misread as a problem with the user's words.
     One narrow path needs no merge words: a monitoring-only PR at its bar (monitoring_merge below,
     references/git-pr-deploy.md § Monitoring-only changes), which Simon authorized for that class.

  1. Committing or pushing on the default branch (main / master). rules/process.md: "If on the
     default branch, create a branch first", and feedback_no_master_commits: never commit/push to
     master without your confirmation. Branch first. The override is CLAUDE_ALLOW_MAIN_COMMIT=1 in
     the ENVIRONMENT the Claude session was started with, which only the user sets. A
     `CLAUDE_ALLOW_MAIN_COMMIT=1 ...` prefix (or `env`, `export`) inside the command does NOT pass:
     the agent types the command, so an inline prefix would let it approve its own default-branch
     commit or push (rules/self-healing-config.md § Safeguard changes).
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

import datetime
import functools
import hashlib
import html
import itertools
import json
import os
import re
import shlex
import signal
import subprocess
import sys
import time
import unicodedata
from urllib.parse import quote, unquote

# Split on shell separators so each command is judged on its own. Runs on the MASKED command, so a
# separator inside quotes or a heredoc body never splits it.
SEGMENT_RE = re.compile(r"(?:\|\||&&|;|\||\n)")

# Tokens that can precede the real command word: `VAR=1 git push`, `sudo git …`, `( git … )`.
PREFIX_WORDS = {"sudo", "env", "command", "time", "nohup", "exec", "(", "{", "!", "then", "do", "else",
                "if", "elif", "while", "until", "coproc", "builtin",
                "noglob", "nocorrect", "-"}  # zsh precommand modifiers run the next word as the command  # a condition runs its command too: `if gh pr merge 12; then`
ASSIGN_RE = re.compile(r"^[A-Za-z_][A-Za-z0-9_]*=")
# git global options that take a separate value: `git -C <path> push`.
GIT_OPTS_WITH_VALUE = {"-C", "-c", "--git-dir", "--work-tree", "--namespace", "--exec-path"}
HEREDOC_START_RE = re.compile(r"(?<!<)<<(?!<)-?\s*(['\"]?)(\w+)\1")  # never a here-string (<<<)
QUOTE_MARK = "\x01"
# Wrappers that run the rest of their line as a command, and the options of theirs that take a value.
WRAPPERS = {"sudo", "env", "command", "builtin", "time", "nohup", "exec", "xargs", "nice", "timeout", "stdbuf",
            "doas"}
WRAPPER_OPTS_WITH_VALUE = {"-u", "-g", "-n", "-I", "-P", "-d", "-L", "-s", "-k", "-a", "-E", "-S",
                           "--user", "--group", "--unset", "--max-args", "--max-procs", "--delimiter",
                           "--signal", "--kill-after"}
SHELLS = {"bash", "sh", "zsh", "dash", "ksh"}
SHELL_C_RE = re.compile(r"^-[a-zA-Z]*c[a-zA-Z]*$")
MAX_UNWRAP = 4

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


def mask(command: str, store: list = None) -> str:
    """Blank out quoted strings and heredoc bodies, keeping the quote marks and heredoc markers.

    The guard judges what the shell RUNS, not text a command carries: a printf writing a note that
    quotes a push command is a printf, and a heredoc body naming `git commit -m` is data. Matching
    the raw text blocked exactly that (a ledger note quoting a push). Fails open: an unterminated
    quote masks to the end, which can only hide a match, never invent one.

    With `store`, each closed quoted string's content is appended to it and a placeholder
    (QUOTE_MARK, its index, QUOTE_MARK) stands inside the quotes, so a caller can read a `bash -c`
    string back without ever matching text inside a quote.
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

    res, quote, esc, buf = [], None, False, []
    for ch in text:
        if quote:
            if quote == '"' and esc:
                esc = False
            elif quote == '"' and ch == "\\":
                esc = True
            elif ch == quote:
                quote = None
                if store is not None:
                    res.append(f"{QUOTE_MARK}{len(store)}{QUOTE_MARK}")
                    store.append("".join(buf))
                res.append(ch)
            if quote:
                buf.append(ch)
            continue
        if ch in ("'", '"'):
            quote = ch
            buf = []
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


def lead_words(seg: str) -> list:
    """Like command_words, but stops at a wrapper so its own options (`env -i`, `sudo -u x`) are read."""
    words = seg.split()
    while words and ((words[0] in PREFIX_WORDS and words[0] not in WRAPPERS) or ASSIGN_RE.match(words[0])):
        words = words[1:]
    return words


def _unwrap_options(words: list) -> list:
    """Drop a wrapper's own options (`sudo -u root`, `env -i`, `timeout 5`, `xargs -n 1`)."""
    head = os.path.basename(words[0])
    rest = words[1:]
    while rest and rest[0].startswith("-") and rest[0] != "--":
        opt = rest.pop(0)
        if opt in WRAPPER_OPTS_WITH_VALUE and rest:
            rest.pop(0)
    if rest and rest[0] == "--":
        rest.pop(0)
    if head in ("timeout", "nice") and rest and re.fullmatch(r"[\d.]+[smhd]?", rest[0]):
        rest.pop(0)
    return rest


def _unmark(text: str) -> str:
    return re.sub(rf"{QUOTE_MARK}\d+{QUOTE_MARK}", "", text)


def expand_words(words: list, store: list, depth: int = 0) -> list:
    """Every command word list `words` really runs: itself, the command behind a wrapper
    (`sudo -u x gh ...`, `xargs gh ...`) and the commands inside a `bash -c "..."` string.

    A command behind `xargs` takes its arguments from stdin, which the guard cannot read, so it
    carries a trailing `$xargs` word: a literal-number check then fails closed.
    """
    out = [words]
    if depth >= MAX_UNWRAP or not words:
        return out
    head = os.path.basename(words[0])
    if head in WRAPPERS:
        rest = command_words(" ".join(_unwrap_options(words)))
        if rest:
            if head == "xargs":
                rest = rest + ["$xargs"]
            out += expand_words(rest, store, depth + 1)
    elif head in SHELLS:
        for i, w in enumerate(words[1:], 1):
            if SHELL_C_RE.match(w):
                m = re.fullmatch(rf"""["']{QUOTE_MARK}(\d+){QUOTE_MARK}["']""", words[i + 1]) if i + 1 < len(words) else None
                if m and int(m.group(1)) < len(store):
                    out += [w for _, w, _ in expand_command(store[int(m.group(1))], depth + 1)]
                break
            if not w.startswith("-"):
                break
    return out


def expand_command(command: str, depth: int = 0) -> list:
    """[(segment, words, top)] for every command in `command`, `bash -c` strings and wrappers
    unwrapped. `top` marks the segment's own command, the only one a `cd` can be read from."""
    store: list = []
    out = []
    for seg in [s.strip() for s in SEGMENT_RE.split(mask(command, store)) if s.strip()]:
        for n, words in enumerate(expand_words(lead_words(seg), store, depth)):
            words = [_unmark(w) for w in words]
            # Placeholders carry the quoted text for the unwrap only; the later checks read the
            # quotes empty, as they always have.
            plain = _unmark(seg) if n == 0 else " ".join(words)
            out.append((plain, words, n == 0 and depth == 0))
    return out


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
    """Why this config-repo push may NOT land on main without a confirmation; "" when it may.

    Only a push that can change main is judged: branch pushes, deletions of task branches and the
    like pass as they did before.
    """
    opts = [a for a in args if a.startswith("-")]
    positional = [a for a in args if not a.startswith("-")]
    if {"--all", "--mirror"} & set(opts):
        return f"{'/'.join(sorted({'--all', '--mirror'} & set(opts)))} pushes main as a side effect"
    if {"-d", "--delete"} & set(opts):
        doomed = [ref.split("refs/heads/")[-1] for ref in positional[1:]]
        return "deleting main" if set(doomed) & DEFAULT_BRANCHES else ""
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
            src, _, dst = spec.partition(":")
            pairs.append((src, dst or src))
    strip = lambda ref: ref.lstrip("+")[len("refs/heads/"):] if ref.lstrip("+").startswith("refs/heads/") else ref.lstrip("+")
    pairs = [(src, strip(dst)) for src, dst in pairs if strip(dst) in DEFAULT_BRANCHES]
    if not pairs:
        return ""
    unsafe = [o for o in opts if o not in SAFE_PUSH_OPTS]
    if unsafe:
        return f"push option {unsafe[0]} is outside the automatic landing path"
    for src, _ in pairs:
        if src.startswith("+"):
            return f"forced refspec {src}"
        if not src:
            return "deleting main"
    verified = None
    for src, dst in pairs:
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


# A merge or a default-branch push is authorized by Simon's OWN words, never by a flag the model can
# set (the fix for two PRs merged off "1 yes" to a model-written question and "this is priority,
# finish it"). hooks/intent-ledger.sh records every prompt verbatim, queued mid-turn ones included.
# The guard reads every ask of the CURRENT turn: from Simon's newest typed prompt in the transcript
# that opened a turn (the one after the assistant's last hand-back) to now (the fix for "merge all
# that's ready 1162 too" losing its authority to a queued "from this session i mean"). No ledger, no
# ask, or a later halt denies: the action is irreversible.
HARNESS_BLOCK_RE = re.compile(
    r"<(system-reminder|task-notification|agent-message|cross-session-message)\b[^>]*>.*?</\1>", re.S | re.I)
# Pasted material inside his message (a fenced block, or everything from a `>` quote line on) is not his
# instruction, as before. A negated merge/push/deploy/ship inside it still halts: clean_asks keeps it.
QUOTED_RE = re.compile(r"^[ \t]*(`{3,}|~{3,}).*?^[ \t]*\1[ \t]*$|^[ \t]*>.*$", re.S | re.M)
QUOTED_HALT = "don't merge: a halt sits in the quoted or pasted text"
ASK_READ_LIMIT = 8000
TOO_LONG_HALT = "don't merge: a message too long to read in time may hold a halt"


def clean_asks(raw: list) -> list:
    """Each ask with harness blocks and quotes removed, and, after any ask whose removed text negated
    merging, pushing, deploying or shipping, a halt standing in for it: quoted text never authorizes,
    and never hides a halt either."""
    out = []
    for a in raw:
        if len(a) > ASK_READ_LIMIT:
            # Too long to clean inside the hook's budget (the fence pattern is superlinear on many
            # unclosed fences): never read, it stands as a halt, and a later short message can lift it.
            out.append(TOO_LONG_HALT)
            continue
        kept = HARNESS_BLOCK_RE.sub("", a).translate(APOSTROPHES)
        cleaned = QUOTED_RE.sub("", kept).strip()
        if cleaned:
            out.append(cleaned)
        if NEGATED_RE.search(kept) and not NEGATED_RE.search(cleaned):
            out.append(QUOTED_HALT)
    return out
# A negator must GOVERN the verb: at most 2 words between them, and no comma or clause-joining word
# crossing: yes, and, then (or its typo "them"), so, ok, ie (the fix for "not be so strict yes merge",
# "no regressions, then merge" and "safe for prod ie no regressions then merge and deploy" read as
# "don't merge": a negator inside the condition clause negates the condition, not the verb).
# stop/hold/wait count only inside the same short clause ("hold off merging", "wait before you merge").
CLAUSE_JOIN = r"(?:yes|and|then|them|so|ok|okay|ie)\b"
NEGATED_RE = re.compile(
    r"\b(don'?t|do not|never|not|no|without|before)\s+(?:(?!" + CLAUSE_JOIN + r")[\w']+\s+){0,2}?"
    r"(merg|push|deploy|ship)"
    r"|\b(stop|hold|wait)\b(?:(?!\b" + CLAUSE_JOIN + r")[^.,;\n]){0,25}?\b(merg|push|deploy|ship)", re.I)
# A question or a hypothetical about the verb is not an instruction to do it. Each sentence is judged
# clause by clause (split on , ; and a colon before a space), and the CLAUSE that says the verb decides:
# it is a question when it ends the sentence and the sentence ends in "?" ("merge 12?"), or when the
# next clause starts with "or" in a sentence ending in "?" ("merge it now, or wait?"). A question
# opener anywhere up to that clause makes it hypothetical: should/would/shall/might I|we|you ...,
# can/may/could I|we (asking permission), what if, whether, do you think, is it ok/safe to ... ("should
# I merge when it's ready?", "can I merge it now, or should we wait?"). A question in a LATER clause
# does not reach back (the fix for "let's merge and deploy that when it's ready ..., u sure we don't
# roll back 1031?" read as a question because the sentence ended in "?"). A polite request
# ("can/could/will you merge 12?", "please merge") stays an instruction.
HYPOTHETICAL_RE = re.compile(
    r"\b(should|would|shall|might)\s+(i|we|you|it|this|that|they|claude)\b|\b(can|may|could)\s+(i|we)\b"
    r"|\bwhat\s+if\b|\bwhether\b"
    r"|\b(do|did)\s+you\s+think\b|\b(is|are)\s+(it|this|that|they)\s+(ok|okay|safe|fine|wise|worth)\s+to\b", re.I)
POLITE_REQUEST_RE = re.compile(r"\b(can|could|will)\s+you\b|\bplease\b", re.I)
SENTENCE_RE = re.compile(r"[^.!?\n]+[.!?]*")
CLAUSE_SPLIT_RE = re.compile(r"[,;]|:(?=\s)")
ALTERNATIVE_RE = re.compile(r"^\s*or\b", re.I)


def clause_readings(ask: str):
    """(clause, instructs?) for every clause of the ask: False when the clause is part of a question
    or a hypothetical, judged as the comment above describes."""
    for sentence in SENTENCE_RE.findall(ask):
        asked = sentence.rstrip().endswith("?")
        clauses = CLAUSE_SPLIT_RE.split(sentence)
        for i, clause in enumerate(clauses):
            prefix = " ".join(clauses[:i + 1])
            last = i == len(clauses) - 1
            alternative = asked and not last and ALTERNATIVE_RE.match(clauses[i + 1])
            question = (asked and last and not POLITE_REQUEST_RE.search(prefix)) or alternative
            yield clause, not (question or HYPOTHETICAL_RE.search(prefix))


def instructs(ask: str, verb: str) -> bool:
    """True when some clause of the ask says the verb as an instruction, not a question or a
    hypothetical (the fix for "should I merge when it's ready?" read as a standing merge)."""
    says = re.compile(VERB_FORMS[verb], re.I)
    return any(ok and says.search(clause) for clause, ok in clause_readings(ask))


def merge_scope(text: str) -> str:
    """The text with question clauses that do not say merge removed, so a PR number named only in a
    side question ("..., u sure we don't roll back 1031?") is neither covered nor read as naming
    another PR."""
    says = re.compile(VERB_FORMS["merge"], re.I)
    return " ".join(c for c, ok in clause_readings(text) if ok or says.search(c))


# Every verb check accepts its inflections: merge/merged/merges/merging, push/pushed/pushes/pushing
# (the fix for "this can be merged if prod deploy ready" missing a `\bmerge\b` check).
VERB_FORMS = {"merge": r"\bmerg(?:e|ed|es|ing)\b", "push": r"\bpush(?:ed|es|ing)?\b"}
# A later ask that does not repeat the verb but says one of these cancels the earlier authority.
HALT_RE = re.compile(r"\b(stop|hold|wait|cancel|pause|don'?t|do not|never)\b", re.I)
PR_NUMBER_RE = re.compile(r"#?\b\d{2,}\b")
# A PR named explicitly, of any length: "#7", "PR 7", "pull request 7"; and a repository-qualified one.
EXPLICIT_SELECTOR_RE = re.compile(r"#\d+|\b(?:pr|pull|pull request)\s*#?\s*\d+", re.I)
QUALIFIED_REF_RE = re.compile(r"(?<![\w.-])(?:github\.com/)?[\w.-]+/[\w.-]+(?:/pull/|#)\d+")
# Plural phrasing ("merge all that's ready", "merge both", "merge them", "the ready ones") covers every open PR this
# session pushed, never a PR it did not push (the "merge everything" incident merged 8 PRs).
BULK_RE = re.compile(r"\b(all|both|every|everything|each|batch|them|these|those|ones)\b", re.I)
API_MERGE_RE = re.compile(
    r"enqueuePullRequest|mergePullRequest|enablePullRequestAutoMerge|/pulls/[^/\s]+/merge\b", re.I)  # any selector
# `gh pr merge` options that take a value, so the value is never read as the PR selector.
GH_MERGE_OPTS_WITH_VALUE = {"-R", "--repo", "-t", "--subject", "-b", "--body", "-F", "--body-file",
                            "-A", "--author-email", "--match-head-commit"}
STATE_DIR = os.path.join(os.path.expanduser("~"), ".claude", ".intent-ledger")
READ_ONLY = False  # set by the --explain dry-run: no state file is written


def _run(args, timeout=None, **kw):
    """subprocess.run in its own process group, killed whole on timeout: a grandchild holding the pipes
    (an awk under the ledger script, a gh credential helper) can no longer keep the hook past its own
    timeout, which would let the command run."""
    kw.pop("check", None)
    data = kw.pop("input", None)
    capture = kw.pop("capture_output", False)
    if capture:
        kw["stdout"], kw["stderr"] = subprocess.PIPE, subprocess.PIPE
    if data is not None:
        kw["stdin"] = subprocess.PIPE
    with subprocess.Popen(args, start_new_session=True, **kw) as proc:
        try:
            out, err = proc.communicate(input=data, timeout=timeout)
        except subprocess.TimeoutExpired:
            try:
                os.killpg(proc.pid, signal.SIGKILL)
            except OSError:
                pass
            proc.communicate(timeout=1)
            raise
    return subprocess.CompletedProcess(args, proc.returncode, out, err)


def session_id(payload: dict) -> str:
    return re.sub(r"[^A-Za-z0-9._-]", "", str(payload.get("session_id", ""))) or "unknown"


def ledger_asks(payload: dict, since: str = "") -> list:
    """This session's recorded asks: the newest one, or with `since` every ask from that second."""
    script = os.path.join(os.path.expanduser("~"), ".claude", "hooks", "intent-ledger.sh")
    if not os.path.isfile(script):
        return []
    try:
        p = _run(["bash", script, "latest-ask", *(["--since", since] if since else [])],
                           text=True, capture_output=True, timeout=bounded(5),
                           input=json.dumps({"session_id": payload.get("session_id", ""),
                                             "cwd": payload.get("cwd", "")}))
    except Exception:
        return []
    if p.returncode != 0:  # an unfinished or unreadable record: no words can authorize from it
        return []
    return [a for a in (p.stdout or "").split("\x1e") if a.strip()]


def _transcript(path: str) -> list:
    try:
        with open(path, "rb") as f:
            return f.read().splitlines()
    except Exception:
        return []


def _entry(line: bytes):
    try:
        e = json.loads(line)
    except Exception:
        return None
    return e if isinstance(e, dict) else None


def _typed_prompt(e: dict) -> bool:
    """A prompt Simon typed. A tool result, a skill body or hook feedback (isMeta), a compaction
    summary, a sidechain and a harness prompt (task notification, origin set) are not."""
    if (e.get("type") != "user" or e.get("isMeta") or e.get("isSidechain")
            or e.get("isCompactSummary") or e.get("origin")):
        return False
    content = (e.get("message") or {}).get("content")
    if isinstance(content, list):
        if any(isinstance(x, dict) and x.get("type") == "tool_result" for x in content):
            return False
        text = part_text(content)
    elif isinstance(content, str):
        text = content
    else:
        return False
    return bool(HARNESS_BLOCK_RE.sub("", text).strip())


NON_TEXT_PART = "[a non-text part: an image or file the guard cannot read]"


def part_text(parts) -> str:
    """A message's text parts joined, each non-text part (an image, a document) as NON_TEXT_PART: the
    guard cannot read it, so it holds (its brackets are markup) rather than vanish."""
    return " ".join(str(x.get("text", "")) if x.get("type", "text") == "text" else NON_TEXT_PART
                    for x in parts or [] if isinstance(x, dict))


def turn_opened_at(path: str) -> str:
    """The ledger second at which the current turn opened: Simon's newest typed prompt in the
    transcript, minus one second for clock rounding. "" when unreadable, which falls back to the
    newest ask alone."""
    for line in reversed(_transcript(path)):
        if b'"user"' not in line:
            continue
        e = _entry(line)
        if not e or not _typed_prompt(e):
            continue
        try:
            opened = datetime.datetime.strptime(str(e.get("timestamp", ""))[:19], "%Y-%m-%dT%H:%M:%S")
        except ValueError:
            return ""
        return (opened - datetime.timedelta(seconds=1)).strftime("%Y-%m-%dT%H:%M:%SZ")
    return ""


# The hand-back's own list of what Simon is to merge ("Merge list: #1204, then #1208"), which
# rules/communication.md has every hand-back with open PRs end on.
MERGE_LIST_RE = re.compile(r"^[\s>*_`-]*merge list\b[^\n]*", re.I | re.M)


def handed_back_merge_list(path: str) -> set:
    """The PR numbers in the merge list of the hand-back Simon is answering: the newest end_turn
    reply before his newest typed prompt. Empty when that reply lists none, so an older list never
    carries over."""
    seen_prompt = False
    for line in reversed(_transcript(path)):
        e = _entry(line)
        if not e:
            continue
        if not seen_prompt:
            seen_prompt = _typed_prompt(e)
            continue
        message = e.get("message") or {}
        if e.get("type") != "assistant" or message.get("stop_reason") != "end_turn":
            continue
        text = " ".join(str(x.get("text", "")) for x in message.get("content") or [] if isinstance(x, dict))
        found = MERGE_LIST_RE.search(text)
        return set(re.findall(r"#(\d{2,})\b", found.group(0))) if found else set()
    return set()


def turn_asks(payload: dict) -> list:
    """Every ask Simon typed this turn, oldest first, with harness blocks and pasted quotes removed."""
    since = turn_opened_at(str(payload.get("transcript_path") or ""))
    raw = ledger_asks(payload, since) if since else ledger_asks(payload)[-1:]
    # A typographic apostrophe ("don’t merge") reads like the ASCII one, so a halt is never missed.
    return clean_asks(raw)


def authorizing_asks(asks: list, verb: str) -> list:
    """The turn's asks after its last halt, when one of them says the verb (merge/push). A halt is an
    ask negating the verb ("don't merge yet") or a later ask saying stop/hold/wait without it."""
    says = re.compile(VERB_FORMS[verb], re.I)
    start = 0
    for i, ask in enumerate(asks):
        if NEGATED_RE.search(ask) or (not says.search(ask) and HALT_RE.search(ask)):
            start = i + 1
    window = asks[start:]
    return window if any(instructs(a, verb) for a in window) else []


def merge_target(words: list) -> tuple:
    """(selector, number, repo) a `gh pr merge` names: a bare number, `#N` or a /pull/N URL, and the
    -R/--repo value. A branch name or no argument gives no number, which the guard denies because
    the user's words cannot be matched to it."""
    selector, repo, rest = "", "", list(words[3:])
    while rest:
        w = rest.pop(0)
        if w in GH_MERGE_OPTS_WITH_VALUE:
            value = rest.pop(0) if rest else ""
            repo = value if w in ("-R", "--repo") else repo
        elif w.startswith("--repo="):
            repo = w.split("=", 1)[1]
        elif w.startswith("-R") and len(w) > 2:  # an attached value: -Rowner/name
            repo = w[2:]
        elif not w.startswith("-") and not selector:
            selector = w
    return selector, selector_number(selector), repo


# The whole selector must be a PR number or a GitHub PR URL: a branch named "feature/pull/12" is no #12.
SELECTOR_RE = re.compile(r"#?(\d+)|(?:https?://)?(?:www\.)?github\.com/[^/\s]+/[^/\s]+/pull/(\d+)/?")


def selector_number(selector: str) -> str:
    m = SELECTOR_RE.fullmatch(selector)
    return (m.group(1) or m.group(2)) if m else ""


def github_slug(url: str) -> str:
    m = re.search(r"github\.com[:/]([^/\s]+/[^/\s]+?)(?:\.git)?/?$", url.strip())
    return m.group(1).lower() if m else ""


PR_FIELDS = "headRefName,state,url,isDraft,mergeable,statusCheckRollup"
_PR_CACHE: dict = {}


def pr_view(selector: str, repo: str, cwd) -> dict:
    """One read-only `gh pr view` per hook run, shared by the ownership and readiness checks, inside
    the hook's budget (bounded(), MONITORING_BUDGET_S). {} when the PR cannot be resolved, which denies."""
    if not repo and "/pull/" not in selector and cwd is None:
        return {}
    key = (selector, repo, cwd)
    if key not in _PR_CACHE:
        try:
            p = _run(["gh", "pr", "view", selector, "--json", PR_FIELDS,
                                *(["--repo", repo] if repo else [])],
                               cwd=cwd or None, capture_output=True, text=True, timeout=bounded(8))
            pr = json.loads(p.stdout) if p.returncode == 0 else {}
        except Exception:
            pr = {}
        # GitHub's answer must be the PR the selector names: any other number (a branch selector that
        # resolved to another PR) is no answer.
        got = re.search(r"/pull/(\d+)/?$", str(pr.get("url", ""))) if isinstance(pr, dict) else None
        if not got or got.group(1) != selector_number(selector):
            pr = {}
        _PR_CACHE[key] = pr if isinstance(pr, dict) else {}
    return _PR_CACHE[key]


def session_pushed_pr(payload: dict, selector: str, repo: str, cwd) -> bool:
    """True when the PR is open and its head branch is one this session pushed to that repo
    (hooks/intent-ledger.sh `push` records every non-default branch push in session state), read from
    the push's own checkout, or from the current checkout once that worktree is gone."""
    try:
        with open(os.path.join(STATE_DIR, f"{session_id(payload)}.pushes")) as f:
            pushed = {tuple(l.rstrip("\n").split("\t")[:2]) for l in f if l.count("\t") >= 2}
    except OSError:
        return False
    if not pushed:
        return False
    pr = pr_view(selector, repo, cwd)
    slug = (re.search(r"github\.com/([^/]+/[^/]+)/pull/", str(pr.get("url", ""))) or [None, ""])[1].lower()
    if pr.get("state") != "OPEN" or not slug or not pr.get("headRefName"):
        return False
    # A worktree removed after its push (task cleanup) has no remote to read: its push still counts
    # through the current checkout's origin, so the branch must match in the same repository (the fix
    # for "merge the ready ones" refused once the PRs' temporary worktrees were cleaned up).
    here = github_slug(_git(str(cwd or ""), "remote", "get-url", "origin"))
    return any(branch == pr["headRefName"]
               and (github_slug(_git(root, "remote", "get-url", "origin")) if os.path.isdir(root) else here) == slug
               for root, branch in pushed)


def too_long_to_read(text: str) -> bool:
    """Words too long to read inside the hook's time budget authorize nothing: a regex cannot be stopped
    mid-match, and a hook that outlives its timeout lets the command run."""
    return len(text) > 4000 or bool(re.search(r"[\w.-]{513}", text))


def excluded(text: str, number: str) -> bool:
    """True when the words EXCLUDE this PR ("merge #13 but not #12", "except 12", "skip 12"): naming
    a number after a negator never authorizes it (the fix for "merge X but not Y" read as merging Y)."""
    # The excluded PR may be named qualified too ("except acme/api#12", a PR URL), and anywhere in a list
    # after the negator ("except #12 and #13", "but not 12, 13 or 14"): the number still counts.
    sel = r"(?:pr\s*)?(?:(?:https?://)?(?:[\w.-]+\.[a-z]+/)?[\w.-]+/[\w.-]+(?:/pull/|#))?#?\d+"
    for m in re.finditer(rf"\b(?:not|except|excluding|skip|skipping|without|but not|other than|apart from|besides|"
                         rf"leave out|leaving out|minus|save)(?:\s+(?:for|the|on|with|of|to))*\s+"
                         rf"(?:{sel}\s*(?:,|\band\b|\bor\b|&|\bnor\b)\s*)*"
                         rf"(?:pr\s*)?(?:(?:https?://)?(?:[\w.-]+\.[a-z]+/)?[\w.-]+/[\w.-]+(?:/pull/|#))?#?0*{int(number)}(?!\d)",
                         text, re.I):
        if not re.search(r"\b(?:don'?t|do not|never)\s+(?:\w+\s+)?$", text[:m.start()], re.I):
            return True
    return False


# A chat UI turns a typed reference into a markdown link ("[#1410](.context/pull-requests/1410.md)"). A link
# to a local file reads as its label alone: the target names a file, never a repository. A link with a
# scheme or to github.com reads as its target, with the label's digits masked: the label is display text for
# that URL, so "[#12](https://github.com/acme/other/pull/12)" names acme/other#12 and never a bare #12.
MD_LINK_RE = re.compile(r"\[([^\[\]\n]*)\]\(([^()\s]*)\)")


def link_labels(text: str) -> str:
    """The words with every markdown link read as above (the fix for a merge of four named PRs refused
    because the chat UI linked the last number to a local .md file, read as a stated repository)."""
    # Spaces on both sides keep a label from joining the text around it ("[#12](a.md)3" is never #123).
    def one(m):
        if re.match(r"[a-z][a-z0-9+.-]*:|//|(?:www\.)?github\.com/", m.group(2), re.I):
            return f" {re.sub(r'[0-9]', ' ', m.group(1))} {m.group(2)} "
        return f" {m.group(1)} "
    return MD_LINK_RE.sub(one, text)


# A file path is not a repository: a token starting with ~, ./, ../, a dot-name (".context/...") or one
# slash ("/tmp/x"; "//host" stays a URL), or a slash path ending in a document or image extension.
FILE_TOKEN_RE = re.compile(r"(?<![^\s(\[<\"'`,;=])(?:~|\.\.?/|\.(?=\w)|/(?!/))[^\s()\[\]<>\"'`,;]*")
FILE_EXT_RE = re.compile(r"\.(?:md|markdown|mdx|txt|log|rst|csv|pdf|png|jpe?g|gif|webp|patch|diff)$", re.I)


def stated_repos(text: str) -> set:
    """Every repository the words state, lowercase owner/name: a github.com URL's first two path parts, and
    any other slash-joined name of two parts ("acme/api", "in acme/service/"). A URL on another host, or a
    longer slash path, states a repository the guard cannot resolve ("\x00unknown"), which no target
    matches. Fail closed: any other two-part slash name counts as a repository; only a clear file path
    (FILE_TOKEN_RE, FILE_EXT_RE) does not."""
    stated = set()
    for m in re.finditer(r"https?://([^\s/]+)(/\S*)?", text):
        parts = [x for x in (m.group(2) or "").split("/") if x]
        if m.group(1).lower() in ("github.com", "www.github.com") and len(parts) >= 2:
            stated.add(f"{parts[0]}/{parts[1]}".rstrip(".,;:)").lower())
        else:
            stated.add("\x00unknown")
    rest = FILE_TOKEN_RE.sub(" ", re.sub(r"https?://\S+", " ", text))
    for m in re.finditer(r"(?<![\w.-])(?:github\.com/)?([\w.-]+(?:/[\w.-]+)+)/*", rest):
        parts = m.group(1).rstrip(".").lower().split("/")
        if FILE_EXT_RE.search(parts[-1]):
            continue
        stated.add("/".join(parts) if len(parts) == 2 else "\x00unknown")
    return stated


def merge_target_repo(selector: str, repo: str, cwd) -> str:
    """The merge's repository, lowercase owner/name, from -R or GitHub's answer; "" when unknown."""
    target = re.sub(r"^(?:https?://)?github\.com/", "", repo or "").strip("/").lower()
    if not target:
        got = re.search(r"github\.com/([^/]+/[^/]+)/pull/", str(pr_view(selector, repo, cwd).get("url", "")))
        target = got.group(1).lower() if got else ""
    return target


def covers(text: str, number: str, payload: dict, selector: str, repo: str, cwd) -> bool:
    """Simon's words name this PR's number, or (naming no other PR, or saying all/both/them) cover
    it as an open PR this session pushed, or say all/both/them in answer to a hand-back whose merge
    list names it (the fix for "merge and deploy both" refused for the base PR of a stack another
    session pushed, which the hand-back had listed for him to merge)."""
    # A period inside a path or repository name ("acme/service.web") is part of the name, never the end
    # of a clause, so names are protected while the message is split into clauses.
    if too_long_to_read(text):
        return False
    text = link_labels(text)
    scoped = merge_scope(re.sub(r"(?<![\w.-])[\w.-]+/[\w.-]+", lambda m: m.group(0).replace(".", "\x07"), text))
    text = scoped.replace("\x07", ".")
    # A URL on another host names a PR GitHub cannot be asked about: it is masked before anything else is
    # read (one space each, so every later position matches), and it leaves the repository unknown.
    foreign = bool(re.search(r"https?://(?!(?:www\.)?github\.com/)\S+", text))
    text = re.sub(r"https?://(?!(?:www\.)?github\.com/)\S+", " ", text)
    # Only a sentence that itself says merge names a PR to merge by number ("Merge #34. Review #12."
    # covers #34). Every other rule reads the whole message: a selector or an exclusion anywhere in it
    # still counts ("Merge it. That is PR #34." names a PR, so no unnumbered fallback runs).
    merge_spans, at = [], 0
    for piece in re.split(r"((?<=[.!?;])\s+|\n+)", text):
        if re.search(r"\bmerg", piece, re.I):
            merge_spans.append((at, at + len(piece)))
        at += len(piece)
    if excluded(text, number):
        return False
    # Every repository-qualified reference (a PR URL, owner/name#N) is read whole first and covers that
    # repository's PR alone: "merge https://github.com/acme/service/pull/12" is no word for acme/bot#12,
    # and the 12 in "acme/service12#34" is part of a reference to #34, never a bare mention of 12.
    refs = list(re.finditer(r"(?<![\w.-])(?:github\.com/)?([\w.-]+/[\w.-]+)(?:/pull/|#)(\d+)(?!\d)", text))
    # A repository stated in words ("merge PR #12 in acme/service", "github.com/acme/service") binds every
    # selector in the message to it: the words cover no PR of another repository.
    bare = text
    for m in reversed(refs):
        bare = bare[:m.start()] + " " * (m.end() - m.start()) + bare[m.end():]
    # Any other slash-joined name in the words ("merge acme/api PR #12", "in acme/service/", a repo URL)
    # is a stated repository; one of more than two parts (a/b/c) cannot be told from a path, so it makes
    # the repository unknown. Fail closed: a two-part file path counts as a repository too.
    stated = stated_repos(bare) | ({"\x00unknown"} if foreign else set())
    # Beside any explicit selector (a qualified reference, "#34", "PR 34"), only an explicit selector names
    # a PR: a bare number there may be anything ("merge #34 for release 12").
    explicit = bool(refs) or bool(EXPLICIT_SELECTOR_RE.search(bare))
    if any(any(a <= m.start() < b for a, b in merge_spans) for m in re.finditer(
            rf"(?<!\d){number}(?!\d)" if not explicit else rf"(?:#|\b(?:pr|pull|pull request)\s*#?\s*){number}(?!\d)",
            bare, re.I)):
        if not stated:
            return True
        # Several repositories stated: which selector belongs to which is not read, so only a qualified
        # reference (owner/name#N) names a PR there ("merge #12 in acme/api and #34 in acme/web").
        if len(stated | {m.group(1).lower() for m in refs}) > 1:
            return False
        target = merge_target_repo(selector, repo, cwd)
        return bool(target) and target in stated
    # Digits compared as written, as the bare match does: "acme/api#0012" names no PR 12 (exclusions,
    # stricter, read the value).
    named_in = {m.group(1).lower() for m in refs if m.group(2) == number
                and any(a <= m.start() < b for a, b in merge_spans)}
    if named_in:
        target = merge_target_repo(selector, repo, cwd)
        return bool(target) and target in named_in
    bulk, numbered = bool(BULK_RE.search(text)), bool(PR_NUMBER_RE.search(text)) or explicit
    if stated:
        # "merge all ready PRs in acme/api": the bulk and unnumbered paths cover that repository alone.
        target = merge_target_repo(selector, repo, cwd)
        if not target or len(stated) > 1 or target not in stated:
            return False
    if bulk and number in handed_back_merge_list(str(payload.get("transcript_path") or "")):
        return True
    return (bulk or not numbered) and session_pushed_pr(payload, selector, repo, cwd)


def turn_merge_allowed(payload: dict, words: list, cwd) -> bool:
    """`gh pr merge` runs when Simon's words this turn say merge after the last halt and either name
    this PR's number anywhere, or (naming no other PR, or saying all/both/them) cover it as an open PR
    this session pushed, or name no PR at all (then ONE other PR per turn, see unnamed_merge_ok)."""
    selector, number, repo = merge_target(words)
    window = authorizing_asks(turn_asks(payload), "merge")
    if not number or not window:
        return False
    text = "\n".join(window)
    if too_long_to_read(text):
        return False
    text = link_labels(text)
    if covers(text, number, payload, selector, repo, cwd):
        return True
    scope = merge_scope(text)
    if BULK_RE.search(scope) or PR_NUMBER_RE.search(scope) or EXPLICIT_SELECTOR_RE.search(scope) \
            or QUALIFIED_REF_RE.search(scope):
        return False
    # "merge the PR in acme/service" names no number, but its one unnamed merge stays in that repository.
    stated = stated_repos(text)
    if stated and (len(stated) > 1 or merge_target_repo(selector, repo, cwd) not in stated):
        return False
    return unnamed_merge_ok(payload, window[0], number)


# A STANDING merge instruction: Simon says, once, to merge when a future condition holds ("fix those
# then merge and deploy all when they're ready", "merge 12 once CI is green"), or to merge them all
# ("merge all", "merge them all", "merge everything"), which carries the same implied condition. It
# keeps its authority across later turns of the SAME session (the ledger is read by session id), so an
# unrelated later message no longer voids it (the fix for a green PR blocked after a message about a
# rotated API key arrived between the instruction and CI going green). Its condition is checked,
# never assumed: the PR must be open, not a draft, mergeable, and report at least one check with
# every check passed. A check is judged by its LATEST run only, as branch protection does: a run
# superseded by a rerun no longer counts (the fix for a green PR blocked by two cancelled runs of a
# concurrency-grouped workflow), while a check whose latest run failed still blocks. A plural still
# covers only open PRs this session pushed. An explicit merge ask that NAMES a PR number ("merge
# 1191", "yes merge #1198") is standing for that PR alone until it merges or a later message halts it
# or says close naming it, with the same readiness check (the fix for a queued merge that GitHub's
# queue dropped on a CI API 503, whose re-enqueue next turn was denied because "merge 1191" was this
# turn's ask only). The condition may come before or after the verb, with or without "then" (or its
# typo "them"): "merge it when it's green", "once green then merge", "if it's safe merge it", "when
# it's ready and safe for prod ie no regressions then merge and deploy" (the fix for that last one
# blocked because its condition came first and its "no regressions" was read as "don't merge").
CONDITIONAL_RE = re.compile(
    r"\b(when|whenever|once|as soon as|as|after|if)\s+(?:[\w-]+(?:'\w+)?\s+){0,4}?"
    r"(ready|green|pass|passes|passed|passing|succeeds?|done|finished|complete[sd]?|clean|safe|stable"
    r"|approved)\b", re.I)
# A later message cancels a standing instruction when it negates merging, pushing, deploying or
# shipping, or says stop/hold/wait/cancel/pause AS AN ORDER: at the start of the message or a clause,
# after please/ok/and/but/now/just, in a message of three words or fewer, or within four words of
# merge/push/deploy/ship/it/them/a PR number. A halt word a subject or subordinator describes ("while
# we wait", "the bot will wait", "I'll pause") is not an order, even near a merge word. A bare "don't"
# about something else does not halt either: the instruction spans many messages, and most of them
# are about other work (the fix for "when ready merge and deploy both" cancelled by a later question,
# "so will this work while we wait for appstoreconnect review?").
STANDING_NEGATED_RE = NEGATED_RE
STANDING_HALT_RE = re.compile(r"\b(stop|hold|wait|cancel|pause)\b", re.I)
HALT_ORDER_RE = re.compile(r"(?:^|[.,;:!?\n]|\b(?:please|pls|ok|okay|and|but|now|just|then|hey)\b)[\s,]*"
                           r"\b(stop|hold|wait|cancel|pause)\b", re.I)
HALT_TARGET_RE = re.compile(r"\b(?:merg\w*|push\w*|deploy\w*|ship\w*|it|them|pr)\b|#?\b\d{2,}\b", re.I)
HALT_DESCRIBED_RE = re.compile(r"(?:\b(?:while|until|till|as|when|once|if|because|since)\s+(?:[\w'’]+\s+){0,2}"
                               r"|\b(?:will|would|i[’']?ll|i[’']?d|i[’']?m|we|they|it|he|she|can[’']?t)\s+)$", re.I)
STANDING_CLOSE_RE = re.compile(r"\b(close|closed|closing|abandon)\b", re.I)
# "merge all", "merge them all", "merge both", "merge everything": a merge over the whole set.
STANDING_BULK_RE = re.compile(r"\bmerg(?:e|ed|es|ing)\b[^.\n?]{0,30}?\b(all|everything|every|both|each)\b", re.I)
PASSED_CONCLUSIONS = {"SUCCESS", "NEUTRAL", "SKIPPED"}


def session_asks(payload: dict) -> list:
    """Every ask Simon typed this session, oldest first, cleaned like turn_asks."""
    raw = ledger_asks(payload, "1970-01-01T00:00:00Z")
    # A typographic apostrophe ("don’t merge") reads like the ASCII one, so a halt is never missed.
    return clean_asks(raw)


def halts_standing(ask: str) -> bool:
    """True when a later message cancels a standing merge: it negates the verb, or orders a halt."""
    if STANDING_HALT_RE.search(ask) and len(re.findall(r"[\w'’#]+", ask)) <= 3:
        return True
    if HALT_ORDER_RE.search(ask):
        return True
    for m in STANDING_HALT_RE.finditer(ask):
        before = re.search(r"(?:[\w'’#]+\W+){0,4}$", ask[:m.start()]).group(0)
        after = re.match(r"(?:\W+[\w'’#]+){0,4}", ask[m.end():]).group(0)
        if not HALT_DESCRIBED_RE.search(ask[:m.start()]) and HALT_TARGET_RE.search(before + " " + after):
            return True
    return any(not (STANDING_HALT_RE.match(m.group(0)) and HALT_DESCRIBED_RE.search(ask[:m.start()]))
               for m in STANDING_NEGATED_RE.finditer(ask))


def standing_merge_ask(asks: list, number: str = "") -> str:
    """The session's newest standing merge ask with no later halt, or "". Standing asks are
    conditional ones, merge-all ones, and (given `number`) an explicit merge ask that names that PR."""
    named = re.compile(rf"(?<!\d){number}(?!\d)") if number else None
    for i in range(len(asks) - 1, -1, -1):
        ask = asks[i]
        standing = CONDITIONAL_RE.search(ask) or STANDING_BULK_RE.search(ask) or (
            named and named.search(ask) and not excluded(ask, number))
        if instructs(ask, "merge") and standing and not STANDING_NEGATED_RE.search(ask):
            later = asks[i + 1:]
            halted = any(halts_standing(a) or (named and STANDING_CLOSE_RE.search(a) and named.search(a))
                         for a in later)
            return "" if halted else ask
    return ""


def _check_time(c: dict) -> str:
    """completedAt, else startedAt, as an ISO string; "" when neither is set (gh reports an unset
    time as 0001-01-01)."""
    for field in ("completedAt", "startedAt"):
        t = str(c.get(field) or "")
        if t and not t.startswith("0001-"):
            return t
    return ""


def latest_checks(rollup: list) -> list:
    """The newest entry per check identity (a CheckRun's workflowName + name, a StatusContext's
    context), by completedAt, else startedAt, else list order. Branch protection reads only the
    latest run per check, so a superseded run never decides readiness. A pending entry always ranks
    newest: an unfinished run has not been superseded, and a queued rerun may carry no time yet."""
    latest: dict = {}
    for i, c in enumerate(c for c in rollup if isinstance(c, dict)):
        if "state" in c and "status" not in c:
            key = ("status", c.get("context") or c.get("name") or "")
            pending = c.get("state") in ("PENDING", "EXPECTED")
        else:
            key = ("run", c.get("workflowName") or "", c.get("name") or "")
            pending = c.get("status") != "COMPLETED"
        rank = (pending, _check_time(c), i)
        if key not in latest or rank >= latest[key][0]:
            latest[key] = (rank, c)
    return [c for _, c in latest.values()]


def pr_not_ready(pr: dict) -> str:
    """Why the PR fails the standing instruction's condition right now; "" when it is ready."""
    if not pr:
        return "the PR lookup failed"
    if pr.get("state") != "OPEN":
        return f"the PR is {str(pr.get('state', 'unknown')).lower()}"
    if pr.get("isDraft"):
        return "the PR is a draft"
    if pr.get("mergeable") != "MERGEABLE":
        return f"mergeable is {pr.get('mergeable') or 'unknown'}"
    checks = latest_checks(pr.get("statusCheckRollup") or [])
    if not checks:
        return "no CI checks are reported"
    for c in checks:
        name = c.get("name") or c.get("context") or "a check"
        if "state" in c and "status" not in c:  # a commit status context
            if c.get("state") != "SUCCESS":
                return f"{name} is {str(c.get('state')).lower()}"
        elif c.get("status") != "COMPLETED":
            return f"{name} is still {str(c.get('status') or 'pending').lower()}"
        elif c.get("conclusion") not in PASSED_CONCLUSIONS:
            return f"{name} concluded {str(c.get('conclusion')).lower()}"
    return ""


def standing_merge(payload: dict, words: list, cwd) -> tuple:
    """(allowed, why_not) under a standing merge instruction. why_not is "" when no
    standing instruction covers this PR, so the deny message only reports a failed condition."""
    selector, number, repo = merge_target(words)
    if not number:
        return False, ""
    asks = session_asks(payload)
    ask = standing_merge_ask(asks, number) or standing_merge_ask(asks)
    if not ask or not covers(ask, number, payload, selector, repo, cwd):
        return False, ""
    why = pr_not_ready(pr_view(selector, repo, cwd))
    return (not why), why


# A MONITORING-ONLY merge: Simon gave standing authorization (references/git-pr-deploy.md §
# Monitoring-only changes) for a PR whose every file sits inside the paths his local overlay declares
# for the project's monitoring bot (bin/monitoring_only.py owns the class). With no merge words it runs
# only when ALL hold, each read fresh, and any read error declines:
#   - the command is ONE plain `gh pr merge <N> -R github.com/<owner/name> --match-head-commit <40-hex sha>`
#     with at most one --squash (or -s) flag: no env assignment, wrapper, pipe, compound,
#     substitution, GH_REPO/GH_HOST in the environment, --auto or --admin, so what is checked is what
#     merges, and GitHub refuses the merge if the head moved after the check;
#   - the overlay entry lists that exact owner/name and declares the paths;
#   - one gh pr view of that repo shows the PR open, isDraft false, MERGEABLE, merge state CLEAN or
#     HAS_HOOKS, review decision none or APPROVED, based on the default branch, every check passing as
#     monitoring_not_ready reads it (each overlay requiredChecks entry SUCCESS on every run on the head), a
#     squash merge (no queue, or a queue that squashes), a complete file list with
#     known change types (no rename or copy) and every path inside the paths, and a head equal to the
#     pinned sha; and the base renamed, copied or removed none of the PR's paths since it branched;
#   - this session's newest gate record for that branch and exact head is a standard or deep PASS
#     whose reason ends with monitoring_only.BAR_PHRASE;
#   - Simon's asks read cleanly and no hold stands (monitoring_halt reads the whole session in order).
# No --rebase: replaying the PR's commits one by one can undo a base change the PR's net file list never
# shows (a commit that repeats a base change, then one that reverts it). Squash or a merge commit applies
# the net diff the file list describes.
# Squash only: a merge commit would make every ancestor PR's head part of the default branch, which GitHub
# then marks merged too (a product PR the bot branched from, its change reverted in the bot PR). No -d: it
# switches and pulls the local checkout.
MONITORING_FLAGS = {"--squash", "-s"}
# One budget for the whole hook run, under the timeout settings.json gives this hook: a hook that runs
# past its timeout is a non-blocking error, so the merge would go ahead. Every subprocess on this path
# gets only the time left, and the path declines once too little remains.
HOOK_STARTED = time.monotonic()
MONITORING_BUDGET_S = 22.0  # 8 s under the 30 s hook timeout: the scans after the last read and the deny fit


class OutOfTime(Exception):
    pass


def bounded(limit: float) -> float:
    """A timeout for the older merge paths' reads: at most `limit`, and never into the last 6 s the
    deny message keeps for itself."""
    left = MONITORING_BUDGET_S - 6 - (time.monotonic() - HOOK_STARTED)
    if left < 0.5:
        raise OutOfTime()  # main() turns it into a deny, never a timed-out hook
    return min(limit, left)


def time_left(need: float = 0.5) -> float:
    left = MONITORING_BUDGET_S - (time.monotonic() - HOOK_STARTED)
    if left < need:
        raise OutOfTime()
    return left
# Read from the hook's own environment, which the harness shares with the Bash tool's; a host set only
# in a shell profile could still differ, which the full --match-head-commit pin makes fail at GitHub.
MONITORING_ENV = ("GH_REPO", "GH_HOST", "GH_ENTERPRISE_TOKEN", "GITHUB_ENTERPRISE_TOKEN")
MONITORING_FIELDS = ("number,headRefName,headRefOid,baseRefName,state,url,isDraft,mergeable,"
                     "mergeStateStatus,reviewDecision,statusCheckRollup,files,changedFiles")
GATE_LINE_RE = re.compile(r"\Agate: ([^\s]+) ([0-9a-f]+) (PASS|BLOCKED|N/A)(?: (light|standard|deep)(?= |$))?([^\n]*)\Z")
FULL_SHA_RE = re.compile(r"[0-9a-f]{40}")
APOSTROPHES = str.maketrans({"’": "'", "‘": "'", "ʼ": "'"})


def _unrecorded(payload: dict) -> bool:
    """True when the prompt recorder failed to append one of this session's prompts."""
    try:
        os.stat(os.path.join(STATE_DIR, f"{session_id(payload)}.unrecorded"))
    except FileNotFoundError:
        return False
    except OSError:
        return True  # the marker cannot be checked: treat it as present
    return True


def _ledger_read(payload: dict, *args: str) -> tuple:
    """(ok, stdout) from this hook's sibling intent-ledger.sh; ok False on any failure, so the
    monitoring path can tell a failed read from an empty one."""
    script = os.path.join(os.path.dirname(os.path.realpath(__file__)), "intent-ledger.sh")
    if not os.path.isfile(script):
        return False, ""
    try:
        p = _run(["bash", script, *args], text=True, capture_output=True, timeout=min(5, time_left()),
                           input=json.dumps({"session_id": payload.get("session_id", ""),
                                             "cwd": payload.get("cwd", "")}))
    except OutOfTime:
        raise
    except Exception:
        return False, ""
    return p.returncode == 0, p.stdout or ""


def _monitoring_module():
    bin_dir = os.path.join(os.path.dirname(os.path.realpath(__file__)), "..", "bin")
    if bin_dir not in sys.path:
        sys.path.insert(0, bin_dir)
    try:
        import monitoring_only
    except Exception as exc:  # a named cause, not a bare traceback: every caller still declines
        raise RuntimeError(f"bin/monitoring_only.py could not be loaded ({type(exc).__name__}: {exc})") from exc
    return monitoring_only


def monitoring_shape(command: str) -> tuple:
    """(number, slug, pinned sha, why_not) for the one command shape the path accepts."""
    if not re.fullmatch(r"[ -~]+", command) or any(ch in command for ch in ";&|<>()$`\\'\"") \
            or any(os.environ.get(k) for k in MONITORING_ENV):
        return "", "", "", "the command must be one plain `gh pr merge`, with no shell syntax or GH_REPO/GH_HOST"
    words = command.split()
    if words[:3] != ["gh", "pr", "merge"]:
        return "", "", "", "the command must start with `gh pr merge`, with no env assignment or wrapper"
    number = slug = pinned = ""
    flags = set()
    rest = words[3:]
    while rest:
        w = rest.pop(0)
        if w in ("-R", "--repo", "--match-head-commit") and rest:
            value = rest.pop(0)
            if w == "--match-head-commit":
                pinned = value if not pinned else "conflict"
            else:
                slug = value if not slug else "conflict"
        elif w.startswith("--repo="):
            slug = w.split("=", 1)[1] if not slug else "conflict"
        elif w.startswith("--match-head-commit="):
            pinned = w.split("=", 1)[1] if not pinned else "conflict"
        elif w in MONITORING_FLAGS:
            if "method" in flags:
                return "", "", "", f"`{w}` repeats a method flag"
            flags.add("method")
        elif re.fullmatch(r"\d+", w) and not number:
            number = w
        else:
            return "", "", "", f"`{w}` is outside the monitoring-only merge shape"
    if not number:
        return "", "", "", "the command names no bare PR number"
    host_slug = re.fullmatch(r"github\.com/([A-Za-z0-9_.-]+/[A-Za-z0-9_.-]+)", slug)
    if not host_slug:
        return "", "", "", ("the command needs `-R github.com/<owner>/<name>` naming the repository once, "
                            "so the host is pinned whatever GH_HOST the shell sets")
    slug = host_slug.group(1)
    if not FULL_SHA_RE.fullmatch(pinned.lower()):
        return "", "", "", "the command needs `--match-head-commit <full 40-character head sha>` once"
    return number, slug, pinned.lower(), ""


def _gh_env() -> dict:
    env = {k: v for k, v in os.environ.items() if k not in MONITORING_ENV}
    return {**env, "GH_HOST": "github.com"}


def monitoring_default_branch(slug: str) -> str:
    try:
        p = _run(["gh", "repo", "view", slug, "--json", "defaultBranchRef", "-q", ".defaultBranchRef.name"],
                           capture_output=True, text=True, timeout=min(8, time_left()), env=_gh_env())
    except OutOfTime:
        raise
    except Exception:
        return ""
    name = p.stdout.strip() if p.returncode == 0 else ""
    return name if re.fullmatch(r"[\w./-]+", name) else ""


def monitoring_base_moves(slug: str, head: str, base: str, paths: set) -> str:
    """Why the base branch's own changes since the PR branched could carry the PR's edit outside the
    bot paths; "" when they cannot. Git applies an edit to a file the base renamed at its new path, so a
    PR whose file list is all bot paths could still change a product file: any base-side rename, copy
    or removal of a path the PR touches declines, as does a compare that cannot be read whole."""
    try:
        # The branch name is URL-encoded: a "#" or "?" in it would otherwise cut the path short.
        p = _run(["gh", "api", f"repos/{slug}/compare/{head}...{quote(base, safe='')}"], capture_output=True,
                           text=True, timeout=min(8, time_left()), env=_gh_env())
        data = json.loads(p.stdout) if p.returncode == 0 else None
    except OutOfTime:
        raise
    except Exception:
        data = None
    if not isinstance(data, dict) or not isinstance(data.get("files"), list):
        return "the base branch's changes since the PR branched could not be read"
    files = data["files"]
    if len(files) >= 300:
        return "the base branch changed 300 or more files since the PR branched, so the list may be cut"
    for f in files:
        status = f.get("status") if isinstance(f, dict) else None
        if (status not in ("added", "modified", "removed", "renamed", "copied", "changed", "unchanged")
                or not isinstance(f.get("filename"), str)
                or (status in ("renamed", "copied") and not isinstance(f.get("previous_filename"), str))):
            return "the base branch's changes since the PR branched could not be read"
        before = f.get("previous_filename") or f.get("filename")
        parts = before.split("/")[:-1]
        folders = ["/".join(parts[:k]) + "/" for k in range(1, len(parts) + 1)]
        # A rename moves the PR's edit to the file, and git's directory-rename detection can move a file the
        # PR adds anywhere under a renamed folder, so a PR path under any folder of the old path declines too.
        if status in ("renamed", "copied", "removed") and (
                {before, f.get("filename")} & paths or any(x.startswith(d) for d in folders for x in paths)):
            return (f"the base branch {status} {before} since the PR branched, so the PR's edit to it or "
                    "beside it could land elsewhere: merge the base in and rerun the bar")
    return ""


def monitoring_merge_method(slug: str, base: str, command: str) -> str:
    """Why the merge would not squash; "" when it does. A merge queue on the base uses its own method,
    which must be SQUASH; with no queue the command must name --squash. A rebase replays commits and a
    merge commit marks ancestor PRs merged, so both decline. An unreadable rule set declines."""
    try:
        p = _run(["gh", "api", f"repos/{slug}/rules/branches/{quote(base, safe='')}"], capture_output=True, text=True,
                           timeout=min(8, time_left()), env=_gh_env())
        rules = json.loads(p.stdout) if p.returncode == 0 else None
    except OutOfTime:
        raise
    except Exception:
        rules = None
    if not isinstance(rules, list) or not all(isinstance(r, dict) and isinstance(r.get("type"), str) and r["type"]
                                              for r in rules):
        return f"the rules on {base} could not be read, so the merge method is unknown"
    # A queue set up in classic branch protection is absent from the rule set: GraphQL's mergeQueue
    # covers both kinds, and an unreadable answer declines.
    owner, _, name = slug.partition("/")
    query = ("query($o:String!,$n:String!,$b:String!){repository(owner:$o,name:$n)"
             "{mergeQueue(branch:$b){configuration{mergeMethod}}}}")
    try:
        g = _run(["gh", "api", "graphql", "-f", f"query={query}", "-F", f"o={owner}", "-F", f"n={name}",
                            "-F", f"b={base}"], capture_output=True, text=True, timeout=min(8, time_left()),
                           env=_gh_env())
        repo_data = ((json.loads(g.stdout) if g.returncode == 0 else {}).get("data") or {}).get("repository")
    except OutOfTime:
        raise
    except Exception:
        repo_data = None
    if not isinstance(repo_data, dict) or "mergeQueue" not in repo_data:
        return f"the merge queue on {base} could not be read, so the merge method is unknown"
    graph_queue = repo_data.get("mergeQueue")
    if graph_queue is not None:
        method = str(((graph_queue or {}).get("configuration") or {}).get("mergeMethod") or "").upper()
        if method != "SQUASH":
            return f"the merge queue on {base} uses {method or 'an unknown method'}"
    queues = [r for r in rules if r.get("type") == "merge_queue"]
    if graph_queue is not None and not queues:
        return ""
    if queues:
        methods = {str((r.get("parameters") or {}).get("merge_method") or "").upper() for r in queues}
        return "" if methods == {"SQUASH"} else f"the merge queue on {base} uses {', '.join(sorted(methods))}"
    words = command.split()
    return "" if MONITORING_FLAGS & set(words) else "with no merge queue the command must name --squash"


def monitoring_pr(number: str, slug: str) -> dict:
    try:
        p = _run(["gh", "pr", "view", number, "--repo", slug, "--json", MONITORING_FIELDS],
                           capture_output=True, text=True, timeout=min(8, time_left()), env=_gh_env())
        pr = json.loads(p.stdout) if p.returncode == 0 else {}
    except OutOfTime:
        raise
    except Exception:
        pr = {}
    return pr if isinstance(pr, dict) else {}


CHECK_PAGE = 100  # gh reads at most this many contexts; a full page may be truncated


def monitoring_not_ready(pr: dict, required: list, default_branch: str, collect: list = None) -> str:
    """Stricter than pr_not_ready, and local to this path. isDraft must be false, the base the default
    branch, and the check list complete and well formed. Nothing may be pending, and any failed or
    cancelled check declines, a rerun gone green included. Each of the overlay's requiredChecks must
    have succeeded on every run on the head, so a rollup of skips alone never passes. The hook takes the
    first failing check; the --explain dry-run passes `collect` to list every one."""
    found = []
    for why in itertools.chain(_monitoring_state_causes(pr, default_branch), _monitoring_check_causes(pr, required)):
        if collect is None:
            return why
        found.append(why)
    if collect is not None:
        collect.extend(found)
    return found[0] if found else ""


def _monitoring_state_causes(pr: dict, default_branch: str):
    """Each failing PR-state check of monitoring_not_ready, in its order."""
    if pr.get("state") != "OPEN":
        yield f"the PR is {str(pr.get('state', 'unknown')).lower()}"
    if pr.get("isDraft") is not False:
        yield "the PR is a draft" if pr.get("isDraft") else "the PR's draft state could not be read"
    if pr.get("mergeable") != "MERGEABLE":
        yield f"mergeable is {pr.get('mergeable') or 'unknown'}"
    # Only a PR GitHub would merge or enqueue at once: anything short of that (a review still required,
    # the branch behind, a blocked rule) makes `gh pr merge` turn on auto-merge, which merges later with
    # no further check.
    if pr.get("mergeStateStatus") not in ("CLEAN", "HAS_HOOKS"):
        yield f"the merge state is {pr.get('mergeStateStatus') or 'unknown'}, so the merge would not run at once"
    # No decision (null, or "" as gh prints it) or APPROVED; a missing key or any other value is unknown.
    if "reviewDecision" not in pr or pr["reviewDecision"] not in (None, "", "APPROVED"):
        yield f"the review decision is {pr.get('reviewDecision') or 'unreadable'}"
    if not default_branch or pr.get("baseRefName") != default_branch:
        yield (f"the PR targets {pr.get('baseRefName') or 'an unknown branch'}, not the repository's "
                f"default branch {default_branch or '(unreadable)'}")


def _monitoring_check_causes(pr: dict, required: list):
    """Each failing check-list condition of monitoring_not_ready, in its order. An unreadable or possibly
    truncated list ends the read; any other failure reads on, so the first yielded is the hook's cause."""
    rollup = pr.get("statusCheckRollup")
    if not isinstance(rollup, list) or not rollup or not all(isinstance(c, dict) for c in rollup):
        yield "the PR's checks could not be read"
        return
    if len(rollup) >= CHECK_PAGE:
        yield f"the PR reports {len(rollup)} checks, so the list may be truncated"
        return
    runs = []
    for i, c in enumerate(rollup):
        if "state" in c and "status" not in c:  # a commit status context
            if not c.get("context"):
                yield "a check on the PR has no name or status"
            elif c.get("state") != "SUCCESS":
                yield f"{c['context']} is {str(c.get('state')).lower()}"
            continue
        if not (c.get("name") and c.get("status")):
            yield "a check on the PR has no name or status"
            continue
        if c.get("status") != "COMPLETED":
            yield f"{c['name']} is still {str(c.get('status')).lower()}"
            continue
        stamp = _check_time(c)
        when = None
        if stamp:  # compared as instants, never as strings ("12:00:00Z" before "12:00:00.500Z")
            m = re.fullmatch(r"(\d{4}-\d\d-\d\dT\d\d:\d\d:\d\d)(?:\.(\d{1,6})\d*)?Z", stamp)
            if not m:
                yield f"{c['name']} carries an unreadable time ({stamp[:30]}), so the order of its runs is unknown"
                continue
            when = datetime.datetime.strptime(m.group(1), "%Y-%m-%dT%H:%M:%S").replace(
                microsecond=int((m.group(2) or "0").ljust(6, "0")))
        runs.append(((c.get("workflowName") or "", c["name"]), "", when, i, c))
    for key, run, when, i, c in runs:
        # Any failed or cancelled check declines, even beside a later success of the same name: two jobs
        # can share a display name in one run, so a success is no proof the failed job ran again. After a
        # rerun, the PR waits for Simon's merge word.
        verdict = c.get("conclusion")
        # Stricter than PASSED_CONCLUSIONS on purpose: a NEUTRAL check declines here too.
        if verdict not in ("SUCCESS", "SKIPPED"):
            yield f"{key[1]} concluded {str(verdict).lower()}"
    for name in required:
        workflow, job = name.split(" / ", 1)
        ran = [r for r in runs if r[0] == (workflow, job)]
        if any(not r[2] for r in ran):
            yield f"a run of the bot's own check {name} has no recorded time, so its latest run is unknown"
        # Every run of a required bot check on this head must succeed: which run is newest cannot be read
        # for certain from start and finish times that overlap, so an older success never masks a skip.
        if not ran or any(r[4].get("conclusion") != "SUCCESS" for r in ran):
            yield f"the bot's own check {name} has not succeeded on every run"


# The halt reading on this path fails closed; a hold naming PRs holds only those (_hold_scope). _is_hold and
# _lifts are the predicates. A hold is an explicit hold aimed at merging or shipping, read as WHOLE
# words and phrases (HOLD_RES): a hold word given as an order ("hold the bot PRs", "wait before
# merging", "stop"), a negated merge or ship ("don't merge #1405", "do not deploy"), or a hold phrase
# ("not yet", "leave it open", "nothing goes live", "needs my sign-off"). A mention of the bot, a PR,
# merging or a fix holds nothing, and neither does "not", "if" or "no" alone (Simon, 2026-11-23: the
# old reading held on any bot, PR or merge mention and on prefix-matched words, so 25 of his last 30
# messages held, his own "look at sre bots threads and see if we need to make any more fixes" too, and
# the automatic path never ran). Only a whole raw message matching LIFT_RE lifts a hold.
MARKUP_RE = re.compile(r"<[A-Za-z!/][^<>]*>")
# System text inside Simon's prompt is not his words: the harness blocks, a host's `<system_instruction>`
# (Conductor's workspace notes and attachment lists) and a slash command's own name tags.
SYSTEM_TAG_RE = re.compile(r"<(system-reminder|task-notification|agent-message|cross-session-message"
                           r"|system_instruction|command-message|command-name)\b[^>]*>", re.I)


def own_words(text: str) -> str:
    """The text with every closed system block removed, in linear time: each tag name's closing tag is
    searched for once it is missing, so many unclosed tags cannot make the strip quadratic."""
    lower, out, last, pos, missing = text.lower(), [], 0, 0, set()
    while True:
        m = SYSTEM_TAG_RE.search(text, pos)
        if not m:
            break
        name = m.group(1).lower()
        close = -1 if name in missing else lower.find("</" + name + ">", m.end())
        if close < 0:
            missing.add(name)
            pos = m.end()
            continue
        out.append(text[last:m.start()])
        last = pos = close + len(name) + 3
    out.append(text[last:])
    return "".join(out)
MERGE_VERB = (r"(?:(?:auto-?)?(?:merge|merging)|ship|shipping|deploy|deploying|land|release|releasing"
              r"|roll(?:ing)? ?out)\b|go(?:es|ing)? live\b")
# A hold word ordering something else ("stop alerting on 429s", "pause sending") is a bot fix, not a hold.
NOT_MERGE_GERUND = r"(?!\s+(?!merg|ship|deploy|releas|land|(?:every|any|no|some)thing\b)[A-Za-z]+ing\b)"
HOLD_WORD = (r"(?:hold|holding|wait|stop|pause|paused|pausing|cancel|halt|freeze|freezing|abort|belay|veto"
             r"|suspend|refrain|shelve|shelf|embargo|park|parked)\b")
# A clause-joining word ends a negation's reach: "no regressions then merge" negates the regressions.
HOLD_JOIN = r"(?:yes|and|then|them|so|ok|okay|ie|but|or|if|when|once)\b"
HOLD_RES = [re.compile(p, re.I | re.A) for p in (
    # A hold word as an order: at the start of the message or a clause, after a softener, or first person.
    r"(?:^|[.,;:!?(]\s*|\b(?:please|pls|ok|okay|and|but|now|just|then|hey|so|no|nope|actually|guys)\s+)"
    + HOLD_WORD + NOT_MERGE_GERUND,
    r"\b(?:i|we|let'?s|lets)\s+(?:(?:should|must|will|need to|want to|have to|would|d|'d|'ll|ll)\s+)?" + HOLD_WORD
    + NOT_MERGE_GERUND,
    # A hold word aimed at a merge: a merge or ship word, a PR or a PR number within four words after it.
    r"\b" + HOLD_WORD + r"(?:\s+[\w'#-]+){0,4}?\s+(?:" + MERGE_VERB + r"|merges\b|deploys\b|releases\b|prs?\b"
    r"|pull requests?\b|#\d+)",
    # A negated merge or ship, the verb within two words of the negator, no clause crossing.
    r"\b(?:don'?t|dont|do not|never)\s+(?:(?!" + HOLD_JOIN + r")[\w'-]+\s+){0,4}?(?:" + MERGE_VERB + r"|push\b)",
    r"\b(?:not|without)\s+(?:(?!" + HOLD_JOIN + r")[\w'-]+\s+){0,2}?(?:" + MERGE_VERB + ")",
    # A merge told to wait: "the merge can wait until tomorrow", "merging must wait".
    r"\b(?:merg\w*|ship\w*|deploy\w*|prs?|it|that|this|they|these|those)\s+(?:must|can|should|will|has to|have to"
    r"|needs? to|is going to|are going to)\s+(?:wait|hold|pause)\b",
    r"\bno (?:more )?(?:(?:auto-?)?merg\w*|ship\w*|deploy\w*)",
    # A passive negated merge: "should not be merged", "mustn't get shipped".
    r"(?:\b(?:should|must|will|can|could|would|may|to)\s+(?:not|never)|\b(?:shouldn|mustn|won|can|couldn|wouldn)'?t)"
    r"\s+(?:be|get)\s+(?:auto-?)?(?:merged|shipped|deployed|released)\b",
    r"(?<!\bor )\bnot (?:yet|now|today)\b",
    # A PR set apart from a merge: "merge #1300 but not #401", "all except 401".
    r"\b(?:not|except|excluding|apart from|other than)\s+(?:pr\s*)?(?:#\d+|\d{2,}\b)",
    r"\b(?:hang|hold) (?:on|off|fire)\b|\bsit tight\b|\bstand ?by\b|\bon (?:hold|ice|pause)\b|\boff[- ]limits\b",
    r"\b(?:(?:give me|gimme)(?: a| one| 1)?|one|1|just a) (?:sec|second|minute|min|moment)\b",
    r"\bhands[- ]?off\b|\bhands away\b",
    r"\b(?:leave|leaving|keep|keeping)\s+(?:it|them|that|this|those|these|(?:the\s+|all\s+)?(?:[\w'-]+\s+){0,2}?"
    r"(?:prs?|pull requests?|fix(?:es)?|branch(?:es)?|merges?|#\d+))\s+(?:open|alone|unmerged|as is)\b"
    r"|\b(?:leave|leaving)\s+(?:it|them|that|this|those|these)(?:\s+\w+)?\s+(?:for now|there)\b"
    r"|\b(?:set|put|kept|keep)\s+(?:[\w'#-]+\s+){0,2}?aside\b",
    r"\b(?:stays?|staying|remains?|remain|kept)\s+(?:open|unmerged|on hold)\b"
    r"|\b(?:is|are|be|being)\s+(?:held|paused|frozen|embargoed)\b",
    r"\bnothing (?:goes|gets|should go|is going|ships|lands|merges|deploys)\b",
    r"\bwithout (?:me|my|asking|checking)\b|\b(?:my|me) (?:sign-?off|say|say-?so|approval|go-?ahead|call|decision)\b",
    r"\b[A-Za-z]+'s (?:call|decision|sign-?off|approval|say)\b|\bneeds? (?:my|your|his|her|their|[A-Za-z]+'s) (?:review|approval|sign-?off|go-?ahead|ok)\b"
    r"|\b(?:prs?|pull requests?|#\d+|merges?|it|this|that)\s+needs?\s+(?:a\s+|more\s+)?(?:review|approval|sign-?off)\b",
    # A merge gated on a person: "until I approve", "blocked until Bob signs off".
    r"\buntil\s+(?:i|me|my|we|you|[A-Z][a-z]+)\s+(?:\w+\s+)?(?:approve|approves|review|reviews|sign|signs|say|says|check"
    r"|checks|look|looks|ok|okay|decide|decides)\b|\b(?:merg\w*|prs?|pull requests?|it)\s+(?:is|are)\s+blocked\b",
    r"\b(?:i'?ll|i will|i'?d like to|i want to|i wanna|let me|lemme)\s+(?:\w+\s+)?(?:review|test|eyeball|merge|ship|deploy"
    r"|land|decide|approve|sign off)\b",
    r"\bforbid\w*|\bforbade\b|\bprohibit\w*|\bunmerged\b|\bembargo\w*|\bdisable (?:\w+ )?auto-?merg\w*|\bno[- ]go\b",
    r"\b(?:close|closing)\s+(?:[\w'-]+\s+){0,3}?(?:prs?|pull requests?|#\d+)\b",
)]


# A lift is ONLY a message that is, whole, a plain unconditional merge of this PR or of the bot class:
# "merge #12", "ok merge the bot fixes", "please merge the monitoring PRs now". Anything more (a
# condition, a person, a time, a report, a question) is no lift.
LIFT_RE = re.compile(
    r"\A(?:(?:ok|okay|yes|yep|sure|please|go ahead|and|so|then)[\s,!.]+)*merge\s+(?:"
    r"(?:pr\s*)?#?(?P<n>\d+)"
    r"|(?:the\s+|all\s+(?:the\s+)?)?(?:bot|monitoring|sre)(?:'s)?(?:\s+(?:fix|fixes|prs?|changes?))?"
    r")(?:\s+(?:now|please))?[\s.!]*\Z", re.I)


def _names(ask: str, number: str) -> bool:
    """The ask names this PR by value ("#012" names 12)."""
    return any(int(n) == int(number) for n in re.findall(r"(?<![\d.])\d+(?!\d|\.\d)", ask) if len(n) < 12)


# A hold that names PRs holds those PRs only, never every monitoring-only PR (Simon, 18 Nov: "merge 1296.
# also the sre bot has another pr .../pull/1298 - should we ... cancel this pr?" questioned #1298 alone,
# yet it held PR #1399 on 23 Nov because any number in a hold made it need "merge #1399"). A PR is named
# by "#<n>", "PR <n>", "pull request <n>", a /pull/<n> URL, "GH-<n>", a merge, close or cancel verb
# before a run of numbers of three or more digits ("merge 1294 1295 1296"), or such a number opening a
# line as a list item ("1306 - i think we should cancel this", his 18 Nov 10:02 list). The hold stays a
# class hold, holding every PR, when no PR is named, when a holding sentence speaks of the class, a
# related PR, a range or a condition ("all", "the bot queue, including #1405", "its sibling",
# "PR10-PR20", "until #13 lands"), when a named PR sits near an unnamed one ("hold #1405, and this PR"),
# when the sentences naming no PR hold on their own, or when no single sentence holds.
PR_REF_RE = re.compile(r"(?:#|\bprs?\s*#?\s*|\bpull\s+requests?\s*#?\s*|/pulls?/|\bgh-)(\d+)\b"
                       r"|\b(?:merge|merging|close|closing|cancel|cancell?ing|land|ship)\s+"
                       r"((?:#?\d{3,}\b[\s,]*(?:(?:and|&)\s+)?)+)"
                       r"|\A\s*[>*-]?\s*#?(\d{3,})\s*[-:)]\s", re.I | re.A)
_DEICTIC_PR = (r"(?:this|that|the current|current|the other|these|those|your|my|our|it|its)"
               r"(?:\s+(?:one|ones|prs?|pull requests?|fix|fixes|change|changes|branch|branches))?\b")
CLASS_HOLD_RE = re.compile(r"\b(?:all|any|every\w*|anything|nothing|none|others?|rest|remaining|prs|pull requests"
                           r"|fixes|merges|changes|until|unless|before|after|once|when|while|till|both|siblings?|related|linked|stack\w*"
                           r"|dependents?|child|children|parents?|follow-?ups?|queue|batch|bunch|lot|set|group|series"
                           r"|wave|round|including|incl|starting|such as|like|e\.?g|for example|among|also|too"
                           r"|as well|plus|other|another|more)\b"
                           # Merging itself held beside a named PR: "hold #1405 and pause auto-merging".
                           r"|\b(?:auto-?)?merg(?:ing|es)\b(?!\s+(?:of\s+)?(?:pr\s*)?#?\d)|\bauto-?merge\b"
                           # A range names PRs it does not spell out: "PR10-PR20", "#10 to #20".
                           r"|\d\s*(?:-|to|through|thru|\.\.)\s*(?:prs?\s*)?#?\d"
                           # A named PR joined to an unnamed one: "hold #1405 and this PR", "this one and #12".
                           r"|(?:#\d+|/pulls?/\d+|\bprs?\s*#?\d+|\bgh-\d+|\d{3,})\s*(?:,|and|or|&|with|along with"
                           r"|together with)\s+" + _DEICTIC_PR +
                           r"|" + _DEICTIC_PR + r"\s*(?:,|and|or|&|with|along with|together with)\s+(?:prs?\s*)?#?\d",
                           re.I | re.A)
SENTENCE_END_RE = re.compile(r"(?<=[.!?;])\s+|\n+")


_UNNAMED_PR_RE = re.compile(r"\b(?:this|that|the current|current|these|those|your|my|our|the)\s+(?:one|ones|prs?"
                            r"|pull requests?|branch|branches|fix|fixes|change|changes)\b(?!\s*(?:pr\s*)?#?\d)",
                            re.I | re.A)


def _unnamed_pr_near_ref(sentence: str) -> bool:
    """An unnamed PR ("this PR", "that one") within eight words of a named one is a second PR held beside it
    ("Hold #1405, and hold this PR."). Farther off it is the named PR spoken of again: Simon's 18 Nov
    "/pull/1298 - should we not leave stripe to handle that ... and cancel this pr?" puts 21 words between."""
    def at(m) -> int:
        return len(sentence[:m.start()].split())
    refs = [at(m) for m in PR_REF_RE.finditer(sentence)]
    return any(abs(at(u) - r) <= 8 for u in _UNNAMED_PR_RE.finditer(sentence) for r in refs)


def _hold_scope(text: str):
    """The PR numbers a hold is confined to, or None for a class hold (every PR). Fails toward None: text
    the hold reading cannot read for certain (_is_hold's fail-closed cases) is a class hold."""
    if (len(text) > HOLD_SCAN_LIMIT or not text.isascii() or "[REDACTED CREDENTIAL]" in text
            or NON_TEXT_PART in text or re.search(r"[\x00-\x08\x0b\x0c\x0e-\x1f\x7f]", text)):
        return None
    named = lambda s: {int(n) for groups in PR_REF_RE.findall(_normalize(s)) for g in groups
                       for n in re.findall(r"\d+", g) if len(n) < 12}
    sentences = [s for s in SENTENCE_END_RE.split(text) if s.strip()]
    refs, rest, scoped = set(), [], False
    for s in sentences:
        found = named(s)
        refs |= found
        if not found:
            rest.append(s)
        elif _is_hold(s, "0"):
            if CLASS_HOLD_RE.search(_normalize(s)) or _unnamed_pr_near_ref(_normalize(s)):
                return None
            scoped = True
    if not refs or not scoped or (rest and _is_hold("\n".join(rest), "0")):
        return None
    # Every other number in it counts as named too ("merge 1296 but not 1298"): the scope only grows.
    return frozenset(refs | {int(n) for n in re.findall(r"\d{2,}", _normalize(text)) if len(n) < 12})


def _numbered(hold: str, number: str) -> bool:
    """A class hold that could name this PR: it carries this PR's number or names a PR (PR_REF_RE). A
    number that names no PR ("1 but this pr can be cancelled?", "after 14 days") leaves it a class hold
    his class restatement lifts (the fix for two numbered answers on 16-17 Nov outliving it on 23 Nov)."""
    norm = _normalize(hold)
    return _names(norm, number) or bool(PR_REF_RE.search(norm))


DASHES = str.maketrans({c: "-" for c in "\u2010\u2011\u2012\u2013\u2014\u2015\u2212\ufe63\uff0d"})


def _normalize(text: str) -> str:
    """The words the way a person reads them, for every hold and PR-number check: compatibility forms
    folded (full-width digits and #), every dash a hyphen, "P.R." as "PR", markdown emphasis and other
    symbols as spaces (`_` is a word character and would hide a hold word from every \\b), and any
    whitespace run as one space."""
    text = unicodedata.normalize("NFKC", text)
    # Invisible format characters (soft hyphen, zero-width joiners) vanish, so "Do\u00adn't" reads "Don't".
    text = "".join(c for c in text if unicodedata.category(c) != "Cf").translate(DASHES).translate(APOSTROPHES)
    text = " ".join(text.split())  # whitespace runs first, so "P.  R." reads as "P. R."
    text = re.sub(r"\bp\s*\.\s*r\s*\.?(?=\W|$|s\b)", "PR", text, flags=re.I)
    text = re.sub(r"[^\w\s'#/.,:;!?()-]|_", " ", text)
    # A digit glued to a word ("1sec", "2hold") is read apart, since \b sees no boundary there.
    text = re.sub(r"(?<=[0-9])(?=[A-Za-z])|(?<=[A-Za-z])(?=[0-9])", " ", text)
    return " ".join(text.split())


HOLD_SCAN_LIMIT = 4000  # characters; a longer message (a pasted log, a token) holds without a scan
SYSTEM_SCAN_LIMIT = 1000000  # characters; system text is stripped up to this length, beyond it the text holds
# A word spelled letter by letter ("S-T-O-P", "w a i t"): its letters are read joined as well.
SPELLED_RE = re.compile(r"(?<![A-Za-z])[A-Za-z](?:[\s.\-*_'+/|~,]+[A-Za-z](?![A-Za-z])){2,}")


def _readings(ask: str) -> list:
    """Every way the message can read once rendered: as typed, NFKC-folded, entities and escapes decoded,
    markup and Markdown link targets dropped, emphasis marks dropped, struck text dropped, punctuation
    inside a word dropped, and each letter-by-letter run joined. A hold in any reading holds."""
    folded = unicodedata.normalize("NFKC", ask)
    decoded = unquote(html.unescape(folded))
    decoded = re.sub(r"\\u([0-9A-Fa-f]{4})", lambda m: chr(int(m.group(1), 16)), decoded)
    decoded = re.sub(r"\\x([0-9A-Fa-f]{2})", lambda m: chr(int(m.group(1), 16)), decoded).replace("\\", "")
    out = [ask, folded, decoded]
    untagged = re.sub(r"<!--.*?(?:-->|$)", "", decoded, flags=re.S)
    out += [re.sub(r"<[^<>]*>", "", untagged), re.sub(r"<[^<>]*>", " ", untagged)]
    # A Markdown link renders its text only: "W[ai](https://x/a(b))t" reads "Wait".
    unlinked = re.sub(r"\]\((?:[^()]|\([^()]*\))*\)|\]\[[^\]]*\]|^\s*\[[^\]]*\]:.*$", "", out[3], flags=re.M)
    unlinked = unlinked.replace("[", "").replace("]", "")
    out += [unlinked, re.sub(r"~~.*?~~", "", unlinked, flags=re.S)]
    out += [re.sub(r"[*_~`]+", "", t) for t in out[-2:]]
    out += [re.sub(r"(?<=[A-Za-z])[^\w\s]+(?=[A-Za-z])", "", t) for t in out[-2:]]
    out += [SPELLED_RE.sub(lambda m: re.sub(r"[^A-Za-z]", "", m.group(0)), t) for t in list(out)]
    return out


def _is_hold(ask: str, number: str) -> bool:
    """True when the message holds. Every reading of it (_readings) is matched against HOLD_RES; what
    cannot be read for certain (a look-alike letter, a control character, a redaction) fails closed."""
    time_left()  # each message costs time: the scan declines through OutOfTime, never runs past the hook
    if len(ask) > HOLD_SCAN_LIMIT:
        return True
    if "[REDACTED CREDENTIAL]" in ask or NON_TEXT_PART in ask:
        return True  # redacted, or an image or file the guard cannot read: what it said is unknown
    if re.search(r"[\x00-\x08\x0b\x0c\x0e-\x1f\x7f]", ask):
        return True  # an ASCII control (a terminal color escape) can glue itself to a word
    folded = unicodedata.normalize("NFKC", ask)
    # Checked on the text as typed AND as folded: NFKC turns some symbols into ASCII letters ("ⓘ" to "i"),
    # which would glue them to the next word.
    if any(ord(c) > 127 and unicodedata.category(c)[0] in "LNSMC" for c in ask + folded):
        # A letter, digit, symbol, mark or control outside ASCII (a look-alike "о", a 🤖, a variation
        # selector, a zero-width joiner) fails closed; only non-ASCII punctuation and spaces read through.
        return True
    return _reads_as_hold(ask)


@functools.lru_cache(maxsize=4096)
def _reads_as_hold(ask: str) -> bool:
    """The reading match, once per distinct text: a session's messages are read from the ledger and the
    transcript, with and without quotes, so the same text comes back many times in one hook run."""
    # Most readings are identical: each distinct one is normalized and matched once.
    seen = dict.fromkeys(_normalize(r) for r in dict.fromkeys(_readings(ask)))
    return any(_is_hold_text(t) for t in seen)


def _is_hold_text(ask: str) -> bool:
    # A negated hold word is no hold: "don't stop merging", "no need to wait, merge it".
    ask = re.sub(r"\b(?:don'?t|dont|do not|never|no need to)\s+" + HOLD_WORD, " ", ask, flags=re.I | re.A)
    if len(re.findall(r"[\w'#]+", ask)) <= 3 and re.search(
            r"\b(?:" + HOLD_WORD + NOT_MERGE_GERUND + r"|don'?t\b|dont\b|do not\b)", ask, re.I | re.A):
        return True  # a message of three words or fewer with a hold word in it ("ok 2wait", "stop pls", "Don't.")
    return any(r.search(ask) for r in HOLD_RES)


# Simon restating the standing class merge is a class lift too ("remember that sre bot fixes which
# don't influence user prod and have been validated should be merged", his third time on 23 Nov): it
# names the bot's fixes or PRs and tells them merged (STANDING_LIFT_RE), carries no PR number, no
# question and no hold, and every word in it is from STANDING_LIFT_WORDS: the bar's own conditions and
# nothing else, so any added person, time, condition or framing ("if Bob consents", "next month", "it
# is false that") makes it no lift.
STANDING_LIFT_RE = re.compile(
    r"\A(?=.*\b(?:sre|monitoring|bot)\b)(?=.*\b(?:fix|fixes|prs?|pull requests?|changes)\b)"
    r"(?=.*(?:\b(?:should|must|can|are to|need to|needs to|to)\s+(?:be|get)\s+merged\b|\bjust\s+merge\s+(?:them|those|these)\b"
    r"|\bget\s+(?:them|those|these)\s+merged\b))", re.I | re.A)
STANDING_LIFT_WORDS = frozenset("""
remember reminder again note please ok okay so yes and also that the any all every sre bot bots
monitoring bot's fix fixes pr prs pull request requests change changes which that are is don't doesn't do does influence influences affect affects touch touches impact impacts change risk user users user's prod production
pay payment paths path flows flow customer customers and or have has been validated tested verified checked green
passed pass passing the bar its their own safe should must can be get merged merge just them those these they
automatically auto always to of with without in on for
""".split())


def _lifts(ask: str, number: str) -> bool:
    """A later ask lifts a hold on this PR only when it is, whole, LIFT_RE: a plain merge of this PR, or
    of the bot class with no PR number; or a restated standing class merge (STANDING_LIFT_RE)."""
    if not re.fullmatch(r"[!-~]+(?: [!-~]+)*", ask):
        # One line of printable ASCII words split by single spaces: no newline, tab or indent can make a
        # code block of it, and case-insensitive Unicode matching cannot read "ı" as "i".
        return False
    m = LIFT_RE.match(ask.strip())
    if not m:
        words = re.findall(r"[a-z']+", ask.lower())
        return (len(ask) <= 300 and bool(STANDING_LIFT_RE.match(ask)) and not re.search(r"[\d?]", ask)
                and all(w in STANDING_LIFT_WORDS for w in words) and not _is_hold(ask, number))
    return bool(m) and (m.group("n") == number if m.group("n") else True)


ANSWER_TOOL_RE = re.compile(r"(?:^|__)(?:AskUserQuestion|ExitPlanMode)$")
# The harness's own wording for a user's denial, at the start of the result: never a hook's own deny, nor a
# failed command whose output happens to quote these words.
DENIAL_RE = re.compile(r"\A\s*(?:The user doesn'?t want to|The user does not want to|User rejected|The user rejected)",
                       re.I)


def transcript_answers(path: str) -> tuple:
    """(ok, answers, typed, events): what the user said through a tool, which never reaches the ledger (an
    AskUserQuestion or ExitPlanMode answer, or the feedback typed when a tool call was denied), what he typed,
    each [(stamp, text)], and both in file order as events [(kind "answer" or "typed", stamp, text)]."""
    lines = _transcript(path) if path else []
    if not lines:
        return False, [], [], []
    asked, answers, typed, events, fine = set(), [], [], [], []
    for n, line in enumerate(lines):
        if n % 2000 == 0:
            time_left()  # a long transcript declines through OutOfTime, never runs past the hook
        if not line.strip():
            continue
        e = _entry(line)
        if not e:  # an undecodable record could be the answer that holds: the read fails
            return False, [], [], []
        # Metadata lines (a title, a cost state) carry no message and often no time: only a user, assistant
        # or attachment line can hold what Simon said, and each of those must carry a plain UTC stamp, as
        # the harness writes it. Any other form (an offset, no time) leaves the order unknown.
        if e.get("type") not in ("user", "assistant", "attachment"):
            continue
        raw_stamp = str(e.get("timestamp") or "")
        if not re.fullmatch(r"\d{4}-\d\d-\d\dT\d\d:\d\d:\d\d(?:\.\d+)?Z", raw_stamp):
            return False, [], [], []
        stamp = raw_stamp[:19] + "Z"
        frac = raw_stamp[20:-1] if len(raw_stamp) > 20 else ""
        precise = raw_stamp[:19] + "." + frac[:6].ljust(6, "0")  # full precision, for the order check only
        # What Simon typed, read from the transcript as well as the ledger, so a prompt the recorder never
        # saw (its dependency missing, its hook skipped) still holds.
        queued = (e.get("attachment") or {}) if e.get("type") == "attachment" else {}
        if queued.get("type") == "queued_command" and (
                (isinstance(queued.get("origin"), dict) and queued["origin"].get("kind") in ("task-notification", "peer"))
                or queued.get("commandMode") == "task-notification"
                or not own_words(str(queued.get("prompt") or "")).strip()):
            # A background task's notification or a peer session's message, queued by the harness (its
            # origin names the sender): no word of Simon's, whatever text sits outside the envelope.
            pass
        elif queued.get("type") == "queued_command":
            typed.append((stamp, str((e.get("attachment") or {}).get("prompt") or "")))
            events.append(("queued",) + typed[-1])  # holds like a typed prompt; its later delivery is no new word
            fine.append(precise)
        elif _typed_prompt(e):
            body = (e.get("message") or {}).get("content")
            typed.append((stamp, body if isinstance(body, str) else part_text(body)))
            events.append(("typed",) + typed[-1])
            fine.append(precise)
        content = (e.get("message") or {}).get("content")
        if not isinstance(content, list):
            continue
        for item in content:
            if not isinstance(item, dict):
                continue
            if e.get("type") == "assistant" and item.get("type") == "tool_use" and \
                    ANSWER_TOOL_RE.search(str(item.get("name") or "")):
                asked.add(item.get("id"))
            elif e.get("type") == "user" and item.get("type") == "tool_result":
                body = item.get("content")
                text = body if isinstance(body, str) else part_text(body)
                if item.get("tool_use_id") in asked or (item.get("is_error") and DENIAL_RE.match(text)):
                    answers.append((stamp, text))
                    events.append(("answer",) + answers[-1])
                    fine.append(precise)
    # Typed prompts and answers share one file order: together they must run forward in time, or an answer
    # stamped before an earlier lift (a clock that stepped back) could be read as cleared by it.
    # Every message line, in file order, must run forward at full precision: within one second a record
    # written after another but stamped before it (a queued lift behind an answer) leaves the order unknown.
    if any(b[1] < a[1] for a, b in zip(events, events[1:])) or any(b < a for a, b in zip(fine, fine[1:])):
        return False, [], [], []
    return True, answers, typed, events


def _delegated(payload: dict) -> bool:
    """A delegated worker or an Agent-tool subagent: its transcript holds the task brief, not the user's
    own messages and answers, so it never merges a monitoring-only PR; the parent session does."""
    return (os.environ.get("AGENT_DELEGATED_WORKER") == "1" or bool(payload.get("agent_id"))
            or bool(payload.get("agent_type"))
            or "/subagents/" in str(payload.get("transcript_path") or "").replace(os.sep, "/"))


def monitoring_halt(payload: dict, number: str, gate_stamp: str, head: str = "",
                    strict_gate: bool = True) -> str:
    """Why Simon's words stop this merge, "" when they do not. ONE stamped read of the session's asks
    serves both rules, so no message can fall between two reads. Both rules fail closed:
    - any message from the gate record's second on that is not, whole, a lift declines, an empty one
      (only a quote or a pasted block) included: read it, then record the gate again;
    - every message this session is read in order for a hold (_is_hold) not lifted since (_lifts)."""
    if _delegated(payload):
        return ("a delegated subagent cannot read the user's answers in the parent's transcript, so it hands "
                "this merge back to the parent session")
    if _unrecorded(payload):
        return "a message from the user failed to reach the ledger, so a halt cannot be ruled out"
    ok, raw = _ledger_read(payload, "latest-ask", "--stamped", "--since", "1970-01-01T00:00:00Z")
    records = [r.split("\x1f", 2) for r in raw.split("\x1e") if r] if ok else []
    if ok and not records:
        return "no message from the user is recorded this session, so a halt cannot be ruled out"
    if not ok or any(len(r) != 3 or not re.fullmatch(r"\d{4}-\d\d-\d\dT\d\d:\d\d:\d\dZ", r[0])
                                    or r[1] not in ("ask", "peer", "gate") for r in records):
        return "the user's messages could not be read completely, so a halt cannot be ruled out"
    ok_t, answers, typed, events = transcript_answers(str(payload.get("transcript_path") or ""))
    if not ok_t:
        return "the session transcript could not be read, so an answer given through a question cannot be ruled out"
    # Time order is the only order shared across the sources, so each source must run forward in time as
    # written: a clock that stepped back could otherwise sort a hold before the lift it followed.
    for name, stamps in (("ledger", [r[0] for r in records]), ("transcript", [t for t, _ in typed]),
                         ("transcript answers", [t for t, _ in answers])):
        if any(b < a for a, b in zip(stamps, stamps[1:])):
            return f"the {name} timestamps run backwards, so the order of the user's messages is unknown"
    # The ledger's own gate records took part in that order check (a message stamped before a gate it was
    # written after is caught there). The newest one on this head, in this same read, must still be the
    # PASS the gate check found: a later record (a BLOCKED, a re-run) declines.
    if head and not strict_gate:
        # Merged on Simon's own words: the newest gate on this head in this same read, if any, is the cutoff,
        # so a gate recorded since the earlier gates read still bounds the messages after it.
        parsed = [(r[0], GATE_LINE_RE.match(r[2].strip())) for r in records if r[1] == "gate"]
        on_head = [t for t, m in parsed if m and m.group(2) == head]
        if on_head:
            gate_stamp = min(gate_stamp, on_head[-1])
    elif head:
        parsed = [(r[0], GATE_LINE_RE.match(r[2].strip())) for r in records if r[1] == "gate"]
        on_head = [(t, m) for t, m in parsed if m and m.group(2) == head]
        mo = _monitoring_module()
        if not on_head:
            return "the gate record is missing from the final ledger read, so the merge declines"
        t, m = on_head[-1]
        if (t != gate_stamp or m.group(3) != "PASS" or m.group(4) not in ("standard", "deep")
                or not (m.group(5) or "").rstrip().endswith(mo.BAR_PHRASE)):
            return "the newest gate record on this head is not the PASS the gate check found, so the merge declines"
    # A peer record is a turn the recorder found to be nothing but a peer's envelope (another session's
    # <cross-session-message>, a subagent's <agent-message>): Claude-authored data, not a word of Simon's,
    # so it neither holds, lifts nor counts as a message after the gate (the fix for a peer's FYI ending
    # "Don't push to config main separately" read as Simon's hold on a monitoring-only merge). A turn
    # where he typed beside an envelope is an ask, judged below on his text alone (own_words).
    records = [r for r in records if r[1] not in ("gate", "peer")]
    if not records:  # gate or peer records alone: no message of the user's is recorded here (another checkout's ledger?)
        return "no message from the user is recorded in this ledger, so a halt cannot be ruled out"
    # The transcript's typed prompts join the ledger's records in time order (the ledger first on a tie):
    # a prompt the recorder missed still holds, and a duplicate of a recorded one changes nothing.
    # Transcript copies are kind "typed": they can hold, never lift, and a plain lift among them is neutral,
    # so a copy re-sorted on a tie cannot reorder a lift past a recorded hold.
    records = sorted([tuple(r) for r in records] + [(t, "typed", text) for t, text in typed], key=lambda r: r[0])
    clean = lambda text: (text if len(text) > HOLD_SCAN_LIMIT else
                          QUOTED_RE.sub("", HARNESS_BLOCK_RE.sub("", text)).strip().translate(APOSTROPHES))
    full = lambda text: (text if len(text) > HOLD_SCAN_LIMIT else
                         HARNESS_BLOCK_RE.sub("", text).strip().translate(APOSTROPHES))
    # Simon's own words: system text (SYSTEM_TAG_RE: a task notification, a reminder, the host's
    # instructions, a slash command's name tags) is no word of his, so it never holds. A hold is judged
    # with quoted lines kept and dropped.
    # Stripped at any length up to SYSTEM_SCAN_LIMIT, so a long notification pasted whole holds nothing.
    own = lambda text: (text if len(text) > SYSTEM_SCAN_LIMIT else
                        own_words(text).strip().translate(APOSTROPHES))
    hold_texts = lambda kind, text: ([own(text)] if len(own(text)) > HOLD_SCAN_LIMIT else
                                     [own(text), QUOTED_RE.sub("", own(text)).strip()])
    holds = lambda kind, text: any(_is_hold(t, number) for t in hold_texts(kind, text) if t)
    spoken = lambda kind, text: bool(own(text))
    # Only Simon's own recorded ask can lift.
    # A message past HOLD_SCAN_LIMIT is never cleaned or matched: it can only hold (_is_hold says so first).
    # The body as recorded must itself be the lift: no indent (a Markdown code sample), no quote, no tag.
    # Trailing newlines are dropped from every source alike (the recorder's shell capture drops them), so
    # "merge #12" with a final newline is the same lift in the ledger and in the transcript.
    body = lambda text: text.rstrip("\n")
    lifting = lambda kind, text: (kind == "ask" and len(text) <= HOLD_SCAN_LIMIT and text.isascii()
                                  and body(text) == clean(text) and _lifts(clean(text), number))
    neutral = lambda kind, text: (kind == "typed" and len(text) <= HOLD_SCAN_LIMIT and text.isascii()
                                  and body(text) == clean(text) and _lifts(clean(text), number))
    for stamp, kind, text in records:
        if stamp >= gate_stamp and spoken(kind, text) and not lifting(kind, text) and not neutral(kind, text):
            shown = " ".join(clean(text).split())[:80] or "a message holding only quoted or pasted text"
            if holds(kind, text):
                return (f"the user's message after the gate PASS reads as a hold (\"{shown}\"): it needs his "
                        "plain lift, \"merge the bot fixes\" or \"merge #<n>\"; once he lifts it, record the gate "
                        "again on this head")
            return (f"the user wrote after the gate PASS was recorded (\"{shown}\"): read it, and if it is "
                    "no halt, record the gate again on this head and retry")
    def typed_after(when: str, text: str) -> bool:
        """The transcript shows this lift typed after `when`: queued after it, or typed directly after it
        and not the delivery of a copy queued at or before it (a queued prompt keeps its queue time)."""
        early = {body(x).strip() for k, t, x in events if k == "queued" and t <= when}
        return any(t > when and body(x) == body(text) and (k == "queued" or body(x).strip() not in early)
                   for k, t, x in events if k in ("typed", "queued"))

    def standing(seq, lifts) -> tuple:
        held, held_this, held_at = "", False, ""
        for stamp, kind, text in seq:
            if not spoken(kind, text) or (neutral(kind, text) and not lifts(kind, text)):
                continue
            if lifts(kind, text):
                # A hold that named this PR is lifted only by a lift naming it, never by a class lift. A
                # record is stamped when written, and a lift's record can be written long after Simon typed
                # it, so a hold lifts only on a lift the transcript shows typed in a later second.
                certain = not held_at or typed_after(held_at, text)
                if certain and (not held_this or _names(_normalize(clean(text)), number)):
                    held, held_this, held_at = "", False, ""
            elif holds(kind, text):
                # A hold naming other PRs only (_hold_scope) is no hold on this one. A class hold that could
                # name this PR (_numbered), or one naming it, lifts only on "merge #<n>".
                said = own(text)
                scope = _hold_scope(said)
                if scope is not None and int(number) not in scope:
                    continue
                held, held_this = said, held_this or _numbered(said, number)
                held_at = max(held_at, stamp)
        return held, held_this

    # Read twice, and a hold either reading leaves standing stands: in the time-sorted records (ledger
    # asks, where only Simon's own recorded ask lifts), and in the transcript's own file order
    # of what he typed (where his typed lift lifts). The ledger stamps a record when its writer takes the
    # lock, so two prompts can be appended in the opposite order to the one he typed them in.
    held, held_this = standing(records, lifting)
    if not held:
        held, held_this = standing([(t, "typed", text) for t, text in typed], neutral)
    # Answers given through a tool (a question, a plan, a denied call) never reach the ledger: one at or
    # after the gate declines, and an earlier one that holds stands unless a lift Simon typed AFTER it in the
    # transcript's own file order clears it. The ledger's append time is no order for an answer (the recorder
    # can append a lift typed before the answer after it), so a ledger lift never clears one. A hold carrying
    # a number needs a lift naming this PR, as for ledger holds.
    for i, (kind, stamp, text) in enumerate(events):
        if kind != "answer":
            continue
        if stamp >= gate_stamp:
            return ("the user answered a question or a denied tool call after the gate PASS: read it, and once "
                    "it is no halt, record the gate again on this head")
        scope = _hold_scope(text)
        if scope is not None and int(number) not in scope:
            continue  # an answer holding other named PRs only is no hold on this one
        named = _numbered(text, number)
        # A prompt queued before the answer and delivered after it was typed before it: its delivery is
        # no lift given after the answer.
        queued_before = {body(t).strip() for k, _, t in events[:i] if k == "queued"}
        cleared = any(k == "typed" and neutral("typed", t) and body(t).strip() not in queued_before
                      and (not named or _names(_normalize(clean(t)), number))
                      for k, _, t in events[i + 1:])
        if not cleared and _is_hold(text, number):
            return f"the user's answer holds the merge: \"{' '.join(text.split())[:100]}\""
    if held:
        needed = f"merge #{number}" if held_this else "merge the bot fixes"
        return (f"the user's hold on merging still stands: \"{' '.join(held.split())[:100]}\"; it lifts only "
                f"on his plain \"{needed}\"")
    return ""


def monitoring_merge(payload: dict, command: str, words: list, collect: list = None, facts: dict = None) -> tuple:
    """(allowed, cause, declared): the monitoring-only merge path. `declared` is True when the
    command's repository declares monitoring-only paths (or its overlay could not be read), so the
    deny message adds this path's own Cause line only where it applies. The hook stops at the first
    failing check; the --explain dry-run passes `collect` to read on and list every check that fails,
    stopping only where a later check needs an earlier read. `facts["monitoring_only"]` is set True
    once the PR's file list reads whole and inside the declared paths."""
    facts = facts if facts is not None else {}
    causes = []

    def fail(cause: str) -> bool:
        """Record a failed check; True when the caller must stop here (the hook, not the dry-run)."""
        causes.append(cause)
        return collect is None

    def result() -> tuple:
        if collect is not None:
            collect.extend(causes)
        return (False, causes[0], True) if causes else (True, "", True)

    selector, number, repo = merge_target(words)
    # Case is kept for the overlay lookup: the registry's work/personal boundary match is case-sensitive,
    # so a lowercased owner reads as the other boundary (the fix for a draft that denied every real merge).
    hosted = re.fullmatch(r"(?:https?://)?github\.com/([^/\s]+/[^/\s]+?)(?:\.git)?/?", repo or "")
    named = hosted.group(1) if hosted else (repo or "")  # github_slug lowercases; this keeps the case
    if not number or not named or NON_LITERAL_RE.search(selector):
        return False, "", False
    try:
        mo = _monitoring_module()
        spec, error = mo.spec_for(named)
    except Exception as exc:
        fail(f"bin/monitoring_only.py could not be loaded ({exc})")
        return result()
    if error.startswith("the connector overlay could not be read"):
        fail(f"{error}, so whether this repo declares monitoring-only paths is unknown")
        return result()
    if error:  # this repo's own entry is malformed
        fail(error)
        return result()
    if not spec:
        return False, "", False
    number, slug, pinned, why = monitoring_shape(command.strip())
    if why:
        fail(why)
        return result()
    if slug.lower() != named.lower():
        fail("the command names its repository more than once")
        return result()
    pr = monitoring_pr(number, slug)
    if not pr:
        fail("the PR lookup failed")
        return result()
    read_back = re.search(r"github\.com/([^/]+/[^/]+)/pull/(\d+)$", str(pr.get("url", "")))
    if not read_back or read_back.group(1).lower() != slug.lower() or read_back.group(2) != number:
        fail(f"the PR read back is not {slug}#{number}")
        return result()
    outside = mo.classify(pr.get("files"), pr.get("changedFiles"), spec)
    facts["monitoring_only"] = not outside
    if collect is None:
        not_ready = monitoring_not_ready(pr, spec["requiredChecks"], monitoring_default_branch(slug))
        if not_ready and fail(not_ready):
            return result()
    else:
        monitoring_not_ready(pr, spec["requiredChecks"], monitoring_default_branch(slug), collect=causes)
    if outside and fail(outside):
        return result()
    head, branch = str(pr.get("headRefOid") or "").lower(), str(pr.get("headRefName") or "")
    if not FULL_SHA_RE.fullmatch(head) or not branch:
        fail("the PR's head commit could not be read")
        return result()
    facts["head"] = head
    if pinned != head and fail(f"--match-head-commit {pinned[:12]} is not the PR's head {head[:12]}"):
        return result()
    method = monitoring_merge_method(slug, str(pr.get("baseRefName") or ""), command)
    if method and fail(method):
        return result()
    moved = monitoring_base_moves(slug, head, str(pr.get("baseRefName") or ""),
                                  {f.get("path") for f in pr.get("files") or [] if isinstance(f, dict)})
    if moved and fail(moved):
        return result()
    if session_id(payload) == "unknown":
        fail("the session id is missing, so its gate records cannot be read")
        return result()
    ok, raw = _ledger_read(payload, "gates")
    if not ok:
        fail("this session's ledger could not be read, or a prompt sits in its lock-contention "
             "fallback file")
        return result()
    # Split on the writer's own delimiter only: splitlines() also breaks on U+2028 and other separators
    # a one-line reason may carry, which could turn one BLOCKED record into a forged PASS.
    gates = []
    for line in raw.split("\n"):
        stamp, _, rest = line.partition(" ")
        m = GATE_LINE_RE.match(rest)
        if m and re.fullmatch(r"\d{4}-\d\d-\d\dT\d\d:\d\d:\d\dZ", stamp):
            gates.append(m.groups() + (stamp,))
    mine = [g for g in gates if g[0] == branch and g[1] == head]
    if not mine:
        older = [g for g in gates if g[0] == branch and g[2] == "PASS"]
        hint = f" (this session's newest PASS for it is on {older[-1][1][:12]})" if older else ""
        if fail(f"no gate record from this session is on {branch} at the full head {head[:12]}{hint}. "
                "Run the monitoring-only bar on this head and record it with intent-ledger.sh gate"):
            return result()
        # The dry-run reads the holds anyway, as a hold read with no gate record does.
        halt = monitoring_halt(payload, number, "9999-12-31T23:59:59Z", head, strict_gate=False)
        facts["hold_read"] = True
        if halt:
            facts["held"] = True
            fail(halt)
        return result()
    status, tier, reason = mine[-1][2], mine[-1][3] or "", mine[-1][4] or ""
    if status != "PASS" or tier not in ("standard", "deep") or not reason.rstrip().endswith(mo.BAR_PHRASE):
        if fail(f"the newest gate record at {head[:12]} is not a standard or deep PASS whose reason "
                f"ends with \"{mo.BAR_PHRASE}\""):
            return result()
    halt = monitoring_halt(payload, number, mine[-1][5], head)
    facts["hold_read"] = True
    if halt:
        facts["held"] = True
        fail(halt)
    return result()


def pinned_head(words: list) -> str:
    """The full sha a merge command pins with --match-head-commit, "" when none or more than one."""
    found = [words[i + 1] for i, w in enumerate(words[:-1]) if w == "--match-head-commit"]
    found += [w.split("=", 1)[1] for w in words if w.startswith("--match-head-commit=")]
    return found[0].lower() if len(found) == 1 else ""


def monitoring_word_hold(payload: dict, words: list, cwd) -> str:
    """For a monitoring-only PR merged on Simon's own words, the monitoring hold reading still applies, so
    a later "I veto this" stops an earlier "merge #12". Returns "" only for a PR known NOT to be
    monitoring-only (one listed path outside the declared paths) or a repo that declares nothing; an
    unreadable overlay, PR or file list in a declaring repo holds."""
    selector, number, repo = merge_target(words)
    if not number:
        return ""
    try:
        mo = _monitoring_module()
    except RuntimeError as exc:
        return str(exc)
    hosted = re.fullmatch(r"(?:https?://)?github\.com/([^/\s]+/[^/\s]+?)(?:\.git)?/?", repo or "")
    in_url = re.search(r"github\.com/([^/]+/[^/]+)/pull/\d+", selector)
    named = [x for x in (hosted.group(1) if hosted else (repo or ""), in_url.group(1) if in_url else "") if x]
    if len({x.lower() for x in named}) > 1:
        return "the merge names two different repositories, so the hold read declines"
    # GitHub's own answer for the PR names the repository, in its current name (an old name or a remote
    # alias redirects there): the read is cached from the readiness check.
    try:
        got = re.search(r"github\.com/([^/]+/[^/]+)/pull/\d+", str(pr_view(selector, repo, cwd).get("url", "")))
        if not got and cwd is None and not named:
            return "the directory the merge runs in is unknown (a cd or pushd the guard cannot follow), so name the repository with -R"
        if not got:
            # No answer: hold when some repository gh could have meant may declare monitoring paths. A
            # remote can carry a renamed repo's old name, so an owner with any declared repo holds too.
            try:
                listed = _run(["git", "config", "--get-regexp", r"^remote\..*\.url$"], cwd=cwd or None,
                                        capture_output=True, text=True, timeout=min(5, time_left()))
                urls = [l.split(None, 1)[1] for l in listed.stdout.splitlines() if " " in l] if listed.returncode == 0 else []
                known = listed.returncode in (0, 1) and all(mo.repo_slug(u) for u in urls)
            except OutOfTime:
                raise
            except Exception:
                known, urls = False, []
            candidates = {x for x in named + [re.sub(r"^(?:https?://)?github\.com/", "", os.environ.get("GH_REPO", ""))]
                          + [mo.repo_slug(u) for u in urls] if x}
            owners = mo.declared_owners()
            if known and owners is not None and not any(
                    x[0] or x[1] for x in map(mo.spec_for, candidates)) and not any(
                    c.split("/", 1)[0].lower() in owners for c in candidates):
                return ""
            return "the PR could not be read, so the repository it is in, and any hold on it, is unknown"
        slug = got.group(1)
        spec, error = mo.spec_for(slug)
        if error:
            return f"{error}, so whether this PR is monitoring-only is unknown"
        if not spec:
            return ""
        pr = monitoring_pr(number, slug)
        files = pr.get("files") if pr else None
        if isinstance(files, list) and any(isinstance(f, dict) and isinstance(f.get("path"), str)
                                           and not mo.path_matches(f["path"], spec) for f in files):
            # One path outside the declared paths: not monitoring-only, so the ordinary words decide, for
            # THIS head only. Pinned to it, a push that makes the PR monitoring-only after this read cannot
            # merge past a hold the read skipped.
            head = str(pr.get("headRefOid") or "").lower()
            if not re.fullmatch(r"[0-9a-f]{40}", head) or pinned_head(words) != head:
                return (f"the PR is not monitoring-only at its head {head or '(unreadable)'}, and a merge of it in "
                        f"this repository must pin that head: add --match-head-commit {head or '<full head sha>'}")
            return ""
        if not pr or not isinstance(files, list) or pr.get("changedFiles") != len(files):
            return "the PR's file list could not be read whole, so whether it is monitoring-only is unknown"
        # A gate already recorded on this head still bounds the read: any message after it that is no
        # lift declines here too, whichever words authorized the merge.
        stamp = "9999-12-31T23:59:59Z"
        head, branch = str(pr.get("headRefOid") or "").lower(), str(pr.get("headRefName") or "")
        ok, raw = _ledger_read(payload, "gates")
        if not ok:
            return "this session's ledger could not be read, so the hold read declines"
        for line in raw.split("\n"):
            when, _, rest = line.partition(" ")
            m = GATE_LINE_RE.match(rest)
            if m and m.group(1) == branch and m.group(2) == head:
                stamp = when
        return monitoring_halt(payload, number, stamp, head, strict_gate=False)
    except OutOfTime:
        return "the monitoring-only hold read ran out of time"
    except Exception as exc:
        return f"the monitoring-only hold read hit malformed data ({type(exc).__name__})"


def merge_allowed(payload: dict, words: list, cwd, command: str = "", facts: dict = None) -> tuple:
    """(allowed, why_not, monitoring_cause): this turn's words authorize the merge, or a standing
    merge instruction from this session does and the PR is ready now, or the PR passes the
    monitoring-only path. monitoring_cause is that path's reason when it applied and declined.
    `facts["words"]` names the word path that covered the PR when a later check declined it, and
    `facts["monitoring_only"]` is set when the monitoring path read the PR as inside its class."""
    facts = facts if facts is not None else {}
    if turn_merge_allowed(payload, words, cwd):
        held = monitoring_word_hold(payload, words, cwd)
        if held:
            facts["words"] = "the user's merge words this turn"
            return False, "", held
        return True, "", ""
    allowed, why_not = standing_merge(payload, words, cwd)
    if allowed:
        held = monitoring_word_hold(payload, words, cwd)
        if held:
            facts["words"] = "a standing merge instruction this session"
            return False, "", held
        return True, "", ""
    try:
        ok, cause, declared = monitoring_merge(payload, command, words, facts=facts)
    except OutOfTime:
        ok, cause, declared = False, "the monitoring-only checks ran out of time, so they declined", True
    except Exception as exc:  # malformed data from gh or the ledger declines, never crashes the hook
        ok, cause, declared = False, f"the monitoring-only checks hit malformed data ({type(exc).__name__})", True
    if ok:
        return True, "", ""
    return False, why_not, (cause if declared else "")


# What already authorizes a merge the guard declined, so the deny never sends the agent back to the
# user for words he already gave (the fix for four merge words on SRE-bot PRs, each answered with
# "reply 'merge them'" because every deny ended on "ask", while the real causes were five guard
# defects). Read-only, and it never widens the verdict: it only picks the deny's closing instruction.
# The PR is authorized by: the word path that covered it before a later check declined it; a message
# this session that says merge and names its number with no later message halting a standing merge
# (halts_standing) or closing it; or the monitoring-only standing rule for a PR read as inside its class
# with no hold read on it.
def merge_authorization(payload: dict, words: list, facts: dict, cwd=None) -> str:
    if facts.get("words"):
        return facts["words"]
    selector, number, repo = merge_target(words)
    if number:
        try:
            asks = session_asks(payload)
        except Exception:
            asks = []
        named = re.compile(rf"(?:#|\b(?:pr|pull|pull request)\s*#?\s*|/pull/|(?<![\d.#/]))0*{number}(?!\d)", re.I)
        for i in range(len(asks) - 1, -1, -1):
            ask = asks[i]
            if not any(instructs(piece, "merge") and named.search(piece)
                       for piece in re.split(r"(?<=[.!?;])\s+|\n+", link_labels(ask))):
                continue  # names the PR only outside a sentence that says merge
            if NEGATED_RE.search(ask) or excluded(ask, number):
                break  # the newest message naming the PR negates its merge
            stated = stated_repos(link_labels(ask))
            if stated and (len(stated) > 1 or merge_target_repo(selector, repo, cwd) not in stated):
                continue  # words for a PR of another repository
            if instructs(ask, "merge"):
                if not any(halts_standing(a) or (STANDING_CLOSE_RE.search(a) and named.search(a))
                           for a in asks[i + 1:]):
                    text = " ".join(ask.split())
                    return f"the user's message \"{text[:100]}\""
                break
    if facts.get("monitoring_only") and not facts.get("held"):
        # A hold suspends the standing rule; the hook stops before its hold read on an earlier failure, so
        # read it here (a gate-free read, as monitoring_word_hold does).
        if not facts.get("hold_read") and (not number or monitoring_halt(
                payload, number, "9999-12-31T23:59:59Z", facts.get("head", ""), strict_gate=False)):
            return ""
        return "the monitoring-only standing rule (references/git-pr-deploy.md § Monitoring-only changes)"
    return ""


AUTHORIZED_CLOSE = (" The user already authorized this merge ({}); do not ask again. Fix the stated cause "
                    "(a guard defect goes through /sk:claude-config-update under § Safeguard changes) and "
                    "retry. Run `python3 ~/.claude/hooks/git-commit-guard.py --explain --repo <owner/name> "
                    "--pr <n> --transcript <session .jsonl>` to list every failing check at once. If the "
                    "cause is a hold the user really gave, report in one line that the PR waits for the lift "
                    "it names.")


# "merge and deploy" with no number authorizes ONE merge of a PR this session did not push: the first
# such PR merged on that turn is recorded against the turn's first merge ask, and a second, different
# PR is denied (the fix for a guard so strict it refused Simon's plain "ok merge and deploy" for the
# one PR in front of him, without reopening the "merge everything" incident that merged 8 PRs).
def unnamed_merge_ok(payload: dict, ask: str, number: str) -> bool:
    key = hashlib.sha256(ask.encode()).hexdigest()[:16]
    marker = os.path.join(STATE_DIR, f"{session_id(payload)}.unnamed-merge.{key}")
    try:
        with open(marker) as f:
            return f.read().strip() == number
    except FileNotFoundError:
        if READ_ONLY:  # the --explain dry-run reads the verdict and never records the merge
            return True
        try:
            os.makedirs(STATE_DIR, exist_ok=True)
            with open(marker, "w") as f:
                f.write(number)
            return True
        except OSError:
            return False


# The deny message leads with the ONE check that failed, so the agent fixes the right thing instead of
# guessing (the fix for a `for n in ...; do gh pr merge $n; done` loop denied with the generic rule
# text, which the agent misread as a halt word in Simon's message and asked him twice to resend, while
# the real cause was the selector `$n`: the same merges with literal numbers passed at once). Read-only:
# it re-reads what merge_allowed judged and never changes the verdict or writes the unnamed-merge marker.
NON_LITERAL_RE = re.compile(r"[$`]|^(?:''|\"\")$")


def merge_deny_cause(payload: dict, words: list, why_not: str, cwd=None) -> tuple:
    """(cause, ask_user): the failing check, stated first in the deny message, and whether asking the
    user for a merge word is the right next step."""
    selector, number, repo = merge_target(words)
    if NON_LITERAL_RE.search(selector):
        shown = selector if selector not in ("''", '""') else "a quoted value"
        return (f"the PR selector `{shown}` is a shell variable, substitution or quoted value, not a "
                "literal number, so the guard cannot match it to the user's words. The user's words are "
                "NOT the problem: do not ask the user to resend them. Rerun as one command per PR with "
                "the bare number, e.g. `gh pr merge 301 --squash`, never a loop over a variable"), False
    if not selector:
        return "the command names no PR. Rerun with its bare number, e.g. `gh pr merge 301`", False
    if not number:
        return (f"the selector `{selector}` is a branch or other name, not a PR number or /pull/N URL. "
                "Rerun with the bare number, e.g. `gh pr merge 301`"), False
    if why_not:
        return (f"a standing merge instruction covers #{number}, but it is not ready: {why_not}. Wait for "
                "CI and retry; do not ask the user again"), False
    asks = turn_asks(payload)
    says = re.compile(VERB_FORMS["merge"], re.I)
    said = [i for i, a in enumerate(asks) if instructs(a, "merge")]
    if not said:
        return ("no message from the user this turn says merge as an instruction (a question, a quote, "
                "a peer's report or a yes to your own question does not count)"), True
    halts = [i for i, a in enumerate(asks)
             if NEGATED_RE.search(a) or (not says.search(a) and HALT_RE.search(a))]
    if halts and halts[-1] >= said[-1]:
        text = " ".join(asks[halts[-1]].split())
        return (f"a message this turn reads as a halt after the merge ask: \"{text[:100]}\""), True
    scope = merge_scope(link_labels("\n".join(authorizing_asks(asks, "merge"))))
    # A repository the words state binds their selectors to it: say so, rather than blaming the numbers
    # (the fix for "name other PRs" shown when a link target read as a stated repository was the cause).
    stated = stated_repos(scope)
    if stated and re.search(rf"(?<!\d){number}(?!\d)", scope):
        target = merge_target_repo(selector, repo, cwd)
        if len(stated) > 1 or target not in stated:
            shown = ", ".join(sorted(r if r != "\x00unknown" else "a path or URL no repository can be read from"
                                     for r in stated))
            return (f"the user's merge words name repository {shown}, not {target or 'the repository of #' + number}, "
                    f"so they cover no PR there"), True
    named = sorted(set(re.findall(r"\d{2,}", " ".join(PR_NUMBER_RE.findall(scope)))) - {number})
    if named:
        return (f"the user's merge words name other PRs ({', '.join('#' + n for n in named)}), "
                f"not #{number}"), True
    if BULK_RE.search(scope):
        return (f"the user's merge words say all/both/them, which covers only open PRs this session "
                f"pushed or a hand-back Merge list names, and #{number} is neither"), True
    return (f"an unnumbered merge ask covers ONE PR per message, and this message already merged "
            f"another, so #{number} needs its own number named"), True


MERGE_SEEN = False  # set by main() once the payload is read; the crash handler denies only a merge


GH_PR_OPTS_WITH_VALUE = {"-R", "--repo"}
# Setting or clearing any of these changes which repository an unqualified merge resolves in.
# Git's own discovery variables change which checkout, and so which repository, gh reads too.
REPO_ENV_RE = re.compile(r"\b(?:GH_REPO|GH_HOST|GH_ENTERPRISE_TOKEN|GITHUB_ENTERPRISE_TOKEN|GIT_DIR|GIT_WORK_TREE"
                         r"|GIT_COMMON_DIR|GIT_CONFIG\w*|GIT_CEILING_DIRECTORIES|GIT_DISCOVERY_ACROSS_FILESYSTEM)\s*="
                         r"|\b(?:unset|env\s+(?:-\S+\s+)*-u|-u)\s+(?:GH_REPO|GH_HOST)\b|--unset[= ](?:GH_REPO|GH_HOST)\b")


# A shell word anywhere outside heredoc bodies (`} | bash`, `| /bin/sh`, `| "sh"`, `coproc`, `.`): any
# heredoc body in the command may be what it reads, so every body is kept as code.
SHELL_READER_WORD = r"(?:^|[\s;&|({\"'/])(?:bash|sh|zsh|dash|ksh|eval|source|coproc)(?=[\s;&|)}\"']|$)"
SHELL_READER_RE = re.compile(SHELL_READER_WORD + r"|(?:^|[\s;&|({])\.(?=\s)")
# A `.` in command position: one after a space is an argument (`--root .`), never a file a shell reads.
DOT_COMMAND_RE = re.compile(r"(?:^|[;&|({\n]|\b(?:do|then|else)[ \t])[ \t]*\.(?=\s)")
# Command words whose heredoc is data to the shell (a file's text, a message, another language's
# program, which the guard cannot read anyway). Any other command word in the command keeps every body.
HEREDOC_DATA_COMMANDS = {"cat", "tee", "gh", "git", "cd", "mkdir", "python", "python3", "node", "deno",
                         "echo", "printf", "grep", "wc", "jq", "head", "tail", "sort", "ls", "true", ":"}
# Interpreters that run the heredoc they read as their program (`python3 - <<'EOF'`): that body is code.
HEREDOC_PROGRAM_COMMANDS = {"python", "python3", "node", "deno"}
# A file no command runs unless something names it: a document, or /dev/null.
DOC_FILE_RE = re.compile(r"[^\s$`*?\[\]{}]*\.(?:md|markdown|txt|log|rst)|/dev/null", re.I)


def _shell_lexer(command: str) -> list:
    """The shell's tokens: a newline separates commands as ";" does. `#` is literal here; shell_text has
    already dropped real comments (a `#` inside a word is no comment to bash)."""
    lexer = shlex.shlex(command, posix=True, punctuation_chars=";&|()<>\n")
    lexer.whitespace = " \t\r"
    lexer.whitespace_split = True
    lexer.commenters = ""
    return list(lexer)


def _simple_commands(text: str):
    """The raw tokens of every simple command in text (split at `;&|()` and newlines); None when text
    cannot be tokenized."""
    try:
        tokens = _shell_lexer(text)
    except ValueError:
        return None
    out, segment = [], []
    for tok in tokens + [";"]:
        if tok and set(tok) <= set(";&|()\n"):
            out.append(segment)
            segment = []
        else:
            segment.append(tok)
    return out


def _head_words(segment: list) -> list:
    """A simple command's words from its command word on: redirections, prefixes, assignments and
    wrappers dropped."""
    words = _drop_redirections(segment)
    while words and (words[0] in PREFIX_WORDS or ASSIGN_RE.match(words[0]) or words[0] in ("{", "}")):
        words = words[1:]
    while words and os.path.basename(words[0]) in WRAPPERS:
        words = _unwrap_options(words)
        while words and ASSIGN_RE.match(words[0]):
            words = words[1:]
    return words


def _doc_writes(segment: list):
    """The files a `cat` or `tee` simple command writes when its standard output and every file it writes
    is a literal document or /dev/null (DOC_FILE_RE), so its heredoc reaches no pipe and no program;
    None for any other command, output, input or redirection."""
    words = _head_words(segment)
    if not words or words[0] not in ("cat", "tee"):
        return None
    files, stdout, i = [w for w in words[1:] if not w.startswith("-")] if words[0] == "tee" else [], False, 0
    while i < len(segment):
        tok = segment[i]
        if tok and set(tok) <= set("<>&|") and set(tok) & set("<>"):
            fd = segment[i - 1] if i and segment[i - 1].isdigit() else ""
            if tok != "<<":
                if tok not in (">", ">>", ">|", "&>", "&>>") or fd not in ("", "1", "2") or i + 1 >= len(segment):
                    return None
                files.append(segment[i + 1])
                stdout = stdout or fd != "2"
            i += 2
            continue
        i += 1
    return files if stdout and all(DOC_FILE_RE.fullmatch(f) for f in files) else None


def _data_heredocs(command: str, marks: list) -> set:
    """Ordinals (in marks, as shell_text_once lists them) of the heredocs whose body is data, never run:
      - every one, when every command word reads its heredoc as data (HEREDOC_DATA_COMMANDS), except one
        an interpreter runs as its program (HEREDOC_PROGRAM_COMMANDS: `python3 - <<'EOF'`);
      - otherwise, a quoted one that `cat`/`tee` writes only to documents (`_doc_writes`: `cat >>
        plan.md <<'EOF'`), when every other command word outside HEREDOC_DATA_COMMANDS is literal and no
        runner (`_is_runner`) and nothing else in the command, kept heredoc bodies included, names a file
        it wrote or holds a pattern or substitution that could: no command left can run that file.
        (the fix for plan notes naming `gh pr merge` in a `cat >> plan.md <<'EOF'` beside a ledger tool,
        denied as a hidden merge)
    Every other body stays code, and a command the parse cannot place keeps them all."""
    segments = _simple_commands(shell_text_once(command, keep_delims=False))
    if segments is None:
        return set()
    owners = [k for k, seg in enumerate(segments) for tok in seg if tok == "<<"]
    if len(owners) != len(marks):
        return set()
    heads = [os.path.basename(w[0]) for w in map(_head_words, segments) if w]
    owner_head = lambda k: (_head_words(segments[k]) or [""])[0]
    if all(h in HEREDOC_DATA_COMMANDS for h in heads):
        return {i for i, k in enumerate(owners) if os.path.basename(owner_head(k)) not in HEREDOC_PROGRAM_COMMANDS}
    if any(re.search(r"[$`*?\[\]{}]", h) or _is_runner(h) for h in heads if h not in HEREDOC_DATA_COMMANDS):
        return set()
    writes = {k: _doc_writes(segments[k]) for k in set(owners)}
    data = {i for i, k in enumerate(owners) if marks[i] and writes[k] is not None}
    names = [os.path.basename(f) for k in {owners[i] for i in data} for f in writes[k] if f != "/dev/null"]
    rest = shell_text_once(command, keep_bodies=True, keep_delims=False, drop=data)
    if re.search(r"[*?\[`]|\$\(|\{[^{}\s]*(?:,|\.\.)[^{}\s]*\}", rest):
        return set()  # a pattern or a substitution may name a written file at run time
    return data if all(rest.count(b) == names.count(b) for b in names) else set()


def shell_text(command: str, inert: bool = False) -> str:
    """shell_text_once with every data heredoc body dropped (`_data_heredocs`) and every other kept, or
    every body kept when a shell may read one (SHELL_READER_RE). inert drops, as well, each program body
    that cannot name a gh merge (`_inert_heredocs`): for the merge-word checks only, never the API checks."""
    marks = []
    inert = _inert_heredocs(command) if inert else set()
    if SHELL_READER_RE.search(shell_text_once(command, marks=marks)):
        return shell_text_once(command, keep_bodies=True, drop=inert)
    return shell_text_once(command, keep_bodies=True, drop=_data_heredocs(command, marks) | inert)


def _stdin_program(words: list) -> bool:
    """True when an interpreter's words read its program from standard input: options with no inline-code
    or module flag (-c, -e, -m, -p, --eval, --print), then nothing or `-` and that program's own arguments
    (`python3 - "$dir" <<'EOF'`). A script path or a subcommand (`deno run`) is no stdin program."""
    for w in words[1:]:
        if w == "-":
            return True
        if not w.startswith("-") or w in ("--eval", "--print") or (
                not w.startswith("--") and re.search(r"[cemp]", w[1:])):
            return False
    return True


@functools.lru_cache(maxsize=64)
def _inert_heredocs(command: str) -> frozenset:
    """Ordinals of the heredocs an interpreter reads as its whole program (`python3 - <<'EOF'`,
    `_stdin_program`) whose delimiter is quoted, whose body names no `gh` (quotes, escapes and `+` joins removed)
    and whose program prints only to the terminal (`_sealed_output`), when no shell reads any input
    (SHELL_READER_WORD, DOT_COMMAND_RE). Such a body is another language's text: a merge word in its strings names no command
    the shell runs, and its apostrophes are no shell quotes (the fix for a PR-body edit in `python3 -
    <<'EOF'` with "Safe to merge" and "first-flow's" in its strings, denied as a hidden merge, 24 Nov 2026).
    Its own call of a merge is still judged: a body naming gh is never inert."""
    marks, bodies = [], []
    outer = shell_text_once(command, marks=marks, bodies=bodies)
    if re.search(SHELL_READER_WORD, outer) or DOT_COMMAND_RE.search(outer) or len(bodies) != len(marks):
        return frozenset()
    flat = shell_text_once(command, keep_delims=False)
    ops = [i for i, ch in _unquoted_chars(flat) if flat.startswith("<<", i) and not flat.startswith("<<<", i)
           and (i == 0 or flat[i - 1] != "<")]
    owners = [next(((a, b) for a, b in _command_spans(flat) if a <= i < b), None) for i in ops]
    if len(owners) != len(marks) or None in owners:
        return frozenset()
    inert = set()
    for k, ((a, b), (quoted, body)) in enumerate(zip(owners, bodies)):
        words = _span_words(flat[a:b])
        if (quoted and words and os.path.basename(words[0]) in HEREDOC_PROGRAM_COMMANDS
                and _stdin_program(words)
                and not re.search(r"\bgh\b", re.sub(r"['\"\\+]", "", body))
                and _sealed_output(flat, a, b)):
            inert.add(k)
    return frozenset(inert)


def shell_text_once(command: str, keep_bodies: bool = False, keep_delims: bool = True, drop=(),
                    marks: list = None, bodies: list = None) -> str:
    """The command as bash reads it before splitting words: a backslash-newline outside single quotes
    joined away (`me\\<newline>rge` is `merge`), and the body of every heredoc whose marker sits outside
    quotes dropped (data, never run). The closing delimiter line is kept, so mask() still finds it.
    keep_bodies keeps every body but those whose ordinal is in drop; marks collects, per heredoc in
    order, whether its delimiter is quoted; bodies collects (quoted, body text) per heredoc read."""
    out, i, n, quote, pending, arith, esc_end = [], 0, len(command), None, [], [], -1
    marks = [] if marks is None else marks
    while i < n:
        ch = command[i]
        if arith and not quote:  # inside $(( )), (( )) or $[ ]: `<<` is a shift, never a heredoc
            if ch in "([":
                arith.append(")" if ch == "(" else "]")
            elif ch == arith[-1]:
                arith.pop()
            out.append(ch)
            i += 1
            continue
        if not quote and (command.startswith("$((", i) or command.startswith("((", i) or command.startswith("$[", i)):
            opener = "$((" if command.startswith("$((", i) else "((" if command.startswith("((", i) else "$["
            arith = [")", ")"] if "(" in opener else ["]"]
            out.append(opener)
            i += len(opener)
            continue
        if quote == "'":
            out.append(ch)
            quote = None if ch == "'" else quote
            i += 1
            continue
        if ch == "\\" and i + 1 < n:
            if command[i + 1] == "\n":
                i += 2
                continue
            out.append(command[i:i + 2])
            i += 2
            esc_end = i  # the escaped character is part of the word: a "#" right after it is no comment
            continue
        if quote:  # a double quote, or an ANSI-C $'...' (backslash escapes handled above)
            out.append(ch)
            quote = None if ch == quote[-1] else quote
            i += 1
            continue
        if ch == "#" and i != esc_end and (i == 0 or command[i - 1] in " \t\n;&|()"):  # a comment: dropped
            j = command.find("\n", i)
            i = n if j == -1 else j
            continue
        if ch in "'\"":
            quote = ch
        elif ch == "$" and command.startswith("$'", i):
            out.append("$'")
            quote, i = "$'", i + 2
            continue
        elif command.startswith("<<<", i):  # a here-string: one redirection, never a heredoc
            out.append("<<<")
            i += 3
            continue
        elif command.startswith("<<", i):
            m = re.match(r"<<(-?)[ \t]*([^\s<>;&|()]+)", command[i:])
            if m:
                word = m.group(2)
                delim, quoted = re.sub(r"[\\'\"]", "", word), bool(re.search(r"[\\'\"]", word))
                # A body a shell reads is code (`bash <<EOF`, `cat <<EOF | sh`): it stays, so its merges count.
                pending.append((delim, m.group(1) == "-", keep_bodies and len(marks) not in drop, quoted))
                marks.append(quoted)
                out.append(m.group(0))
                i += m.end()
                continue
        elif ch == "\n" and pending:
            out.append("\n")
            i += 1
            for delim, tabs, code, quoted in pending:
                # An unquoted delimiter expands its body: a substitution in it runs, so that body is code.
                body_end = re.compile(rf"^\t*{re.escape(delim)}$" if tabs else rf"^{re.escape(delim)}$", re.M)
                found = body_end.search(command, i)
                body = command[i:found.start() if found else n]
                if bodies is not None:
                    bodies.append((quoted, body))
                code = code or (not quoted and bool(re.search(r"\$\(|`", body)))
                while i < n:
                    j = command.find("\n", i)
                    line = command[i:] if j == -1 else command[i:j]
                    nxt = n if j == -1 else j + 1
                    if (line.lstrip("\t") if tabs else line) == delim:
                        break
                    if code:
                        out.append(command[i:nxt])
                    i = nxt
                if keep_delims:
                    out.append(command[i:n if command.find("\n", i) == -1 else command.find("\n", i) + 1])
                else:
                    out.append("\n")
                i = n if command.find("\n", i) == -1 else command.find("\n", i) + 1
            pending = []
            continue
        out.append(ch)
        i += 1
    return "".join(out)


# Constructs that build or run a command word the parsers cannot read (`$'gh'`, `{gh,pr,merge,12}`, `gh pr $X merge`, `eval gh ...`,
# `find -exec gh ...`, `${X:-gh}`, `$(echo gh)`): with gh and merge both in the text, they count as a
# hidden merge when the masked parse saw no plain one. (xargs is a wrapper both parsers read.)
DYNAMIC_RE = re.compile(r"\$'|\$\(|\$\{|\$[A-Za-z_@*#?0-9!-]|`|\{[^{}\s]*(?:,|\.\.)[^{}\s]*\}|\beval\b|-exec(?:dir)?\b|-ok\b|\bparallel\b|\bsource\b|(?:^|[\s;&|(])\.\s")


def _shell_merge(command: str, depth: int = 0) -> int:
    """True when the shell, with its own quoting resolved, would run `gh ... pr ... merge` in command
    position (after env assignments and wrappers), directly or inside a `bash -c` string. A command it
    cannot tokenize counts when it names gh and merge."""
    raw, bodies = command, []
    shell_text_once(raw, bodies=bodies)
    # Tokens come from the text with inert program bodies dropped (their apostrophes are no shell quotes);
    # a merge word anywhere, those bodies included, still marks a built command word as a possible merge.
    full, command = shell_text(command), shell_text(command, inert=True)
    try:
        tokens = _shell_lexer(command)
    except ValueError:
        # Unreadable: never matched by the masked parse. Quotes and escapes go first so `g''h pr me\rge`
        # still counts; whole words only, so prose with "weight" or "through" beside "merge" is no merge.
        plain = re.sub(r"['\"\\]", "", command)
        return int(bool(re.search(r"\bgh\b", plain) and re.search(r"\bmerge\b", plain))) * 99
    segment, count, piped = [], 0, False
    names_merge = bool(re.search(r"\bgh\b", full) and re.search(r"\bmerge\b", full))
    # What a reader of a pipe or a redirection may receive: a quoted merge word that a data-only command
    # prints straight to the terminal (`_without_data_merge_words` with sealed output) never reaches it
    # (a poll loop's `gh pr checks | awk` beside a ledger call quoting `merge-readiness`, 24 Nov 2026).
    names_fed = names_merge and bool(re.search(r"\bmerge\b", _without_data_merge_words(
        command, sealed=True, heredocs_inert=_all_heredocs_inert(raw))))
    # A heredoc an interpreter runs as its program (`python3 - <<'EOF'`) is text the guard reads: it can
    # run a merge only when a body names gh and merge, or an unquoted body expands a value that may
    # (a body editing a PR description with "merge" in its prose was denied, 24 Nov 2026).
    bodies_merge = any(
        (re.search(r"\bgh\b", re.sub(r"['\"\\+]", "", b)) and re.search(r"merge", b, re.I))
        or (not quoted and re.search(r"[$`]", b)) for quoted, b in bodies)
    # Outside the bodies, gh and merge named where the program can read them (a file `echo "gh pr merge 1"
    # > f` wrote) keep every heredoc program suspect.
    if bodies and not bodies_merge:
        outside = _without_data_merge_words(re.sub(r"<<-?[ \t]*\S+", " ", shell_text_once(raw, keep_delims=False)),
                                            sealed=True)
        bodies_merge = bool(re.search(r"\bgh\b", outside) and re.search(r"\bmerge\b", outside))
    for tok in tokens + [";"]:
        if tok and set(tok) <= set(";&|()\n"):
            feeds = [t for t in segment if t and set(t) <= set("<>&") and "<" in t]
            fed = piped or bool(feeds)
            heredoc_only = not piped and bool(feeds) and all(t == "<<" for t in feeds)
            piped = tok in ("|", "|&")
            words = _drop_redirections(segment)
            segment = []
            if any(ASSIGN_RE.match(w) and re.search(r"\bgh\b", w) and re.search(r"\bmerge\b", w) for w in words):
                count += 99  # GIT_PAGER='gh pr merge 42' git log: a variable some program runs as a command
            while words and (words[0] in PREFIX_WORDS or ASSIGN_RE.match(words[0])):
                words = words[1:]
            fills = False  # xargs or parallel supplies arguments, or replaces words (-I {}), at run time
            while words and os.path.basename(words[0]) in WRAPPERS:
                fills = fills or os.path.basename(words[0]) == "xargs"
                words = _unwrap_options(words)
                while words and ASSIGN_RE.match(words[0]):
                    words = words[1:]
            if not words:
                continue
            if words[0].startswith("="):  # zsh's =cmd expands to the command's path
                words = [words[0][1:]] + words[1:]
            head = os.path.basename(words[0])
            # Per command: a command word, or a gh subcommand, that the shell builds at run time (`$G pr
            # merge 13`, `gh pr $X merge 13`, `{gh,pr}`) beside a merge named anywhere in the input may be
            # one more merge, even when another command in the input is a plain, checked merge.
            built = lambda w: bool(re.search(r"[$`]|\{[^{}]*(?:,|\.\.)[^{}]*\}", w))
            # A pathname pattern as the command word (`/opt/homebrew/bin/g[h]`) is expanded by the shell.
            globbed_head = bool(re.search(r"[*?\[]", words[0])) and "merge" in words[1:]
            built_merge = names_merge and (built(words[0]) or (
                head == "gh" and _gh_subcommand(words) != ("pr", "merge") and not _gh_literal_read(words)
                and any(built(w) for w in words[1:4])))
            if globbed_head or built_merge:
                count += 99
            # A pathname pattern in gh's command or subcommand place (`gh pr m*` beside a file named
            # merge) is expanded by the shell after the hook reads it. Only `pr`'s subcommand can become
            # a merge, so a `?` in an API path's query string (`gh api "repos/o/r/x?per_page=4"`) is no
            # pattern to fear; API merges have their own check below.
            places = [w for w in words[1:] if not w.startswith("-")][:2]
            globbed = lambda w: bool(re.search(r"[*?\[]", w))
            if head == "gh" and places and (globbed(places[0]) or (
                    places[0] == "pr" and len(places) > 1 and globbed(places[1]))):
                count += 99
            if head == "gh" and _gh_subcommand(words) == ("pr", "merge"):
                count += 1
            elif head == "gh" and fills and names_merge:
                count += 99  # `echo merge 42 | xargs gh pr`, `xargs -I{} gh pr {} 42`: the subcommand comes later
            elif head not in INERT_COMMANDS and head != "gh" and not (
                    head == "git" and not any(w == "-c" or w.startswith(("-c", "--config", "--exec-path"))
                                              or "alias." in w or w.startswith("!") for w in words)) and not (
                    head in SHELLS and any(
                    SHELL_C_RE.match(w) for w in words[1:])) and any(
                    re.search(r"\bgh\b", w) and re.search(r"\bmerge\b", w) for w in words[1:] if " " in w or "\t" in w):
                # One argument holding a whole merge command (`trap 'gh pr merge 42' EXIT`, `python3 -c "..."`,
                # `ssh host 'gh pr merge 42'`): a command that may run its argument as code.
                count += 99
            elif head not in INERT_COMMANDS and head not in SHELLS and any(
                    os.path.basename(w) == "gh" and _gh_subcommand(words[k:]) == ("pr", "merge")
                    for k, w in enumerate(words[1:], 1)):
                # `gh pr merge` as the arguments of a command word neither parser knows (`builtin command
                # gh ...`, `find -exec gh ...`): it may run, so it counts, and the guard cannot check it.
                count += 1
            if head in SHELLS:
                for i, w in enumerate(words[1:], 1):
                    if SHELL_C_RE.match(w) and i + 1 < len(words):
                        # The words after the string are its positional arguments: `bash -c '"$@"' _ gh pr
                        # merge 42` and `bash -c 'gh "$@"' _ pr merge 42` run them, so gh and merge across the
                        # string and its arguments count.
                        rest = words[i + 2:]
                        joined = " ".join(words[i + 1:])  # the string and its arguments together
                        if rest and re.search(r"\bgh\b", joined) and re.search(r"merge", joined):
                            count += 99
                        # Past the nesting limit the string is not read, so naming gh and merge counts.
                        inner = words[i + 1]
                        count += _shell_merge(inner, depth + 1) if depth < 3 else 99 * bool(
                            re.search(r"\bgh\b", inner) and re.search(r"\bmerge\b", inner))
                        break
            # A command reading a pipe or a redirection that may run what it reads (`printf 'gh pr merge 12' |
            # sh`, `| fish`, `sh <<< "..."`, `sh < f`) runs text no parser here reads: with gh and merge named
            # anywhere in the command, that text may be a merge. Only known readers of data are exempt.
            program_heredoc = heredoc_only and head in HEREDOC_PROGRAM_COMMANDS and not bodies_merge
            if fed and names_fed and head not in STDIN_DATA_COMMANDS and not program_heredoc and not (
                    head in SHELLS and any(SHELL_C_RE.match(w) for w in words[1:])):
                count += 99
            continue
        segment.append(tok)
    return count


# Commands that read their standard input as data, never as commands.
STDIN_DATA_COMMANDS = {"cat", "grep", "egrep", "fgrep", "wc", "head", "tail", "jq", "tee", "uniq", "comm", "diff",
                       "gh", "git", "less", "more", "base64", "xxd", "od", "tr", "cut"}
# Commands that never run their arguments: `echo gh pr merge 12` only prints.
# (Not rg, whose --pre runs a program, nor sort, whose --compress-program does.)
INERT_COMMANDS = {"echo", "printf", ":", "true", "false", "test", "[", "grep", "egrep", "fgrep", "cat",
                  "head", "tail", "wc", "uniq", "jq", "comm", "diff", "ls"}


def _drop_redirections(tokens: list) -> list:
    """The shell's words with every redirection and its operand removed, wherever it sits: `>/dev/null gh
    pr merge 42` runs gh as its command word. A file-descriptor number before the operator goes too."""
    out, skip = [], False
    for tok in tokens:
        if skip:
            skip = False
            continue
        if tok and set(tok) <= set("<>&") and set(tok) & set("<>"):
            if out and out[-1].isdigit():
                out.pop()
            skip = True
            continue
        out.append(tok)
    return out


def _gh_subcommand(words: list) -> tuple:
    """(command, subcommand) of a gh invocation, options and their values skipped: `gh pr -R o/r merge`
    gives ("pr", "merge"), `gh pr list --search merge` gives ("pr", "list")."""
    found, rest = [], list(words[1:])
    while rest and len(found) < 2:
        w = rest.pop(0)
        if w.startswith("-"):
            if w in GH_PR_OPTS_WITH_VALUE and rest:
                rest.pop(0)
            continue
        found.append(w)
    return tuple(found)


# gh's own commands; any other first word is an alias or an extension, which gh resolves after the hook.
GH_COMMANDS = {"auth", "browse", "codespace", "discussion", "gist", "issue", "org", "pr", "project", "release",
               "repo", "skill", "cache", "run", "workflow", "stack", "agent-task", "alias", "api", "attestation",
               "completion", "config", "copilot", "extension", "ext", "gpg-key", "label", "licenses", "preview",
               "ruleset", "search", "secret", "ssh-key", "status", "variable", "help", "version", "--version",
               "--help", "-h"}


def _gh_alias_uses(command: str, depth: int = 0):
    """(first word, the words after it) of every gh invocation whose first word is no gh command, in the
    command and in every `bash -c` string it runs, at any depth; None when the outer text is unreadable."""
    try:
        tokens = _shell_lexer(shell_text(command))
    except ValueError:
        return None if depth == 0 else [("\x00unreadable", [])]
    found, segment = [], []
    for tok in tokens + [";"]:
        if tok and set(tok) <= set(";&|()\n"):
            words = _drop_redirections(segment)
            segment = []
            while words and (words[0] in PREFIX_WORDS or ASSIGN_RE.match(words[0])):
                words = words[1:]
            while words and os.path.basename(words[0]) in WRAPPERS:
                words = _unwrap_options(words)
            if words and os.path.basename(words[0]) == "gh":
                at = next((i for i, w in enumerate(words[1:], 1) if not w.startswith("-")), 0)
                if at and words[at] not in GH_COMMANDS:
                    found.append((words[at], words[at + 1:]))
            elif words and os.path.basename(words[0]) in SHELLS:
                for i, w in enumerate(words[1:], 1):
                    if SHELL_C_RE.match(w) and i + 1 < len(words):
                        inner = _gh_alias_uses(words[i + 1], depth + 1) if depth < 3 else [("\x00deep", [])]
                        found.extend(inner or [])
                        break
            continue
        segment.append(tok)
    return found


def gh_alias_merge(command: str) -> bool:
    """A gh invocation whose first word is no gh command (an alias such as `gh pm 42` for `pr merge`, or a
    shell alias `!...`) whose expansion may merge, read from `gh alias list`; an unreadable list counts."""
    words_seen = _gh_alias_uses(command)
    if words_seen is None:
        return False  # hidden_merge already judged an unreadable command
    if not words_seen:
        return False
    try:
        p = _run(["gh", "alias", "list"], capture_output=True, text=True, timeout=bounded(5))
    except Exception:
        return True
    if p.returncode != 0:
        return True
    aliases = {}
    for line in p.stdout.splitlines():
        name, _, expansion = line.partition(":")
        aliases[name.strip().strip("'\"")] = expansion.strip().strip("'\"")  # the list may quote YAML-style
    for w, args in words_seen:
        if w.startswith("\x00"):  # an inner string too deep or unreadable to read: its alias is unknown
            return True
        expansion = aliases.get(w)
        if expansion is None:
            continue  # an extension (gh-<name>), which merges only through its own code: a script residual
        # The alias rebuilt with its arguments, as gh runs it: a shell alias, a placeholder, or a merge
        # word anywhere counts (`p: pr` then `gh p merge 5` runs `gh pr merge 5`).
        rebuilt = expansion.split() + list(args)
        # An alias to `gh api` sends whatever request it builds, and "merge" anywhere in it (an endpoint
        # path included) may be one.
        if expansion.startswith("!") or "$" in expansion or re.search(r"merge", " ".join(rebuilt), re.I) \
                or (rebuilt and rebuilt[0] == "api") or _gh_subcommand(["gh"] + rebuilt) == ("pr", "merge"):
            return True
    return False


# git's common commands; any other first word may be an alias from the invocation's git config.
GIT_COMMANDS = set("""add am apply archive bisect blame branch bundle cat-file check-attr check-ignore checkout
cherry-pick clean clone commit commit-tree config describe diff diff-tree fetch for-each-ref format-patch gc grep
hash-object help init lfs log ls-files ls-remote ls-tree maintenance merge merge-base mv name-rev notes pull push
range-diff read-tree rebase reflog remote reset restore rev-list rev-parse revert rm shortlog show show-ref
sparse-checkout stash status submodule switch symbolic-ref tag update-index update-ref var verify-commit version
worktree write-tree filter-repo""".split())
# Deprecated commands an alias of the same name still overrides (git-config(1) alias.*, checked on git 2.54).
GIT_ALIAS_OVERRIDABLE = {"whatchanged", "pack-redundant"}
_GIT_OWN = None


def is_git_command(name: str) -> bool:
    """git runs its own commands before any alias of the same name, so none needs an alias lookup: the
    common list above plus every builtin and exec-path command `git --list-cmds` names (merge-tree, a
    dry-run merge, was looked up as an alias and denied whenever the directory was unknown)."""
    global _GIT_OWN
    if _GIT_OWN is None:
        try:
            p = _run(["git", "--list-cmds=builtins,main"], capture_output=True, text=True, timeout=bounded(3))
            _GIT_OWN = set(p.stdout.split()) if p.returncode == 0 else set()
        except OutOfTime:
            raise
        except Exception:
            _GIT_OWN = set()
    return name not in GIT_ALIAS_OVERRIDABLE and (name in GIT_COMMANDS or name in _GIT_OWN)


def git_alias_merge(command: str, cwd) -> bool:
    """A git invocation whose first word is a configured alias that may merge a PR: a shell alias (`!...`)
    or any alias naming gh, curl, an API call or a merge. An unreadable alias read counts."""
    try:
        tokens = _shell_lexer(shell_text(command))
    except ValueError:
        return False
    # The directory each git runs in, as the shell moves: a literal cd or pushd moves it, successive -C
    # options stack, and anything the guard cannot follow (cd -, popd, a variable, GIT_DIR) makes it
    # unknown, which counts for any alias lookup.
    uses, segment, here = [], [], os.path.abspath(cwd or ".")
    pure_chain = not re.search(r"\|\||;|\n|(?<!&)&(?!&)|\|", mask(command))
    for tok in tokens + [";"]:
        if tok and set(tok) <= set(";&|()\n"):
            words = _drop_redirections(segment)
            segment = []
            if any(re.match(r"GIT_(?:DIR|WORK_TREE|CONFIG\w*|COMMON_DIR)=", w) for w in words):
                here = None
            while words and (words[0] in PREFIX_WORDS or ASSIGN_RE.match(words[0])):
                words = words[1:]
            while words and os.path.basename(words[0]) in WRAPPERS:
                words = _unwrap_options(words)
            if words and words[0] in ("cd", "pushd"):
                target = words[1] if len(words) == 2 else ""
                via_cdpath = ((bool(os.environ.get("CDPATH")) or "CDPATH" in command)
                              and not target.startswith(("/", ".", "~")))
                literal = (pure_chain and target and target != "-" and not via_cdpath
                           and not re.search(r"[$`*?\[{]", target))
                here = (os.path.normpath(os.path.join(here, os.path.expanduser(target)))
                        if literal and here else None)
            elif words and words[0] == "popd":
                here = None
            elif words and os.path.basename(words[0]) == "git":
                rest, where = words[1:], here
                while rest and rest[0].startswith("-"):
                    opt = rest.pop(0)
                    if opt in GIT_OPTS_WITH_VALUE and rest:
                        value = rest.pop(0)
                        if opt == "-C":
                            where = (os.path.normpath(os.path.join(where, os.path.expanduser(value)))
                                     if where and not re.search(r"[$`*?\[{]", value) else None)
                        elif opt in ("--git-dir", "--work-tree", "-c"):
                            where = where if opt == "-c" and not value.lower().startswith("include") else None
                if rest and not is_git_command(rest[0]):
                    uses.append((rest[0], where))
            continue
        segment.append(tok)
    for name, where in uses:
        if where is None:  # the directory git reads its config in is unknown
            return True
        # Followed alias to alias as git does, to a shell alias or a git command; a cycle or a chain past
        # five links counts.
        seen = set()
        while name:
            if name in seen or len(seen) >= 5:
                return True
            seen.add(name)
            try:
                p = _run(["git", "config", "--get", f"alias.{name}"], cwd=where,
                         capture_output=True, text=True, timeout=bounded(3))
            except Exception:
                return True
            if p.returncode not in (0, 1):
                return True
            value = p.stdout.strip()
            if value and (value.startswith("!") and re.search(r"\bgh\b|\bcurl\b|\bmerge\b|\bapi\b|\$", value)
                          or re.search(r"\bgh\b|\bcurl\b", value)):
                return True
            first = value.split()[0] if value and not value.startswith("!") else ""
            name = first if first and not is_git_command(first) else ""
    return False


# gh (command, subcommand) pairs that only read. Once gh has read a literal read subcommand, a variable in
# its arguments cannot turn it into a merge, however it word-splits. `gh api` is not here: a split
# variable can add `-X PUT` or a merge path to it.
GH_READS = {("pr", "view"), ("pr", "list"), ("pr", "checks"), ("pr", "diff"), ("pr", "status"),
            ("issue", "view"), ("issue", "list"), ("issue", "status"), ("run", "view"), ("run", "list"),
            ("run", "watch"), ("workflow", "view"), ("workflow", "list"), ("repo", "view"),
            ("release", "view"), ("release", "list"), ("search", "prs"), ("search", "issues")}
SIMPLE_PARAM_RE = re.compile(r"\$(?:[A-Za-z_][A-Za-z0-9_]*|\{[A-Za-z_][A-Za-z0-9_]*\})")


def _gh_literal_read(words: list) -> bool:
    """`gh pr view $n`: a literal gh whose command, subcommand and every word before the subcommand are
    literal, naming a GH_READS pair. A variable there (`gh pr $verb`, `gh pr -R $r view`, which may split
    into `-R o/r merge`) is no read."""
    if not words or os.path.basename(words[0]) != "gh" or re.search(r"[$`{*?\[]", words[0]):
        return False
    found, i, value = 0, 1, False
    while i < len(words) and found < 2:
        w = words[i]
        if re.search(r"[$`*?\[]|\{[^{}]*(?:,|\.\.)[^{}]*\}", w):
            return False
        if value or w.startswith("-"):
            value = not value and w in GH_PR_OPTS_WITH_VALUE
        else:
            found += 1
        i += 1
    return _gh_subcommand(words) in GH_READS


def _command_spans(text: str) -> list:
    """(start, end) of each simple command in text, split at unquoted `;&|()` and newlines; a quoted or
    escaped character never splits."""
    spans, start, quote, i = [], 0, None, 0
    while i < len(text):
        ch = text[i]
        if quote == "'":
            quote = None if ch == "'" else quote
        elif ch == "\\":
            i += 1
        elif quote:
            quote = None if ch == '"' else quote
        elif ch in "'\"":
            quote = ch
        elif ch in ";&|()\n":
            spans.append((start, i))
            start = i + 1
        i += 1
    spans.append((start, len(text)))
    return spans


def _span_words(span: str):
    """The command words of one span, prefixes and assignments dropped; None when the lexer cannot read
    it or disagrees with the split (an operator token left inside the span)."""
    try:
        words = _drop_redirections(_shell_lexer(span))
    except ValueError:
        return None
    while words and (words[0] in PREFIX_WORDS or ASSIGN_RE.match(words[0])):
        words = words[1:]
    return None if any(set(w) <= set(";&|()\n") for w in words) else words


def _read_argument_params(text: str) -> set:
    """Start offsets in text of each simple parameter (`$n`, `${n}`) that is an argument of a literal gh
    read (`_gh_literal_read`), per `_command_spans` command."""
    benign = set()
    for a, b in _command_spans(text):
        words = _span_words(text[a:b])
        if words and _gh_literal_read(words):
            benign.update(a + m.start() for m in SIMPLE_PARAM_RE.finditer(text[a:b]))
    return benign


# Command words that may run an argument as code, a command, a request or a file of commands: a variable in
# their words is never judged by its value. Any other literal command word only receives it as data.
RUNNERS = SHELLS | WRAPPERS | {"gh", "git", "curl", "wget", "http", "eval", "source", ".", "exec", "command",
                               "builtin", "xargs", "parallel", "find", "ssh", "trap", "fish", "csh", "tcsh",
                               "python", "python3", "node", "deno", "bun", "perl", "ruby", "osascript", "awk",
                               "gawk", "sed", "make", "watch", "script", "open", "coproc", "php", "lua",
                               "luajit", "tclsh", "expect", "Rscript", "julia", "swift", "cmake", "ninja", "npx",
                               "npm", "pnpm", "yarn", "uv", "uvx", "pipx", "go", "cargo", "java", "jshell", "pwsh",
                               "screen", "tmux", "vim", "nvim", "emacs", "gdb", "lldb", "busybox", "nohup",
                               "tar", "rsync", "less", "man", "git-lfs", "zip", "unzip"}
# A versioned or variant interpreter name (`python3.11`, `pypy3`, `node18`) runs code like its base name.
VERSIONED_RUNNER_RE = re.compile(r"(?:python|pypy|node|perl|ruby|php|lua|tclsh|bash|zsh|ksh|sh)[\d.]*")
NAMES_GH_OR_MERGE_RE = re.compile(r"\bgh\b|merge", re.I)
ASSIGN_PREFIX_RE = re.compile(r"\s*(?:(?:export|local|declare|readonly|typeset)\s+(?:-\w+\s+)*)?"
                              r"[A-Za-z_][A-Za-z0-9_]*=\"?")


def _simple_command_end(text: str, i: int) -> int:
    """Offset of the first unquoted `;&|` or newline at or after i outside a `$( )`: where the simple
    command holding offset i ends."""
    quote, depth = None, 0
    while i < len(text):
        ch = text[i]
        if quote == "'":
            quote = None if ch == "'" else quote
        elif ch == "\\":
            i += 1
        elif quote:
            quote = None if ch == '"' else quote
        elif ch in "'\"":
            quote = ch
        elif ch == "(":
            depth += 1
        elif ch == ")":
            depth -= 1
            if depth < 0:
                return i
        elif ch in ";&|\n" and depth == 0:
            return i
        i += 1
    return len(text)


def _is_runner(head: str) -> bool:
    return head in RUNNERS or bool(VERSIONED_RUNNER_RE.fullmatch(head))


def _literal_head(command: str):
    """The basename of a simple command's literal command word; None when it has none or the shell builds it."""
    words = _span_words(command)
    while words and words[0] in ("{", "}", "!"):
        words = words[1:]
    if not words or re.search(r"[$`{}*?\[\]]", words[0]):
        return None
    return os.path.basename(words[0])


# Commands whose output a command cannot choose to spell another command (a path, a time, a count): a
# variable set from one holds data. printf, echo, cat, sed, tr and base64 can spell anything, and git
# prints stored config (`git config --get x`).
VALUE_PRODUCERS = {"mktemp", "date", "pwd", "uname", "hostname", "whoami", "id", "nproc", "uuidgen"}
CLEAN_LITERAL_RE = re.compile(r"[\w./:@%+,=~-]*")


def _clean_substitution(body: str) -> bool:
    """`$(mktemp -d)`: one simple command run by a VALUE_PRODUCERS word, with nothing the shell expands and
    neither gh nor merge named."""
    if re.search(r"[$`\\;&|<>()\n]", body) or NAMES_GH_OR_MERGE_RE.search(body):
        return False
    return _literal_head(body) in VALUE_PRODUCERS


def _unclean_names(text: str) -> set:
    """Every variable the text may set to a value that spells a command: any assignment whose value is not a
    plain literal naming neither gh nor merge, nor one clean substitution (`_clean_substitution`); every
    `for` variable; and every name `read`, `mapfile`, `readarray`, `getopts` or `printf -v` sets."""
    unclean = set()
    for m in re.finditer(r"(?:^|[\s;&|(`{])([A-Za-z_][A-Za-z0-9_]*)\+?=", text):
        v = m.end()
        if text.startswith(("$(", '"$('), v):
            q = int(text[v] == '"')
            close = _simple_command_end(text, v + 2 + q)
            after = close + 1 + q
            clean = (text[close:close + 1] == ")" and text[close + 1:close + 1 + q] == '"' * q
                     and _clean_substitution(text[v + 2 + q:close])
                     and text[after:after + 1] in ("", " ", "\t", "\n", ";", "&", "|", ")"))
        else:
            value = (text[v:_simple_command_end(text, v)].split() or [""])[0]
            bare = value[1:-1] if len(value) > 1 and value[0] == value[-1] and value[0] in "'\"" else value
            clean = bool(CLEAN_LITERAL_RE.fullmatch(bare)) and not NAMES_GH_OR_MERGE_RE.search(bare)
        if not clean:
            unclean.add(m.group(1))
    unclean.update(re.findall(r"\bfor\s+([A-Za-z_][A-Za-z0-9_]*)\s", text))
    for m in re.finditer(r"\b(?:read|mapfile|readarray|getopts)\b([^;&|\n]*)", text):
        unclean.update(re.findall(r"[A-Za-z_][A-Za-z0-9_]*", m.group(1)))
    unclean.update(re.findall(r"\bprintf\s+-v\s*([A-Za-z_][A-Za-z0-9_]*)", text))
    return unclean


def _brace_unexpanded(text: str, a: int, p: int) -> bool:
    """True when the `{` at offset p, in the simple command starting at offset a, is inside quotes or escaped
    by a backslash, so the shell passes it on as written rather than expanding it. Any `$(`, `$'`, `$"` or
    backquote before it in the command opens a context this scan does not model, so the brace counts."""
    if re.search(r"\$[('\"]|`", text[a:p]):
        return False
    quote, i = None, a
    while i < p:
        ch = text[i]
        if quote == "'":
            quote = None if ch == "'" else quote
        elif ch == "\\":
            if i + 1 == p:
                return True
            i += 1
        elif quote:
            quote = None if ch == '"' else quote
        elif ch in "'\"":
            quote = ch
        i += 1
    return quote is not None


def _data_dynamics(text: str) -> set:
    """Start offsets in text of each DYNAMIC_RE construct that can only hand data to a command, so it builds
    no gh command or merge however the rest of the input reads. Judged per simple command:
      - `f=$(mktemp)`, `f="$(date +%s)"`: an assignment's whole value from one clean substitution
        (`_clean_substitution`). The variable's use is judged where it is used.
      - `> "$f"`: a simple parameter as an output redirection's file.
      - `printf ... "$f"`: a simple parameter in an argument of an inert command (INERT_COMMANDS).
      - `tool note "$f"`: a simple parameter in an argument of a literal command word that is no runner
        (RUNNERS), in a command naming neither gh nor merge, when the text never sets the variable to a value
        that could spell a command (`_unclean_names`; an inherited variable such as $HOME counts as data).
      - `grep -o 'x\\{0,3\\}'`: a quoted or escaped brace (`_brace_unexpanded`) in an argument of an inert
        command, or of a literal non-runner command naming neither gh nor merge. (the fix for a read-only
        `grep -n "gh pr merge" f | grep -o 'x\\{0,3\\}'` denied as a run-time-built merge)
    Anything else (a built command word, a backquote, eval, a shell or interpreter, gh or git, a value built
    by printf or echo) stays a possible hidden merge. (the fix for a read-only `gh api graphql` query
    denied because a later `f=$(mktemp) && printf '... merge ...' > "$f"` named merge and built a temp path)"""
    benign, unclean = set(), None
    spans = _command_spans(text)
    for m in DYNAMIC_RE.finditer(text):
        p = m.start()
        a, b = next(((a, b) for a, b in spans if a <= p < b), (p, p))
        if m.group().startswith("{"):
            # A brace the shell never expands, quoted or escaped (`grep -o 'x\{0,3\}'`), reaches the command as
            # written: data for an inert command, and for a literal non-runner naming neither gh nor merge.
            if _brace_unexpanded(text, a, p):
                head = _literal_head(text[a:b])
                if head in INERT_COMMANDS or (head is not None and not _is_runner(head)
                                              and not NAMES_GH_OR_MERGE_RE.search(text[a:b])):
                    benign.add(p)
            continue
        if m.group() == "$(" and not text.startswith("$((", p):
            close = _simple_command_end(text, p + 2)
            if (ASSIGN_PREFIX_RE.fullmatch(text[a:p]) and text[close:close + 1] == ")"
                    and _clean_substitution(text[p + 2:close])):
                benign.add(p)
            continue
        param = SIMPLE_PARAM_RE.match(text, p)
        if not param:
            continue
        if re.search(r"(?:^|[^<>&])(?:\d?>>?|&>>?|>\|)\s*\"?$", text[a:p]):
            benign.add(p)  # an output redirection's file
            continue
        head = _literal_head(text[a:b])
        if head is None:
            continue  # no command word, or one the shell builds
        if head in INERT_COMMANDS:
            benign.add(p)
            continue
        if unclean is None:
            unclean = _unclean_names(text)
        if (not _is_runner(head) and not NAMES_GH_OR_MERGE_RE.search(text[a:b])
                and param.group().strip("${}") not in unclean):
            benign.add(p)
    return benign


# `gh api` options that take a value, by what the value is; and its options that take none.
GH_API_VALUE_OPTS = {"-X": "method", "--method": "method", "-f": "field", "--raw-field": "field",
                     "-F": "field", "--field": "field", "-H": "header", "--header": "header", "-q": "",
                     "--jq": "", "-t": "", "--template": "", "-p": "", "--preview": "", "--cache": "",
                     "--hostname": ""}
GH_API_FLAGS = {"-i", "--include", "--paginate", "--slurp", "--silent", "--verbose"}


def _unquoted(span: str):
    """span with every quoted character blanked to NUL, or None when the shell would expand anything in it:
    `$` or a backquote outside single quotes, or an unquoted glob or brace expansion."""
    out, quote, i = [], None, 0
    while i < len(span):
        ch = span[i]
        if quote == "'":
            quote = None if ch == "'" else quote
            out.append("\0")
        elif ch == "\\":
            out.append("\0\0")
            i += 1
        elif ch in "$`":
            return None
        elif quote:
            quote = None if ch == '"' else quote
            out.append("\0")
        elif ch in "'\"":
            quote = ch
            out.append("\0")
        else:
            out.append(ch)
        i += 1
    text = "".join(out)
    return None if re.search(r"[*?\[]|\{[^{}]*(?:,|\.\.)[^{}]*\}", text) else text


def _gh_api_read(span: str) -> bool:
    """`gh api graphql -f query='{...}'` or `gh api -X GET repos/o/r/pulls/12/comments -f per_page=100`: a
    literal gh api call that only reads. gh and api are written plainly, nothing in it expands, no field
    reads a file or stdin (`@`), no body comes from --input, and no option is unknown. A GraphQL call
    passes only with a query field and no `mutation` anywhere (GraphQL spells every mutation with that
    keyword). A REST call passes only as a GET (fields with no method make gh send a POST) on a path that
    names no merge. Any other call is left to the merge checks."""
    unq = _unquoted(span)
    words = _span_words(span) if unq is not None else None
    if (not words or len(words) < 3 or os.path.basename(words[0]) != "gh" or words[1] != "api"
            or not re.search(r"(?:^|[\s/])gh[ \t]+api(?:[ \t]|$)", unq)):
        return False
    method, fields, endpoint, i = "", [], [], 2
    while i < len(words):
        w = words[i]
        name, eq, val = w.partition("=") if w.startswith("--") else (w, "", "")
        if not w.startswith("--") and len(w) > 2 and w[:2] in GH_API_VALUE_OPTS:  # -XGET, -X=GET, -fq=...
            name, eq, val = w[:2], "=", w[3:] if w[2] == "=" else w[2:]
        if name in GH_API_FLAGS and not eq:
            i += 1
            continue
        if name in GH_API_VALUE_OPTS:
            if not eq:
                if i + 1 >= len(words):
                    return False
                i += 1
                val = words[i]
            kind = GH_API_VALUE_OPTS[name]
            if kind == "method":
                method = val.upper()
            elif kind == "field":
                fields.append(val)
            elif kind == "header" and re.search(r"method|override", val, re.I):
                return False
            i += 1
            continue
        if w.startswith("-"):  # --input, an option cluster or one gh api does not have
            return False
        endpoint.append(w)
        i += 1
    if len(endpoint) != 1 or any(f.partition("=")[2].startswith("@") for f in fields):
        return False
    from urllib.parse import unquote
    path = unquote(unquote(endpoint[0]))
    if path == "graphql":
        # `mutation` is read in the words as the shell joins them (`mu''tation`) and as written; gh fills a
        # {owner}, {repo} or {branch} placeholder into a field, so a field holding one is unread.
        return (method in ("", "POST") and any(f.startswith("query=") for f in fields)
                and not re.search(r"mutation", span + "".join(words), re.I)
                and not any(re.search(r"\{(?:owner|repo|branch)\}", f) for f in fields))
    placeholders = re.sub(r"\{(?:owner|repo|branch)\}", "", path)  # gh fills these in; no other brace
    return ((method == "GET" or (not method and not fields)) and not re.search(r"merge|graphql", path, re.I)
            and not re.search(r"[{}]", placeholders))


def _without_api_reads(text: str) -> str:
    """text with every `_gh_api_read` command blanked, so the API merge checks judge only the rest."""
    for a, b in _command_spans(text):
        if _gh_api_read(text[a:b]):
            text = text[:a] + " " * (b - a) + text[b:]
    return text


# A literal `git` command word at a command position (start, after `;&|(` or a newline, or after do/then/else),
# with only path or pager options, then its merge subcommand: `git merge`, `git merge-base`, `git -C d merge-tree`.
GIT_MERGE_SUBCOMMAND_RE = re.compile(
    r"(?:^|(?<=[;&|(\n])|(?<=\bdo\s)|(?<=\bthen\s)|(?<=\belse\s))\s*git"
    r"(?:\s+(?:-C\s+[^\s;&|()$`'\"\\{}]+|--no-pager|-P|--(?:git-dir|work-tree)=[^\s;&|()$`'\"\\{}]+))*"
    r"\s+(merge(?:-[a-z]+)*)(?=[\s;&|)]|$)")


def _unquoted_at(text: str, p: int) -> bool:
    """True when offset p of text sits outside every quote and is not escaped."""
    quote, i = None, 0
    while i < p:
        ch = text[i]
        if quote == "'":
            quote = None if ch == "'" else quote
        elif ch == "\\":
            i += 1
        elif quote:
            quote = None if ch == '"' else quote
        elif ch in "'\"":
            quote = ch
        i += 1
    return quote is None and i == p


def _without_git_merge_words(text: str, live: list) -> str:
    """text with the merge subcommand of each plain, unquoted `git merge…` command blanked: git consumes that
    word itself, so it never names or builds a gh merge (`$(git merge-base HEAD origin/main)` beside a
    `gh pr list` read was denied as a hidden merge, 23 Nov 2026). Returned unchanged, so the word still
    counts, when text has a heredoc, a backquote or a `${…}` expansion that can slice a word, or when any
    live dynamic construct (offsets in live) sits in a command naming gh or in one with a built command word:
    there git's output (`gh pr $(git merge-base -h 2>&1 | cut -c12-16) 12`) can still build the merge. A
    variable assigned from a substitution (`t=$(git merge-tree …)`) is judged where it is used."""
    if "<<" in text or "`" in text or "${" in text:
        return text
    spans = _command_spans(text)
    for p in live:
        a, b = next(((a, b) for a, b in spans if a <= p < b), (p, p))
        if re.search(r"\bgh\b", text[a:b]):
            return text
        if _literal_head(text[a:b]) is None and not ASSIGN_PREFIX_RE.fullmatch(text[a:p]):
            return text
    out = text
    for m in GIT_MERGE_SUBCOMMAND_RE.finditer(text):
        if _unquoted_at(text, m.start(1)):
            out = out[:m.start(1)] + "_" * len(m.group(1)) + out[m.end(1):]
    return out


# Commands that only pass their input on to their output: a pipe into them reaches no program.
PASSTHROUGH_COMMANDS = {"tail", "head", "wc", "grep", "egrep", "fgrep", "cat", "uniq", "cut", "tr", "jq"}
# A redirection that writes no file a later command can read: stderr into stdout, or /dev/null.
HARMLESS_REDIRECT_RE = re.compile(r"(?:[0-9&]?>&[0-9]|[0-9&]?>>?[ \t]*/dev/null)(?![^\s;&|()])")


def _unquoted_chars(text: str, a: int = 0, b: int = None):
    """(offset, char) of every character of text[a:b] outside quotes and escapes; a is a command start."""
    b = len(text) if b is None else b
    quote, i = None, a
    while i < b:
        ch = text[i]
        if quote == "'":
            quote = None if ch == "'" else quote
        elif ch == "\\":
            i += 1
        elif quote:
            quote = None if ch == '"' else quote
        elif ch in "'\"":
            quote = ch
        else:
            yield i, ch
        i += 1


def _sealable(text: str) -> bool:
    """False when one command's output may reach another past what `_sealed_output` reads: an `exec`
    redirection, or a group, loop, conditional or subshell whose output is piped or redirected
    (`{ echo merge; } | awk ...`, `done > f`)."""
    bare = {i for i, _ in _unquoted_chars(text)}
    plain = "".join(ch if i in bare else " " for i, ch in enumerate(text))
    return not re.search(r"\bexec\b|(?:\}|\bdone|\bfi|\besac|\))[ \t]*(?:[0-9&]?>|\|)", plain)


def _sealed_output(text: str, a: int, b: int) -> bool:
    """True when the command at text[a:b] (a `_command_spans` span) prints only to the terminal: it sits in
    no subshell or substitution, writes no file, and its pipeline, if any, runs only PASSTHROUGH_COMMANDS
    that write no file either (`ledger gate ... "merge-readiness" 2>&1 | tail -2`)."""
    depth = 0
    for _, ch in _unquoted_chars(text, 0, a):
        depth += {"(": 1, ")": -1}.get(ch, 0)
    if depth:
        return False
    # The pipeline from this command on: up to `;`, a newline, `&&`, `||`, a background `&` or the end.
    parts, start, end, prev = [], a, len(text), ""
    for i, ch in _unquoted_chars(text, a):
        nxt = text[i + 1:i + 2]
        if ch in ";\n()" or (ch == "&" and prev not in "<>" and nxt != ">" and not (prev == "&" or nxt == "&")):
            end = i
            if ch in "()":
                return False
            break
        if ch == "&" and nxt == "&":
            end = i
            break
        if ch == "|" and nxt == "|":
            end = i
            break
        if ch == "|" and prev != "|":
            parts.append((start, i))
            start = i + 2 if nxt == "&" else i + 1
        prev = ch
    parts.append((start, end))
    for k, (s, e) in enumerate(parts):
        seg = text[s:e]
        bare = HARMLESS_REDIRECT_RE.sub(" ", seg)
        if any(ch == ">" for _, ch in _unquoted_chars(bare)):
            return False
        if k:
            words = _span_words(seg)
            if not words or os.path.basename(words[0]) not in PASSTHROUGH_COMMANDS:
                return False
    return True



def _all_heredocs_inert(command: str) -> bool:
    """True when command has heredocs and every one is `_inert_heredocs`: shell_text(inert=True) holds
    none of their bodies, so a `<<` left in it feeds no command the merge-word checks must read."""
    marks = []
    shell_text_once(command, marks=marks)
    return bool(marks) and _inert_heredocs(command) == set(range(len(marks)))


def _without_data_merge_words(text: str, sealed: bool = False, heredocs_inert: bool = False) -> str:
    """text with the word `merge` blanked inside a command that only prints or stores it: echo, printf,
    git, a gh read or edit (`gh pr edit --body "merge notes"`), or one of this config's own hook and bin
    scripts, when the word is inside quotes. Such a command never runs its arguments, so a merge word there names no gh merge, and an
    unrelated `$b` elsewhere in the input must not make it one (a loop's `echo "$b needs merge"` and a
    ledger call quoting `ship-check-merge-readiness` were denied as hidden merges, 24 Nov 2026). Left as
    is: a command with a substitution, a heredoc, a gh word in a non-gh command (`echo "gh pr merge 1" | sh`),
    or a gh command that is `pr merge`, an api call, an alias or an extension. sealed keeps, as well, every
    command whose output another command can read (`_sealed_output`), so the result is what a pipe or a
    redirection may carry to a reader. heredocs_inert (`_all_heredocs_inert`) lets a text whose heredocs
    are all inert programs be read like one with none."""
    if ("<<" in text and not heredocs_inert) or (sealed and not _sealable(text)):
        return text
    own = tuple(os.path.expanduser(f"~/.claude/{d}/") for d in ("hooks", "bin"))
    built = r"[$`{}*?\[\]]"
    out = text
    for a, b in _command_spans(text):
        span = text[a:b]
        if not re.search(r"merge", span, re.I) or re.search(r"`|\$\(|[<>]\(|\$\{", span):
            continue
        if sealed and not _sealed_output(text, a, b):
            continue
        words = _span_words(span)
        if not words or re.search(built, words[0]):
            continue
        head = os.path.basename(words[0])
        if head == "gh":
            w = gh_pr_words(words)
            if (len(w) < 3 or w[1] not in ("pr", "issue", "run", "workflow", "release", "repo", "label")
                    or re.search(built, w[1] + w[2]) or w[2] == "merge"):
                continue
        elif head in ("echo", "printf", "git"):
            if re.search(r"\bgh\b", span):
                continue
        elif os.path.abspath(os.path.expanduser(words[0])).startswith(own) and ".." not in words[0]:
            if re.search(r"\bgh\b", span):
                continue
        else:
            continue
        # Only a quoted occurrence is data; a bare `echo merge` beside a built word stays suspect.
        span = re.sub(r"(?i)merge", lambda m: m.group(0) if _unquoted_at(span, m.start())
                      else "_" * len(m.group(0)), span)
        out = out[:a] + span + out[b:]
    return out


def hidden_merge(command: str) -> bool:
    """A merge the shell would run but the masked parse cannot see: `'gh' pr merge`, `g\\h pr merge`,
    `gh pr me''rge`. The shell's own tokens decide, with no substring fast path."""
    shell = _shell_merge(command)
    text = shell_text(command, inert=True)
    # A simple variable argument of a literal gh read (`gh pr view $n`) builds no command, nor does a
    # construct that only hands data to another command (`_data_dynamics`): neither ever counts, so a merge
    # word in one command and a temp-file variable in another never make a gh read a merge. Nor does the
    # merge subcommand of a plain git command (`git merge-base`): git consumes it, so it names no gh merge.
    dynamic = bool(re.search(r"\bgh\b", text) and re.search(r"\bmerge\b", text, re.I) and DYNAMIC_RE.search(text))
    if dynamic:
        benign = _read_argument_params(text) | _data_dynamics(text)
        live = [m.start() for m in DYNAMIC_RE.finditer(text) if m.start() not in benign]
        dynamic = bool(live) and bool(re.search(r"\bmerge\b", _without_data_merge_words(
            _without_git_merge_words(text, live), heredocs_inert=_all_heredocs_inert(command)), re.I))
    # A function or alias defined in the same input can turn any name, an inert one included, into a
    # runner of its arguments (`printf() { "$@"; }; printf gh pr merge 12`).
    defines = re.search(r"(?:^|[\s;&|(])(?:function\s+[\w.:-]+|[\w.:-]+\s*\(\s*\))|\balias\s+\S+=", text)
    if defines and re.search(r"\bgh\b", text) and re.search(r"\bmerge\b", text):
        return True
    if not shell and not dynamic:
        return False
    seen = sum(1 for _, w, _ in expand_command(command)
               if w and os.path.basename(gh_pr_words(w)[0]) == "gh" and gh_pr_words(w)[1:3] == ["pr", "merge"])
    # Every merge the shell would run must be one the guard checks; a built command word with no plain
    # merge beside it is one the guard cannot check.
    return shell > seen or (dynamic and not seen)


def gh_pr_words(words: list) -> list:
    """`gh pr -R o/r merge 12` as `gh pr merge 12 -R o/r`: gh accepts its repository option between `pr`
    and the subcommand, so a merge written that way is judged like any other (it skipped the whole guard)."""
    if len(words) < 3 or os.path.basename(words[0]) != "gh" or words[1] != "pr" or not words[2].startswith("-"):
        return words
    moved, rest = [], list(words[2:])
    while rest and rest[0].startswith("-"):
        w = rest.pop(0)
        moved.append(w)
        if w in GH_PR_OPTS_WITH_VALUE and rest:
            moved.append(rest.pop(0))
    return words[:2] + rest[:1] + rest[1:] + moved if rest else words


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
    global MERGE_SEEN
    # Quotes and escapes removed first, so `gh pr me''rge` that crashed a parse is still a merge to deny.
    plain = re.sub(r"['\"\\\s]", "", command) if isinstance(command, str) else ""
    MERGE_SEEN = isinstance(command, str) and "gh" in plain and "merge" in plain
    if isinstance(command, str) and (hidden_merge(command) or gh_alias_merge(command)
                                     or git_alias_merge(command, payload.get("cwd") or os.getcwd())):
        return deny("Blocked `gh pr merge`. Cause: the command spells `gh` or its subcommand with quotes or "
                    "escapes, builds it at run time, runs it through a gh alias, another command or a shell's "
                    "input, or puts a redirection before it, which hides the merge from this guard. Rerun it "
                    "as a plain `gh pr merge <n>`.")
    # A merge through the API, however gh is spelled ('gh', g\h) or whatever client sends it (curl), is
    # read from the text as bash sees it, before any word parse can miss it. A literal gh api read (a
    # GraphQL query, a REST GET) is blanked first: its braces and fields are no glob or write.
    if isinstance(command, str):
        api_text = _without_api_reads(shell_text(command))
        plain_api = api_text.replace("'", "").replace('"', "").replace("\\", "")
        client = re.search(r"\bgh\b|\bcurl\b|\bwget\b|\bhttp\b|api\.github\.com", plain_api)
        # A GraphQL body read from a file or stdin is a request the hook cannot read: it may be a merge.
        # Only a query written out in the command is read; any file, stdin or JSON body form is not.
        unread_graphql = re.search(r"graphql", plain_api, re.I) and (re.search(
            r"@|--input\b|--json\b|\s-d\s*-|--data[\w-]*[\s=]+-(?:\s|$)|<|\s-T\s|--upload-file", plain_api)
            or not re.search(r"\bquery\b", plain_api))
        # Each URL or path as the client resolves it: %-escapes decoded and dot segments removed
        # (`pulls/12/x/../merge` is the merge endpoint); a pulls path the guard cannot normalize counts.
        def resolved(tok):
            import posixpath
            from urllib.parse import unquote
            t = unquote(unquote(tok))
            head, sep, path = t.partition("://")
            host, _, rest = path.partition("/") if sep else ("", "", t)
            norm = posixpath.normpath("/" + rest.split("?", 1)[0].split("#", 1)[0])
            return f"{head}{sep}{host}{norm}"
        pulls_paths = [resolved(t) for t in plain_api.split() if "pull" in t.lower() or "%" in t]
        # curl expands {a,b} and [1-3] in a URL itself, quoted or not: a pulls URL holding one is unread.
        globbed = any(re.search(r"[{}\[\]]", t) for t in plain_api.split()
                      if re.search(r"pull|repos/|api\.github\.com|graphql", t, re.I))
        # curl reading its options from a config file or stdin (-K f, --config=f, -K-) sends a request the
        # hook cannot read.
        # Only curl's own arguments count: each curl call up to the next command separator, so another
        # tool's --config in the same line (wrangler dev --config w.json && curl …) is no curl config.
        curl_config = any(re.search(r"(?:^|\s)(?:-(?!-)[A-Za-z0-9#:]*K\S*|--config\b\S*)", call)
                          for call in re.findall(r"\bcurl\b([^;&|\n]*)", plain_api))  # -K alone or in a cluster: -sK
        # A state-changing request whose target the shell builds at run time ($U/merge, `cmd`) beside a
        # merge, a pulls path or GraphQL named anywhere is unread too.
        writes = re.search(r"-X\s*(?:PUT|POST|PATCH)|--request[\s=]*(?:PUT|POST|PATCH)|--method[\s=]*(?:PUT|POST|PATCH)"
                           r"|(?:^|\s)-(?:d|F|f|T)\b|--data|--json|--input|--upload-file|\bwget\b.*--post", plain_api, re.I)
        api_client = re.search(r"\bcurl\b|\bwget\b|\bhttp\b|\bgh\s+api\b", plain_api)
        built_target = (api_client and writes and re.search(r"[$`]", plain_api)
                        and re.search(r"merge|pulls|graphql", plain_api, re.I))
        if client and (API_MERGE_RE.search(api_text) or API_MERGE_RE.search(plain_api) or unread_graphql
                       or any(API_MERGE_RE.search(t) for t in pulls_paths) or globbed or curl_config or built_target):
            return deny(
                "Blocked: a merge, enqueue or auto-merge through `gh api` bypasses the merge check. "
                "Use `gh pr merge <n>` with the bare PR number, one command per PR, which runs only "
                "when the user's own words this turn say \"merge\" and cover the PR."
            )
    if not isinstance(command, str) or ("git" not in command and not re.search(r"\bgh\b", command)):
        return 0
    cwd = payload.get("cwd") or os.getcwd()

    target_cwd = command_cwd(command, cwd)
    allow_main = os.environ.get("CLAUDE_ALLOW_MAIN_COMMIT") == "1"
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
                    "the whole diff, then rerun with `--reviewed <diff-sha256>`: it queues on the "
                    "landing lock, merges origin/main, runs the checks and pushes the head it "
                    "verified. Ask the user only for an excluded decision (rules/self-healing-config.md)."
                )
    gh_cwd = cwd  # where a `gh pr view` lookup runs; None once a `cd` cannot be resolved statically
    # A cd counts as run only in a pure && chain: after `;`, `||`, `|`, `&` or a new line, a skipped or
    # failed cd still lets the next command run, in a directory the guard cannot know.
    pure_chain = not re.search(r"\|\||;|\n|(?<!&)&(?!&)|\|", mask(command))
    for seg, words, top in expand_command(command):
        # cd and pushd move the directory a later gh reads its repository from; one the guard cannot
        # follow (popd, cd -, a variable, a move inside a subshell) leaves it unknown.
        if words[:1] in (["cd"], ["pushd"]):
            path = words[1] if len(words) == 2 else ""
            # A relative name may resolve through CDPATH (the environment's, or one set in the command).
            via_cdpath = (bool(os.environ.get("CDPATH")) or "CDPATH" in command) and not path.startswith(("/", ".", "~"))
            literal = (top and pure_chain and path and path != "-" and gh_cwd and not via_cdpath
                       and not any(ch in path for ch in "$`'\"*?[{"))
            gh_cwd = os.path.abspath(os.path.join(gh_cwd, os.path.expanduser(path))) if literal else None
        elif words[:1] == ["popd"]:
            gh_cwd = None
        sub = git_subcommand(words)
        is_commit = sub == "commit"
        is_push = sub == "push"
        words = gh_pr_words(words)
        is_gh_merge = bool(words) and os.path.basename(words[0]) == "gh" and words[1:3] == ["pr", "merge"]
        if is_gh_merge and REPO_ENV_RE.search(command):
            return deny("Blocked `gh pr merge`. Cause: the command sets GH_REPO, GH_HOST or an enterprise "
                        "token, which can point the merge at another repository than the one checked. Name the "
                        "repository with -R instead and rerun.")
        is_gh_api = bool(words) and os.path.basename(words[0]) == "gh" and words[1:2] == ["api"]
        if is_gh_api and API_MERGE_RE.search(_without_api_reads(command)):
            return deny(
                "Blocked: a merge, enqueue or auto-merge through `gh api` bypasses the merge check. "
                "Use `gh pr merge <n>` with the bare PR number, one command per PR, which runs only "
                "when the user's own words this turn say \"merge\" and cover the PR."
            )
        if not (is_commit or is_push or is_gh_merge):
            continue

        # 0. `gh pr merge` merges into the remote default branch — the action that once merged 8 PRs
        # (two on red CI) into master off a general "merge everything". A general instruction is never
        # a yes for a specific merge, so block unless the user's own words this turn cover THIS
        # merge. The deny message is what tells Claude to get that yes.
        try:
            facts = {}
            allowed, why_not, monitoring_cause = merge_allowed(payload, words, gh_cwd, command, facts) if is_gh_merge else (True, "", "")
        except Exception as exc:  # a crash would exit non-zero, which the harness treats as allow
            return deny(f"Blocked `gh pr merge`. Cause: the merge check raised {type(exc).__name__}, so it "
                        "declines. Rerun once; if it repeats, ask the user for the merge word.")
        # Beside other commands, a merge with no -R may run against a repository those commands chose (a
        # remote changed, a config written, a checkout moved): an allowed merge must then name it.
        if is_gh_merge and allowed and len(segments(command)) > 1 and not merge_target(words)[2] \
                and "/pull/" not in merge_target(words)[0]:
            return deny("Blocked `gh pr merge`. Cause: the merge runs beside other commands with no -R, so the "
                        "repository it resolves in may differ from the one checked. Name it with "
                        "-R github.com/<owner>/<name>, or run the merge as its own command.")
        if not allowed:
            if MONITORING_BUDGET_S - (time.monotonic() - HOOK_STARTED) < 6:
                # Too little time is left to read the ledger again for the cause: deny now, before the
                # hook's timeout turns the deny into a non-blocking error that lets the merge run.
                return deny("Blocked `gh pr merge`. Cause: the merge checks ran long and declined. Rerun once;"
                            + (AUTHORIZED_CLOSE.format(facts["words"]) if facts.get("words") else
                               " if it repeats, ask the user for the merge word.")
                            + (f"\nCause (monitoring-only merge): {monitoring_cause}." if monitoring_cause else ""))
            if facts.get("words") and monitoring_cause:
                cause, ask_user = (f"{facts['words']} cover #{merge_target(words)[1]}, but the monitoring-only "
                                   "hold read below declined it"), False
            else:
                cause, ask_user = merge_deny_cause(payload, words, why_not, gh_cwd)
            try:
                authorized = merge_authorization(payload, words, facts, gh_cwd)
            except Exception:
                authorized = ""
            return deny(
                f"Blocked `gh pr merge`. Cause: {cause}.\n"
                + (f"Cause (monitoring-only merge): {monitoring_cause}.\n" if monitoring_cause else "") +
                "The rule: `gh pr merge` merges a PR into the remote default branch, and it runs only "
                "on the user's OWN words this turn (every message since your last hand-back, queued "
                "ones included) saying \"merge\" with no later stop/hold/wait, and naming this PR's "
                "number, covering "
                "it as an open PR this session pushed (no number, or all/both/them), saying all/both/them to a "
                "hand-back whose Merge list names it, or naming no PR "
                "for one other PR; or on a standing merge an earlier message this session gave "
                "(\"merge ... when ready\", \"once CI is green then merge\", or \"merge all\"; never a question) covering it, when no "
                "later message said stop/hold/wait/cancel or not to merge/deploy, and the PR is open, not a draft, "
                "mergeable and every check passed. A standing instruction lasts for this session "
                "only. The guard reads the PR from the command itself: run one `gh pr merge <bare "
                "number>` per PR, never a loop or substitution. "
                "A yes to a question you wrote, 'finish it', 'proceed', 'priority' or 'continue' "
                "is never that. There is no override flag."
                + (AUTHORIZED_CLOSE.format(authorized) if authorized else
                   (" If this PR is monitoring-only, it merges with no merge words once that cause is "
                    "fixed (references/git-pr-deploy.md § Monitoring-only changes); otherwise ask."
                    if monitoring_cause else "")
                   + (" No message from the user this session authorizes this merge: stop at a ready, green "
                      "PR and ask: \"Say 'merge #<n>' to merge it.\""
                      if ask_user else " Fix the cause above and retry; do not ask the user."))
            )

        # 1. Default-branch protection. The override counts only from the hook's OWN env, i.e. the
        # session's starting environment the user set; the same assignment typed into the command is
        # the agent's own word and stays blocked. The config repo was judged above: its commits pass,
        # and its main pushes need a verified head.
        # A config commit the resolver could not parse keeps its old exemption; a config push never
        # does, so an unverified head reaching main still stops here.
        # A push to the remote default branch outside the config repo also needs the user's OWN
        # words this turn to say "push": the flag alone is the model's word, not the user's.
        if is_push and allow_main and not config_scope:
            branch = current_branch(target_cwd or cwd)
            target = re.search(r"(?:^|\s|:)(main|master)\b", seg)
            if (branch in DEFAULT_BRANCHES or target) and not authorizing_asks(turn_asks(payload), "push"):
                return deny(
                    "Blocked: a push to the remote default branch runs only when the user's OWN "
                    "words this turn say \"push\" with no later stop/hold/wait. A yes to an option "
                    "you wrote, 'finish it' or 'continue' is never that. Ask, and stop."
                )
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
                    "wants this exact commit/push on the default branch, they run it in their own "
                    "terminal or start the session with CLAUDE_ALLOW_MAIN_COMMIT=1 in its environment; "
                    "an inline CLAUDE_ALLOW_MAIN_COMMIT=1 prefix in the command is not accepted."
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


# Under the 30 s hook timeout set in settings.json; the environment can only shorten it (the tests do).
def _watchdog_limit() -> float:
    try:
        value = float(os.environ.get("GIT_COMMIT_GUARD_WATCHDOG_S") or 26.0)
    except ValueError:
        return 26.0  # a malformed value never breaks the hook: it would exit non-zero, which allows
    return min(26.0, value) if value == value and value > 0 else 26.0


WATCHDOG_S = _watchdog_limit()
STALL_DENY = json.dumps({"hookSpecificOutput": {
    "hookEventName": "PreToolUse", "permissionDecision": "deny",
    "permissionDecisionReason": "Blocked: the guard did not decide within its time limit, so it declines. "
                                "Rerun once; if it repeats, ask the user."}})


def _worker(data: str, w: int) -> None:
    """The decision itself, in a forked child: its output goes to the supervisor through the pipe."""
    import io
    sys.stdin, sys.stdout = io.StringIO(data), io.StringIO()
    try:
        stall = os.environ.get("GIT_COMMIT_GUARD_TEST_STALL")  # the tests' stand-in for a stalled read
        if stall and re.fullmatch(r"\d+(?:\.\d+)?", stall):
            time.sleep(float(stall))
        code = main()
    except Exception as exc:  # a crash exits non-zero, which the harness treats as allow: deny a merge instead
        code = deny(f"Blocked `gh pr merge`. Cause: the guard crashed ({type(exc).__name__}), so it declines. "
                    "Rerun once; if it repeats, ask the user for the merge word.") if MERGE_SEEN else 0
    out = sys.stdout.getvalue().encode()
    while out:
        out = out[os.write(w, out):]
    os._exit(code or 0)


def _supervise() -> int:
    """The harness-facing process: it runs the decision in a worker and, if the worker has not finished
    by WATCHDOG_S or dies without a word, kills it and denies a possible merge, exiting 0 so the harness
    reads the denial. A stall nothing inside can interrupt (a regex mid-match, a hung read) then declines
    instead of timing out, which the harness would treat as allow."""
    import select
    data = sys.stdin.read()
    plain = re.sub(r"['\"\\\s]", "", data)
    risky = "gh" in plain or "curl" in plain or "git" in plain or "merge" in plain
    r, w = os.pipe()
    try:
        pid = os.fork()
    except OSError:  # no worker means no watchdog: a possible merge declines rather than run unwatched
        os.close(r)
        os.close(w)
        if risky:
            print(STALL_DENY)
            return 0
        import io
        sys.stdin = io.StringIO(data)
        return main()
    if pid == 0:
        os.close(r)
        _worker(data, w)
    os.close(w)
    chunks, timed_out = [], False
    while True:
        left = HOOK_STARTED + WATCHDOG_S - time.monotonic()
        ready = select.select([r], [], [], max(0.0, left))[0] if left > 0 else []
        if not ready:
            timed_out = True
            break
        chunk = os.read(r, 65536)
        if not chunk:
            break
        chunks.append(chunk)
    if timed_out:
        try:
            os.kill(pid, signal.SIGKILL)
        except OSError:
            pass
    _, status = os.waitpid(pid, 0)
    out = b"".join(chunks).decode(errors="replace")
    if timed_out or os.WIFSIGNALED(status):  # a worker that died mid-write may have left half an answer
        if risky:
            print(STALL_DENY)
        return 0
    sys.stdout.write(out)
    sys.stdout.flush()
    return os.WEXITSTATUS(status) if os.WIFEXITED(status) else 0


def _transcript_cwd(path: str) -> str:
    """The newest working directory a session transcript records, "" when none."""
    for line in reversed(_transcript(path)):
        e = _entry(line)
        if e and isinstance(e.get("cwd"), str) and e["cwd"]:
            return e["cwd"]
    return ""


# The read-only dry-run of the whole merge decision (the fix for five guard defects on SRE-bot PRs found
# one merge retry at a time, each retry surfacing only the next first-failing check). It runs the same
# checks the hook runs for `gh pr merge <n> -R github.com/<owner/name> --match-head-commit <head> --squash`
# in the given session, lists EVERY failing check on the word path and the monitoring path, and writes
# no state (READ_ONLY). Exit 0 when the hook would allow the merge, 1 when it would deny, 2 on bad input.
def explain(argv: list) -> int:
    import argparse
    ap = argparse.ArgumentParser(prog="git-commit-guard.py --explain",
                                 description="Read-only dry-run of the merge guard: list every failing check.")
    ap.add_argument("--explain", action="store_true")
    ap.add_argument("--repo", required=True, help="owner/name")
    ap.add_argument("--pr", required=True, help="PR number")
    ap.add_argument("--transcript", required=True, help="the session's transcript .jsonl")
    ap.add_argument("--session", default="", help="session id (default: the transcript's file name)")
    ap.add_argument("--cwd", default="", help="the session's directory (default: the transcript's newest cwd)")
    ap.add_argument("--head", default="", help="full head sha to pin (default: the PR's head now)")
    a = ap.parse_args(argv)
    number, repo = a.pr.lstrip("#"), re.sub(r"^(?:https?://)?github\.com/", "", a.repo).strip("/")
    if not re.fullmatch(r"\d+", number) or not re.fullmatch(r"[\w.-]+/[\w.-]+", repo):
        print("explain: --pr must be a number and --repo owner/name", file=sys.stderr)
        return 2
    global READ_ONLY, MONITORING_BUDGET_S, HOOK_STARTED
    READ_ONLY, MONITORING_BUDGET_S, HOOK_STARTED = True, 600.0, time.monotonic()
    session = a.session or os.path.splitext(os.path.basename(a.transcript))[0]
    cwd = a.cwd or _transcript_cwd(a.transcript) or os.getcwd()
    head = a.head.lower()
    if not head:
        try:
            head = str(monitoring_pr(number, repo).get("headRefOid") or "").lower()
        except Exception:
            head = ""
    failing = []
    if not FULL_SHA_RE.fullmatch(head):
        failing.append(("input", f"the PR's head sha could not be read ({head or 'empty'}); pass --head"))
        head = "0" * 40
    command = f"gh pr merge {number} -R github.com/{repo} --match-head-commit {head} --squash"
    words = command.split()
    payload = {"tool_name": "Bash", "tool_input": {"command": command}, "session_id": session,
               "transcript_path": a.transcript, "cwd": cwd}

    def guarded(fn):
        try:
            return fn()
        except OutOfTime:
            return "ran out of time"
        except Exception as exc:
            return f"raised {type(exc).__name__}: {exc}"

    turn_ok = guarded(lambda: turn_merge_allowed(payload, words, cwd))
    if turn_ok is not True:
        cause = turn_ok if isinstance(turn_ok, str) else guarded(lambda: merge_deny_cause(payload, words, "", cwd)[0])
        failing.append(("word path, this turn", cause))
    standing = guarded(lambda: standing_merge(payload, words, cwd))
    if isinstance(standing, str):
        failing.append(("word path, standing merge", standing))
    elif not standing[0]:
        failing.append(("word path, standing merge",
                        standing[1] or f"no standing merge instruction this session covers #{number}"))
    held = guarded(lambda: monitoring_word_hold(payload, words, cwd))
    if held:
        failing.append(("word path, monitoring hold read", held))
    collect, mfacts = [], {}
    mon = guarded(lambda: monitoring_merge(payload, command, words, collect=collect, facts=mfacts))
    if isinstance(mon, str):
        collect.append(mon)
    elif not mon[2]:
        collect.append("not applicable: the repository declares no monitoring-only paths")
    failing += [("monitoring path", c) for c in collect]
    facts = {}
    verdict = guarded(lambda: merge_allowed(payload, words, cwd, command, facts))
    allowed = isinstance(verdict, tuple) and verdict[0]
    authorized = guarded(lambda: merge_authorization(payload, words, facts, cwd)) or "none found"
    print(f"merge dry-run (read-only): {repo}#{number} at {head[:12]}, session {session}")
    print(f"hook verdict: {'ALLOW' if allowed else 'DENY'}"
          + ("" if isinstance(verdict, tuple) else f" (the decision {verdict})"))
    print(f"authorization: {authorized}")
    print(f"failing checks: {len(failing)}")
    for where, cause in failing:
        print(f"- {where}: {cause}")
    return 0 if allowed else 1


if __name__ == "__main__":
    if "--explain" in sys.argv[1:]:
        sys.exit(explain(sys.argv[1:]))
    sys.exit(_supervise())
