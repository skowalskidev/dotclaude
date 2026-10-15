#!/usr/bin/env python3
"""
Deny a Bash command whose NORMAL output is a credential value, when that output would land in the
transcript.

rules/security.md: "Never surface a secret VALUE into chat, context ... USING a secret is fine."
Prose alone did not hold: a review agent ran `stripe config --list`, which prints every profile's
live and test secret keys, and a key landed in the transcript. This guard enforces the rule where
the command word and subcommand decide the outcome. It does NOT block reading secret files
(rules/security.md: no file-read blockers); it blocks commands whose job is to echo a value.

WHAT IT DENIES (each entry verified against the tool's own help or docs; see the contract entry):
  stripe config --list | stripe listen --print-secret
  gh auth token | gh auth status --show-token/-t
  gcloud auth print-access-token / print-identity-token / application-default print-access-token
  aws configure export-credentials | aws configure get aws_secret_access_key / aws_session_token
  firebase login:ci
  security find-generic-password / find-internet-password with -w or -g | security dump-keychain -d
  op read | op item get --reveal
  bare env / printenv (the whole environment) | printenv <SECRET-LOOKING NAME>
  env piped to cat/sort/head... or to grep/awk/sed with a secret-looking pattern

WHAT IT ALLOWS (USING a value is fine; only an unconsumed print is denied):
  - the value redirected to a file or /dev/null, piped to a consumer (`| docker login ...`,
    `| pbcopy`, `| wc -c`), or captured by `$(...)` into an assignment or another command's argument;
  - help, status and list verbs (`stripe config --help`, `gh auth status`, `npm token list`, which
    prints abbreviated tokens only), and `env VAR=1 cmd`;
  - text that merely NAMES a command: a quoted string, a heredoc body, a grep pattern.

It parses the command (quotes, `$(...)`, backticks, pipelines, `sh -c`, `eval`, command prefixes)
instead of matching raw text, so awkward spacing, an absolute path, `&&` chains and `sh -c '...'`
are judged by what the shell would RUN. Fails OPEN on anything malformed or unparsed: a guard that
breaks the session gets switched off. No override variable: if the user wants a value printed they run
the command in their own terminal.
"""

import json
import os
import re
import sys

ASSIGN_RE = re.compile(r"^[A-Za-z_][A-Za-z0-9_]*=")
REDIR_RE = re.compile(r"^(?P<fd>\d*|&)(?P<op>>>|>\||>&|>|<<<|<&|<)(?P<t>.*)$")
SECRETISH = re.compile(r"(?i)(key|token|secret|passw|credential|auth)")
DYN = "\x00"  # placeholder for a command substitution inside a word

SHELLS = {"sh", "bash", "zsh", "dash", "ksh"}
# Wrappers that run the next command; their own flags and numeric args are skipped.
WRAPPERS = {"sudo", "command", "builtin", "exec", "nohup", "time", "nice", "timeout", "xargs",
            "stdbuf", "if", "then", "else", "elif", "do", "while", "until", "!", "{"}
# Commands that print their stdin (or their arguments): a value piped into one is still printed.
PRINTERS = {"cat", "tee", "head", "tail", "less", "more", "cut", "tr", "sed", "awk", "gawk", "base64",
            "xxd", "od", "hexdump", "rev", "sort", "uniq", "fold", "fmt", "nl", "paste", "jq", "yq",
            "grep", "egrep", "fgrep", "rg", "echo", "printf", "column", "tac", "strings", "bat"}
# Commands that print their arguments: a value substituted into one is printed.
ECHOERS = {"echo", "printf", "print"}
FILTERS = {"grep", "egrep", "fgrep", "rg", "awk", "gawk", "sed", "cut"}


class Cmd:
    def __init__(self):
        self.words = []    # list of (text, quoted)
        self.redirs = []   # list of (fd, op, target)
        self.op = ""       # operator after this command: | |& && || ; & \n
        self.substs = []   # parsed command substitutions: list of list[Cmd]
        self.shell_scripts = []  # parsed sh -c / eval bodies (filled by the analyser)

    def texts(self):
        return [w for w, _ in self.words]


def _match_paren(text, i):
    """Index of the ')' closing a '(' whose body starts at i. Quote-aware; len(text) if unclosed."""
    depth, q, n = 1, None, len(text)
    while i < n:
        c = text[i]
        if q:
            if c == "\\" and q == '"':
                i += 2
                continue
            if c == q:
                q = None
        elif c == "\\":
            i += 2
            continue
        elif c in "'\"":
            q = c
        elif c == "(":
            depth += 1
        elif c == ")":
            depth -= 1
            if depth == 0:
                return i
        i += 1
    return n


def _match_backtick(text, i):
    n = len(text)
    while i < n:
        if text[i] == "\\":
            i += 2
            continue
        if text[i] == "`":
            return i
        i += 1
    return n


