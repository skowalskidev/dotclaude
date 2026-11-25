#!/usr/bin/env python3
"""
Deny a formatter or auto-fixer run aimed at a whole directory, `.`, a glob, or no path at all.

references/code-best-practices.md § Scope discipline: run a formatter or auto-fixer only on the files
the change itself modified, never on a whole directory. Prose alone did not hold: four whole-folder
runs (`dart format lib/features/... test/features/...` the latest) reflowed files the task never
touched, they rode into feature commits, and each needed a restore commit. This guard is the
mechanical backstop for that class.

WHAT IT JUDGES (in write mode only; also inside sh/bash -c, eval, $(...), after &&, ;, |, and behind
npx/pnpm/yarn/bunx/uv run/poetry run/python -m/fvm runners):
  dart format | flutter format | dart fix --apply | prettier --write/-w | black | ruff format |
  ruff check --fix/--fix-only | gofmt -w | swiftformat | ktlint -F/--format | eslint --fix

WHAT IT DENIES:
  - a path argument that is a directory relative to the command's cwd (a `cd` earlier in the chain
    counts), `.`, `..`, `~`, a trailing `/`, or a name with no file extension that is not a file;
  - a glob (`*`, `?`): the tool expands it to every match, touched or not;
  - no path at all (the tool defaults to the working directory), unless stdin feeds it;
  - paths fed by a tree lister (`find`, `fd`, `ls`, `tree`, `git ls-files`, `rg --files`) through
    xargs or `$(...)`.

WHAT IT ALLOWS:
  - explicit file paths (`dart format lib/a.dart test/b_test.dart`);
  - `$(git diff --name-only ...)`, `git diff --name-only ... | xargs <tool>`, and `"$f"`/`$VAR` words;
  - check-only modes: `dart format --output=none --set-exit-if-changed`, `prettier --check`,
    `black --check`/`--diff`, `ruff format --check`, `ruff check` without --fix, `eslint` without --fix,
    `gofmt -l`, `swiftformat --lint`, `dart fix --dry-run`, and help/version flags;
  - text that merely NAMES a command (an echo, a grep pattern, a quoted string, a heredoc body).

Parsing is shared with hooks/secret-echo-guard.py (parse / effective / shell_body). No override: a
whole-tree reformat Simon asked for runs in his own terminal. Fails OPEN on anything malformed.
"""

import importlib.util
import json
import os
import re
import sys
from pathlib import Path

HERE = Path(__file__).resolve().parent
RULE = "references/code-best-practices.md § Scope discipline"

# Options that take a separate value, per tool. A value is never judged as a path.
DART_FORMAT_VALUES = {"-o", "--output", "-l", "--line-length", "--language-version", "--enable-experiment",
                      "--show", "--summary", "-i", "--indent", "--page-width", "--trailing-commas"}
DART_FIX_VALUES = {"--code", "--enable-experiment"}
PRETTIER_VALUES = {"--config", "--ignore-path", "--plugin", "--plugin-search-dir", "--parser", "--print-width",
                   "--tab-width", "--trailing-comma", "--end-of-line", "--log-level", "--loglevel",
                   "--cache-location", "--cache-strategy", "--stdin-filepath", "--arrow-parens", "--prose-wrap",
                   "--quote-props", "--html-whitespace-sensitivity", "--embedded-language-formatting",
                   "--object-wrap", "--experimental-operator-position", "--config-precedence",
                   "--cursor-offset", "--range-start", "--range-end"}
BLACK_VALUES = {"-l", "--line-length", "-t", "--target-version", "--include", "--exclude", "--extend-exclude",
                "--force-exclude", "--config", "--required-version", "--python-cell-magics", "-W", "--workers",
                "--stdin-filename", "-c", "--code", "--enable-unstable-feature", "--line-ranges"}
RUFF_VALUES = {"--config", "--line-length", "--target-version", "--select", "--ignore", "--extend-select",
               "--extend-ignore", "--exclude", "--extend-exclude", "--output-format", "--stdin-filename",
               "--cache-dir", "--range", "-o", "--output-file", "--per-file-ignores", "--extend-per-file-ignores",
               "--fixable", "--unfixable", "--extend-fixable", "--dummy-variable-rgx"}
