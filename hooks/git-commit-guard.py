#!/usr/bin/env python3
"""
PreToolUse Bash guard for the two irreversible git actions an agent can take without Simon:

  1. Merging or enqueueing a PR into the remote default branch: `gh pr merge` (auto-merge included),
     or a merge, enqueue or auto-merge sent through the API (gh api, curl, wget, httpie).
  2. Pushing straight to the remote default branch.

Everything else runs: reads, PR create/edit/comment, dequeue and `--disable-auto`, commits, and any
text that only MENTIONS those commands (a heredoc body, a note, a quoted string, file content). The
guard lexes the command the way the shell will run it and judges only commands that execute, with
wrappers, `bash -c`, eval, command substitutions, gh and git aliases and stdin a shell reads as code
unwrapped. A command word built at run time beside a merge word, or a shell reading code it cannot
see (a pipe, a built string) that names a merge, is denied.

A merge passes on one of two paths, in this order:
  - a monitoring-only PR at its bar (monitoring_merge; references/git-pr-deploy.md § Monitoring-only
    changes). No message is read.
  - Simon's own words, one deterministic rule (words_allow), no model call: among every message he typed
    in the session, the newest that orders #N merged (a present-tense merge verb, not negated, not a question,
    naming #N, or a referent such as "both" or "it" in an imperative aimed at it while the message answers a hand-back that asked a
    merge word for #N on its Merge list, Action needed line or an end-block numbered step) with no later
    message holding merges. The hand-back only resolves the referent: his words still give the order.
Only user turns of the transcript count; a peer envelope, a harness block, a tool answer and a
delegated worker's brief never do. There is no override flag.

A default-branch push needs CLAUDE_ALLOW_MAIN_COMMIT set to 1 in the session's starting environment
AND Simon's typed "push" this turn. In the ~/.claude config repo a push to main passes instead when
bin/config-land-check.py verified every pushed head and it fast-forwards the remote.

It fails open on malformed input that names no merge or push; a crash or stall on a command that
might merge declines.
"""

import datetime
import itertools
import json
import os
import re
import shlex
import signal
import subprocess
import sys
import time
from urllib.parse import quote, unquote

MAX_DEPTH = 6
SYNTAX = {"!", "{", "}", "if", "then", "else", "elif", "fi", "do", "done", "while", "until", "time", "coproc",
          "noglob", "nocorrect", "-", "function"}
ASSIGN_RE = re.compile(r"^[A-Za-z_][A-Za-z0-9_]*\+?=")
WRAPPERS = {"sudo", "doas", "env", "command", "builtin", "exec", "nohup", "nice", "timeout", "gtimeout",
            "stdbuf", "caffeinate", "xargs", "watch"}
WRAPPER_VALUE_OPTS = {"-u", "-g", "-n", "-I", "-J", "-P", "-d", "-L", "-s", "-k", "-a", "-E", "-C", "-t", "-i",
                      "--user", "--group", "--unset", "--max-args", "--max-procs", "--delimiter", "--signal",
                      "--kill-after", "--interval", "--chdir"}
SHELLS = {"bash", "sh", "zsh", "dash", "ksh", "fish"}
SHELL_C_RE = re.compile(r"^-[a-zA-Z]*c[a-zA-Z]*$")
INTERPRETER_RE = re.compile(r"(?:python|pypy|node|deno|bun|perl|ruby|php)[\d.]*")
GH_COMMANDS = {"auth", "browse", "codespace", "discussion", "gist", "issue", "org", "pr", "project", "release",
               "repo", "cache", "run", "workflow", "alias", "api", "attestation", "completion", "config",
               "copilot", "extension", "ext", "gpg-key", "label", "licenses", "preview", "ruleset", "search",
               "secret", "ssh-key", "status", "variable", "help", "version", "skill", "stack", "agent-task",
               "--version", "--help", "-h"}
GIT_COMMON = set("""add am apply archive bisect blame branch bundle cat-file check-attr check-ignore checkout
cherry cherry-pick clean clone commit commit-tree config count-objects describe diff diff-tree difftool fetch
for-each-ref format-patch fsck gc grep hash-object help init lfs log ls-files ls-remote ls-tree maintenance merge
merge-base merge-file merge-tree mergetool mv name-rev notes pull push range-diff read-tree rebase reflog remote
repack replace rerere reset restore rev-list rev-parse revert rm shortlog show show-branch show-ref
sparse-checkout stash status submodule switch symbolic-ref tag update-index update-ref var verify-commit version
whatchanged worktree write-tree""".split())
# A merge, enqueue or auto-merge mutation, a branch merge into a base, and REST endpoints that merge a PR,
# merge a branch or move a default branch.
MERGE_MUTATION_RE = re.compile(r"\b(?:mergePullRequest|enqueuePullRequest|enablePullRequestAutoMerge|mergeBranch)\b",
                               re.I)
MERGE_PATH_RE = re.compile(r"/pulls/[^/]+/merge/?$|/merges/?$|/git/refs/heads/(?:main|master)/?$", re.I)
# What an opaque piece of code (piped into a shell, a built string, an unparsable command) must not name.
OPAQUE_HIT_RE = re.compile(r"\bgh\b[\s\S]*\bmerge\b|\bgit\b[\s\S]*\bpush\b[\s\S]*\b(?:main|master)\b|"
                           r"pulls/\S+/merge|" + MERGE_MUTATION_RE.pattern, re.I)
QUICK_RE = re.compile(r"gh|git|curl|wget|http|xh|merge|push|graphql|eval|python|node|perl|ruby|deno|bun|php", re.I)


def plain(text: str) -> str:
    """text as the shell joins it, quotes and backslashes dropped: `'g'h`, `me''rge` and `g\\h` read plainly."""
    return re.sub(r"['\"\\]", "", text)


# ---------------------------------------------------------------- the shell lexer

class Unparsable(Exception):
    pass


class Word:
    __slots__ = ("text", "dyn", "quoted")

    def __init__(self, text: str, dyn: bool = False, quoted: bool = False):
        self.text, self.dyn, self.quoted = text, dyn, quoted


class Cmd:
    """One simple command: its words, its stdin sources (heredoc, here-string, `<` file) and whether
    a pipe feeds it."""

    def __init__(self, piped: bool = False):
        self.words, self.stdin, self.piped = [], [], piped


def _close_paren(s: str, i: int) -> int:
    """Index of the `)` closing the `(` just before i, skipping quotes and nested parens."""
    depth, n = 1, len(s)
    while i < n:
        ch = s[i]
        if ch == "\\":
            i += 2
            continue
        if ch == "'":
            j = s.find("'", i + 1)
            if j < 0:
                raise Unparsable("unclosed quote")
            i = j + 1
            continue
        if ch == '"':
            i = _dq(s, i + 1, '"', 0)[2]
            continue
        if ch == "(":
            depth += 1
        elif ch == ")":
            depth -= 1
            if depth == 0:
                return i
        i += 1
    raise Unparsable("unclosed parenthesis")


def _dollar(s: str, i: int, depth: int) -> tuple:
    """(text, dynamic, next index, commands it runs) for an expansion starting at s[i] (`$` or a backquote)."""
    n = len(s)
    if s[i] == "`":
        j, buf = i + 1, []
        while j < n and s[j] != "`":
            if s[j] == "\\" and j + 1 < n:
                j += 1
            buf.append(s[j])
            j += 1
        if j >= n:
            raise Unparsable("unclosed backquote")
        return "\x00", True, j + 1, lex("".join(buf), depth + 1)
    nxt = s[i + 1] if i + 1 < n else ""
    if s.startswith("$((", i):
        return "0", True, _close_paren(s, i + 2) + 1, []
    if nxt == "(":
        j = _close_paren(s, i + 2)
        return "\x00", True, j + 1, lex(s[i + 2:j], depth + 1)
    if nxt == "{":
        j = s.find("}", i + 2)
        if j < 0:
            raise Unparsable("unclosed ${")
        return "\x00", True, j + 1, []
    m = re.match(r"[A-Za-z_][A-Za-z0-9_]*|[@*#?$!0-9-]", s[i + 1:])
    if m:
        return "\x00", True, i + 1 + m.end(), []
    return "$", False, i + 1, []


