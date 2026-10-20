#!/usr/bin/env bash
# SessionStart hook: load automatic repair policy and report config state for owned resumption.
# Runs on session start and can re-fire mid-session (Conductor re-runs SessionStart between messages),
# event-driven, NO daemon. Fast — local git only. A rate-limited
# BACKGROUND fetch (at most once / 4h, fully detached) keeps the remote-tracking ref fresh for
# multi-machine use; it never blocks session start and is not an always-on process.
REPO="$HOME/.claude"

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
# it at every session start keeps unfinished owned repairs visible.
pending="$(git -C "$REPO" for-each-ref --no-merged origin/main \
  --format='  %(refname:short) (%(committerdate:relative)): %(contents:subject)' \
  'refs/heads/config-update/' 2>/dev/null)"

out_of_sync=0
{ [ -n "$status" ] || [ "${ahead:-0}" -gt 0 ] || [ "${behind:-0}" -gt 0 ]; } && out_of_sync=1

# Even a clean checkout needs the automatic session lifecycle; this hook does not perform repairs.
msg="CONFIG SELF-REPAIR: apply rules/self-healing-config.md in every task-bearing session, without a manual skill invocation. Queue the bounded audit, repair evidence-backed own-config issues, validate, sync and clean up under standing authorization. Reconcile ownership before resuming pending work; preserve unrelated WIP and report concrete blockers. Do not ask again to commit or merge an in-scope repair."
if [ "$out_of_sync" -eq 1 ]; then
  msg="${msg}

NOTE: your ~/.claude config repo (your config source of truth, a public GitHub repo) is OUT OF SYNC with GitHub."
  [ -n "$status" ] && msg="${msg}
Uncommitted changes:
${status}"
  [ "${ahead:-0}" -gt 0 ] && msg="${msg}
${ahead} local commit(s) not yet pushed."
  [ "${behind:-0}" -gt 0 ] && msg="${msg}
${behind} commit(s) on GitHub not activated — inspect ownership and checkout state before safe activation"
  msg="${msg}
Resume owned authorized repairs via /sk:claude-config-sync after validation and secret scanning. Never stage unrelated changes."
fi
if [ -n "$pending" ]; then
  [ -n "$msg" ] && msg="${msg}

"
  msg="${msg}NOTE: config change(s) drafted by /sk:claude-config-update are NOT on main yet:
${pending}
Inspect each branch's owner, evidence and current purpose. Resume ready authorized repairs; preserve active, superseded or blocked work until its disposition is established. Do not present a generic land-or-drop question."
fi

if command -v jq >/dev/null 2>&1; then
  jq -cn --arg c "$msg" '{hookSpecificOutput:{hookEventName:"SessionStart",additionalContext:$c}}'
else
  printf '%s\n' "$msg"
fi
exit 0
