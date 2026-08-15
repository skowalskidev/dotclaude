#!/usr/bin/env bash
# port-registry.sh
#
# Machine-wide coordination of local dev ports between Claude sessions that cannot see each other.
#
# The problem this encodes: several sessions run at once in different worktrees, every one of them
# wants :3000 and :4000, and the second one to boot gets an opaque "AxiosError: Network Error" or an
# EADDRINUSE that reads like a bug in the code rather than a neighbour holding the port. Nothing on
# the machine records WHO holds a port or what for, so the only recovery is guessing.
#
# So this is the shared record: ~/.claude/port-registry.md, top level because ports are a machine-wide
# resource, and deliberately UNTRACKED by the config repo's allowlist .gitignore — the config knows
# the path and the protocol, the contents are local runtime state.
#
# The load-bearing idea: a row is a CLAIM, not the truth. A session can die without releasing, and a
# registry that believes its own stale rows blocks everyone tomorrow for a server that died today. So
# every read path reconciles against reality (`lsof`) first, and a row with no listener past the grace
# window is dropped. That is what lets the file be trusted without anyone maintaining it by hand.
#
# The grace window exists for the opposite failure: a claim is made just BEFORE the server boots, so a
# brand-new row legitimately has no listener yet. Reaping on "no listener" alone would delete it
# instantly and hand the port to the next session mid-boot.
#
# This script never kills anything. A port held by another session is reported to the user, who decides —
# same detect-and-report contract as bin/kill-orphan-workers.sh's sweep hook, and for the same reason:
# killing a human's running server is worse than waiting.
#
# Usage:
#   port-registry.sh claim <port>... [--for "<what>"]   claim before binding (reconciles first)
#   port-registry.sh release [<port>...]                release mine (all of mine if no port given)
#   port-registry.sh check <port>...                    can I bind these? (no writes)
#   port-registry.sh list [--tsv]                       reconciled table of everything held
#   port-registry.sh wait <port>...                     record that I'm waiting on a held port
#   port-registry.sh unwait [<port>...]                 drop my waiting rows
#   port-registry.sh reconcile                          drop stale rows, report what went
#   port-registry.sh reap                               reconcile PLUS the deeper liveness signals
#   port-registry.sh whoami                             show this session's identity
#
# Exit codes: 0 ok · 2 usage · 3 held by another live session · 4 a listener nobody claimed
#             · 5 an orphaned lane: workspace gone but its server is still listening
#
# `reap` vs `reconcile`. reconcile asks one question, "is anything listening", which cannot see two
# real orphan classes: a row whose WORKSPACE HAS BEEN DELETED (its server may still be listening, so
# the listener test calls it healthy forever), and a row whose SESSION IS LONG DEAD but which keeps
# being re-added. reap adds those two signals — does the workspace path still exist, and is there a
# live Claude session whose cwd is that workspace — and drops the rows they condemn.
#
# reap is deliberately NOT wired into reconcile. Every read path calls reconcile, including the
# SessionStart hook whose contract is report-only, and a deeper sweep on every read would make a
# report-only caller mutate the file in ways its contract forbids. So reap is opt-in, and
# bin/port-slot.sh is what calls it.
#
# reap still never kills and never drops a row that has a live listener. The one case it cannot
# resolve alone — workspace deleted, server still up — exits 5 with the pid, because killing is the
# caller's decision, not this file's.
#
# Env: CLAUDE_PORT_SESSION      override the session label (default: worktree dir name)
#      PORT_REGISTRY_GRACE_MIN  minutes a listener-less row survives (default 10)
#      PORT_REGISTRY_WAIT_TTL_H hours a waiting row survives (default 24)
set -u

REGISTRY="${PORT_REGISTRY_FILE:-$HOME/.claude/port-registry.md}"
LOCK="${REGISTRY%.md}.lock"
GRACE_MIN="${PORT_REGISTRY_GRACE_MIN:-10}"
WAIT_TTL_H="${PORT_REGISTRY_WAIT_TTL_H:-24}"

TAB="$(printf '\t')"
TMPDIR_SELF=""
DROPPED=""