def _dq(s: str, i: int, stop, depth: int) -> tuple:
    """(text, dynamic, next index, commands it runs) for double-quoted text from i up to `stop` (None: to the
    end, as an unquoted heredoc body expands)."""
    out, dyn, subs, n = [], False, [], len(s)
    while i < n:
        ch = s[i]
        if stop and ch == stop:
            return "".join(out), dyn, i + 1, subs
        if ch == "\\" and i + 1 < n:
            if s[i + 1] in '"\\$`':
                out.append(s[i + 1])
            elif s[i + 1] != "\n":
                out.append(ch + s[i + 1])
            i += 2
            continue
        if ch in "$`":
            text, d, i, sub = _dollar(s, i, depth)
            out.append(text)
            dyn, subs = dyn or d, subs + sub
            continue
        out.append(ch)
        i += 1
    if stop:
        raise Unparsable("unclosed double quote")
    return "".join(out), dyn, i, subs


REDIRECT_OPS = ("&>>", "&>", "<<<", "<<-", "<<", "<>", "<&", ">>", ">&", ">|", "<", ">")


def lex(s: str, depth: int = 0) -> list:
    """Every simple command the text runs, in order, the commands inside $(...), backquotes and <(...)
    included. Quoted text and heredoc bodies are data of their command; an unquoted heredoc body is read
    only for the substitutions it runs."""
    if depth > MAX_DEPTH:
        raise Unparsable("nested too deep")
    cmds, n = [], len(s)
    st = {"cur": Cmd(), "buf": [], "dyn": False, "quoted": False, "inword": False, "target": None}
    pending = []

    def flush():
        if not st["inword"]:
            return
        w = Word("".join(st["buf"]), st["dyn"], st["quoted"])
        target, cur = st["target"], st["cur"]
        if target is None:
            cur.words.append(w)
        elif target in ("<<", "<<-"):
            pending.append((cur, w.text, w.quoted, target == "<<-"))
        elif target == "<<<":
            cur.stdin.append(("string", w.text, w.dyn))
        elif target == "<":
            cur.stdin.append(("file", w.text, w.dyn))
        st.update(buf=[], dyn=False, quoted=False, inword=False, target=None)

    def end(sep: str):
        flush()
        st["target"] = None
        cur = st["cur"]
        if cur.words or cur.stdin:
            cmds.append(cur)
        st["cur"] = Cmd(piped=sep in ("|", "|&"))

    def word(text: str, dyn: bool = False, quoted: bool = False):
        st["buf"].append(text)
        st["dyn"] = st["dyn"] or dyn
        st["quoted"] = st["quoted"] or quoted
        st["inword"] = True

    i = 0
    while i < n:
        ch = s[i]
        if ch == "\\":
            if s.startswith("\\\n", i):
                i += 2
                continue
            word(s[i + 1:i + 2], quoted=True)
            i += 2
            continue
        if ch == "'":
            j = s.find("'", i + 1)
            if j < 0:
                raise Unparsable("unclosed single quote")
            word(s[i + 1:j], quoted=True)
            i = j + 1
            continue
        if ch == '"':
            text, d, i, subs = _dq(s, i + 1, '"', depth)
            cmds.extend(subs)
            word(text, d, True)
            continue
        if s.startswith("$'", i):  # ANSI-C quoting: its escapes are not decoded, so the word counts as built
            j = i + 2
            while j < n and s[j] != "'":
                j += 2 if s[j] == "\\" else 1
            if j >= n:
                raise Unparsable("unclosed $'")
            word(s[i + 2:j], True, True)
            i = j + 1
            continue
        if ch in "$`":
            text, d, i, subs = _dollar(s, i, depth)
            cmds.extend(subs)
            word(text, d)
            continue
        if ch in "<>" and s.startswith("(", i + 1) and not st["inword"]:  # process substitution
            j = _close_paren(s, i + 2)
            cmds.extend(lex(s[i + 2:j], depth + 1))
            word("\x00", True)
            i = j + 1
            continue
        if ch == "#" and not st["inword"]:
            j = s.find("\n", i)
            i = n if j < 0 else j
            continue
        if ch in " \t\r":
            flush()
            i += 1
            continue
        if ch == "\n":
            end("\n")
            i += 1
            for cmd, delim, quoted_delim, dash in pending:  # heredoc bodies start on the next line
                lines = []
                while i < n:
                    j = s.find("\n", i)
                    j = n if j < 0 else j
                    line, i = s[i:j], j + 1
                    if (line.lstrip("\t") if dash else line) == delim:
                        break
                    lines.append(line)
                body = "\n".join(lines)
                dyn = False
                if not quoted_delim:
                    _, dyn, _, subs = _dq(body, 0, None, depth)
                    cmds.extend(subs)
                cmd.stdin.append(("heredoc", body, dyn))
            pending.clear()
            continue
        if ch in "<>" or s.startswith("&>", i):
            if st["inword"] and "".join(st["buf"]).isdigit() and not st["quoted"]:
                st.update(buf=[], inword=False)  # a file-descriptor number, not a word
            flush()
            op = next(o for o in REDIRECT_OPS if s.startswith(o, i))
            st["target"] = op if op in ("<<", "<<-", "<<<", "<") else ">"
            i += len(op)
            continue
        if ch in ";&|()":
            two = s[i:i + 2]
            if two in ("&&", "||", ";;", "|&"):
                end(two)
                i += 2
            else:
                end(ch)
                i += 1
            continue
        word(ch)
        i += 1
    end("")
    for cmd, _, _, _ in pending:  # a heredoc whose body never started: an empty body
        cmd.stdin.append(("heredoc", "", False))
    return cmds


# ---------------------------------------------------------------- shared helpers and the config repo

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


DEFAULT_BRANCHES = {"main", "master"}

# Written by bin/config-land-check.py into the config repo's shared Git directory, so every worktree
# of that repo reads the same record. It lists head shas that passed the land checks.
LAND_MARKER = "claude-config-land.json"

# Push options that cannot change WHAT lands. Anything else (force, delete, mirror, all, tags,
# no-verify, a push option) leaves the config push on the ordinary confirmation path.
SAFE_PUSH_OPTS = {"-u", "--set-upstream", "-q", "--quiet", "-v", "--verbose", "--porcelain",
                  "--atomic", "--no-progress", "--progress"}

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


# ---------------------------------------------------------------- what the commands do

