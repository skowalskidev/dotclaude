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
# The same report covers the other resource sessions share without seeing each other: the machine-wide
# heavy lease and simulator claims (bin/local-capacity.py, surfaced through bin/native-slot.sh). It
# prints them when a lease or claim is held, a simulator is booted, or this workspace holds a native project, so a session learns the
# protocol before its first build and never after the machine has stalled.
#
# Output convention matches hooks/config-status.sh, hooks/session-connectors.sh and
# hooks/orphan-worker-sweep.sh: silent (exit 0, no output) when there is nothing to report; a
# hookSpecificOutput/additionalContext blob when there is. Wrapped so a slow or erroring registry can
# never block session start.
REG_SH="${CLAUDE_CONFIG_ROOT:-$HOME/.claude}/bin/port-registry.sh"
NATIVE_SH="${CLAUDE_CONFIG_ROOT:-$HOME/.claude}/bin/native-slot.sh"

port_report() {
  [ -x "$REG_SH" ] || return 0

  out="$("$REG_SH" list 2>/dev/null)"
  [ -n "$out" ] || return 0
  case "$out" in
    "No ports claimed."*) return 0 ;;   # nothing held anywhere: say nothing
  esac

  me="$("$REG_SH" whoami 2>/dev/null | awk '/^session:/ { print $2 }')"

  printf '%s\n' "NOTE: local dev ports are claimed by Claude session(s) on this machine. This session is '${me}'.
${out}

Before binding ANY port: ~/.claude/bin/port-registry.sh claim <port> --for \"<what>\" (exit 3 = held by
another live session). If it is held by someone else, tell the user who holds it and what for, run
\`port-registry.sh wait <port>\`, and wait — do not pick a different port silently and do not kill
their server. Release with \`port-registry.sh release\` the moment you kill your own process; that is
what tells the waiting session it can go. Protocol: ~/.claude/references/dev-server-hygiene.md"
}

# A native project two levels down still counts: the app often sits in ios/ or android/.
has_native_project() {
  local d="${CLAUDE_PROJECT_DIR:-$PWD}"
  [ -d "$d" ] || return 1
  find "$d" -maxdepth 2 \( -name node_modules -o -name .git \) -prune -o \
    \( -name '*.xcodeproj' -o -name '*.xcworkspace' -o -name 'Package.swift' \
       -o -name 'build.gradle' -o -name 'build.gradle.kts' \) -print 2>/dev/null | grep -q .
}

native_report() {
  [ -x "$NATIVE_SH" ] || return 0
  local out
  out="$("$NATIVE_SH" list 2>/dev/null)"
  if [ "$out" = "heavy slot free
booted simulators: none" ]; then
    has_native_project || return 0
  elif [ -z "$out" ]; then
    has_native_project || return 0
    out="Capacity status unavailable; inspect before native work."
  fi

  printf '%s\n' "NOTE: heavy builds and simulators are shared by every local session on this machine.
${out}

Before ANY native build, native test run or simulator boot:
~/.claude/bin/native-slot.sh run --for \"<what>\" [--udid <id>] -- <command>
Exit 75 means the heavy step was deferred and the command did not start. Register each simulator
you create or boot with \`native-slot.sh claim-sim <udid>\`; keep the same lease through shutdown.
Never kill another session's build or shut down its simulator.
Protocol: ~/.claude/references/dev-server-hygiene.md § Machine-wide capacity"
}

run_sweep() {
  set -u
  ports="$(port_report)"
  native="$(native_report)"
  [ -n "$ports$native" ] || return 0
  msg="$ports"
  [ -n "$ports" ] && [ -n "$native" ] && msg="$msg

"
  msg="$msg$native"

  if command -v jq >/dev/null 2>&1; then
    jq -cn --arg c "$msg" '{hookSpecificOutput:{hookEventName:"SessionStart",additionalContext:$c}}'
  else
    printf '%s\n' "$msg"
  fi
}

# Never let a slow or erroring registry block session start.
( run_sweep ) 2>/dev/null

exit 0