# --- identity -------------------------------------------------------------------------------------
# A session's label has to survive a restart and mean something to the user, so it is the WORKTREE, not a
# pid or a uuid: that is the thing they can actually go and look at.
workspace_root() {
  git rev-parse --show-toplevel 2>/dev/null || pwd
}

session_label() {
  if [ -n "${CLAUDE_PORT_SESSION:-}" ]; then
    printf '%s' "$CLAUDE_PORT_SESSION"
    return
  fi
  root="$(workspace_root)"
  printf '%s' "${root##*/}"
}

SESSION="$(session_label)"
WORKSPACE="$(workspace_root)"

# --- helpers --------------------------------------------------------------------------------------
now_utc() { TZ=UTC date +%Y-%m-%dT%H:%M:%SZ; }

# epoch_of ISO8601Z — seconds since epoch, or empty when unparseable (a hand-edited row).
epoch_of() {
  TZ=UTC date -j -f "%Y-%m-%dT%H:%M:%SZ" "$1" +%s 2>/dev/null
}

age_minutes() {
  e="$(epoch_of "$1")"
  [ -n "$e" ] || { printf '%s' "999999"; return; }
  printf '%s' "$(( ( $(date +%s) - e ) / 60 ))"
}

# sanitize — strip the field separator and collapse whitespace, so a description can never break the
# table it is written into.
sanitize() {
  printf '%s' "$1" | tr '|\t\n' '/  ' | sed 's/  */ /g; s/^ *//; s/ *$//'
}

listener_pid() { lsof -nP -iTCP:"$1" -sTCP:LISTEN -t 2>/dev/null | head -1; }

listener_desc() {
  lsof -nP -iTCP:"$1" -sTCP:LISTEN 2>/dev/null | awk 'NR==2 { printf "pid %s (%s)", $2, $1 }'
}

cwd_for_pid() {
  lsof -a -p "$1" -d cwd -Fn 2>/dev/null | awk '/^n/ { print substr($0, 2); exit }'
}

pid_alive() { [ -n "$1" ] && [ "$1" != "-" ] && kill -0 "$1" 2>/dev/null; }

# claude_pids / claude_cwds — the live Claude sessions on this machine, and where each one is working.
#
# Matched on the BASENAME of the command, never on its arguments. Both halves of that are load-bearing
# and both were found by testing rather than reasoning:
#
#   * `pgrep -x claude` is WRONG. `ps -o comm=` reports the full path for a Conductor-launched session
#     (`/Users/…/com.conductor.app/agent-binaries/claude/<ver>/claude`), so -x matched 3 of the
#     sessions on this machine and missed the rest, including the one running this code. A sweep built
#     on it would reap LIVE lanes, which is the worst thing this file could do.
#   * `pgrep -f claude` is also wrong, in the other direction: it matches the Claude DESKTOP app's
#     `Claude Helper (Renderer)` processes, and every `zsh -c` whose argv happens to mention a
#     ~/.claude path. Arg matching is the defect that retired hooks/security-guard.py, and it is no
#     more correct here than it was there.
#
# A basename match on comm gets both right: `/Users/…/claude` and a bare `claude` both count,
# `Claude Helper` does not, and nothing that merely NAMES claude in its arguments can qualify.
#
# The awk rebuilds the command from field 2 onward because these paths contain spaces.
claude_pids() {
  ps -axo pid=,comm= 2>/dev/null | awk '
    { pid = $1; $1 = ""; sub(/^ +/, ""); name = $0; sub(/.*\//, "", name)
      if (name == "claude") print pid }
  '
}

# One batched lsof rather than one per pid: ten sessions would otherwise pay ten round-trips on a path
# that runs on every sweep.
claude_cwds() {
  pids="$(claude_pids | tr '\n' ',' | sed 's/,$//')"
  [ -n "$pids" ] || return 0
  lsof -a -p "$pids" -d cwd -Fn 2>/dev/null | awk '/^n/ { print substr($0, 2) }' | sort -u
}

# session_live_at WORKSPACE CWD_FILE — is a live Claude session sitting in this workspace?
# Matches the workspace itself or anything under it, since a session may be cd'd into a subdirectory.
session_live_at() {
  ws="$1"; f="$2"
  [ -s "$f" ] || return 1
  awk -v ws="$ws" '$0 == ws || index($0, ws "/") == 1 { found = 1; exit } END { exit !found }' "$f"
}

is_port() { case "$1" in ''|*[!0-9]*) return 1 ;; *) [ "$1" -ge 1 ] && [ "$1" -le 65535 ] ;; esac; }