class Scan:
    """Walks the commands a Bash input runs and records the guarded actions in order:
    ("merge", argv words, directory or None), ("push", git argv words, directory or None) and
    ("deny", reason). The directory follows a literal cd; one it cannot follow becomes None."""

    def __init__(self, raw: str, cwd: str):
        self.raw, self.cwd, self.actions, self.repo_env = raw, cwd, [], False

    def deny(self, reason: str):
        self.actions.append(("deny", reason))

    def opaque(self, what: str):
        """Code the guard cannot read runs here: deny only when the input names a merge or default push."""
        if OPAQUE_HIT_RE.search(plain(self.raw)):
            self.deny(f"{what}, so the merge or push it may run cannot be checked. Run it as a plain command")

    def text(self, text: str, depth: int):
        try:
            cmds = lex(text, depth)
        except Unparsable:
            return self.opaque("a nested command could not be parsed")
        for c in cmds:
            self.judge(c.words, c, depth)

    def judge(self, words: list, cmd: Cmd, depth: int = 0):
        if depth > MAX_DEPTH:
            return self.opaque("commands nest too deep")
        w = list(words)
        while w and ((w[0].text in SYNTAX and not w[0].quoted) or ASSIGN_RE.match(w[0].text)):
            self.repo_env = self.repo_env or bool(re.match(r"(?:GH_REPO|GH_HOST|GH_ENTERPRISE_TOKEN)\+?=", w[0].text))
            w = w[1:]
        if not w:
            return
        head, args = w[0], w[1:]
        if head.dyn or re.search(r"[*?\[]", head.text):
            if any(a.text == "merge" or MERGE_MUTATION_RE.search(a.text) or "/merge" in a.text for a in args):
                self.deny("the command word is built at run time beside a merge word, so what it runs cannot "
                          "be checked. Run `gh pr merge <number>` plainly")
            return
        name = os.path.basename(head.text)
        if name in WRAPPERS:
            return self.wrapper(name, args, cmd, depth)
        if name in SHELLS:
            return self.shell(args, cmd, depth)
        if name == "eval":
            if any(a.dyn for a in args):
                return self.opaque("eval runs a string built at run time")
            return self.text(" ".join(a.text for a in args), depth + 1)
        if name in ("export", "declare", "typeset", "local", "readonly"):
            self.repo_env = self.repo_env or any(re.match(r"(?:GH_REPO|GH_HOST|GH_ENTERPRISE_TOKEN)=", a.text)
                                                 for a in args)
            return
        if name == "alias" and any(re.search(r"\bgh\b", a.text) and re.search(r"merge|\bapi\b", a.text) for a in args):
            return self.deny("a shell alias that merges hides the merge. Run `gh pr merge <number>` plainly")
        if name == "find":
            return self.find_exec(args, cmd, depth)
        if INTERPRETER_RE.fullmatch(name):
            return self.interpreter(args, cmd)
        if name in ("cd", "pushd", "popd"):
            return self.cd(name, args, depth)
        if name == "git":
            return self.git(args, cmd, depth)
        if name == "gh":
            return self.gh(args, cmd, depth)
        if name in ("curl", "wget", "http", "https", "xh"):
            why = api_merge(name, args, cmd, self.raw)
            if why:
                self.deny(why)

    def wrapper(self, name: str, args: list, cmd: Cmd, depth: int):
        rest, placeholder = list(args), None
        if name == "command" and rest and rest[0].text in ("-v", "-V"):
            return  # prints where a command lives; runs nothing
        while rest and (rest[0].text.startswith("-") and rest[0].text != "--" or
                        (name == "env" and ASSIGN_RE.match(rest[0].text))):
            o = rest.pop(0)
            if ASSIGN_RE.match(o.text):
                self.repo_env = self.repo_env or bool(re.match(r"(?:GH_REPO|GH_HOST|GH_ENTERPRISE_TOKEN)=", o.text))
                continue
            if name == "env" and o.text in ("-S", "--split-string") and rest:
                return self.text(rest.pop(0).text + " " + " ".join(shlex.quote(a.text) for a in rest), depth + 1)
            if name == "xargs" and o.text in ("-I", "-J", "-i", "--replace") or o.text.startswith(("-I", "--replace=")):
                placeholder = (rest.pop(0).text if o.text in ("-I", "-J") and rest else
                               o.text.split("=", 1)[1] if "=" in o.text else o.text[2:] or "{}")
                continue
            if o.text in WRAPPER_VALUE_OPTS and rest:
                rest.pop(0)
        if rest and rest[0].text == "--":
            rest.pop(0)
        if name in ("timeout", "gtimeout", "nice") and rest and re.fullmatch(r"[\d.]+[smhd]?", rest[0].text):
            rest.pop(0)
        if name == "xargs":  # the command takes arguments from stdin, which the guard cannot read
            rest = [Word(a.text, True, a.quoted) if placeholder and placeholder in a.text else a for a in rest]
            rest.append(Word("\x00", True))
        self.judge(rest, cmd, depth + 1)

    def shell(self, args: list, cmd: Cmd, depth: int):
        i = 0
        while i < len(args):
            t = args[i].text
            if SHELL_C_RE.match(t):
                if i + 1 >= len(args):
                    return
                if args[i + 1].dyn:
                    return self.opaque("a shell runs a string built at run time")
                return self.text(args[i + 1].text, depth + 1)
            if t in ("-o", "+o", "-O", "+O"):
                i += 2
                continue
            if t.startswith(("-", "+")) and t not in ("-", "--"):
                i += 1
                continue
            break
        if i < len(args) and args[i].text not in ("-", "--"):
            return  # runs a script file: file content is not read (a residual: run merges plainly)
        for kind, text, dyn in cmd.stdin:
            if kind == "file":
                continue
            if dyn:
                self.opaque("a shell reads code with expansions from its stdin")
            self.text(text, depth + 1)
        if cmd.piped:
            self.opaque("a shell reads its commands from a pipe")

    def find_exec(self, args: list, cmd: Cmd, depth: int):
        texts = [a.text for a in args]
        for flag in ("-exec", "-execdir", "-ok", "-okdir"):
            if flag in texts:
                start = texts.index(flag) + 1
                end = next((k for k in range(start, len(texts)) if texts[k] in (";", "+")), len(texts))
                self.judge([Word(a.text, a.dyn or "{}" in a.text, a.quoted) for a in args[start:end]], cmd, depth + 1)

    def interpreter(self, args: list, cmd: Cmd):
        """A program given inline (-c, -e, or stdin) that starts gh to merge, or sends a merge request."""
        programs = [args[k + 1].text for k, a in enumerate(args[:-1]) if a.text in ("-c", "-e", "--eval", "-p", "-E")]
        if not any(not a.text.startswith("-") for a in args) or any(a.text == "-" for a in args):
            programs += [t for kind, t, _ in cmd.stdin if kind != "file"]
        for p in programs:
            launches = re.search(r"subprocess|os\.system|os\.exec|popen|spawn|execSync|execFile|child_process|"
                                 r"Deno\.Command|\bsystem\s*\(|`", p)
            sends = re.search(r"requests|urllib|http\.client|fetch\s*\(|axios|Net::HTTP|LWP|curl", p)
            if (launches and re.search(r"\bgh\b['\"\s,\]]+pr['\"\s,]+merge\b", p)) or (
                    sends and (MERGE_MUTATION_RE.search(p) or re.search(r"pulls/[^/\s'\"]+/merge", p))):
                return self.deny("an inline program starts a merge, which hides it from this guard. Run "
                                 "`gh pr merge <number>` plainly")

    def cd(self, name: str, args: list, depth: int):
        if name == "popd" or len(args) != 1 or args[0].dyn or args[0].text == "-" or not self.cwd:
            self.cwd = None
            return
        self.cwd = os.path.abspath(os.path.join(self.cwd, os.path.expanduser(args[0].text)))

    def git(self, args: list, cmd: Cmd, depth: int):
        where, i, config = self.cwd, 0, {}
        while i < len(args) and args[i].text.startswith("-"):
            o = args[i].text
            if o in ("-C", "-c", "--git-dir", "--work-tree", "--namespace", "--exec-path") and i + 1 < len(args):
                value = args[i + 1]
                if o == "-C":
                    where = (os.path.abspath(os.path.join(where, os.path.expanduser(value.text)))
                             if where and not value.dyn else None)
                elif o == "-c":
                    key, _, val = value.text.partition("=")
                    config[key.lower()] = val
                elif o in ("--git-dir", "--work-tree"):
                    where = None
                i += 2
                continue
            if o.startswith(("--git-dir=", "--work-tree=")):
                where = None
            i += 1
        if i >= len(args):
            return
        sub, rest = args[i], args[i + 1:]
        if sub.dyn:
            if any(re.search(r"\b(?:main|master)\b", a.text) for a in rest):
                self.deny("the git subcommand is built at run time beside main/master. Run `git push` plainly")
            return
        if sub.text == "push":
            self.actions.append(("push", rest, where))
            return
        if sub.text in GIT_COMMON:
            return
        alias = config.get(f"alias.{sub.text.lower()}")
        if alias is None:
            try:
                p = subprocess.run(["git", "config", "--get", f"alias.{sub.text}"], cwd=where or self.cwd or None,
                                   capture_output=True, text=True, timeout=3)
                alias = p.stdout.strip() if p.returncode == 0 else ""
            except Exception:
                alias = ""
        if not alias:
            return
        tail = " ".join(shlex.quote(a.text) for a in rest)
        if alias.startswith("!"):
            return self.text(alias[1:] + " " + tail, depth + 1)
        self.text("git " + alias + " " + tail, depth + 1)

    def gh(self, args: list, cmd: Cmd, depth: int):
        if not args:
            return
        sub = args[0]
        if sub.dyn:
            if any(a.text == "merge" or MERGE_MUTATION_RE.search(a.text) for a in args[1:]):
                self.deny("the gh subcommand is built at run time beside a merge word. Run `gh pr merge <number>` plainly")
            return
        if sub.text == "pr":
            rest, moved = list(args[1:]), []
            while rest and rest[0].text.startswith("-"):  # `gh pr -R o/r merge 12`
                moved.append(rest.pop(0))
                if moved[-1].text in ("-R", "--repo") and rest:
                    moved.append(rest.pop(0))
            if rest and rest[0].dyn and any(a.text.isdigit() or a.dyn for a in rest[1:]):
                return self.deny("the gh pr subcommand is built at run time. Run `gh pr merge <number>` plainly")
            if rest and rest[0].text == "merge":
                self.actions.append(("merge", rest[1:] + moved, self.cwd))
            return
        if sub.text == "api":
            why = api_merge("gh", args[1:], cmd, self.raw)
            if why:
                self.deny(why)
            return
        if sub.text == "alias":
            if len(args) > 1 and args[1].text in ("set", "import") and any(
                    re.search(r"merge|\bapi\b", a.text) for a in args[2:]):
                self.deny("a gh alias that merges hides the merge. Run `gh pr merge <number>` plainly")
            return
        if sub.text in GH_COMMANDS or sub.text.startswith("-"):
            return
        try:  # an alias: `gh pm 12` for `pr merge`
            p = subprocess.run(["gh", "alias", "list"], capture_output=True, text=True, timeout=5)
            lines = p.stdout.splitlines() if p.returncode == 0 else []
        except Exception:
            lines = []
        aliases = {}
        for line in lines:
            k, _, v = line.partition(":")
            aliases[k.strip().strip("'\"")] = v.strip().strip("'\"")
        expansion = aliases.get(sub.text)
        if not expansion:
            return  # an extension, which merges only through its own code
        tail = " ".join(shlex.quote(a.text) for a in args[1:])
        if expansion.startswith("!"):
            return self.text(expansion[1:] + " " + tail, depth + 1)
        self.text("gh " + expansion + " " + tail, depth + 1)


