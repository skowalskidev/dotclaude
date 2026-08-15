#!/usr/bin/env bash
# port-registry-sweep.sh
# SessionStart hook: reconcile the shared port registry, then report who currently holds which local
# port. REPORTING ONLY — this hook never kills a process and never releases another session's claim.
#
# Why this runs at session start: the registry's failure mode is a session that died without releasing,
# leaving rows that block everyone afterwards for servers that are long gone. Reconciling here means a
# new session on a new day always opens against a file that has already been cleaned, which is exactly
# what you asked for — the record is kept honest by the next session to arrive, not by remembering.
#
# The second reason is the one the human notices: two sessions fighting over :4000 surfaces as an
# opaque network error, not as a port conflict. Naming the holder up front turns an hour of debugging
# into a sentence.
#
# Output convention matches hooks/config-status.sh, hooks/session-connectors.sh and
# hooks/orphan-worker-sweep.sh: silent (exit 0, no output) when there is nothing to report; a
# hookSpecificOutput/additionalContext blob when there is. Wrapped so a slow or erroring registry can
# never block session start.
REG_SH="$HOME/.claude/bin/port-registry.sh"

run_sweep() {
  set -u
  [ -x "$REG_SH" ] || return 0

  out="$("$REG_SH" list 2>/dev/null)"
  [ -n "$out" ] || return 0
  case "$out" in
    "No ports claimed."*) return 0 ;;   # nothing held anywhere: say nothing
  esac

  me="$("$REG_SH" whoami 2>/dev/null | awk '/^session:/ { print $2 }')"

  msg="NOTE: local dev ports are claimed by Claude session(s) on this machine. This session is '${me}'.
${out}

Before binding ANY port: ~/.claude/bin/port-registry.sh claim <port> --for \"<what>\" (exit 3 = held by
another live session). If it is held by someone else, tell the user who holds it and what for, run
\`port-registry.sh wait <port>\`, and wait — do not pick a different port silently and do not kill
their server. Release with \`port-registry.sh release\` the moment you kill your own process; that is
what tells the waiting session it can go. Protocol: ~/.claude/references/dev-server-hygiene.md"

  if command -v jq >/dev/null 2>&1; then
    jq -cn --arg c "$msg" '{hookSpecificOutput:{hookEventName:"SessionStart",additionalContext:$c}}'
  else
    printf '%s\n' "$msg"
  fi
}

# Never let a slow or erroring registry block session start.
( run_sweep ) 2>/dev/null

exit 0