# --- locking --------------------------------------------------------------------------------------
# mkdir is the portable atomic primitive; flock is not on macOS. Cleanup is registered on EXIT ONLY,
# per references/dev-server-hygiene.md — a trap on EXIT INT TERM runs twice and can release a lock
# another process has since taken.
acquire_lock() {
  tries=0
  while ! mkdir "$LOCK" 2>/dev/null; do
    tries=$((tries + 1))
    if [ "$tries" -gt 50 ]; then
      # A lock older than a minute belonged to a process that died holding it. Break it; the
      # alternative is a registry that is permanently unwritable after one crash.
      if [ -n "$(find "$LOCK" -maxdepth 0 -mmin +1 2>/dev/null)" ]; then
        rm -rf "$LOCK" 2>/dev/null
        tries=0
        continue
      fi
      echo "port-registry: could not acquire $LOCK after 5s" >&2
      return 1
    fi
    sleep 0.1
  done
  init_scratch
  # Capture the real status FIRST. A bare `exit` in an EXIT trap takes the status of the last command
  # IN THE TRAP, which would overwrite the 3/4 exit codes this script's contract depends on.
  trap 'rc__=$?; rm -rf "$LOCK" 2>/dev/null; [ -n "$TMPDIR_SELF" ] && rm -rf "$TMPDIR_SELF" 2>/dev/null; exit $rc__' EXIT
  return 0
}

# init_scratch must run in the PARENT shell, which is why it is separate from scratch().
init_scratch() {
  [ -n "$TMPDIR_SELF" ] || TMPDIR_SELF="$(mktemp -d "${TMPDIR:-/tmp}/port-registry.XXXXXX")"
}

# scratch NAME — a path inside this run's temp dir. It must NEVER create the dir itself: the callers
# all say `h="$(scratch held)"`, which runs this in a SUBSHELL, so an assignment to TMPDIR_SELF made
# here is lost the moment the substitution ends. That silently minted a fresh temp dir per call and
# left every one behind, because the EXIT trap then found TMPDIR_SELF empty and removed nothing —
# 963 abandoned dirs by the time it was noticed.
scratch() {
  printf '%s/%s' "$TMPDIR_SELF" "$1"
}

# --- file I/O -------------------------------------------------------------------------------------
# Rows are read out of the markdown table and the file is REGENERATED from them on every write, so a
# malformed hand edit degrades to a dropped row rather than to a corrupt file.
HEADER='# Port registry — who holds which local port

Machine-wide record of the local ports Claude sessions have claimed. Managed by
`~/.claude/bin/port-registry.sh` (claim · release · check · list · wait · reconcile).

Do not hand-edit this while a session is running. Rows are reconciled against real listeners on
every read, so a row whose port has nothing listening is dropped once it is past the grace window —
a session that died without releasing cannot block anyone tomorrow.

Untracked on purpose: the config knows this path and the protocol, the contents are local state.
The protocol lives in `~/.claude/references/dev-server-hygiene.md`.
'

# read_held / read_wait — emit TSV rows from the markdown tables.
read_held() {
  [ -f "$REGISTRY" ] || return 0
  awk -v FS=' *\\| *' '
    /^## Held/      { sec = "held"; next }
    /^## Waiting/   { sec = "wait"; next }
    sec != "held"   { next }
    /^\| *Port/     { next }
    /^\| *-/        { next }
    /^\|/ && NF >= 7 { printf "%s\t%s\t%s\t%s\t%s\t%s\n", $2, $3, $4, $5, $6, $7 }
  ' "$REGISTRY"
}

read_wait() {
  [ -f "$REGISTRY" ] || return 0
  awk -v FS=' *\\| *' '
    /^## Held/      { sec = "held"; next }
    /^## Waiting/   { sec = "wait"; next }
    sec != "wait"   { next }
    /^\| *Port/     { next }
    /^\| *-/        { next }
    /^\|/ && NF >= 5 { printf "%s\t%s\t%s\t%s\n", $2, $3, $4, $5 }
  ' "$REGISTRY"
}