def parse(text):
    """Split a shell command into simple commands. Not a full shell grammar: enough to judge the
    command word, its arguments, pipelines, redirects, substitutions and nested `sh -c` scripts."""
    cmds, cur = [], Cmd()
    buf, inword, quoted = [], False, False
    heredocs = []
    i, n = 0, len(text)

    def end_word():
        nonlocal buf, inword, quoted
        if inword:
            cur.words.append(("".join(buf), quoted))
        buf, inword, quoted = [], False, False

    def end_cmd(op):
        nonlocal cur
        end_word()
        if cur.words or cur.substs:
            cur.op = op
            cmds.append(cur)
        elif cmds and op in ("|", "|&", "&&", "||"):
            cmds[-1].op = op
        cur = Cmd()

    def sub(inner):
        cur.substs.append(parse(inner))

    while i < n:
        c = text[i]
        nxt = text[i + 1] if i + 1 < n else ""
        if c in " \t":
            end_word()
        elif c == "\n":
            end_cmd("\n")
            for delim in heredocs:
                m = re.compile(rf"^[ \t]*{re.escape(delim)}[ \t]*$", re.M).search(text, i + 1)
                i = m.end() if m else n
            heredocs = []
        elif c == "\\":
            if nxt == "\n":
                i += 1
            elif nxt:
                buf.append(nxt)
                inword = quoted = True
                i += 1
        elif c == "'":
            j = text.find("'", i + 1)
            j = n if j == -1 else j
            buf.append(text[i + 1:j])
            inword = quoted = True
            i = j
        elif c == '"':
            inword = quoted = True
            i += 1
            while i < n and text[i] != '"':
                d = text[i]
                if d == "\\" and i + 1 < n:
                    buf.append(text[i + 1])
                    i += 2
                    continue
                if d == "$" and text[i + 1:i + 2] == "(":
                    j = _match_paren(text, i + 2)
                    sub(text[i + 2:j])
                    buf.append(DYN)
                    i = j + 1
                    continue
                if d == "`":
                    j = _match_backtick(text, i + 1)
                    sub(text[i + 1:j])
                    buf.append(DYN)
                    i = j + 1
                    continue
                buf.append(d)
                i += 1
        elif c == "$" and nxt == "(":
            j = _match_paren(text, i + 2)
            sub(text[i + 2:j])
            buf.append(DYN)
            inword = True
            i = j
        elif c == "`":
            j = _match_backtick(text, i + 1)
            sub(text[i + 1:j])
            buf.append(DYN)
            inword = True
            i = j
        elif c == "(" and buf and "".join(buf) in ("<", ">") and not quoted:
            j = _match_paren(text, i + 1)  # process substitution <(...) / >(...)
            buf, inword = [], False
            sub(text[i + 1:j])
            buf.append(DYN)
            inword = True
            i = j
        elif c == "#" and not inword:
            j = text.find("\n", i)
            i = (n if j == -1 else j) - 1
        elif c == "<" and nxt == "<" and text[i + 2:i + 3] != "<":
            m = re.compile(r"<<-?[ \t]*(['\"]?)([A-Za-z0-9_]+)\1").match(text, i)
            if m:
                heredocs.append(m.group(2))
                i = m.end() - 1
            else:
                buf.append(c)
                inword = True
        elif c == ";":
            end_cmd(";")
        elif c == "|":
            if nxt == "|":
                end_cmd("||")
                i += 1
            elif nxt == "&":
                end_cmd("|&")
                i += 1
            else:
                end_cmd("|")
        elif c == "&":
            if buf and buf[-1] in "<>":  # part of a redirect: >&2, 2>&1
                buf.append(c)
            elif nxt == ">":  # &>file
                buf.append(c)
                inword = True
            elif nxt == "&":
                end_cmd("&&")
                i += 1
            else:
                end_cmd("&")
        elif c in "()":
            end_cmd(";")
        else:
            buf.append(c)
            inword = True
        i += 1
    end_cmd("")
    for cmd in cmds:
        _split_redirects(cmd)
    return cmds


def _split_redirects(cmd):
    words, out, i = cmd.words, [], 0
    while i < len(words):
        text, quoted = words[i]
        m = None if quoted else REDIR_RE.match(text)
        if not m:
            out.append((text, quoted))
            i += 1
            continue
        target = m.group("t")
        if not target and i + 1 < len(words):
            target = words[i + 1][0]
            i += 1
        cmd.redirs.append((m.group("fd"), m.group("op"), target))
        i += 1
    cmd.words = out


