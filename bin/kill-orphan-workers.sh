#!/usr/bin/env bash
# kill-orphan-workers.sh
#
# Detects and clears orphaned framework dev-tool worker processes machine-wide (not scoped to
# this session or this workspace). The lesson this encodes: a dead `next dev` / `turbo dev` /
# `jest` / `vite` run can leave `next-router-worker` / `next-render-worker-pages` / `jest-worker`
# children behind that reparent to PID 1 and pin a CPU core indefinitely — sometimes for hours,
# in a workspace nobody is currently looking at.
#
# This is the ONLY thing in this config that kills these processes. The SessionStart hook
# `hooks/orphan-worker-sweep.sh` only ever REPORTS candidates (calls this script with --list) and
# never signals anything — see that file's header for why.
#
# Detection — a process must satisfy ALL THREE:
#   (a) PPID == 1                      — its parent died and it reparented to launchd/init.
#   (b) interpreter or dev-tool match  — comm/args names node, bun, deno, python*, ruby*, or
#                                         contains -worker, vite, esbuild, tsc, nodemon, webpack,
#                                         rollup, jest, turbo.
#   (c) cwd resolves inside a git working tree — the false-positive guard. Real daemons and
#       LaunchAgents never run with a cwd inside a source checkout.
# (c) is the expensive check (one `lsof` per candidate), so it only ever runs on processes that
# already passed (a) and (b) — that set is normally empty, so a clean machine costs one `ps` call.
#
# Kill sequence (the reason this script exists instead of a bare `pkill`):
#   1. Collect the full process family (each root candidate + ALL its descendants, recursively via
#      `pgrep -P`) BEFORE signalling anything — a child's ppid changes the instant its parent dies,
#      so the tree has to be captured while it's still intact.
#   2. SIGTERM every pid in every family directly (not just the roots).
#   3. Wait ~2s.
#   4. RE-SCAN: a family member can survive SIGTERM (trapped/ignored/uninterruptible), and if only
#      the root died, its live children just became freshly-orphaned PPID-1 processes of their own
#      — re-running the SAME detector catches those in addition to plain liveness-checking the
#      original family. This step is the fix for the incident that motivated this script: SIGTERM
#      to a parent alone left `next-render-worker-pages` children alive and reparented to PID 1.
#   5. SIGKILL whatever is still alive. Verify. Report what was killed and what (if anything)
#      survived.
#
# Safety invariant: every pid this script ever signals is either a PPID==1 root (verified to have
# no live parent at all) or a descendant reachable ONLY through such a root's own process tree —
# so nothing it touches can have a live dev-server ancestor. That is the "never kill a worker with
# a live parent" guard; it holds by construction, not by an extra check.
#
# Usage:
#   kill-orphan-workers.sh            # detect + kill (the default; this is the point of the script)
#   kill-orphan-workers.sh --dry-run  # detect + print the family that would be killed; kill nothing
#   kill-orphan-workers.sh --list     # detect only, print raw candidate rows (used by the SessionStart hook)
#   kill-orphan-workers.sh --help
# -f (noglob) is deliberate and load-bearing: this script repeatedly word-splits unquoted
# variables built from `ps`/`pgrep` output (pids, and once a raw command line) for portability
# with bash 3.2 (macOS's system bash has no arrays worth relying on for this). Without -f, a
# command line containing a literal `*` would get glob-expanded against the script's cwd.
set -uf
shopt -s nocasematch # macOS's homebrew python3 re-execs into a framework binary literally named
                      # "Python" (capital P) — match case-insensitively so that isn't missed.

INTERP_RE='^(node|bun|deno|python.*|ruby.*)$'
KEYWORD_RE='(-worker|vite|esbuild|tsc|nodemon|webpack|rollup|jest|turbo)'

usage() {
  printf '%s\n' \
    "Usage: $(basename "$0") [--dry-run|--list|--help]" \
    "  (no flag)   detect orphaned framework worker processes machine-wide and kill them" \
    "  --dry-run   detect and print what would be killed; kill nothing" \
    "  --list      detect only, print raw candidate rows (pid/ppid/cpu/etime/cwd/args, tab-separated)" \
    "  --help      show this message"
}

# cwd_for_pid PID — resolved cwd via lsof, or empty if unavailable.
cwd_for_pid() {
  lsof -a -p "$1" -d cwd -Fn 2>/dev/null | awk '/^n/ { print substr($0, 2); exit }'
}