def _read_file(path: str) -> str:
    try:
        with open(os.path.expanduser(path), encoding="utf-8", errors="replace") as f:
            return f.read(1_000_000)
    except Exception:
        return None


def _graphql_names_merge(query: str) -> bool:
    """A GraphQL document calls a merge, enqueue or auto-merge mutation; names inside its string literals and
    comments are data."""
    q = re.sub(r'"""[\s\S]*?"""|"(?:\\.|[^"\\])*"', '""', query or "")
    q = re.sub(r"#[^\n]*", "", q)
    return bool(MERGE_MUTATION_RE.search(q))


def _query_of(body: str) -> str:
    """The query of a JSON GraphQL body, or the body itself."""
    try:
        data = json.loads(body)
    except Exception:
        return body
    if isinstance(data, dict):
        return str(data.get("query", ""))
    if isinstance(data, list):
        return "\n".join(str(d.get("query", "")) for d in data if isinstance(d, dict))
    return body


def api_merge(client: str, args: list, cmd: Cmd, raw: str) -> str:
    """Why this API call merges, enqueues or auto-merges a PR, merges a branch or moves a default branch;
    "" when it does not. Only the call's own arguments and the body it sends are read; when those cannot be
    read (a variable, stdin from a pipe, a missing file), the whole input decides through OPAQUE_HIT_RE."""
    method, urls, bodies, queries, opaque = "", [], [], [], False
    stdin = [t for kind, t, d in cmd.stdin if kind != "file"]

    def source(value: str):
        """The text a `@file` or `-` value refers to; None when unreadable."""
        if value in ("@-", "-"):
            return "\n".join(stdin) if stdin and not cmd.piped else None
        return _read_file(value[1:]) if value.startswith("@") else value

    k, texts = 0, [a.text for a in args]
    while k < len(args):
        a, t = args[k], texts[k]
        name, eq, val = t.partition("=") if t.startswith("--") else (t, "", "")
        if client == "gh" and not t.startswith("--") and len(t) > 2 and t[:2] in ("-X", "-f", "-F", "-H"):
            name, val, eq = t[:2], t[2:].lstrip("="), "="
        needs_value = name in ("-X", "--method", "--request", "-f", "-F", "--field", "--raw-field", "-H", "--header",
                               "--input", "-d", "--data", "--data-raw", "--data-binary", "--data-urlencode", "--json",
                               "-T", "--upload-file", "-K", "--config", "--post-data", "--post-file", "--body-data",
                               "--body-file", "--url") or name in (
            ("-q", "--jq", "-t", "--template", "-p", "--preview", "--hostname", "--cache") if client == "gh" else
            ("-o", "--output", "-u", "--user", "-A", "-e", "-w", "-m", "-b", "-c", "--connect-timeout", "--max-time"))
        if needs_value and not eq:
            if k + 1 >= len(args):
                break
            k += 1
            a, val = args[k], texts[k]
        if needs_value:
            if a.dyn:
                opaque = True
            if name in ("-X", "--method", "--request"):
                method = val.upper()
            elif name in ("-f", "-F", "--field", "--raw-field") and client == "gh":
                key, _, v = val.partition("=")
                got = source(v) if v.startswith("@") else v
                opaque = opaque or got is None
                if key == "query":
                    queries.append(got or "")
                bodies.append(got or "")
            elif name in ("-F",) and client == "curl":
                bodies.append(val)
            elif name in ("--input", "-d", "--data", "--data-raw", "--data-binary", "--data-urlencode", "--json",
                          "--post-data", "--body-data", "--post-file", "--body-file", "-T", "--upload-file"):
                got = source(val if name not in ("--input", "--post-file", "--body-file", "-T", "--upload-file")
                             or val == "-" else "@" + val)
                opaque = opaque or got is None
                bodies.append(got or "")
                queries.append(_query_of(got or ""))
            elif name in ("-K", "--config"):
                opaque = True
            elif name in ("-H", "--header") and re.search(r"method-override", val, re.I):
                opaque = True
            elif name == "--url":
                urls.append(a)
        elif not t.startswith("-"):
            if client in ("http", "https", "xh") and not urls and re.fullmatch(r"GET|POST|PUT|PATCH|DELETE|HEAD", t):
                method = t
            elif client == "gh" or re.search(r"://|api\.github\.com|^/|graphql", t) and not urls:
                if client == "gh" and urls:
                    bodies.append(t)
                else:
                    urls.append(a)
            elif client in ("http", "https", "xh") and re.match(r"[^=:]+:?=", t):
                key, _, v = t.partition("=")
                bodies.append(v)
                if key.rstrip(":") == "query":
                    queries.append(v)
        k += 1
    if not method:
        method = "POST" if bodies else "GET"
    for u in urls:
        if u.dyn:
            opaque = True
        path = unquote(unquote(u.text)).split("?", 1)[0]
        path = re.sub(r"^[a-z]+://[^/]+", "", path)
        path = os.path.normpath("/" + path.lstrip("/")) if path else "/"
        if MERGE_PATH_RE.search(path) and method not in ("GET", "HEAD"):
            return ("a merge or default-branch write through the API bypasses the merge check. Use "
                    "`gh pr merge <number>`, one command per PR")
        if path.rstrip("/").endswith("graphql") and any(_graphql_names_merge(q) for q in queries + bodies):
            return ("a merge, enqueue or auto-merge mutation through the API bypasses the merge check. Use "
                    "`gh pr merge <number>`, one command per PR")
    if (opaque or cmd.piped and any(b in (None, "") for b in bodies)) and OPAQUE_HIT_RE.search(plain(raw)):
        return ("an API call whose target or body is built at run time sits beside a merge word, so it cannot "
                "be checked. Write the call out plainly, or use `gh pr merge <number>`")
    return ""


# ---------------------------------------------------------------- Simon's typed messages

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


def part_text(parts) -> str:
    return " ".join(str(x.get("text", "")) for x in parts or [] if isinstance(x, dict) and x.get("type", "text") == "text")


# System text inside a prompt is never Simon's: harness blocks, a host's instructions, slash-command tags.
SYSTEM_BLOCK_RE = re.compile(r"<(system-reminder|task-notification|agent-message|cross-session-message|system_instruction"
                             r"|command-message|command-name|local-command-std(?:out|err)|bash-input|bash-std(?:out|err))"
                             r"\b[^>]*>[\s\S]*?</\1>", re.I)
# Pasted material: a fenced block, or a `>` quote line.
PASTED_RE = re.compile(r"^[ \t]*(`{3,}|~{3,})[\s\S]*?^[ \t]*\1[ \t]*$|^[ \t]*>.*$", re.M)
# A turn that opens with another session's attribution is that session's note relayed, not Simon's words.
PEER_OPENER_RE = re.compile(r"\A\W*(?:from (?!this\b|that\b|my\b|our\b|the current\b)(?:the )?[\w .'/-]{1,60}? session\b"
                            r"|another claude session sent a message"
                            r"|this came from another claude session|\[?(?:peer|agent) message\b)", re.I)