GOFMT_VALUES = {"-r", "--r", "-cpuprofile", "--cpuprofile"}
SWIFTFORMAT_FLAGS = {"--lint", "--dryrun", "--verbose", "--quiet", "--strict", "--lenient", "--help",
                     "--version", "--options", "--inferoptions", "--ruleinfo"}
KTLINT_VALUES = {"--reporter", "--editorconfig", "--baseline", "--color-name", "--limit", "-l", "--log-level",
                 "--code-style", "-R", "--ruleset"}
ESLINT_VALUES = {"-c", "--config", "--ext", "--parser", "--parser-options", "--resolve-plugins-relative-to",
                 "--rulesdir", "--plugin", "--rule", "--ignore-path", "--ignore-pattern", "-f", "--format", "-o",
                 "--output-file", "--max-warnings", "--cache-location", "--cache-strategy", "--env", "--global",
                 "--fix-type", "--report-unused-disable-directives-severity", "--stdin-filename", "--flag",
                 "--concurrency"}

TOOL_HINT = re.compile(r"(dart|flutter|prettier|black|ruff|gofmt|swiftformat|ktlint|eslint)")
STDIN_FLAGS = ("--stdin-filepath", "--stdin-filename", "--stdinpath", "--stdin")
HELP_FLAGS = {"-h", "--help", "-help", "--version", "-V", "-v", "help"}
TREE_LISTERS = {"find", "fd", "fdfind", "ls", "tree"}
PY_RUNNERS = {"uv", "poetry", "pipx", "pdm", "hatch", "rye"}
JS_RUNNERS = {"pnpm", "yarn", "bun", "npm"}
X_RUNNERS = {"npx", "bunx", "pnpx", "uvx"}

JS_GLOB = "'*.ts' '*.tsx' '*.js' '*.jsx'"
FIX_CMDS = {"dart format": "dart format", "flutter format": "dart format", "dart fix": "dart fix --apply",
            "prettier": "prettier --write", "eslint": "eslint --fix", "black": "black",
            "ruff format": "ruff format", "ruff check": "ruff check --fix", "gofmt": "gofmt -w",
            "swiftformat": "swiftformat", "ktlint": "ktlint -F"}
GLOBS = {"dart format": "'*.dart'", "flutter format": "'*.dart'", "dart fix": "'*.dart'",
         "prettier": JS_GLOB, "eslint": JS_GLOB, "black": "'*.py'", "ruff format": "'*.py'",
         "ruff check": "'*.py'", "gofmt": "'*.go'", "swiftformat": "'*.swift'", "ktlint": "'*.kt' '*.kts'"}


def _load_parser():
    spec = importlib.util.spec_from_file_location("secret_echo_guard", HERE / "secret-echo-guard.py")
    mod = importlib.util.module_from_spec(spec)  # type: ignore[arg-type]
    spec.loader.exec_module(mod)  # type: ignore[union-attr]
    return mod


def _base(word):
    return os.path.basename(word)


def strip_runners(words):
    """Drop package-runner prefixes (npx, pnpm exec, uv run, python -m, fvm) to reach the tool."""
    for _ in range(4):
        if not words:
            return words
        b = _base(words[0])
        if b in X_RUNNERS:
            i = 1
            while i < len(words) and words[i].startswith("-"):
                i += 2 if words[i] in ("-p", "--package", "--from", "--with") else 1
            words = words[i:]
        elif b in JS_RUNNERS:
            rest = words[1:]
            if rest[:1] and rest[0] in ("exec", "dlx", "x"):
                rest = rest[1:]
            elif b == "npm":
                return words
            words = rest[1:] if rest[:1] == ["--"] else rest
        elif b in PY_RUNNERS and words[1:2] == ["run"]:
            i = 2
            while i < len(words) and words[i].startswith("-"):
                i += 2 if words[i] in ("--with", "--python", "-p", "--from", "--project") else 1
            words = words[i:]
        elif re.fullmatch(r"python[0-9.]*", b) and words[1:2] == ["-m"]:
            words = words[2:]
        elif b == "fvm":
            words = words[1:]
        else:
            return words
    return words