def effective(words):
    """Strip env assignments and wrapper commands. Returns (words, env_bare).
    env_bare is True for a plain `env` that is left with nothing to run (it prints the environment)."""
    i, env_bare = 0, False
    while i < len(words):
        w = words[i]
        base = os.path.basename(w)
        if ASSIGN_RE.match(w):
            i += 1
        elif base == "env":
            i += 1
            start = i
            while i < len(words) and (words[i].startswith("-") or ASSIGN_RE.match(words[i])):
                i += 2 if words[i] in ("-u", "--unset") else 1
            env_bare = i >= len(words) and i == start
        elif base in WRAPPERS:
            i += 1
            while i < len(words) and (words[i].startswith("-") or words[i].isdigit()
                                      or ASSIGN_RE.match(words[i])):
                i += 1
        else:
            break
    return words[i:], env_bare and i >= len(words)


def _positional(args):
    return [a for a in args if not a.startswith("-")]


def _flags(args):
    return [a for a in args if a.startswith("-")]


def _cluster_has(args, letters):
    """True when a single-dash flag cluster (-wa, -g) carries any of the letters."""
    return any(re.fullmatch(r"-[A-Za-z]+", a) and any(ch in a[1:] for ch in letters) for a in args)


def classify(words, env_bare):
    """Return (what, instead, stream, narrowing) when the command prints a credential, else None.
    stream is 'stdout' or 'stderr' (security -g); narrowing marks env dumps, where a grep/cut that
    narrows the output to non-secret names counts as consumed."""
    if not words:
        if env_bare:
            return ("env", "printenv NAME >/dev/null && echo set (existence) or env | cut -d= -f1 (names)",
                    "stdout", True)
        return None
    cmd, args = os.path.basename(words[0]), words[1:]
    pos = _positional(args)
    if cmd == "stripe":
        if "config" in pos and "--list" in args:
            return ("stripe config --list",
                    "grep -E '^\\[|display_name|account_id' ~/.config/stripe/config.toml", "stdout", False)
        if "listen" in pos and "--print-secret" in args:
            return ("stripe listen --print-secret",
                    "pass the secret to the process that needs it: STRIPE_WEBHOOK_SECRET=$(stripe listen "
                    "--print-secret) your-command", "stdout", False)
    elif cmd == "gh":
        if pos[:2] == ["auth", "token"]:
            return ("gh auth token", "GH_TOKEN=$(gh auth token) your-command, or just run gh, which "
                    "authenticates itself", "stdout", False)
        if pos[:2] == ["auth", "status"] and ("--show-token" in args or _cluster_has(args, "t")):
            return ("gh auth status --show-token", "gh auth status (no token flag)", "stdout", False)
    elif cmd == "gcloud":
        if "auth" in pos:
            tail = pos[pos.index("auth") + 1:]
            if tail and tail[-1] in ("print-access-token", "print-identity-token"):
                return ("gcloud auth " + tail[-1], "TOKEN=$(gcloud auth " + tail[-1] +
                        ") your-command, or let gcloud authenticate itself", "stdout", False)
    elif cmd == "aws":
        if "configure" in pos:
            tail = pos[pos.index("configure") + 1:]
            if tail[:1] == ["export-credentials"]:
                return ("aws configure export-credentials",
                        "eval \"$(aws configure export-credentials --format env)\" (consumed, never "
                        "printed), or pass --profile to the aws command", "stdout", False)
            if tail[:1] == ["get"] and len(tail) > 1 and tail[1] in ("aws_secret_access_key",
                                                                       "aws_session_token"):
                return ("aws configure get " + tail[1],
                        "pass --profile to the aws command that needs it", "stdout", False)
    elif cmd == "firebase":
        if "login:ci" in pos:
            return ("firebase login:ci", "ask the user to run it in their own terminal, or use a service "
                    "account key via GOOGLE_APPLICATION_CREDENTIALS", "stdout", False)
    elif cmd == "security":
        if pos[:1] in (["find-generic-password"], ["find-internet-password"]):
            flags = _flags(args)
            if any(f.startswith("-") and not f.startswith("--") and "w" in f[1:] for f in flags):
                return ("security " + pos[0] + " -w",
                        "pass it to the consumer: security " + pos[0] + " -w ... | your-command",
                        "stdout", False)
            if any(f.startswith("-") and not f.startswith("--") and "g" in f[1:] for f in flags):
                return ("security " + pos[0] + " -g", "omit -g; without -w or -g only attributes print",
                        "stderr", False)
        if pos[:1] == ["dump-keychain"] and _cluster_has(args, "d"):
            return ("security dump-keychain -d", "security dump-keychain (no -d) lists items without secrets",
                    "stdout", False)
    elif cmd == "op":
        if pos[:1] == ["read"]:
            return ("op read", "op run -- your-command, or op read ... | your-command, or "
                    "op read --out-file <path>", "stdout", False)
        if pos[:2] == ["item", "get"] and "--reveal" in args:
            return ("op item get --reveal", "op item get without --reveal, or op run -- your-command",
                    "stdout", False)
    elif cmd == "printenv":
        if not pos:
            return ("printenv", "printenv NAME >/dev/null && echo set (existence), or env | cut -d= -f1 (names)",
                    "stdout", True)
        if any(SECRETISH.search(p) for p in pos):
            return ("printenv " + " ".join(pos), "printenv NAME >/dev/null && echo set (existence)",
                    "stdout", False)
    return None