write_file() {
  held_f="$1"; wait_f="$2"
  {
    printf '%s\n' "$HEADER"
    printf '## Held\n\n'
    printf '| Port | Session | Workspace | What | Claimed (UTC) | PID |\n'
    printf '| --- | --- | --- | --- | --- | --- |\n'
    if [ -s "$held_f" ]; then
      sort -n -k1,1 "$held_f" | while IFS="$TAB" read -r p s w d c pid; do
        [ -n "$p" ] || continue
        printf '| %s | %s | %s | %s | %s | %s |\n' "$p" "$s" "$w" "$d" "$c" "$pid"
      done
    fi
    printf '\n## Waiting\n\n'
    printf '| Port | Session | Workspace | Since (UTC) |\n'
    printf '| --- | --- | --- | --- |\n'
    if [ -s "$wait_f" ]; then
      sort -n -k1,1 "$wait_f" | while IFS="$TAB" read -r p s w c; do
        [ -n "$p" ] || continue
        printf '| %s | %s | %s | %s |\n' "$p" "$s" "$w" "$c"
      done
    fi
    printf '\n'
  } > "$REGISTRY.tmp" && mv "$REGISTRY.tmp" "$REGISTRY"
}

# --- reconcile ------------------------------------------------------------------------------------
# The whole reason this file can be trusted. Sets DROPPED to a human-readable report.
reconcile_into() {
  out_held="$1"; out_wait="$2"
  : > "$out_held"; : > "$out_wait"
  DROPPED=""
  # Path computed in the parent, content filled lazily inside the loop below. Only a row that is
  # actually about to be dropped pays for the ps+lsof, so the common path stays free.
  cwds_f="$(scratch cwds)"

  read_held | while IFS="$TAB" read -r p s w d c pid; do
    [ -n "$p" ] || continue
    lp="$(listener_pid "$p")"
    if [ -n "$lp" ]; then
      # Something is listening: the claim is live. Refresh the pid, which is unknown at claim time
      # because the claim deliberately happens BEFORE the server binds.
      printf '%s\t%s\t%s\t%s\t%s\t%s\n' "$p" "$s" "$w" "$d" "$c" "$lp" >> "$out_held"
      continue
    fi
    age="$(age_minutes "$c")"
    if [ "$age" -gt "$GRACE_MIN" ] || { [ "$pid" != "-" ] && ! pid_alive "$pid"; }; then
      # A lane belongs to the SESSION, not to the process that happened to bind it. If a live Claude
      # session is still working in that workspace, its server has merely died or not booted yet and
      # it will boot again — handing the lane to a neighbour just moves the EADDRINUSE one session
      # over. So a live session keeps its lane past the grace window. This check lives HERE rather
      # than only in `reap` because every read path reconciles, so a rule applied in one place and
      # not the other means the next `list` silently undoes what `reap` just decided.
      [ -s "$cwds_f" ] || claude_cwds > "$cwds_f" 2>/dev/null || : > "$cwds_f"
      if session_live_at "$w" "$cwds_f"; then
        printf '%s\t%s\t%s\t%s\t%s\t%s\n' "$p" "$s" "$w" "$d" "$c" "$pid" >> "$out_held"
        continue
      fi
      printf '%s\t%s\t%s\n' "$p" "$s" "$age" >> "$out_held.dropped"
      continue
    fi
    # Inside the grace window with no listener yet: a claim made just before boot. Keep it.
    printf '%s\t%s\t%s\t%s\t%s\t%s\n' "$p" "$s" "$w" "$d" "$c" "$pid" >> "$out_held"
  done

  read_wait | while IFS="$TAB" read -r p s w c; do
    [ -n "$p" ] || continue
    age="$(age_minutes "$c")"
    [ "$age" -gt $((WAIT_TTL_H * 60)) ] && continue
    printf '%s\t%s\t%s\t%s\n' "$p" "$s" "$w" "$c" >> "$out_wait"
  done

  if [ -s "$out_held.dropped" ]; then
    DROPPED="$(while IFS="$TAB" read -r p s age; do
      printf '  - port %s (claimed by %s, %s min ago) — nothing is listening, claim dropped\n' "$p" "$s" "$age"
    done < "$out_held.dropped")"
    rm -f "$out_held.dropped"
  fi
}

