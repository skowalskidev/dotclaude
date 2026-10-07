#!/usr/bin/env bash
# session-root.sh
# One session, one root. Prints the directory a session's records (.context/<slug>-plan.md, the
# dashboard, .context/intent-ledger.md) belong in, so every hook that writes one agrees.
#
# The problem it removes: hooks read the prompt's cwd, and the cwd follows the shell. A session that
# makes a worktree UNDER its own root (.context/<name>, .claude/worktrees/<name>) and runs commands
# in it then resolves a different git top level, and each hook opens a second plan and a second
# ledger there. The session ends up with two records and neither is whole.
#
# The rule: the first root a session resolves is remembered. While the shell is in that root or in a
# worktree nested under it, that root is the answer. A move to a directory OUTSIDE it is a real move
# and re-homes the session.
#
# Usage:
#   session-root.sh <session-id> <cwd>     print the root for this session; exit 1 = cwd is not a directory
#   session-root.sh forget <session-id>    drop the remembered root
#
# An empty session id, or a cwd outside any git repository, is answered without remembering anything:
# the git top level when there is one, the cwd otherwise.
#
# Env: CLAUDE_SESSION_ROOT_DIR  where the records live (tests point this at a temp directory)
set -u

DIR="${CLAUDE_SESSION_ROOT_DIR:-$HOME/.claude/.session-root}"

physical() { (cd -P "$1" 2>/dev/null && pwd -P); }

if [ "${1:-}" = "forget" ]; then
  sid="$(printf '%s' "${2:-}" | tr -cd '[:alnum:]._-')"
  [ -n "$sid" ] && rm -f "$DIR/$sid"
  exit 0
fi

# Never let a crafted session id escape the state directory.
sid="$(printf '%s' "${1:-}" | tr -cd '[:alnum:]._-')"
cwd="${2:-$PWD}"
[ -d "$cwd" ] || exit 1

top="$(git -C "$cwd" rev-parse --show-toplevel 2>/dev/null)"
if [ -z "$top" ]; then
  physical "$cwd"
  exit 0
fi
top="$(physical "$top")" || exit 1

if [ -z "$sid" ]; then
  printf '%s\n' "$top"
  exit 0
fi

memo=""
[ -f "$DIR/$sid" ] && memo="$(head -1 "$DIR/$sid" 2>/dev/null)"
if [ -n "$memo" ] && [ -d "$memo" ]; then
  case "$top/" in
    "$memo"/*) touch "$DIR/$sid" 2>/dev/null; printf '%s\n' "$memo"; exit 0 ;;
  esac
fi

mkdir -p "$DIR" 2>/dev/null && find "$DIR" -type f -mtime +14 -delete 2>/dev/null
mkdir -p "$DIR" 2>/dev/null && printf '%s\n' "$top" > "$DIR/$sid.tmp.$$" 2>/dev/null \
  && mv "$DIR/$sid.tmp.$$" "$DIR/$sid" 2>/dev/null
printf '%s\n' "$top"