MERGE_LIST_RE = re.compile(r"^[\s>*_`-]*merge list\b[^\n]*", re.I | re.M)
# The hand-back's mandated ask lines (rules/communication.md § Answer first): line 1 `Action needed…`, and the numbered
# steps under the closing `Your call` / `Questions` block.
ACTION_LINE_RE = re.compile(r"^[\s>*_`-]*action needed\b[^\n]*", re.I | re.M)
END_BLOCK_RE = re.compile(r"^[\s>*_`#-]*(?:your call|questions)\b[^\n]*$", re.I | re.M)
ASK_STEP_RE = re.compile(r"^[ \t>*_`-]*\d+[.)][ \t]+[^\n]*", re.M)


def handback_merge_list(text: str) -> set:
    """The PRs a hand-back asks Simon to give a merge word for: its `Merge list` line, else every #N on an
    `Action needed` line or an end-block numbered step that carries a merge verb. It only names the referent of
    his own reply ("merge both"); his typed words still have to give the order."""
    found = MERGE_LIST_RE.search(text)
    if found:
        return set(re.findall(r"#(\d+)\b", found.group(0)))
    ends = list(END_BLOCK_RE.finditer(text))
    asks = ACTION_LINE_RE.findall(text) + (ASK_STEP_RE.findall(text, ends[-1].end()) if ends else [])
    return {n for line in asks if MERGE_VERB_RE.search(line) for n in re.findall(r"#(\d+)\b", line)}


def own_text(text: str) -> str:
    """Simon's own words in a typed turn: system blocks and pasted material removed; "" for a relayed note."""
    text = PASTED_RE.sub("", SYSTEM_BLOCK_RE.sub("", text or "")).strip()
    return "" if PEER_OPENER_RE.match(text) else text


def typed_messages(path: str) -> tuple:
    """([(text, merge list it answers, hand-backs before it)], hand-backs in all) for every message Simon
    typed, oldest first:
    turn-opening prompts and prompts queued mid-turn. Tool results (an AskUserQuestion answer included),
    isMeta entries, harness prompts (a task notification, a peer delivery) and sidechains are not his."""
    msgs, merge_list, handbacks = [], set(), 0
    for line in _transcript(path):
        e = _entry(line)
        if not e:
            continue
        kind, message = e.get("type"), e.get("message") or {}
        if kind == "assistant" and message.get("stop_reason") == "end_turn":
            handbacks += 1
            merge_list = handback_merge_list(part_text(message.get("content")))
            continue
        text = None
        if kind == "attachment":
            att = e.get("attachment") or {}
            origin = att.get("origin") if isinstance(att.get("origin"), dict) else {}
            if (att.get("type") == "queued_command" and not att.get("isMeta") and att.get("commandMode") != "task-notification"
                    and origin.get("kind") not in ("task-notification", "peer")):
                text = str(att.get("prompt") or "")
        elif (kind == "user" and not e.get("isMeta") and not e.get("isSidechain") and not e.get("isCompactSummary")
              and not e.get("origin")):
            content = message.get("content")
            if isinstance(content, str):
                text = content
            elif isinstance(content, list) and not any(isinstance(x, dict) and x.get("type") == "tool_result"
                                                       for x in content):
                text = part_text(content)
        text = own_text(text) if text else ""
        if text:
            msgs.append((text, merge_list, handbacks))
    return msgs, handbacks


# ---------------------------------------------------------------- the default-branch push

def _push_default(repo: str, args: list) -> str:
    """The default branch this `git push` writes ("" for none): main/master or the remote's HEAD branch,
    pushed by name, through HEAD or a bare push, deleted, or as part of --all/--mirror."""
    texts = [a.text for a in args if not a.dyn]
    opts, pos, k = [], [], 0
    while k < len(texts):
        t = texts[k]
        if t in ("-o", "--push-option", "--repo", "--receive-pack", "--exec"):
            k += 2
            continue
        (opts if t.startswith("-") else pos).append(t)
        k += 1
    remote = pos[0] if pos else "origin"
    defaults = set(DEFAULT_BRANCHES)
    head = _git(repo, "symbolic-ref", "--quiet", "--short", f"refs/remotes/{remote}/HEAD")
    if "/" in head:
        defaults.add(head.split("/", 1)[1])
    if {"--all", "--mirror"} & set(opts):
        return "every branch"
    strip = lambda ref: re.sub(r"^refs/heads/", "", ref.lstrip("+"))
    if {"-d", "--delete"} & set(opts):
        return next((strip(r) for r in pos[1:] if strip(r) in defaults), "")
    if len(pos) <= 1 and len(texts) == len(args):
        dest = _git(repo, "rev-parse", "--abbrev-ref", "--symbolic-full-name", "@{push}")
        branch = dest.split("/", 1)[1] if "/" in dest else current_branch(repo)
        return branch if branch in defaults else ""
    for spec in pos[1:]:
        src, _, dst = spec.lstrip("+").partition(":")
        dst = strip(dst or src)
        dst = current_branch(repo) if dst == "HEAD" else dst
        if dst in defaults:
            return dst
    return ""


PUSH_WORD_RE = re.compile(r"\bpush(?:ed|es|ing)?\b", re.I)
NEGATORS = {"don't", "dont", "do", "not", "never", "no", "without", "stop", "hold", "cancel", "won't", "shouldn't",
            "cannot", "can't", "wait"}


def _negated_before(text: str, at: int) -> bool:
    """A negator among the last three words before `at`, inside the same clause (a comma, colon or a
    then/and/so/ok/ie/but join ends a clause, so "no regressions then merge" is no negation)."""
    clause = re.split(r"[.,;:!?\n()]|\b(?:then|and|so|ok|okay|ie|yes|but)\b", text[:at].casefold())[-1]
    return any(w.strip("'\"*_") in NEGATORS for w in clause.split()[-3:])


def push_denial(repo: str, args: list, payload: dict, allow_main: bool) -> str:
    target = _push_default(repo, args)
    if not target:
        return ""
    if not allow_main:
        return (f"Blocked: push to the default branch ({target}). Branch first (git switch -c <branch>) and "
                "push there. A push to the default branch needs CLAUDE_ALLOW_MAIN_COMMIT in the environment "
                "the session started with plus the user's own \"push\"; a prefix typed into the command does "
                "not count.")
    msgs, handbacks = typed_messages(str(payload.get("transcript_path") or ""))
    turn = [t for t, _, h in msgs if h == handbacks]
    if not any(PUSH_WORD_RE.search(t) and not _negated_before(t, PUSH_WORD_RE.search(t).start()) for t in turn):
        return ("Blocked: a push to the default branch runs only when the user's own words this turn say "
                "\"push\". A yes to an option you wrote is not that. Ask, and stop.")
    return ""


# ---------------------------------------------------------------- the monitoring-only path

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


PASSED_CONCLUSIONS = {"SUCCESS", "NEUTRAL", "SKIPPED"}

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
#   - no message is read: Simon, 25 Nov, "bot fixes are always auto merge".
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

GATE_LINE_RE = re.compile(r"\Agate: ([^\s]+) ([0-9a-f]+) (PASS|BLOCKED|N/A)(?: (hotfix|light|standard|deep)(?= |$))?([^\n]*)\Z")

FULL_SHA_RE = re.compile(r"[0-9a-f]{40}")

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


# `gh pr merge` options that take a value, so the value is never read as the PR selector.
GH_MERGE_OPTS_WITH_VALUE = {"-R", "--repo", "-t", "--subject", "-b", "--body", "-F", "--body-file",
                            "-A", "--author-email", "--match-head-commit"}

# The whole selector must be a PR number or a GitHub PR URL: a branch named "feature/pull/12" is no #12.
SELECTOR_RE = re.compile(r"#?(\d+)|(?:https?://)?(?:www\.)?github\.com/[^/\s]+/[^/\s]+/pull/(\d+)/?")

def selector_number(selector: str) -> str:
    m = SELECTOR_RE.fullmatch(selector)
    return (m.group(1) or m.group(2)) if m else ""


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


