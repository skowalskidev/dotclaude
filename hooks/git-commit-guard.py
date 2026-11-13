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
     calls are denied outright.

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

import datetime
import hashlib
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
# Pasted material inside his message (a fenced block, a `>` quote) is not his instruction.
QUOTED_RE = re.compile(r"^[ \t]*(`{3,}|~{3,}).*?^[ \t]*\1[ \t]*$|^[ \t]*>.*$", re.S | re.M)
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
# A question or a hypothetical about the verb is not an instruction to do it: a sentence saying the
# verb that ends in "?" ("merge 12?"), or that asks should/would/shall/might I|we|you ..., what if,
# whether, do you think, is it ok/safe to ... ("should I merge when it's ready?", "would you merge?").
# A polite request ("can/could/will you merge 12?", "please merge") stays an instruction.
HYPOTHETICAL_RE = re.compile(
    r"\b(should|would|shall|might)\s+(i|we|you|it|this|that|they|claude)\b|\bwhat\s+if\b|\bwhether\b"
    r"|\b(do|did)\s+you\s+think\b|\b(is|are)\s+(it|this|that|they)\s+(ok|okay|safe|fine|wise|worth)\s+to\b", re.I)
POLITE_REQUEST_RE = re.compile(r"\b(can|could|will)\s+you\b|\bplease\b", re.I)
SENTENCE_RE = re.compile(r"[^.!?\n]+[.!?]*")


def instructs(ask: str, verb: str) -> bool:
    """True when some sentence of the ask says the verb as an instruction, not a question or a
    hypothetical (the fix for "should I merge when it's ready?" read as a standing merge)."""
    says = re.compile(VERB_FORMS[verb], re.I)
    for sentence in SENTENCE_RE.findall(ask):
        if not says.search(sentence) or HYPOTHETICAL_RE.search(sentence):
            continue
        if sentence.rstrip().endswith("?") and not POLITE_REQUEST_RE.search(sentence):
            continue
        return True
    return False
# Every verb check accepts its inflections: merge/merged/merges/merging, push/pushed/pushes/pushing
# (the fix for "this can be merged if prod deploy ready" missing a `\bmerge\b` check).
VERB_FORMS = {"merge": r"\bmerg(?:e|ed|es|ing)\b", "push": r"\bpush(?:ed|es|ing)?\b"}
# A later ask that does not repeat the verb but says one of these cancels the earlier authority.
HALT_RE = re.compile(r"\b(stop|hold|wait|cancel|pause|don'?t|do not|never)\b", re.I)
PR_NUMBER_RE = re.compile(r"#?\b\d{2,}\b")
# Plural phrasing ("merge all that's ready", "merge both", "merge them", "the ready ones") covers every open PR this
# session pushed, never a PR it did not push (the "merge everything" incident merged 8 PRs).
BULK_RE = re.compile(r"\b(all|both|every|everything|each|batch|them|these|those|ones)\b", re.I)
API_MERGE_RE = re.compile(
    r"enqueuePullRequest|mergePullRequest|enablePullRequestAutoMerge|/pulls/\d+/merge\b", re.I)
# `gh pr merge` options that take a value, so the value is never read as the PR selector.
GH_MERGE_OPTS_WITH_VALUE = {"-R", "--repo", "-t", "--subject", "-b", "--body", "-F", "--body-file",
                            "-A", "--author-email", "--match-head-commit"}
STATE_DIR = os.path.join(os.path.expanduser("~"), ".claude", ".intent-ledger")


def session_id(payload: dict) -> str:
    return re.sub(r"[^A-Za-z0-9._-]", "", str(payload.get("session_id", ""))) or "unknown"


