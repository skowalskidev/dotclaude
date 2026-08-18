#!/usr/bin/env bash
# worktree-freshness.sh
# SessionStart hook: when this session runs in a git worktree that has fallen behind its main branch,
# warn ONCE at session start so stale-base work is caught before it starts — not discovered 29 commits
# later at merge time (which is exactly what happened building the config-metrics subsystem).
#
# DETECTION AND REPORTING ONLY. It injects one context note and nothing else: never edits, never
# rebases, never blocks. The fix (merge/rebase main) stays a human decision.
#
# Why a SessionStart detector and not a creation-time fix: worktrees here are created by the harness
# from whatever HEAD the repo was at, and a long-lived worktree then drifts as main advances. Nothing
# updates it automatically, so the drift is invisible until a test fails against a part that only
# exists on main. This makes the drift visible at the one moment it can still be acted on cheaply.

set -uo pipefail

cwd="$(pwd)"
command -v git >/dev/null 2>&1 || exit 0

# Only fire inside a LINKED worktree (main checkout has no drift to report).
common="$(git -C "$cwd" rev-parse --path-format=absolute --git-common-dir 2>/dev/null)" || exit 0
gitdir="$(git -C "$cwd" rev-parse --absolute-git-dir 2>/dev/null)" || exit 0
case "$gitdir" in
  "$common") exit 0 ;;  # not a linked worktree
esac

# Pick the mainline ref that exists.
main_ref=""
for r in main master; do
  if git -C "$cwd" rev-parse --verify --quiet "$r" >/dev/null 2>&1; then main_ref="$r"; break; fi
done
[ -n "$main_ref" ] || exit 0

behind="$(git -C "$cwd" rev-list --count "HEAD..$main_ref" 2>/dev/null || echo 0)"
[ -n "$behind" ] || behind=0
# Threshold: a handful of commits is normal churn; only shout when the base is meaningfully stale.
[ "$behind" -ge 10 ] 2>/dev/null || exit 0

branch="$(git -C "$cwd" rev-parse --abbrev-ref HEAD 2>/dev/null || echo '?')"
msg="WORKTREE FRESHNESS: this worktree's branch ($branch) is $behind commits behind $main_ref. It was created from an older HEAD and main has moved on. Before building, bring it current — 'git merge $main_ref' (or rebase) — so you are not working on a stale base (parts that only exist on $main_ref will look missing, and tests against them will fail)."

# Emit as SessionStart additionalContext (same shape as session-identity.sh).
printf '{"hookSpecificOutput":{"hookEventName":"SessionStart","additionalContext":%s}}\n' \
  "$(printf '%s' "$msg" | sed 's/\\/\\\\/g; s/"/\\"/g' | awk '{printf "\"%s\"", $0}')"
exit 0
