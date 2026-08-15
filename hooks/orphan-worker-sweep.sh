#!/usr/bin/env bash
# orphan-worker-sweep.sh
# SessionStart hook: reports orphaned framework dev-tool worker processes machine-wide (not just
# in this session's cwd). DETECTION AND REPORTING ONLY — this hook must NEVER kill anything.
# Killing is a separate, explicit command you run yourself: ~/.claude/bin/kill-orphan-workers.sh.
# An unattended SessionStart hook that signals processes is exactly what rules/security.md forbids
# (a machine change with no provenance gate), so the two are kept hard-separated.
#
# Why this exists: a dead `next dev` / `turbo dev` / `jest` / `vite` run can leave child workers
# (the classic offender is `next-router-worker`) that reparent to PID 1 and pin a CPU core
# indefinitely — in a Conductor workspace nobody is currently looking at. One was found still
# running 5+ hours later at 97% CPU. `rules/process.md`'s "clean up after yourself" only covers
# processes YOU started at task end; this hook is the proactive, machine-wide backstop.
#
# Detection is delegated entirely to bin/kill-orphan-workers.sh --list — ONE source of truth for
# "what counts as an orphaned worker" shared with the script that actually clears them. See that
# script's header for the full (a)/(b)/(c) detection contract and why it's cheap on a clean
# machine (the expensive `lsof` cwd check only ever runs on the rare candidate that already passed
# the PPID==1 + interpreter/keyword checks).
#
# Output convention matches hooks/config-status.sh and hooks/session-connectors.sh: silent
# (exit 0, no output) when there's nothing to report; a hookSpecificOutput/additionalContext JSON
# blob (or plain text if jq is unavailable) when there is. Wrapped so a slow or erroring detector
# can never block session start.
KILLER="$HOME/.claude/bin/kill-orphan-workers.sh"

run_sweep() {
  set -u
  [ -x "$KILLER" ] || return 0

  rows="$("$KILLER" --list 2>/dev/null)"
  [ -n "$rows" ] || return 0

  lines="Orphaned framework worker process(es) found machine-wide (PID 1 parent, dev-tool process, cwd inside a git checkout) — each has been burning CPU with no live dev server attached:
"
  # shellcheck disable=SC2034 # ppid is always 1 by the detection contract; consumed, not reported
  while IFS="$(printf '\t')" read -r pid ppid pcpu etime cwd args; do
    [ -n "$pid" ] || continue
    lines="${lines}  - pid ${pid}  %cpu=${pcpu}  elapsed=${etime}  cwd=${cwd}
    ${args}
"
  done <<EOF
$rows
EOF
  lines="${lines}
CLEAR THESE NOW, BEFORE STARTING THE TASK: run ~/.claude/bin/kill-orphan-workers.sh
Every row above is already parentless and already burning a core, so there is nothing to triage.
Deferring to task-end cleanup costs a core for the whole session, which is unbounded — one run
burned 97% of a core for ten hours because this report arrived at minute zero of an all-day task.
(--dry-run previews, --list re-checks. This hook only reports; it never kills, because an
unattended machine change is what rules/security.md gates.)"

  if command -v jq >/dev/null 2>&1; then
    jq -cn --arg c "$lines" '{hookSpecificOutput:{hookEventName:"SessionStart",additionalContext:$c}}'
  else
    printf '%s\n' "$lines"
  fi
}

# Never let a slow/erroring detector block session start: run in a subshell so `set -u` (or
# anything else) inside run_sweep can only abort that subshell, never this script, and force
# exit 0 unconditionally regardless of what happened above.
( run_sweep ) 2>/dev/null

exit 0