def _sub(words, name):
    """Index after subcommand `name` past leading global flags, else None."""
    i = 1
    while i < len(words) and words[i].startswith("-"):
        i += 1
    return i + 1 if i < len(words) and words[i] == name else None


def _has(args, *names):
    return any(a in names or any(a.startswith(n + "=") for n in names if n.startswith("--")) for a in args)


def _opt_value(args, short, long):
    for k, a in enumerate(args):
        if a in (short, long):
            return args[k + 1] if k + 1 < len(args) else ""
        if a.startswith(long + "="):
            return a.split("=", 1)[1]
        if short and a.startswith(short) and len(a) > len(short) and not a.startswith("--"):
            return a[len(short):]
    return None


def identify(words):
    """(tool label, args, value-option set or 'swift') for a formatter run in write mode, else None."""
    if not words:
        return None
    b = _base(words[0])
    if b in ("dart", "flutter"):
        k = _sub(words, "format")
        if k is not None:
            args = words[k:]
            out = _opt_value(args, "-o", "--output")
            if (out and out.split(":")[0] in ("none", "show", "json")) or _has(args, "-n", "--dry-run"):
                return None
            return (b + " format", args, DART_FORMAT_VALUES)
        k = _sub(words, "fix") if b == "dart" else None
        if k is not None:
            args = words[k:]
            return ("dart fix", args, DART_FIX_VALUES) if _has(args, "--apply") else None
        return None
    args = words[1:]
    if b == "prettier":
        return ("prettier", args, PRETTIER_VALUES) if _has(args, "--write", "-w") else None
    if b == "black":
        return None if _has(args, "--check", "--diff", "-c", "--code") else ("black", args, BLACK_VALUES)
    if b == "ruff":
        k = _sub(words, "format")
        if k is not None:
            rest = words[k:]
            return None if _has(rest, "--check", "--diff") else ("ruff format", rest, RUFF_VALUES)
        k = _sub(words, "check")
        if k is not None:
            rest = words[k:]
            if _has(rest, "--fix", "--fix-only") and not _has(rest, "--diff", "--no-fix"):
                return ("ruff check", rest, RUFF_VALUES)
        return None
    if b == "gofmt":
        return ("gofmt", args, GOFMT_VALUES) if _has(args, "-w", "--w") or "-w=true" in args else None
    if b == "swiftformat":
        return None if _has(args, "--lint", "--dryrun") else ("swiftformat", args, "swift")
    if b == "ktlint":
        return ("ktlint", args, KTLINT_VALUES) if _has(args, "-F", "--format") else None
    if b == "eslint":
        return ("eslint", args, ESLINT_VALUES) if _has(args, "--fix") else None
    return None


def positionals(args, values):
    out, i, only = [], 0, False
    while i < len(args):
        a = args[i]
        if only:
            out.append(a)
        elif a == "--":
            only = True
        elif a.startswith("-") and a != "-":
            takes = (a.startswith("--") and a not in SWIFTFORMAT_FLAGS) if values == "swift" else a in values
            if takes and "=" not in a:
                i += 1
        else:
            out.append(a)
        i += 1
    return out


def lister(P, cmd_words):
    """True when these words list a whole tree rather than the change's files."""
    words, _ = P.effective(cmd_words)
    if not words:
        return False
    b = _base(words[0])
    if b in TREE_LISTERS:
        return True
    if b == "git" and "ls-files" in words:
        return True
    return b in ("rg", "ripgrep") and "--files" in words


