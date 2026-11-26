#!/usr/bin/env python3
"""
Both directions for hooks/formatter-scope-guard.py: a guard is assumed vacuous until it has been seen
to fail, and assumed harmful until it has been seen NOT to fire on a scoped run, a check-only mode or
text that merely names a command.

Drives the hook the way the harness does (a tool_use JSON payload on stdin, with `cwd`). Nothing is
run: the guard only parses the command text and stats paths under a temporary directory.

The MUST-NOT-FIRE block is the important half. The class that gets a guard switched off is a false
positive on legitimate use: explicit files, an option value such as `-l 100` read as a folder, the
`$(git diff --name-only ...)` substitution the deny message itself recommends, or a check-only run.
"""

import json
import subprocess
import sys
import tempfile
from pathlib import Path

GUARD = Path(__file__).parent / "formatter-scope-guard.py"
DIFF = "$(git diff --name-only --diff-filter=AM main -- '*.dart')"

# (label, command, substring the deny reason must contain)
MUST_FIRE = [
    # the incident: whole feature folders
    ("dart format two feature folders", "dart format lib/features/auth test/features/auth", "lib/features/auth"),
    ("dart format lib test", "dart format lib test", "`lib`"),
    ("dart format .", "dart format .", "`.`"),
    ("dart format existing dir with a dot in its name", "dart format pkg.v2", "pkg.v2"),
    ("dart format trailing slash", "dart format lib/", "lib/"),
    ("dart format a glob", "dart format 'lib/**/*.dart'", "a glob"),
    ("dart format unquoted glob", "dart format lib/*.dart", "a glob"),
    ("dart format with line length then a folder", "dart format -l 100 lib", "`lib`"),
    ("dart format after cd", "cd app && dart format lib", "`lib`"),
    ("dart format inside bash -c", "bash -c 'dart format lib'", "`lib`"),
    ("dart format after ;", "echo go; dart format .", "`.`"),
    ("dart format under timeout", "timeout 60 dart format lib", "`lib`"),
    ("fvm dart format", "fvm dart format lib", "`lib`"),
    ("dart format, explicit write output", "dart format --output=write lib", "`lib`"),
    ("dart format, mixed file and folder", "dart format lib/a.dart test", "`test`"),
    ("flutter format", "flutter format lib", "`lib`"),
    ("dart fix --apply, no path", "dart fix --apply", "whole working directory"),
    ("dart fix --apply .", "dart fix --apply .", "`.`"),
    ("find fed to xargs", "find lib -name '*.dart' | xargs dart format", "lister"),
    ("git ls-files fed to xargs", "git ls-files '*.dart' | xargs dart format", "lister"),
    ("find in a substitution", "dart format $(find lib -name '*.dart')", "lister"),
    # js
    ("prettier --write .", "prettier --write .", "`.`"),
    ("prettier -w glob", "prettier -w 'src/**/*.{ts,tsx}'", "a glob"),
    ("npx prettier --write src", "npx prettier --write src", "`src`"),
    ("pnpm exec prettier --write .", "pnpm exec prettier --write .", "`.`"),
    ("yarn prettier --write .", "yarn prettier --write .", "`.`"),
    ("eslint --fix .", "eslint --fix .", "`.`"),
    ("eslint --fix, no path", "npx eslint --fix", "whole working directory"),
    ("eslint --fix with ext then dir", "eslint --fix --ext .ts,.tsx src", "`src`"),
    # python
    ("black .", "black .", "`.`"),
    ("python -m black src", "python3 -m black src", "`src`"),
    ("uv run black", "uv run black app", "`app`"),
    ("ruff format .", "ruff format .", "`.`"),
    ("ruff format, no path", "ruff format", "whole working directory"),
    ("ruff check --fix", "ruff check --fix src", "`src`"),
    ("ruff check --fix-only", "ruff check --fix-only --select E,F .", "`.`"),
    # go, swift, kotlin
    ("gofmt -w .", "gofmt -w .", "`.`"),
    ("gofmt -s -w dir", "gofmt -s -w ./internal", "./internal"),
    ("swiftformat .", "swiftformat .", "`.`"),
    ("swiftformat Sources with an option value", "swiftformat --swiftversion 5.9 Sources", "`Sources`"),
    ("ktlint -F, no path", "ktlint -F", "whole working directory"),
    ("ktlint --format glob", "ktlint --format 'src/**/*.kt'", "a glob"),
]

