#!/usr/bin/env python3
"""
Deny a PATTERN kill that can signal other sessions' processes; allow a kill scoped to your own.

rules/process.md and references/dev-server-hygiene.md § Private process inspection: signal only
proven owned processes. Prose alone did not hold: a delegated worker ran
`pkill -f "local-capacity.py run"` to drop its own queued job, the pattern matched every live
session's lease wrappers, and another owner's heavy slot showed free afterwards. This guard is the
mechanical backstop for that class: a kill selected by NAME or a shared command line, rather than
by a pid or a path only the caller owns.

WHAT IT DENIES (any flags; also inside sh/bash -c, eval, sudo, $(...), and after &&, ;, |):
  - pkill with a path-free pattern (`pkill node`, `pkill -f vitest`, `pkill -f "local-capacity.py run"`);
  - pkill without -f (it matches the process NAME, which every session shares);
  - pkill -f naming a shared ~/.claude/bin tool or a system install path, even with a `/`
    (`pkill -f ~/.claude/bin/local-capacity.py` is the same incident with a path);
  - pkill with only user/group/tty selectors (`pkill -u me` signals everything you own);
  - killall with any target (it matches by name); `killall -l` passes;
  - pgrep with an unscoped pattern feeding kill (`pgrep -f x | xargs kill`, `kill $(pgrep -f x)`);
  - kill -1 / kill -- -1 (signals every process you own).

WHAT IT ALLOWS:
  - `kill <pid>` and `kill -- -<pgid>`: the owned-pid route this guard points to;
  - pkill -f scoped to the caller's own path: a non-shared shell variable (`pkill -f "$TMP"`) or a
    literal path with at least two directory segments outside system and ~/.claude/bin roots;
  - pkill selected by pid: -F pidfile, -P ppid, -g pgrp, -s sid;
  - text that merely NAMES a command (a quoted string, heredoc body or grep pattern).

Parsing is shared with hooks/secret-echo-guard.py (parse / effective / shell_body), one shell
grammar for both guards. Override: CLAUDE_ALLOW_PATTERN_KILL=1 in the environment or as an inline
prefix on that command, only for a case the user named. Fails OPEN on anything malformed: a guard
that breaks the session gets switched off.
"""

import importlib.util
import json
import os
import re
import sys
from pathlib import Path

HERE = Path(__file__).resolve().parent
OVERRIDE = "CLAUDE_ALLOW_PATTERN_KILL"

# pkill/pgrep options that take a value (BSD and procps). Pid-scoped ones select by pid, not pattern.
VALUE_OPTS = set("FGgJMNPstUu")
PID_OPTS = set("FPgs")
LONG_VALUE = {"--signal", "--pidfile", "--parent", "--pgroup", "--session", "--terminal", "--euid",
              "--uid", "--group", "--ns", "--nslist", "--runstates", "--cgroup"}
LONG_PID = {"--pidfile", "--parent", "--pgroup", "--session"}
SUDO_VALUE = {"-u", "-g", "-U", "-C", "-h", "-p", "-r", "-t", "-T", "-D"}

VAR_RE = re.compile(r"\$\{?([A-Za-z_][A-Za-z0-9_]*)\}?")
# Variables every session shares: a pattern scoped to one of them alone is not owned.
SHARED_VARS = {"HOME", "USER", "LOGNAME", "TMPDIR", "PATH", "SHELL"}
SYSTEM_PREFIX = re.compile(r"^/(usr|bin|sbin|opt|System|Applications|Library|private/var|var)(/|$)")
LITERAL_SEG = re.compile(r"[\w.@+-]+")


def _load_parser():
    spec = importlib.util.spec_from_file_location("secret_echo_guard", HERE / "secret-echo-guard.py")
    mod = importlib.util.module_from_spec(spec)  # type: ignore[arg-type]
    spec.loader.exec_module(mod)  # type: ignore[union-attr]
    return mod


def _shared_tool_re():
    """Names of the shared ~/.claude/bin tools, derived from the directory (never a copied list)."""
    names = set()
    try:
        for p in (HERE.parent / "bin").iterdir():
            if p.is_file():
                names.add(re.escape(p.name))
                if len(p.stem) >= 6:
                    names.add(re.escape(p.stem) + r"(?=$|[\s'\"])")
    except OSError:
        pass
    alts = [r"\.claude/(bin|hooks)(/|$)", r"\.claude/?$"] + sorted(names)
    return re.compile(r"(^|[/\s])(" + "|".join(alts) + ")")


SHARED_TOOL = _shared_tool_re()


def path_scoped(pattern):
    """True when a pkill -f pattern can only match processes under the caller's own path."""
    if SHARED_TOOL.search(pattern):
        return False
    if any(m.group(1) not in SHARED_VARS for m in VAR_RE.finditer(pattern)):
        return True  # the caller's own temp dir or worktree held in a variable (e.g. "$TMP")
    for tok in pattern.split():
        tok = VAR_RE.sub("~", tok)
        if "/" not in tok or SYSTEM_PREFIX.match(tok):
            continue
        segs = [s for s in tok.split("/") if s not in ("", "~", ".")]
        if sum(1 for s in segs if LITERAL_SEG.fullmatch(s)) >= 2:
            return True
    return False