NON_LITERAL_RE = re.compile(r"[$`]|^(?:''|\"\")$")

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
    cancelled check declines, a rerun gone green included, except a cancel superseded_cancels proves a
    later all-green run of the same workflow replaced. Each of the overlay's requiredChecks must
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


def _instant(stamp: str):
    """A gh ISO time as a datetime, or None when unreadable. Compared as instants, never as strings
    ("12:00:00Z" sorts before "12:00:00.500Z")."""
    m = re.fullmatch(r"(\d{4}-\d\d-\d\dT\d\d:\d\d:\d\d)(?:\.(\d{1,6})\d*)?Z", stamp or "")
    if not m:
        return None
    return datetime.datetime.strptime(m.group(1), "%Y-%m-%dT%H:%M:%S").replace(
        microsecond=int((m.group(2) or "0").ljust(6, "0")))


RUN_URL_RE = re.compile(r"https://github\.com/([^/\s]+/[^/\s]+)/actions/runs/(\d+)/job/\d+")


def _run_of(c: dict):
    """(repo, run id) of a GitHub Actions CheckRun, read from its detailsUrl; None when unreadable."""
    m = RUN_URL_RE.fullmatch(str(c.get("detailsUrl") or ""))
    return (m.group(1).lower(), int(m.group(2))) if m else None


def superseded_cancels(rollup: list) -> set:
    """Rollup indices of CANCELLED CheckRuns a later workflow run replaced. A workflow with concurrency
    cancel-in-progress starts two runs on one head and cancels the first; the later run of the SAME
    workflow on the SAME head (the rollup is the head's) is the one that counts. A cancel at index i is
    superseded only when its run id reads from detailsUrl and another run of the same repo and
    workflowName exists with a higher run id (created later), whose every check is COMPLETED SUCCESS or
    SKIPPED, which ran a job of the same name to SUCCESS, and whose earliest startedAt is not before the
    cancelled run's earliest time. A FAILURE is never superseded, nor a cancel beside a success in its
    own run (two jobs can share a name), nor one whose run id or times cannot be read."""
    groups: dict = {}
    for i, c in enumerate(rollup):
        if not isinstance(c, dict) or ("state" in c and "status" not in c):
            continue
        run = _run_of(c)
        if run and c.get("workflowName"):
            groups.setdefault((run[0], c["workflowName"], run[1]), []).append((i, c))

    def start(checks, started_only):
        times = []
        for _, c in checks:
            stamp = str(c.get("startedAt") or "")
            if (not stamp or stamp.startswith("0001-")) and not started_only:
                stamp = _check_time(c)
            when = _instant(stamp) if stamp and not stamp.startswith("0001-") else None
            if when is None:
                return None
            times.append(when)
        return min(times) if times else None

    green = {k: v for k, v in groups.items() if all(
        c.get("status") == "COMPLETED" and c.get("conclusion") in ("SUCCESS", "SKIPPED") for _, c in v)}
    out = set()
    for (repo, workflow, run_id), checks in groups.items():
        cancels = [(i, c) for i, c in checks if c.get("status") == "COMPLETED" and c.get("conclusion") == "CANCELLED"]
        began = start(checks, started_only=False) if cancels else None
        if began is None:
            continue
        for i, c in cancels:
            for (r2, w2, id2), later in green.items():
                if (r2, w2) != (repo, workflow) or id2 <= run_id:
                    continue
                later_start = start(later, started_only=True)
                if later_start is None or later_start < began:
                    continue
                if any(l.get("name") == c.get("name") and l.get("conclusion") == "SUCCESS" for _, l in later):
                    out.add(i)
                    break
    return out


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
    superseded = superseded_cancels(rollup)
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
        when = _instant(stamp) if stamp else None
        if stamp and when is None:
            yield f"{c['name']} carries an unreadable time ({stamp[:30]}), so the order of its runs is unknown"
            continue
        if i in superseded:
            continue
        runs.append(((c.get("workflowName") or "", c["name"]), "", when, i, c))
    for key, run, when, i, c in runs:
        # Any failed or cancelled check declines, even beside a later success of the same name: two jobs
        # can share a display name in one run, so a success is no proof the failed job ran again. The one
        # exception is a cancel superseded_cancels proves was replaced by a later, all-green run of the
        # same workflow (dropped above). After any other rerun, the PR waits for Simon's merge word.
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


def _delegated(payload: dict) -> bool:
    """A delegated worker or an Agent-tool subagent: its transcript holds the task brief, not the user's
    own messages and answers, so it never merges a monitoring-only PR; the parent session does."""
    return (os.environ.get("AGENT_DELEGATED_WORKER") == "1" or bool(payload.get("agent_id"))
            or bool(payload.get("agent_type"))
            or "/subagents/" in str(payload.get("transcript_path") or "").replace(os.sep, "/"))


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
        return result()
    status, tier, reason = mine[-1][2], mine[-1][3] or "", mine[-1][4] or ""
    if status != "PASS" or tier not in ("standard", "deep") or not reason.rstrip().endswith(mo.BAR_PHRASE):
        if fail(f"the newest gate record at {head[:12]} is not a standard or deep PASS whose reason "
                f"ends with \"{mo.BAR_PHRASE}\""):
            return result()
    # Simon, 25 Nov: "bot fixes are always auto merge": at the bar no message of his or anyone's holds it.
    if _delegated(payload):
        fail("a delegated subagent cannot read the user's answers in the parent's transcript, so it hands "
             "this merge back to the parent session")
    return result()


# ---------------------------------------------------------------- the merge decision

MERGING_FLAGS = {"--auto", "--admin", "--merge", "-m", "--squash", "-s", "--rebase", "-r", "--delete-branch", "-d",
                 "--subject", "-t", "--body", "-b", "--body-file", "-F", "--author-email", "-A", "--match-head-commit"}
MERGE_VERB_RE = re.compile(r"\b(?:merg\w*|ship\w*|deploy\w*|land\w*|releas\w*|push\w*|enqueue\w*|go(?:es|ing)? live"
                           r"|roll(?:ing)? (?:it |them )?out)\b", re.I)
# A short message (4 words at most) opening with one of these holds every merge ("wait", "pause for now").
BARE_HOLD_RE = re.compile(r"^\W*(?:stop|hold|wait|pause|cancel|halt|freeze|not now|not yet)\b", re.I)
# A hold aimed at merging: a hold word up to 3 words before a merge verb ("don't merge", "hold off on merging",
# "wait before merging"), "hold off", or a dequeue. A verb inside a slash command ("/sk:ship-…") is not one.
HOLD_MERGE_RE = re.compile(r"\b(?:don't|dont|do not|never|stop|hold|wait|pause|cancel|halt|freeze|not yet|not now)"
                           r"(?:\s+\S+){0,3}?\s+(?:merg|ship|deploy|land|releas|enqueue)\w*|\bhold off\b"
                           r"|\b(?:un-?|de-?)queue\w*", re.I)
PR_REF_RE = re.compile(r"(?:#|\bprs?\s*#?\s*|\bpull requests?\s*#?\s*|/pulls?/)(\d+)\b", re.I)
# Words in an order that point at PRs named elsewhere: in the same message, else in the hand-back it answers.
REFERENT_RE = re.compile(r"\b(?:both|all|them|these|those|it|this|that|the prs|yes|ok(?:ay)?|go|do it)\b", re.I)
QUESTION_RE = re.compile(r"^\W*(?:(?:so|ok|okay|and|but|then)\W+)?(?:should|shall|can|could|would|is|are|was|what|why|how|which|who|does|did"
                         r"|do (?:we|you|i))\b", re.I)
# A sentence that defines or generalises merging ("a deploy/merge means merge", "merging is", "a merge should",
# "when you merge") states a rule, not an order, so its referent never stands in for a PR.
DEFINITION_RE = re.compile(r"\b(?:means|meant)\b|\bwhen(?:ever)?\s+(?:you|i|we|they)\s+(?:\S+\s+){0,2}"
                           r"(?:merg|deploy|ship|land)|\b(?:merg|deploy|ship|land)\w*(?:/\w+)?\s+(?:is|are|should|must"
                           r"|has to|have to|needs? to)\b", re.I)
# Where an imperative merge verb starts its clause: the sentence start, a comma or colon, or a joining word.
CLAUSE_START_RE = re.compile(r"(?:^|[,;:(]|\b(?:and|then|so|now|please|pls|just))\W*$", re.I)
APOSTROPHES = str.maketrans({"’": "'", "‘": "'", "ʼ": "'", "“": '"', "”": '"'})