# family_is_serving PID — true if PID or any descendant holds a LISTENING socket.
#
# PPID==1 proves nobody is SUPERVISING the process. It does not prove the process is DEAD, and
# those are different claims. A dev server started detached (`nohup`, `&` from a shell that then
# exited, a task runner that daemonizes) is reparented to launchd exactly like a crashed worker,
# so the PPID test alone cannot tell "abandoned and spinning" from "alive and serving another
# session". Both look identical in `ps`.
#
# Serving traffic is the difference, and it is the one signal that cannot be faked by an orphan: a
# dead worker's listener is closed by the kernel when its owner dies, so a live LISTEN socket means
# something in that family is still doing its job. CPU is NOT usable here — an idle live server
# sits at 0% and a spinning orphan at 100%, but a freshly-crashed one is also near 0%.
#
# The check that stopped this script killing a colleague's running dev server on another port: a
# `yarn … dev --port 3040` family, PPID 1, 0% CPU, whose grandchild was LISTENING. `--dry-run`
# showed all five pids queued for SIGTERM.
# Two thresholds, because PPID==1 alone cannot tell a dead worker from a live detached server.
#
# A LISTEN socket looked like the answer and is NOT: an orphaned `next-router-worker` holds its own
# internal IPC ports (observed on *:64359 and *:64362 while its dev server was long gone), so
# "holds a listener" is true of exactly the thing this script exists to kill. Testing it suppressed
# the entire sweep while a worker burned 27% of a core.
#
# What actually separates them is the harm itself, which is also this script's whole mission: a
# core being burned. An idle live server sits near 0% and costs nothing, so leaving it alone is
# both safe and correct. A worker spinning on a dead IPC channel sits high and never comes down.
#
# ELAPSED guards the other direction. A dev server that has just started, or is mid-compile, is
# legitimately busy, so a young process is never a candidate however hot it is. The live server
# this pair was written to protect was 0.0% at 53 seconds old; the orphan it must catch was 25%
# at 23 minutes.
MIN_ORPHAN_CPU=20        # percent, sustained
MIN_ORPHAN_SECONDS=300   # 5 minutes

# etime_seconds ETIME — ps elapsed ([dd-]hh:mm:ss | mm:ss) to seconds.
etime_seconds() {
  echo "$1" | awk -F'[-:]' '{
    if (NF==4) print (($1*24+$2)*60+$3)*60+$4;
    else if (NF==3) print (($1*60)+$2)*60+$3;
    else if (NF==2) print ($1*60)+$2;
    else print 0
  }'
}

# in_git_worktree DIR — true if DIR or any ancestor contains a .git entry.
in_git_worktree() {
  dir="$1"
  while [ -n "$dir" ] && [ "$dir" != "/" ]; do
    [ -e "$dir/.git" ] && return 0
    dir="$(dirname "$dir")"
  done
  return 1
}

# detect_candidates — the single source of truth for detection. Emits one tab-separated row per
# candidate: pid, ppid, %cpu, elapsed, cwd, full command line.
detect_candidates() {
  ps -Awwo pid=,ppid=,pcpu=,etime=,args= 2>/dev/null | while IFS= read -r line; do
    # shellcheck disable=SC2086 # deliberate word-splitting to peel off the four numeric fields
    set -- $line
    pid="$1"; ppid="$2"; pcpu="$3"; etime="$4"
    shift 4
    args="$*"
    [ -n "$pid" ] || continue
    [ "$ppid" = "1" ] || continue

    first_token="${args%% *}"
    base="${first_token##*/}"

    is_match=1
    [[ "$base" =~ $INTERP_RE ]] && is_match=0
    if [ "$is_match" -ne 0 ]; then
      echo "$args" | grep -Eq -- "$KEYWORD_RE" && is_match=0
    fi
    [ "$is_match" -eq 0 ] || continue

    cwd="$(cwd_for_pid "$pid")"
    [ -n "$cwd" ] || continue
    in_git_worktree "$cwd" || continue

    # Both thresholds, and both cheap, so they run before nothing. See MIN_ORPHAN_CPU for why
    # PPID==1 alone is not evidence of death and why a LISTEN socket is not either.
    awk -v c="$pcpu" -v m="$MIN_ORPHAN_CPU" 'BEGIN{exit !(c+0 >= m+0)}' || continue
    [ "$(etime_seconds "$etime")" -ge "$MIN_ORPHAN_SECONDS" ] || continue

    printf '%s\t%s\t%s\t%s\t%s\t%s\n' "$pid" "$ppid" "$pcpu" "$etime" "$cwd" "$args"
  done
}