def parse_select(args):
    """Split pkill/pgrep args into (full_match, pid_scoped, has_selector, patterns)."""
    full = pid_scoped = selector = False
    patterns, i = [], 0
    while i < len(args):
        a = args[i]
        if a == "--":
            patterns += args[i + 1:]
            break
        if a.startswith("--"):
            name = a.split("=", 1)[0]
            full = full or name == "--full"
            pid_scoped = pid_scoped or name in LONG_PID
            selector = selector or name in LONG_VALUE
            if name in LONG_VALUE and "=" not in a:
                i += 1
        elif a.startswith("-") and len(a) > 1:
            body = a[1:]
            if body.isdigit() or (len(body) >= 2 and body.isupper()):
                i += 1  # a signal: -9, -TERM, -SIGKILL
                continue
            for k, ch in enumerate(body):
                if ch in VALUE_OPTS:
                    selector = True
                    pid_scoped = pid_scoped or ch in PID_OPTS
                    if k == len(body) - 1:
                        i += 1
                    break
                full = full or ch == "f"
        else:
            patterns.append(a)
        i += 1
    return full, pid_scoped, selector, patterns


def unscoped_select(args):
    """Reason string when a pkill/pgrep selection reaches beyond the caller's own processes."""
    full, pid_scoped, selector, patterns = parse_select(args)
    if pid_scoped:
        return None
    if not patterns:
        return "it selects by user, group or terminal alone" if selector else None
    if not full:
        return "without -f it matches the process NAME, which every session shares"
    for p in patterns:
        if not path_scoped(p):
            return f"the pattern {p!r} is not scoped to a path only you own"
    return None


def kill_all_target(args):
    """True for `kill -1` style targets: every process the user owns."""
    i = 0
    if args and args[0] in ("-s", "-n"):
        i = 2
    elif args and args[0].startswith("-") and args[0] not in ("--", "-l", "-L"):
        i = 1
    targets = [a for a in args[i:] if a != "--"]
    return "-1" in targets


def _prefix_assignments(words):
    """The VAR=value words (env included) before a command's first real word."""
    out = []
    for w in words:
        if re.match(r"^[A-Za-z_][A-Za-z0-9_]*=", w):
            out.append(w)
        elif os.path.basename(w) not in ("env", "sudo"):
            break
    return out


def strip_sudo(words):
    out, i = [], 0
    while i < len(words):
        if os.path.basename(words[i]) == "sudo":
            i += 1
            while i < len(words) and words[i].startswith("-"):
                i += 2 if words[i] in SUDO_VALUE else 1
            continue
        out.append(words[i])
        i += 1
    return out


def judge(P, cmds, depth=0):
    """Return (what, why) for the first unscoped kill in the parsed commands, else None."""
    if depth > 6:
        return None
    for idx, cmd in enumerate(cmds):
        raw = cmd.texts()
        if f"{OVERRIDE}=1" in _prefix_assignments(raw):
            continue  # inline override on this command only
        words, _ = P.effective(strip_sudo(raw))
        base = os.path.basename(words[0]) if words else ""
        args = words[1:]
        if base == "pkill":
            why = unscoped_select(args)
            if why:
                return (" ".join(words), why)
        elif base == "killall":
            if [a for a in args if a not in ("-l",)]:
                return (" ".join(words), "killall matches by process NAME, which every session shares")
        elif base == "kill":
            if kill_all_target(args):
                return (" ".join(words), "a target of -1 signals every process you own")
            for inner in cmd.substs:
                hit = _pgrep_feeds(P, inner)
                if hit:
                    return hit
        elif base == "pgrep" and cmd.op in ("|", "|&") and idx + 1 < len(cmds):
            nxt, _ = P.effective(strip_sudo(cmds[idx + 1].texts()))
            if nxt and os.path.basename(nxt[0]) == "kill":
                why = unscoped_select(args)
                if why:
                    return (" ".join(words) + " | kill", why)
        body = P.shell_body(words)
        if body:
            hit = judge(P, P.parse(body), depth + 1)
            if hit:
                return hit
        for inner in cmd.substs:
            hit = judge(P, inner, depth + 1)
            if hit:
                return hit
    return None


def _pgrep_feeds(P, cmds):
    for cmd in cmds:
        words, _ = P.effective(strip_sudo(cmd.texts()))
        if words and os.path.basename(words[0]) == "pgrep":
            why = unscoped_select(words[1:])
            if why:
                return ("kill $(" + " ".join(words) + ")", why)
    return None


def main() -> int:
    try:
        payload = json.load(sys.stdin)
        if payload.get("tool_name") != "Bash":
            return 0
        command = payload.get("tool_input", {}).get("command", "")
        if not isinstance(command, str) or not command.strip():
            return 0
        if os.environ.get(OVERRIDE) == "1":
            return 0
        if not re.search(r"\b(pkill|killall|kill|pgrep)\b", command):
            return 0
        P = _load_parser()
        hit = judge(P, P.parse(command))
    except Exception:
        return 0  # fail open
    if not hit:
        return 0
    what, why = hit
    print(json.dumps({
        "hookSpecificOutput": {
            "hookEventName": "PreToolUse",
            "permissionDecision": "deny",
            "permissionDecisionReason": (
                f"Blocked: pattern kill `{what}`: {why}. It can signal other live sessions' processes "
                "(lease wrappers, dev servers, builds). rules/process.md: signal only your own processes.\n"
                "Instead: `kill <pid>` with the pid your command printed (or `$!`), stop your own "
                "background task, or use the tool's own release (e.g. `local-capacity.py release "
                "--token <token>`). See references/dev-server-hygiene.md § Private process inspection.\n"
                "A pkill -f scoped to a path only you own passes (e.g. `pkill -f \"$TMP\"`, your worktree "
                f"path). Override with {OVERRIDE}=1 only for a case the user named."
            ),
        }
    }))
    return 0


if __name__ == "__main__":
    sys.exit(main())