# --- commands -------------------------------------------------------------------------------------
cmd_reconcile() {
  acquire_lock || return 1
  h="$(scratch held)"; wq="$(scratch wait)"
  reconcile_into "$h" "$wq"
  write_file "$h" "$wq"
  if [ -n "$DROPPED" ]; then
    echo "Reconciled — stale claims removed:"
    printf '%s\n' "$DROPPED"
  else
    echo "Reconciled — no stale claims."
  fi
}

cmd_reap() {
  acquire_lock || return 1
  h="$(scratch held)"; wq="$(scratch wait)"

  # reconcile_into already honours the live-session rule and already drops a deleted workspace's rows,
  # because a workspace that no longer exists cannot have a live session in it. So reap does not
  # re-derive any of that. What it adds is the ONE case reconcile cannot resolve: a row whose workspace
  # is gone but whose server is still listening. reconcile keeps that row (correctly — the port really
  # is bound), and it would therefore look healthy forever.
  reconcile_into "$h" "$wq"
  write_file "$h" "$wq"

  orphans=""; rc=0
  while IFS="$TAB" read -r p s w d c pid; do
    [ -n "$p" ] || continue
    [ -d "$w" ] && continue
    orphans="${orphans}  - port $p — workspace '$w' is gone but pid $pid still holds it (claimed by $s)
"
    rc=5
  done < "$h"

  if [ -n "$DROPPED" ]; then
    echo "Reaped:"
    printf '%s\n' "$DROPPED"
  else
    echo "Reaped — nothing stale."
  fi
  if [ -n "$orphans" ]; then
    echo "Orphaned lanes — workspace deleted, server still up (this file never kills; the caller decides):"
    printf '%s' "$orphans"
  fi
  return $rc
}

# report_conflicts HELD_FILE PORTS... — prints conflicts, returns the exit code to use.
report_conflicts() {
  hf="$1"; shift
  rc=0
  for p in "$@"; do
    row="$(awk -v FS="$TAB" -v port="$p" '$1 == port { print; exit }' "$hf")"
    if [ -n "$row" ]; then
      owner="$(printf '%s' "$row" | cut -f2)"
      if [ "$owner" != "$SESSION" ]; then
        ws="$(printf '%s' "$row" | cut -f3)"
        what="$(printf '%s' "$row" | cut -f4)"
        since="$(printf '%s' "$row" | cut -f5)"
        echo "port $p is HELD by session '$owner' ($what) since $since"
        echo "   workspace: $ws"
        echo "   Tell the user who holds it, run: $0 wait $p — then stop. Do not kill their server."
        rc=3
      fi
      continue
    fi
    lp="$(listener_pid "$p")"
    if [ -n "$lp" ]; then
      echo "port $p has a LISTENER that no session claimed: $(listener_desc "$p")"
      echo "   cwd: $(cwd_for_pid "$lp")"
      echo "   Report this to the user before doing anything with it; it may be their own server."
      [ "$rc" -eq 0 ] && rc=4
    fi
  done
  return $rc
}