def ledger_asks(payload: dict, since: str = "") -> list:
    """This session's recorded asks: the newest one, or with `since` every ask from that second."""
    script = os.path.join(os.path.expanduser("~"), ".claude", "hooks", "intent-ledger.sh")
    if not os.path.isfile(script):
        return []
    try:
        p = subprocess.run(["bash", script, "latest-ask", *(["--since", since] if since else [])],
                           text=True, capture_output=True, timeout=5,
                           input=json.dumps({"session_id": payload.get("session_id", ""),
                                             "cwd": payload.get("cwd", "")}))
    except Exception:
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
        text = " ".join(str(x.get("text", "")) for x in content if isinstance(x, dict))
    elif isinstance(content, str):
        text = content
    else:
        return False
    return bool(HARNESS_BLOCK_RE.sub("", text).strip())


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
    cleaned = (QUOTED_RE.sub("", HARNESS_BLOCK_RE.sub("", a)).strip() for a in raw)
    return [a for a in cleaned if a]


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
        elif not w.startswith("-") and not selector:
            selector = w
    m = re.fullmatch(r"#?(\d+)", selector) or re.search(r"/pull/(\d+)", selector)
    return selector, (m.group(1) if m else ""), repo


def github_slug(url: str) -> str:
    m = re.search(r"github\.com[:/]([^/\s]+/[^/\s]+?)(?:\.git)?/?$", url.strip())
    return m.group(1).lower() if m else ""


PR_FIELDS = "headRefName,state,url,isDraft,mergeable,statusCheckRollup"
_PR_CACHE: dict = {}


def pr_view(selector: str, repo: str, cwd) -> dict:
    """One read-only `gh pr view` per hook run, shared by the ownership and readiness checks, inside
    the hook's 10 s budget. {} when the PR cannot be resolved, which denies."""
    if not repo and "/pull/" not in selector and cwd is None:
        return {}
    key = (selector, repo, cwd)
    if key not in _PR_CACHE:
        try:
            p = subprocess.run(["gh", "pr", "view", selector, "--json", PR_FIELDS,
                                *(["--repo", repo] if repo else [])],
                               cwd=cwd or None, capture_output=True, text=True, timeout=8)
            pr = json.loads(p.stdout) if p.returncode == 0 else {}
        except Exception:
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


def covers(text: str, number: str, payload: dict, selector: str, repo: str, cwd) -> bool:
    """Simon's words name this PR's number, or (naming no other PR, or saying all/both/them) cover
    it as an open PR this session pushed, or say all/both/them in answer to a hand-back whose merge
    list names it (the fix for "merge and deploy both" refused for the base PR of a stack another
    session pushed, which the hand-back had listed for him to merge)."""
    if re.search(rf"(?<!\d){number}(?!\d)", text):
        return True
    bulk, numbered = bool(BULK_RE.search(text)), bool(PR_NUMBER_RE.search(text))
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
    if covers(text, number, payload, selector, repo, cwd):
        return True
    if BULK_RE.search(text) or PR_NUMBER_RE.search(text):
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
# shipping, or says stop/hold/wait/cancel/pause. A bare "don't" about something else does not: the
# instruction spans many messages, and most of them are about other work.
STANDING_NEGATED_RE = NEGATED_RE
STANDING_HALT_RE = re.compile(r"\b(stop|hold|wait|cancel|pause)\b", re.I)
STANDING_CLOSE_RE = re.compile(r"\b(close|closed|closing|abandon)\b", re.I)
# "merge all", "merge them all", "merge both", "merge everything": a merge over the whole set.
STANDING_BULK_RE = re.compile(r"\bmerg(?:e|ed|es|ing)\b[^.\n?]{0,30}?\b(all|everything|every|both|each)\b", re.I)
PASSED_CONCLUSIONS = {"SUCCESS", "NEUTRAL", "SKIPPED"}


def session_asks(payload: dict) -> list:
    """Every ask Simon typed this session, oldest first, cleaned like turn_asks."""
    raw = ledger_asks(payload, "1970-01-01T00:00:00Z")
    cleaned = (QUOTED_RE.sub("", HARNESS_BLOCK_RE.sub("", a)).strip() for a in raw)
    return [a for a in cleaned if a]


def standing_merge_ask(asks: list, number: str = "") -> str:
    """The session's newest standing merge ask with no later halt, or "". Standing asks are
    conditional ones, merge-all ones, and (given `number`) an explicit merge ask that names that PR."""
    named = re.compile(rf"(?<!\d){number}(?!\d)") if number else None
    for i in range(len(asks) - 1, -1, -1):
        ask = asks[i]
        standing = CONDITIONAL_RE.search(ask) or STANDING_BULK_RE.search(ask) or (named and named.search(ask))
        if instructs(ask, "merge") and standing and not STANDING_NEGATED_RE.search(ask):
            later = asks[i + 1:]
            halted = any(STANDING_NEGATED_RE.search(a) or STANDING_HALT_RE.search(a)
                         or (named and STANDING_CLOSE_RE.search(a) and named.search(a)) for a in later)
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