def names_pr(text: str, number: str) -> bool:
    n = number.lstrip("0") or "0"
    return bool(re.search(rf"(?:#|\bprs?\s*#?\s*|\bpull requests?\s*#?\s*|/pulls?/|\bmerge\s+)0*{n}(?!\d)", text, re.I)
                or (len(n) >= 3 and re.search(rf"(?<![\w.#/:-]){n}(?![\w:]|\.\d)", text)))


def _gives_order(sentence: str) -> bool:
    """A merge verb used as one: not past tense, not a noun after a determiner ("the merge guard"), not
    negated, in a sentence that is not a question."""
    if sentence.rstrip().endswith("?") or QUESTION_RE.match(sentence):
        return False
    return any(_verb_orders(sentence, m) for m in MERGE_VERB_RE.finditer(sentence))


def _verb_orders(sentence: str, m) -> bool:
    """This merge-verb match is used as one: not past tense, not negated, not a noun after a determiner."""
    return (not m.group(0).lower().endswith("ed") and not _negated_before(sentence, m.start())
            and not re.search(r"(?:\b(?:the|a|an|this|that|my|our|your|its)\W+|[/:-])$", sentence[:m.start()], re.I))


def _referent_order(sentence: str) -> bool:
    """A sentence naming no PR orders by referent only as an imperative aimed at it: a merge verb within 3 words
    of a referent ("merge it", "yes merge", "go ahead and merge", "do that and merge") or starting its clause
    ("then merge if it's ok"), in a sentence that does not define or generalise merging (DEFINITION_RE)."""
    if DEFINITION_RE.search(sentence) or not REFERENT_RE.search(sentence):
        return False
    for m in MERGE_VERB_RE.finditer(sentence):
        before, after = sentence[:m.start()], sentence[m.end():]
        near = " ".join(before.split()[-3:] + after.split()[:3])
        if not _verb_orders(sentence, m):
            continue
        if REFERENT_RE.search(near) or CLAUSE_START_RE.search(before):
            return True
    return False


def orders(text: str, number: str, asked: set) -> bool:
    """One sentence of this typed message orders #N merged: by its number, or by a referent ("both", "it")
    while the message names #N, or names no PR and answers a hand-back that asked a merge word for #N. A
    referent counts only in an imperative aimed at it (_referent_order)."""
    text = text.translate(APOSTROPHES)
    covered = names_pr(text, number) or (not PR_REF_RE.search(text) and number in asked)
    return any(_gives_order(s) and (names_pr(s, number) or (covered and _referent_order(s)))
               for s in re.split(r"(?<=[.!?;])\s+|\n+", text) if s.strip())


def holds(text: str, number: str) -> bool:
    """A typed message that holds merging #N, as narrow as the order rule: a short standalone hold ("wait",
    "pause for now"), "hold #N", or a hold aimed at merging (HOLD_MERGE_RE) for #N or no PR in particular.
    A hold word about other work ("doesn't stop till it works", "stop the bot posting alerts") never holds."""
    text = text.translate(APOSTROPHES)
    n = number.lstrip("0") or "0"
    if (BARE_HOLD_RE.match(text) and len(text.split()) <= 4) or re.search(
            rf"\b(?:hold|pause|freeze|stop)\s+(?:off\s+)?(?:on\s+)?(?:pr\s*)?#?0*{n}(?!\d)", text, re.I):
        return True
    return bool(HOLD_MERGE_RE.search(text) and (names_pr(text, number) or not PR_REF_RE.search(text)))


def _unnamed_order(text: str) -> bool:
    """An imperative merge aimed at a referent ("merge it", "just do it all and merge it") in a message naming no PR."""
    text = text.translate(APOSTROPHES)
    return not PR_REF_RE.search(text) and any(
        _gives_order(s) and _referent_order(s) for s in re.split(r"(?<=[.!?;])\s+|\n+", text) if s.strip())


def _hold_scope_covers(text: str, asked: set, number: str) -> bool:
    """A hold covers #N when it names #N, or names no PR and is a short bare hold ("wait") or was given with no
    merge list in view; a hold given against a merge list that lacks #N was scoped to those PRs."""
    if PR_REF_RE.search(text):
        return names_pr(text, number) or bool(BARE_HOLD_RE.match(text) and len(text.split()) <= 4)
    return not asked or number in asked or bool(BARE_HOLD_RE.match(text) and len(text.split()) <= 4)


def words_allow(number: str, window: list) -> tuple:
    """(allowed, cause): the newest of Simon's typed messages that mentions merging #N decides. An order names
    #N (or a referent that reaches it, or an unnamed "merge it" once he has named #N in any typed message); a
    hold decides only when its scope covers #N. A later order clears an earlier hold."""
    named = any(names_pr(t, number) or number in a for t, a, _ in window)
    for text, asked, _ in reversed(window):
        if orders(text, number, asked) or (named and _unnamed_order(text)):
            return True, ""
        if holds(text, number) and _hold_scope_covers(text, asked, number):
            return False, f"the user's later message (\"{' '.join(text.split())[:80]}\") holds merging"
    return False, f"no message the user typed says merge #{number}"


def pr_view(number: str, slug: str, where) -> dict:
    try:
        p = _run(["gh", "pr", "view", number, "--json", "number,title,headRefName,headRefOid,state,url",
                  *(["--repo", slug] if slug else [])], cwd=where or None, capture_output=True, text=True,
                 timeout=min(6, time_left()))
        pr = json.loads(p.stdout) if p.returncode == 0 else {}
    except OutOfTime:
        raise
    except Exception:
        pr = {}
    got = re.search(r"/pull/(\d+)/?$", str(pr.get("url", ""))) if isinstance(pr, dict) else None
    return pr if got and got.group(1) == number else {}


def pinned_head(words: list) -> str:
    found = [words[i + 1] for i, w in enumerate(words[:-1]) if w == "--match-head-commit"]
    found += [w.split("=", 1)[1] for w in words if w.startswith("--match-head-commit=")]
    return found[0].lower() if len(found) == 1 else ""


def merge_denial(payload: dict, margs: list, where, scan: Scan) -> str:
    texts = [w.text for w in margs]
    flags = {t.split("=", 1)[0] for t in texts}
    if "--disable-auto" in flags and not flags & MERGING_FLAGS:
        return ""  # turns auto-merge off and takes the PR out of the queue: the opposite of a merge
    words = ["gh", "pr", "merge"] + texts
    selector, number, repo = merge_target(words)
    if any(w.dyn for w in margs):
        return ("Blocked `gh pr merge`: the command carries a shell variable or substitution, so the PR it merges "
                "cannot be matched to the user's words. Run one `gh pr merge <bare number>` per PR; the user's "
                "words are not the problem, so do not ask him to resend them.")
    if not number:
        return (f"Blocked `gh pr merge`: `{selector}` is not a PR number." if selector else
                "Blocked `gh pr merge`: the command names no PR.") + " Run `gh pr merge <number>`."
    if scan.repo_env:
        return (f"Blocked `gh pr merge {number}`: the command sets GH_REPO or GH_HOST, which can point the merge at "
                "another repository. Name it with -R github.com/<owner>/<name> instead.")
    facts = {}
    try:
        ok, mcause, declared = monitoring_merge(payload, str((payload.get("tool_input") or {}).get("command", "")).strip(),
                                                words, facts=facts)
    except OutOfTime:
        ok, mcause, declared = False, "the monitoring-only checks ran out of time", True
    except Exception as exc:
        ok, mcause, declared = False, f"the monitoring-only checks hit malformed data ({type(exc).__name__})", True
    if ok:
        return ""
    mline = f"\nCause (monitoring-only merge): {mcause}." if declared and mcause else ""
    if _delegated(payload):
        return (f"Blocked `gh pr merge {number}`: a delegated worker reads a task brief, not the user's messages, "
                f"so it never merges. Hand #{number} back to the parent session.{mline}")
    hosted = re.search(r"github\.com/([^/\s]+/[^/\s]+?)(?:/pull/\d+|\.git)?/?$", selector if "/pull/" in selector else repo)
    slug = hosted.group(1) if hosted else (repo if re.fullmatch(r"[\w.-]+/[\w.-]+", repo or "") else "")
    if where is None and not slug:
        return (f"Blocked `gh pr merge {number}`: the directory it runs in is unknown (a cd the guard cannot "
                "follow). Name the repository with -R github.com/<owner>/<name>.")
    try:
        mo = _monitoring_module()
        slug = slug or mo.origin_slug(where)
        spec, error = mo.spec_for(slug) if slug else (None, "")
        if spec or error:  # a repository with a bot class: the merge pins the head that was read
            pr = pr_view(number, slug, where)
            head = str(pr.get("headRefOid") or "").lower()
            if error:
                return f"Blocked `gh pr merge {number}`: {error}, so the merge declines.{mline}"
            if not FULL_SHA_RE.fullmatch(head) or pinned_head(words) != head:
                return (f"Blocked `gh pr merge {number}`: merges in this repository pin the PR's head; add "
                        f"--match-head-commit {head or '<full head sha>'} and rerun.{mline}")
        msgs, _ = typed_messages(str(payload.get("transcript_path") or ""))
        # Every typed message counts, however old: a merge word stands until a later message holds it.
        allowed, cause = words_allow(number, msgs)
    except OutOfTime:
        allowed, cause = False, "the merge check ran out of time"
    except Exception as exc:
        allowed, cause = False, f"the merge check failed ({type(exc).__name__})"
    if allowed:
        return ""
    return f"Blocked `gh pr merge {number}`: {cause}. Say 'merge #{number}' to merge it.{mline}"