cmd_claim() {
  what=""
  ports=""
  while [ $# -gt 0 ]; do
    case "$1" in
      --for) shift; what="${1:-}" ;;
      --for=*) what="${1#--for=}" ;;
      -*) echo "port-registry: unknown flag $1" >&2; return 2 ;;
      *) is_port "$1" || { echo "port-registry: not a port: $1" >&2; return 2; }
         ports="$ports $1" ;;
    esac
    shift
  done
  [ -n "$ports" ] || { echo "port-registry: claim needs at least one port" >&2; return 2; }
  [ -n "$what" ] || what="unspecified"

  acquire_lock || return 1
  h="$(scratch held)"; wq="$(scratch wait)"
  reconcile_into "$h" "$wq"

  # shellcheck disable=SC2086 # ports is a deliberately space-separated list
  # Capture directly, never via `! cmd` — after a negation $? is 0/1 and the 3-vs-4 distinction
  # (held by a session / listener nobody claimed) is lost, which is the whole point of the codes.
  report_conflicts "$h" $ports
  rc=$?
  if [ "$rc" -ne 0 ]; then
    write_file "$h" "$wq"   # persist the reconcile even on refusal, so the file stays honest
    return "$rc"
  fi

  ts="$(now_utc)"
  swhat="$(sanitize "$what")"
  sws="$(sanitize "$WORKSPACE")"
  ssess="$(sanitize "$SESSION")"
  for p in $ports; do
    # Re-claiming my own port refreshes it rather than duplicating the row.
    awk -v FS="$TAB" -v OFS="$TAB" -v port="$p" '$1 != port' "$h" > "$h.new" && mv "$h.new" "$h"
    lp="$(listener_pid "$p")"
    [ -n "$lp" ] || lp="-"   # claiming happens BEFORE the bind, so no listener yet is the normal case
    printf '%s\t%s\t%s\t%s\t%s\t%s\n' "$p" "$ssess" "$sws" "$swhat" "$ts" "$lp" >> "$h"
    # Claiming clears my own waiting row for that port.
    awk -v FS="$TAB" -v port="$p" -v me="$ssess" '!($1 == port && $2 == me)' "$wq" > "$wq.new" && mv "$wq.new" "$wq"
  done
  write_file "$h" "$wq"
  echo "Claimed:$ports  (session '$SESSION', for: $what)"
  echo "Release them the moment you kill the process: $0 release$ports"
}

cmd_release() {
  for p in "$@"; do
    is_port "$p" || { echo "port-registry: not a port: $p" >&2; return 2; }
  done
  acquire_lock || return 1
  h="$(scratch held)"; wq="$(scratch wait)"

  # Which ports did I hold BEFORE reconciling? Load-bearing: a row is reaped as soon as its recorded
  # pid dies, and the correct sequence is kill-the-process-THEN-release — so by the time release runs
  # the row is normally already gone. Reading the raw rows first is what stops the waiting hand-off
  # being lost in the ordinary path, which is the entire reason the waiting list exists.
  mine_before="$(read_held | awk -v FS="$TAB" -v me="$SESSION" '$2 == me { printf " %s", $1 }')"

  reconcile_into "$h" "$wq"

  released=""
  for p in $mine_before; do
    if [ $# -eq 0 ]; then
      released="$released $p"
    else
      for q in "$@"; do
        [ "$p" = "$q" ] && released="$released $p"
      done
    fi
  done

  for p in $released; do
    awk -v FS="$TAB" -v port="$p" -v me="$SESSION" '!($1 == port && $2 == me)' "$h" > "$h.new" && mv "$h.new" "$h"
    awk -v FS="$TAB" -v port="$p" -v me="$SESSION" '!($1 == port && $2 == me)' "$wq" > "$wq.new" && mv "$wq.new" "$wq"
  done
  write_file "$h" "$wq"

  if [ -z "$released" ]; then
    echo "Nothing to release for session '$SESSION'."
    return 0
  fi
  echo "Released:$released"
  for p in $released; do
    # Releasing a port you are still bound to hands it to someone else while your server is up.
    lp="$(listener_pid "$p")"
    [ -n "$lp" ] && echo "  WARNING: port $p still has a listener (pid $lp) — kill the process, it is not actually free."
    # The hand-off: the releasing session is the only one that knows the port just came free.
    awk -v FS="$TAB" -v port="$p" '$1 == port {
      printf "  Session %s (%s) was WAITING on port %s since %s — tell the user it is now free.\n", $2, $3, $1, $4
    }' "$wq"
  done
}