def merge_allowed(payload: dict, words: list, cwd) -> tuple:
    """(allowed, why_not): this turn's words authorize the merge, or a standing merge instruction
    from this session does and the PR is ready now."""
    if turn_merge_allowed(payload, words, cwd):
        return True, ""
    return standing_merge(payload, words, cwd)


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
        try:
            os.makedirs(STATE_DIR, exist_ok=True)
            with open(marker, "w") as f:
                f.write(number)
            return True
        except OSError:
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
    gh_cwd = cwd  # where a `gh pr view` lookup runs; None once a `cd` cannot be resolved statically
    for seg in segments(command):
        words = command_words(seg)
        if words[:1] == ["cd"]:
            path = words[1] if len(words) == 2 else ""
            literal = path and gh_cwd and not any(ch in path for ch in "$`'\"")
            gh_cwd = os.path.abspath(os.path.join(gh_cwd, os.path.expanduser(path))) if literal else None
        sub = git_subcommand(words)
        is_commit = sub == "commit"
        is_push = sub == "push"
        is_gh_merge = bool(words) and os.path.basename(words[0]) == "gh" and words[1:3] == ["pr", "merge"]
        is_gh_api = bool(words) and os.path.basename(words[0]) == "gh" and words[1:2] == ["api"]
        if is_gh_api and API_MERGE_RE.search(command):
            return deny(
                "Blocked: a merge, enqueue or auto-merge through `gh api` bypasses the merge check. "
                "Use `gh pr merge <n>`, which runs only when the user's own words this turn say "
                "\"merge\" and cover the PR."
            )
        if not (is_commit or is_push or is_gh_merge):
            continue

        # 0. `gh pr merge` merges into the remote default branch — the action that once merged 8 PRs
        # (two on red CI) into master off a general "merge everything". A general instruction is never
        # a yes for a specific merge, so block unless the user's own words this turn cover THIS
        # merge. The deny message is what tells Claude to get that yes.
        allowed, why_not = merge_allowed(payload, words, gh_cwd) if is_gh_merge else (True, "")
        if not allowed:
            number = merge_target(words)[1]
            return deny(
                "Blocked: `gh pr merge` merges a PR into the remote default branch, and it runs only "
                "on the user's OWN words this turn (every message since your last hand-back, queued "
                "ones included) saying \"merge\" with no later stop/hold/wait, and naming this PR's "
                "number"
                + (f" (#{number})" if number else " (name the number, not a branch)") + ", covering "
                "it as an open PR this session pushed (no number, or all/both/them), saying all/both/them to a "
                "hand-back whose Merge list names it, or naming no PR "
                "for one other PR; or on a standing merge an earlier message this session gave "
                "(\"merge ... when ready\", \"once CI is green then merge\", or \"merge all\"; never a question) covering it, when no "
                "later message said stop/hold/wait/cancel or not to merge/deploy, and the PR is open, not a draft, "
                "mergeable and every check passed. A standing instruction lasts for this session "
                "only. "
                + (f"A standing instruction covers this PR, but it is not ready: {why_not}. Wait for "
                   "CI and retry; do not ask the user again. " if why_not else "")
                + "A yes to a question you wrote, 'finish it', 'proceed', 'priority' or 'continue' "
                "is never that. There is no override flag. Stop at a ready, green PR and ask: "
                "\"Say 'merge #<n>' to merge it.\""
            )

        # 1. Default-branch protection. The override counts whether the flag is in the hook's OWN env
        # OR prefixed inline on the command (`CLAUDE_ALLOW_MAIN_COMMIT=1 git push …`). Claude only
        # adds it once the user has confirmed THIS push; a bare push with no flag stays blocked. The
        # config repo was judged above: its commits pass, and its main pushes need a verified head.
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