MUST_NOT_FIRE = [
    # explicit files
    ("dart format two files", "dart format lib/a.dart test/b_test.dart"),
    ("dart format an existing file", "dart format pubspec.yaml"),
    ("dart format with line length", "dart format -l 100 lib/a.dart"),
    ("dart format --line-length=120", "dart format --line-length=120 lib/a.dart"),
    ("dart format after cd, file", "cd app && dart format lib/a.dart"),
    ("dart fix --apply one file", "dart fix --apply lib/a.dart"),
    ("prettier --write files", "prettier --write src/a.ts src/b.tsx"),
    ("prettier --write with parser value", "npx prettier --write --parser babel src/a.js"),
    ("eslint --fix files with format value", "eslint --fix -f stylish src/a.ts"),
    ("black file with line length", "black -l 100 app/main.py"),
    ("ruff check --fix with select", "ruff check --fix --select E,F app/main.py"),
    ("gofmt -w file", "gofmt -w main.go"),
    ("swiftformat file with options", "swiftformat --swiftversion 5.9 --indent 4 Sources/App.swift"),
    ("ktlint -F file", "ktlint -F src/main/A.kt"),
    # the recommended diff-scoped forms
    ("git diff substitution", "dart format " + DIFF),
    ("git diff substitution, quoted", 'dart format "' + DIFF + '"'),
    ("git diff fed to xargs", "git diff --name-only --diff-filter=AM main -- '*.dart' | xargs dart format"),
    ("git diff through grep to xargs", "git diff --name-only main | grep '\\.dart$' | xargs -r dart format"),
    ("loop over git diff", 'for f in $(git diff --name-only HEAD); do dart fix --apply "$f"; done'),
    ("a shell variable", 'dart format $CHANGED'),
    ("stdin formatting", "cat a.dart | dart format"),
    ("prettier on stdin", "prettier --write --stdin-filepath a.ts"),
    # check-only modes
    ("dart format check mode", "dart format --output=none --set-exit-if-changed lib test"),
    ("dart format -o none", "dart format -o none --set-exit-if-changed ."),
    ("dart format show", "dart format --output show lib"),
    ("flutter format dry run", "flutter format -n lib"),
    ("dart fix dry run", "dart fix --dry-run"),
    ("dart analyze", "dart analyze lib"),
    ("prettier --check", "npx prettier --check ."),
    ("prettier list-different", "prettier --list-different src"),
    ("black --check", "black --check ."),
    ("black --diff", "python -m black --diff src"),
    ("ruff format --check", "ruff format --check ."),
    ("ruff check without fix", "ruff check src"),
    ("ruff check --fix --diff", "ruff check --fix --diff src"),
    ("eslint without fix", "eslint ."),
    ("eslint --fix-dry-run", "eslint --fix-dry-run src"),
    ("gofmt -l", "gofmt -l ."),
    ("swiftformat --lint", "swiftformat --lint ."),
    ("ktlint lint only", "ktlint 'src/**/*.kt'"),
    ("help", "dart format --help"),
    ("version", "prettier --version"),
    # non-formatter commands and text that names one
    ("git status", "git status"),
    ("flutter test dir", "flutter test test/features"),
    ("echo naming the command", "echo 'dart format lib'"),
    ("grep for the command text", "grep -rn 'prettier --write .' docs"),
    ("heredoc body naming it", "cat > note.md <<'EOF'\ndart format lib test\nEOF"),
    ("git commit naming it", "git commit -F msg.txt"),
    # fail open
    ("empty command", ""),
    ("malformed unterminated substitution", "dart format $(git diff --name-only"),
]


def run(command: str, cwd: str) -> str:
    payload = {"tool_name": "Bash", "tool_input": {"command": command}, "cwd": cwd}
    p = subprocess.run([sys.executable, str(GUARD)], input=json.dumps(payload), text=True,
                       capture_output=True)
    if p.returncode != 0:
        return f"CRASH rc={p.returncode} {p.stderr[-200:]}"
    if not p.stdout.strip():
        return ""
    return json.loads(p.stdout)["hookSpecificOutput"]["permissionDecisionReason"]


def main() -> int:
    failures, passes = [], 0
    with tempfile.TemporaryDirectory() as td:
        root = Path(td)
        for d in ("lib/features/auth", "test/features/auth", "app/lib", "src", "pkg.v2", "internal"):
            (root / d).mkdir(parents=True, exist_ok=True)
        (root / "pubspec.yaml").write_text("name: x\n")
        for label, cmd, expect in MUST_FIRE:
            reason = run(cmd, td)
            if reason and not reason.startswith("CRASH") and expect in reason:
                passes += 1
            else:
                failures.append(f"MUST FIRE: {label}: {cmd!r} -> {reason[:140]!r}")
        for label, cmd in MUST_NOT_FIRE:
            reason = run(cmd, td)
            if not reason:
                passes += 1
            else:
                failures.append(f"MUST NOT FIRE: {label}: {cmd!r} -> {reason[:140]!r}")
        # The deny names the rule and the diff-scoped fix.
        reason = run("dart format lib test", td)
        for needle in ("Scope discipline", "dart format $(git diff --name-only --diff-filter=AM <base> -- '*.dart')"):
            if needle in reason:
                passes += 1
            else:
                failures.append(f"DENY MESSAGE lacks {needle!r}: {reason[:200]!r}")
    # Non-Bash tools and a garbage payload are never touched.
    for raw in ('{"tool_name": "Read", "tool_input": {"command": "dart format ."}}', "not json"):
        p = subprocess.run([sys.executable, str(GUARD)], input=raw, text=True, capture_output=True)
        if p.returncode == 0 and not p.stdout.strip():
            passes += 1
        else:
            failures.append(f"MUST FAIL OPEN: {raw[:40]!r} -> rc={p.returncode} out={p.stdout[:80]!r}")
    for f in failures:
        print(f)
    print(f"{passes} pass, {len(failures)} fail")
    return 1 if failures else 0


if __name__ == "__main__":
    sys.exit(main())