# collect_descendants PID — prints PID and every descendant (recursive, space-separated, deduped).
collect_descendants() {
  root="$1"
  all=" $root "
  queue="$root"
  while [ -n "$queue" ]; do
    next=""
    for p in $queue; do
      kids="$(pgrep -P "$p" 2>/dev/null)"
      for k in $kids; do
        case "$all" in
          *" $k "*) ;;
          *)
            all="$all$k "
            next="$next $k"
            ;;
        esac
      done
    done
    queue="$next"
  done
  printf '%s\n' "$all"
}

pid_alive() {
  kill -0 "$1" 2>/dev/null
}

do_list() {
  detect_candidates
}

do_dry_run() {
  rows="$(detect_candidates)"
  if [ -z "$rows" ]; then
    echo "No orphaned worker processes found."
    return 0
  fi
  echo "Would terminate the following process families (dry run — nothing was killed):"
  echo
  all_pids=""
  while IFS="$(printf '\t')" read -r pid ppid pcpu etime cwd args; do
    [ -n "$pid" ] || continue
    printf 'root pid %s  %%cpu=%s  elapsed=%s  cwd=%s\n  %s\n' "$pid" "$pcpu" "$etime" "$cwd" "$args"
    family="$(collect_descendants "$pid")"
    all_pids="$all_pids $family"
    printf '  family: %s\n' "$family"
  done <<EOF
$rows
EOF
  echo
  # shellcheck disable=SC2086 # all_pids is a deliberately space-separated pid list
  echo "Total pids that would be signalled: $(printf '%s\n' $all_pids | sort -u | tr '\n' ' ')"
}

do_kill() {
  rows="$(detect_candidates)"
  if [ -z "$rows" ]; then
    echo "No orphaned worker processes found."
    return 0
  fi

  all_pids=""
  echo "Orphaned worker process(es) found:"
  while IFS="$(printf '\t')" read -r pid ppid pcpu etime cwd args; do
    [ -n "$pid" ] || continue
    printf '  pid %s  %%cpu=%s  elapsed=%s  cwd=%s\n    %s\n' "$pid" "$pcpu" "$etime" "$cwd" "$args"
    family="$(collect_descendants "$pid")"
    all_pids="$all_pids $family"
  done <<EOF
$rows
EOF
  # shellcheck disable=SC2086 # all_pids is a deliberately space-separated pid list
  all_pids="$(printf '%s\n' $all_pids | sort -un | tr '\n' ' ')"

  echo
  echo "Step 1/5: family collected: $all_pids"
  echo "Step 2/5: sending SIGTERM to the whole family..."
  for p in $all_pids; do
    kill -TERM "$p" 2>/dev/null
  done

  echo "Step 3/5: waiting ~2s..."
  sleep 2

  echo "Step 4/5: re-scanning for survivors (including newly re-orphaned descendants)..."
  survivors=""
  for p in $all_pids; do
    pid_alive "$p" && survivors="$survivors $p"
  done
  rescan_pids="$(detect_candidates | cut -f1)"
  for p in $rescan_pids; do
    case " $survivors " in
      *" $p "*) ;;
      *) pid_alive "$p" && survivors="$survivors $p" ;;
    esac
  done

  if [ -n "$survivors" ]; then
    echo "  survivors after SIGTERM: $survivors — escalating to SIGKILL"
    for p in $survivors; do
      kill -9 "$p" 2>/dev/null
    done
    sleep 1
  else
    echo "  none — SIGTERM was sufficient"
  fi

  echo "Step 5/5: verifying..."
  remaining=""
  # shellcheck disable=SC2086 # deliberately re-joining two space-separated pid lists for a uniqued check
  for p in $(printf '%s %s\n' "$all_pids" "$survivors" | tr ' ' '\n' | sort -un); do
    [ -n "$p" ] || continue
    pid_alive "$p" && remaining="$remaining $p"
  done

  if [ -n "$remaining" ]; then
    echo "WARNING: still alive after SIGKILL: $remaining"
    return 1
  fi
  echo "Done. Killed: $all_pids"
  [ -n "$survivors" ] && echo "(escalated to SIGKILL: $survivors)"
  return 0
}

main() {
  case "${1:-}" in
    --list) do_list ;;
    --dry-run) do_dry_run ;;
    --help | -h) usage ;;
    "") do_kill ;;
    *)
      usage >&2
      exit 2
      ;;
  esac
}

main "$@"