# ---------------------------------------------------------------- the hook

RISKY = False  # set once the payload is read: the crash and stall handlers deny only a possible merge or push


def deny(reason: str) -> int:
    print(json.dumps({"hookSpecificOutput": {"hookEventName": "PreToolUse", "permissionDecision": "deny",
                                             "permissionDecisionReason": reason}}))
    return 0


CONFIG_PUSH_DENY = ("Blocked: push to the config repo's main: {}. A validated config repair lands with no question to "
                    "the user: run `/usr/bin/python3 ~/.claude/bin/config-land-check.py --root {} --diff`, read the "
                    "whole diff, then rerun with `--reviewed <diff-sha256>`.")


def main() -> int:
    try:
        payload = json.load(sys.stdin)
    except Exception:
        return 0
    if not isinstance(payload, dict) or payload.get("tool_name") != "Bash":
        return 0
    command = (payload.get("tool_input") or {}).get("command")
    if not isinstance(command, str) or not QUICK_RE.search(plain(command)):
        return 0
    global RISKY
    RISKY = bool(OPAQUE_HIT_RE.search(plain(command)) or re.search(r"merge|push", plain(command), re.I))
    cwd = payload.get("cwd") or os.getcwd()
    scan = Scan(command, cwd)
    try:
        cmds = lex(command)
    except Unparsable:
        if OPAQUE_HIT_RE.search(plain(command)):
            return deny("Blocked: the command could not be parsed and names a merge or a default-branch push. "
                        "Rerun it as a plain command.")
        return 0
    for c in cmds:
        scan.judge(c.words, c)
    allow_main = os.environ.get("CLAUDE_ALLOW_MAIN_COMMIT") == "1"
    for action in scan.actions:
        if action[0] == "deny":
            return deny(f"Blocked: {action[1]}.")
        if action[0] == "push":
            _, args, where = action
            if where and is_config_repo(where):
                problem = ("the push carries a shell variable" if any(a.dyn for a in args)
                           else config_push_problem(where, [a.text for a in args]))
                if problem and not allow_main:
                    return deny(CONFIG_PUSH_DENY.format(problem, where))
                continue
            why = push_denial(where or cwd, args, payload, allow_main)
            if why:
                return deny(why)
        if action[0] == "merge":
            why = merge_denial(payload, action[1], action[2], scan)
            if why:
                return deny(why)
    return 0


# Under the 30 s hook timeout set in settings.json; the environment can only shorten it (the tests do).
def _watchdog_limit() -> float:
    try:
        value = float(os.environ.get("GIT_COMMIT_GUARD_WATCHDOG_S") or 26.0)
    except ValueError:
        return 26.0
    return min(26.0, value) if value == value and value > 0 else 26.0


WATCHDOG_S = _watchdog_limit()
STALL_DENY = json.dumps({"hookSpecificOutput": {
    "hookEventName": "PreToolUse", "permissionDecision": "deny",
    "permissionDecisionReason": "Blocked: the merge/push guard did not decide within its time limit, so it declines. "
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
    except Exception as exc:  # a crash exits non-zero, which the harness reads as allow
        code = deny(f"Blocked: the merge/push guard crashed ({type(exc).__name__}), so it declines. Rerun once; "
                    "if it repeats, ask the user.") if RISKY else 0
    out = sys.stdout.getvalue().encode()
    while out:
        out = out[os.write(w, out):]
    os._exit(code or 0)


def _supervise() -> int:
    """Runs the decision in a worker; one that has not finished by WATCHDOG_S, or dies without a word, is
    killed and a possible merge or push declines (a timed-out hook would let the command run)."""
    import select
    data = sys.stdin.read()
    risky = bool(re.search(r"gh|curl|git|merge|push", plain(data)))
    r, w = os.pipe()
    try:
        pid = os.fork()
    except OSError:
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
    if timed_out or os.WIFSIGNALED(status):
        if risky:
            print(STALL_DENY)
        return 0
    sys.stdout.write(b"".join(chunks).decode(errors="replace"))
    sys.stdout.flush()
    return os.WEXITSTATUS(status) if os.WIFEXITED(status) else 0


def explain(argv: list) -> int:
    """Read-only dry-run for one PR: every failing monitoring-only check, then the user's-words verdict over
    --transcript. Exit 0 when either path would merge it, 1 when neither would, 2 on bad input."""
    import argparse
    ap = argparse.ArgumentParser(prog="git-commit-guard.py --explain")
    ap.add_argument("--explain", action="store_true")
    ap.add_argument("--repo", required=True, help="owner/name")
    ap.add_argument("--pr", required=True)
    ap.add_argument("--transcript", default="")
    ap.add_argument("--session", default="", help="session id (default: the transcript's file name)")
    ap.add_argument("--cwd", default=os.getcwd())
    ap.add_argument("--head", default="", help="full head sha to pin (default: the PR's head now)")
    a = ap.parse_args(argv)
    number, repo = a.pr.lstrip("#"), re.sub(r"^(?:https?://)?github\.com/", "", a.repo).strip("/")
    if not re.fullmatch(r"\d+", number) or not re.fullmatch(r"[\w.-]+/[\w.-]+", repo):
        print("explain: --pr must be a number and --repo owner/name", file=sys.stderr)
        return 2
    global MONITORING_BUDGET_S, HOOK_STARTED
    MONITORING_BUDGET_S, HOOK_STARTED = 600.0, time.monotonic()
    head = (a.head or str(monitoring_pr(number, repo).get("headRefOid") or "")).lower()
    command = f"gh pr merge {number} -R github.com/{repo} --match-head-commit {head or '0' * 40} --squash"
    session = a.session or os.path.splitext(os.path.basename(a.transcript))[0]
    payload = {"tool_name": "Bash", "tool_input": {"command": command}, "session_id": session,
               "transcript_path": a.transcript, "cwd": a.cwd}
    collect = []
    try:
        ok, cause, declared = monitoring_merge(payload, command, command.split(), collect=collect)
    except Exception as exc:
        ok, declared, collect = False, True, collect + [f"raised {type(exc).__name__}: {exc}"]
    if not declared:
        collect.append("the repository declares no monitoring-only paths")
    print(f"monitoring-only dry-run (read-only): {repo}#{number} at {head[:12] or '(unreadable head)'}")
    print(f"verdict: {'MERGES AT THE BAR' if ok else 'DECLINES'}; failing checks: {len(collect)}")
    for cause in collect:
        print(f"- {cause}")
    words, why = words_allow(number, typed_messages(a.transcript)[0]) if a.transcript else (False, "")
    if a.transcript:
        print(f"user's words: {'ALLOW' if words else 'DECLINE: ' + why}")
    return 0 if ok or words else 1


if __name__ == "__main__":
    if "--explain" in sys.argv[1:]:
        sys.exit(explain(sys.argv[1:]))
    sys.exit(_supervise())
