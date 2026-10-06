#!/usr/bin/env bash
# SessionStart hook: surface out-of-sync ~/.claude config so Claude proactively offers to sync it.
# Runs on session start and can re-fire mid-session (Conductor re-runs SessionStart between messages),
# event-driven, NO daemon. Fast — local git only. A rate-limited
# BACKGROUND fetch (at most once / 4h, fully detached) keeps the remote-tracking ref fresh for
# multi-machine use; it never blocks session start and is not an always-on process.
REPO="$HOME/.claude"

# Clear a STALE config-edit authorization sentinel. The /sk:claude-config-update flow sets it after
# your yes and removes it when done; a sentinel left behind means that flow crashed, and leaving it
# would hold config-edit-guard.py open. Only clear a STALE one (>2 min old): this hook can re-fire
# mid-session (Conductor re-runs SessionStart between messages), and an unconditional rm would wipe a
# LIVE sentinel a flow just touched — blocking the very edits it authorized. A crashed-flow sentinel is
# minutes old and still gets cleaned.
find "$REPO/.config-edit-authorized" -mmin +2 -delete 2>/dev/null

[ -d "$REPO/.git" ] || exit 0

# Rate-limited, non-blocking background fetch (keeps @{upstream} fresh across machines).
stamp="$REPO/.git/.last-config-fetch"
if [ ! -f "$stamp" ] || [ -n "$(find "$stamp" -mmin +240 2>/dev/null)" ]; then
  touch "$stamp" 2>/dev/null
  ( git -C "$REPO" fetch -q origin >/dev/null 2>&1 & ) >/dev/null 2>&1
fi

status="$(git -C "$REPO" status --porcelain 2>/dev/null)"
ahead="$(git -C "$REPO" rev-list --count @{upstream}..HEAD 2>/dev/null || echo 0)"
behind="$(git -C "$REPO" rev-list --count HEAD..@{upstream} 2>/dev/null || echo 0)"

# A change /sk:claude-config-update drafted and has not landed. The branch is the record, so naming
# it at every session start is what keeps an unanswered proposal from being forgotten.
pending="$(git -C "$REPO" for-each-ref --no-merged origin/main \
  --format='  %(refname:short) (%(committerdate:relative)): %(contents:subject)' \
  'refs/heads/config-update/' 2>/dev/null)"

out_of_sync=0
{ [ -n "$status" ] || [ "${ahead:-0}" -gt 0 ] || [ "${behind:-0}" -gt 0 ]; } && out_of_sync=1

# Fully clean, pushed, up to date and nothing waiting -> say nothing.
[ "$out_of_sync" -eq 0 ] && [ -z "$pending" ] && exit 0

msg=""
if [ "$out_of_sync" -eq 1 ]; then
  msg="NOTE: your ~/.claude config repo (your config source of truth, a public GitHub repo) is OUT OF SYNC with GitHub."
  [ -n "$status" ] && msg="${msg}
Uncommitted changes:
${status}"
  [ "${ahead:-0}" -gt 0 ] && msg="${msg}
${ahead} local commit(s) not yet pushed."
  [ "${behind:-0}" -gt 0 ] && msg="${msg}
${behind} commit(s) on GitHub not pulled — offer to run: git -C ~/.claude pull --rebase"
  msg="${msg}
Proactively OFFER to sync via the /sk:claude-config-sync skill (it secret-scans first). NEVER commit secrets."
fi
if [ -n "$pending" ]; then
  [ -n "$msg" ] && msg="${msg}

"
  msg="${msg}NOTE: config change(s) drafted by /sk:claude-config-update are NOT on main yet:
${pending}
Tell Simon once this session, one line per branch, and ask: land or drop. Land = /sk:claude-config-sync on the branch. Drop = delete the branch and its worktree."
fi

if command -v jq >/dev/null 2>&1; then
  jq -cn --arg c "$msg" '{hookSpecificOutput:{hookEventName:"SessionStart",additionalContext:$c}}'
else
  printf '%s\n' "$msg"
fi
exit 0