def _redirect_hides(cmd, stream):
    """True when the command's own redirects keep the stream out of the transcript."""
    visible = ("/dev/stdout", "/dev/stderr", "/dev/tty")
    merged = any(fd == "2" and op == ">&" and t == "1" for fd, op, t in cmd.redirs)
    if stream == "stderr" and not merged:
        return any(fd == "2" and op in (">", ">>", ">|") and t not in visible for fd, op, t in cmd.redirs)
    for fd, op, t in cmd.redirs:
        if fd in ("", "1", "&") and op in (">", ">>", ">|") and t not in visible:
            return True
        if fd in ("", "1") and op == ">&" and not t.isdigit() and t not in visible:
            return True
    return False


def _pipe_continues(nxt_cmd, narrowing):
    """Does the next stage of a pipeline pass the value through to the transcript?"""
    words, _ = effective(nxt_cmd.texts())
    if not words:
        return False
    base, args = os.path.basename(words[0]), words[1:]
    if base in ("grep", "egrep", "fgrep", "rg") and (_cluster_has(args, "qcl") or "--quiet" in args
                                                       or "--count" in args):
        return False
    if narrowing and base in FILTERS:
        if base == "cut":
            return "-f1" not in args and not ("-f" in args and "1" in args)
        return any(SECRETISH.search(a) for a in args)
    return base in PRINTERS


def echoed(cmds, idx, stream, narrowing, parent_echoed):
    """Does the output of cmds[idx] reach the transcript?"""
    if not parent_echoed:
        return False
    first = cmds[idx]
    merged = any(fd == "2" and op == ">&" and t == "1" for fd, op, t in first.redirs)
    if stream == "stderr" and not merged:
        return not _redirect_hides(first, "stderr")  # a pipe carries stdout only
    j = idx
    while True:
        cmd = cmds[j]
        if _redirect_hides(cmd, stream if j == idx else "stdout"):
            return False
        if cmd.op in ("|", "|&") and j + 1 < len(cmds):
            if not _pipe_continues(cmds[j + 1], narrowing):
                return False
            j += 1
            continue
        return True


def shell_body(words):
    """The script text of `sh -c '...'` / `bash -lc '...'` / `eval ...`, else None."""
    if not words:
        return None
    base, args = os.path.basename(words[0]), words[1:]
    if base == "eval":
        return " ".join(args)
    if base in SHELLS:
        for k, a in enumerate(args):
            if re.fullmatch(r"-[A-Za-z]*c[A-Za-z]*", a):
                rest = [x for x in args[k + 1:] if not x.startswith("-")]
                return rest[0] if rest else None
    return None


def find_violation(cmds, parent_echoed=True, depth=0):
    if depth > 6:
        return None
    for idx, cmd in enumerate(cmds):
        words, env_bare = effective(cmd.texts())
        hit = classify(words, env_bare)
        if hit and echoed(cmds, idx, hit[2], hit[3], parent_echoed):
            return hit
        cmd_echoed = echoed(cmds, idx, "stdout", False, parent_echoed)
        body = shell_body(words)
        if body:
            found = find_violation(parse(body), cmd_echoed, depth + 1)
            if found:
                return found
        subs_echoed = bool(words) and os.path.basename(words[0]) in ECHOERS and cmd_echoed
        for inner in cmd.substs:
            found = find_violation(inner, subs_echoed, depth + 1)
            if found:
                return found
    return None


def main() -> int:
    try:
        payload = json.load(sys.stdin)
        if payload.get("tool_name") != "Bash":
            return 0
        command = payload.get("tool_input", {}).get("command", "")
        if not isinstance(command, str) or not command.strip():
            return 0
        hit = find_violation(parse(command))
    except Exception:
        return 0  # fail open
    if not hit:
        return 0
    what, instead, _stream, _narrowing = hit
    print(json.dumps({
        "hookSpecificOutput": {
            "hookEventName": "PreToolUse",
            "permissionDecision": "deny",
            "permissionDecisionReason": (
                f"Blocked: `{what}` prints a credential value into the transcript. rules/security.md: "
                "never surface a secret VALUE into chat or context.\n"
                f"Run instead: {instead}\n"
                "Using a credential stays allowed (redirect it to a file, pipe it to the consumer, or "
                "capture it with $(...) into the command that needs it). If the user wants the value "
                "shown, ask them to run the command in their own terminal."
            ),
        }
    }))
    return 0


if __name__ == "__main__":
    sys.exit(main())