cmd_check() {
  [ $# -gt 0 ] || { echo "port-registry: check needs at least one port" >&2; return 2; }
  for p in "$@"; do is_port "$p" || { echo "port-registry: not a port: $p" >&2; return 2; }; done
  acquire_lock || return 1
  h="$(scratch held)"; wq="$(scratch wait)"
  reconcile_into "$h" "$wq"
  write_file "$h" "$wq"
  report_conflicts "$h" "$@"
  rc=$?
  if [ "$rc" -eq 0 ]; then
    echo "Free for session '$SESSION':$(for p in "$@"; do printf ' %s' "$p"; done)"
  fi
  return "$rc"
}

cmd_wait() {
  [ $# -gt 0 ] || { echo "port-registry: wait needs at least one port" >&2; return 2; }
  acquire_lock || return 1
  h="$(scratch held)"; wq="$(scratch wait)"
  reconcile_into "$h" "$wq"
  ts="$(now_utc)"
  for p in "$@"; do
    is_port "$p" || { echo "port-registry: not a port: $p" >&2; return 2; }
    awk -v FS="$TAB" -v port="$p" -v me="$SESSION" '!($1 == port && $2 == me)' "$wq" > "$wq.new" && mv "$wq.new" "$wq"
    printf '%s\t%s\t%s\t%s\n' "$p" "$(sanitize "$SESSION")" "$(sanitize "$WORKSPACE")" "$ts" >> "$wq"
  done
  write_file "$h" "$wq"
  echo "Waiting recorded for session '$SESSION' on:$(for p in "$@"; do printf ' %s' "$p"; done)"
  echo "The holding session will surface this when it releases. Ask the user before taking any other action."
}

cmd_unwait() {
  acquire_lock || return 1
  h="$(scratch held)"; wq="$(scratch wait)"
  reconcile_into "$h" "$wq"
  if [ $# -eq 0 ]; then
    awk -v FS="$TAB" -v me="$SESSION" '$2 != me' "$wq" > "$wq.new" && mv "$wq.new" "$wq"
  else
    for p in "$@"; do
      awk -v FS="$TAB" -v port="$p" -v me="$SESSION" '!($1 == port && $2 == me)' "$wq" > "$wq.new" && mv "$wq.new" "$wq"
    done
  fi
  write_file "$h" "$wq"
  echo "Waiting rows cleared for session '$SESSION'."
}

cmd_list() {
  tsv=0
  [ "${1:-}" = "--tsv" ] && tsv=1
  acquire_lock || return 1
  h="$(scratch held)"; wq="$(scratch wait)"
  reconcile_into "$h" "$wq"
  write_file "$h" "$wq"
  # --tsv exists so a caller can act on rows without parsing the human table or re-implementing
  # read_held. Columns: port, session, workspace, what, claimed, pid.
  if [ "$tsv" -eq 1 ]; then
    [ -s "$h" ] && sort -n -k1,1 "$h"
    return 0
  fi
  if [ ! -s "$h" ] && [ ! -s "$wq" ]; then
    echo "No ports claimed. (registry: $REGISTRY)"
    return 0
  fi
  if [ -s "$h" ]; then
    echo "Held:"
    sort -n -k1,1 "$h" | while IFS="$TAB" read -r p s w d c pid; do
      mine=""; [ "$s" = "$SESSION" ] && mine="  <- this session"
      printf '  %-6s %-16s %-28s %s  (since %s, pid %s)%s\n' "$p" "$s" "$d" "$w" "$c" "$pid" "$mine"
    done
  fi
  if [ -s "$wq" ]; then
    echo "Waiting:"
    sort -n -k1,1 "$wq" | while IFS="$TAB" read -r p s w c; do
      printf '  %-6s %-16s %s  (since %s)\n' "$p" "$s" "$w" "$c"
    done
  fi
  [ -n "$DROPPED" ] && { echo "Stale claims removed:"; printf '%s\n' "$DROPPED"; }
  return 0
}

cmd_whoami() {
  echo "session:   $SESSION"
  echo "workspace: $WORKSPACE"
  echo "registry:  $REGISTRY"
  echo "grace:     ${GRACE_MIN}m before a listener-less claim is reaped"
}

usage() {
  sed -n '/^# Usage:/,/^# Env:/p' "$0" | sed 's/^# \{0,1\}//'
}

main() {
  cmd="${1:-}"
  [ $# -gt 0 ] && shift
  case "$cmd" in
    claim) cmd_claim "$@" ;;
    release) cmd_release "$@" ;;
    check) cmd_check "$@" ;;
    list | "") cmd_list "$@" ;;
    wait) cmd_wait "$@" ;;
    unwait) cmd_unwait "$@" ;;
    reconcile) cmd_reconcile ;;
    reap) cmd_reap ;;
    whoami) cmd_whoami ;;
    --help | -h | help) usage ;;
    *) usage >&2; exit 2 ;;
  esac
}

main "$@"
