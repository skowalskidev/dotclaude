#!/usr/bin/env bash
# session-root.sh
# One session, one root. Prints the directory a session's records (.context/<slug>-plan.md, the
# dashboard, .context/intent-ledger.md) belong in, so every hook and CLI that reads or writes one agrees:
# hooks/task-intake.sh, hooks/intent-ledger.sh (and through it the git-commit-guard ledger lookup) and
# bin/workflow-dashboard.py init/link.
#
# The problem it removes: a hook payload's cwd, and a shell's $PWD, follow every `cd`. Keyed on the cwd,
# a session that runs commands in a worktree nested under its root, or anywhere else, opens a second
# plan and a second ledger there, and a lookup from there misses what the session recorded.
#
# The rule: the record is keyed by SESSION ID and anchored to the directory the session started in.
# The first root a session resolves is written once and returned for every later call, whatever the
# cwd. Nothing a later call does moves it. The anchor comes from CLAUDE_PROJECT_DIR (Claude Code sets
# it on every hook process to the root the session started in; it does not follow `cd`), else from the
# cwd of that first call. A remembered root that no longer exists is re-anchored the same way.
#
# Usage:
#   session-root.sh <session-id> <cwd>     print the root for this session; exit 1 = cwd is not a directory
#   session-root.sh forget <session-id>    drop the remembered root
#
# An empty session id, or an anchor outside any git repository, is answered without remembering
# anything: the git top level when there is one, the cwd otherwise.
#
# Env: CLAUDE_SESSION_ROOT_DIR  where the records live (tests point this at a temp directory)
#      CLAUDE_PROJECT_DIR       the session's start directory (set by Claude Code on hook processes)
set -u

DIR="${CLAUDE_SESSION_ROOT_DIR:-$HOME/.claude/.session-root}"

physical() { (cd -P "$1" 2>/dev/null && pwd -P); }
git_top() { # $1 = directory; prints its physical git top level, or nothing
  t="$(git -C "$1" rev-parse --show-toplevel 2>/dev/null)" && [ -n "$t" ] && physical "$t"
}

if [ "${1:-}" = "forget" ]; then
  sid="$(printf '%s' "${2:-}" | tr -cd '[:alnum:]._-')"
  [ -n "$sid" ] && rm -f "$DIR/$sid"
  exit 0
fi

# Never let a crafted session id escape the state directory.
sid="$(printf '%s' "${1:-}" | tr -cd '[:alnum:]._-')"
cwd="${2:-$PWD}"
[ -d "$cwd" ] || exit 1

if [ -n "$sid" ] && [ -f "$DIR/$sid" ]; then
  memo="$(head -1 "$DIR/$sid" 2>/dev/null)"
  if [ -n "$memo" ] && [ -d "$memo" ]; then
    touch "$DIR/$sid" 2>/dev/null
    printf '%s\n' "$memo"
    exit 0
  fi
fi

top=""
start="${CLAUDE_PROJECT_DIR:-}"
[ -n "$start" ] && [ -d "$start" ] && top="$(git_top "$start")"
[ -n "$top" ] || top="$(git_top "$cwd")"
if [ -z "$top" ]; then
  physical "$cwd"
  exit 0
fi

if [ -n "$sid" ]; then
  mkdir -p "$DIR" 2>/dev/null && find "$DIR" -type f -mtime +14 -delete 2>/dev/null
  mkdir -p "$DIR" 2>/dev/null && printf '%s\n' "$top" > "$DIR/$sid.tmp.$$" 2>/dev/null \
    && mv "$DIR/$sid.tmp.$$" "$DIR/$sid" 2>/dev/null
fi
printf '%s\n' "$top"