def path_problem(word, cwd):
    """Why this path argument spans more than named files, else None."""
    if word == "-" or "$" in word:
        return None
    p = word[1:] if word.startswith("!") else word
    if "*" in p or "?" in p:
        return "a glob"
    if re.fullmatch(r"[0-9]+(\.[0-9]+)*", p):
        return None
    if p in (".", "..", "./", "../", "~", "~/") or p.endswith("/"):
        return "a directory"
    full = os.path.join(cwd, os.path.expanduser(p))
    if os.path.isdir(full):
        return "a directory"
    if os.path.isfile(full):
        return None
    if not os.path.splitext(os.path.basename(p))[1]:
        return "a directory (no file extension)"
    return None


def judge(P, cmds, idx, cwd):
    """The deny reason for cmds[idx], else None."""
    cmd = cmds[idx]
    raw = cmd.texts()
    eff, _ = P.effective(raw)
    via_xargs = any(_base(w) == "xargs" for w in raw[:len(raw) - len(eff)])
    hit = identify(strip_runners(eff))
    if not hit:
        return None
    tool, args, values = hit
    if _has(args, *HELP_FLAGS):
        return None
    shown = " ".join(w for w in strip_runners(eff) if P.DYN not in w)
    upstream, j = [], idx
    while j > 0 and cmds[j - 1].op in ("|", "|&"):
        upstream.append(cmds[j - 1])
        j -= 1
    if any(lister(P, u.texts()) for u in upstream):
        return tool, shown, "is fed every file of a tree by a lister such as find or git ls-files"
    pos = positionals(args, values)
    for word in pos:
        if P.DYN in word:
            if any(lister(P, c.texts()) for inner in cmd.substs for c in inner):
                return tool, shown, "takes every file of a tree from a $(...) lister such as find"
            continue
        why = path_problem(word, cwd)
        if why:
            return tool, shown, "points at `%s`, %s" % (word, why)
    if not pos and not via_xargs and not upstream and not any(a.startswith(STDIN_FLAGS) for a in args):
        return tool, shown, "names no file and defaults to the whole working directory"
    return None


def find_violation(P, cmds, cwd, depth=0):
    if depth > 6:
        return None
    for idx, cmd in enumerate(cmds):
        words, _ = P.effective(cmd.texts())
        if words and words[0] in ("cd", "pushd") and len(words) > 1 and P.DYN not in words[1] \
                and "$" not in words[1]:
            cwd = os.path.join(cwd, os.path.expanduser(words[1]))
            continue
        found = judge(P, cmds, idx, cwd)
        if found:
            return found
        body = P.shell_body(words)
        if body:
            found = find_violation(P, P.parse(body), cwd, depth + 1)
            if found:
                return found
        for inner in cmd.substs:
            found = find_violation(P, inner, cwd, depth + 1)
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
        if not TOOL_HINT.search(command):
            return 0
        cwd = payload.get("cwd") or os.getcwd()
        P = _load_parser()
        hit = find_violation(P, P.parse(command), cwd)
    except Exception:
        return 0  # fail open
    if not hit:
        return 0
    tool, shown, why = hit
    fix = "%s $(git diff --name-only --diff-filter=AM <base> -- %s)" % (FIX_CMDS[tool], GLOBS[tool])
    if tool == "dart fix":
        fix = ("for f in $(git diff --name-only --diff-filter=AM <base> -- '*.dart'); do "
               "dart fix --apply \"$f\"; done")
    print(json.dumps({
        "hookSpecificOutput": {
            "hookEventName": "PreToolUse",
            "permissionDecision": "deny",
            "permissionDecisionReason": (
                f"Blocked: `{shown}` {why}, so it reflows files this change never touched and they land "
                f"in the commit. {RULE}: run a formatter or auto-fixer only on the files the change "
                "modified, never on a whole directory.\n"
                f"Run instead: {fix}\n"
                "(add the same flags you passed; <base> is the branch point, or HEAD for uncommitted "
                "work). Check-only modes (--check, --output=none --set-exit-if-changed, --lint) stay "
                "allowed. If Simon asked for a whole-tree reformat, ask him to run it in his own terminal."
            ),
        }
    }))
    return 0


if __name__ == "__main__":
    sys.exit(main())
