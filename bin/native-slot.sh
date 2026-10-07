#!/usr/bin/env bash
# native-slot.sh
# Machine-wide coordination of NATIVE work (a simulator or emulator, xcodebuild, Gradle) between
# Claude sessions that cannot see each other. bin/port-registry.sh does this for ports; this does it
# for the one resource ports do not cover: a native build or simulator test run is CPU-bound for the
# whole machine, and N of them at once stall every session instead of running in parallel.
#
# Two records, both under $NATIVE_SLOT_DIR (default ~/.claude/native-slot):
#   slot.d/      the ONE native slot. Whoever made the directory holds it. slot.d/holder names them.
#   sims.tsv     the simulator ledger: which session registered which device.
#
# Usage:
#   native-slot.sh run --for "<what>" [--udid <id>] [--wait-min N] -- <command...>
#       Take the slot, run the command, release on exit. Waits while another LIVE holder has it
#       (default 60 minutes), printing who holds it. Exits with the command's own status.
#       Exit 3 = still held by another live session when the wait ran out. Nothing was run.
#   native-slot.sh list
#       The holder, every registered simulator, and booted simulators nobody registered.
#   native-slot.sh claim-sim <udid> [--for "<what>"]     record that this session owns a simulator
#   native-slot.sh release-sim <udid>                    drop this session's row for it
#   native-slot.sh jobs                                  a job count that leaves the machine usable
#   native-slot.sh whoami                                the session label this script would record
#
# What it never does: kill a process, shut down or delete a simulator, or release a slot another
# live session holds. A holder whose process is gone is not live, so its slot is taken over.
#
# Env: CLAUDE_NATIVE_SESSION  override the session label (default: the worktree directory name)
#      NATIVE_SLOT_DIR        where the records live (tests point this at a temp directory)
#      NATIVE_SLOT_POLL_SEC   seconds between checks while waiting (default 10)
#      NATIVE_SLOT_SIMCTL_SEC seconds `list` gives simctl to answer (default 10)
set -u

DIR="${NATIVE_SLOT_DIR:-$HOME/.claude/native-slot}"
SLOT="$DIR/slot.d"
SIMS="$DIR/sims.tsv"
SIMS_LOCK="$DIR/sims.lock.d"
POLL="${NATIVE_SLOT_POLL_SEC:-10}"
SIMCTL_SEC="${NATIVE_SLOT_SIMCTL_SEC:-10}"
TAB="$(printf '\t')"

die() { printf 'native-slot: %s\n' "$*" >&2; exit 2; }

workspace() {
  local top
  top="$(git rev-parse --show-toplevel 2>/dev/null)" || top="$PWD"
  printf '%s' "$top"
}

session() {
  if [ -n "${CLAUDE_NATIVE_SESSION:-}" ]; then printf '%s' "$CLAUDE_NATIVE_SESSION"; return; fi
  basename "$(workspace)"
}

alive() { [ -n "${1:-}" ] && kill -0 "$1" 2>/dev/null; }

holder_field() { # $1 = field number in slot.d/holder
  [ -f "$SLOT/holder" ] || return 1
  cut -f"$1" "$SLOT/holder" 2>/dev/null
}

describe_holder() {
  local pid who where since what udid age
  pid="$(holder_field 1)"; who="$(holder_field 2)"; where="$(holder_field 3)"
  since="$(holder_field 4)"; what="$(holder_field 5)"; udid="$(holder_field 6)"
  age=$(( ( $(date +%s) - ${since:-$(date +%s)} ) / 60 ))
  printf '%s  %s  (pid %s, %s min, %s%s)' "${who:-?}" "${what:-?}" "${pid:-?}" "$age" "${where:-?}" \
    "${udid:+, simulator $udid}"
}

# Drop a slot whose holder process is gone. A holder file that is not written yet is given a short
# grace, because the directory is made before the file.
reap_stale_slot() {
  [ -d "$SLOT" ] || return 0
  local pid
  pid="$(holder_field 1)"
  if [ -z "$pid" ]; then
    sleep 1
    pid="$(holder_field 1)"
    [ -n "$pid" ] || { rm -rf "$SLOT"; return 0; }
  fi
  alive "$pid" || rm -rf "$SLOT"
}

take_slot() { # $1 = what, $2 = udid
  mkdir -p "$DIR" || die "cannot create $DIR"
  reap_stale_slot
  mkdir "$SLOT" 2>/dev/null || return 1
  printf '%s\t%s\t%s\t%s\t%s\t%s\n' "$$" "$(session)" "$(workspace)" "$(date +%s)" "$1" "$2" \
    > "$SLOT/holder"
  return 0
}

release_slot() {
  [ "$(holder_field 1)" = "$$" ] && rm -rf "$SLOT"
}

cmd_run() {
  local what="" udid="" wait_min=60
  while [ $# -gt 0 ]; do
    case "$1" in
      --for) what="${2:-}"; shift 2 ;;
      --udid) udid="${2:-}"; shift 2 ;;
      --wait-min) wait_min="${2:-}"; shift 2 ;;
      --) shift; break ;;
      *) die "run: unknown option $1" ;;
    esac
  done
  [ -n "$what" ] || die 'run: --for "<what>" is required'
  [ $# -gt 0 ] || die "run: no command after --"
  case "$wait_min" in ''|*[!0-9]*) die "run: --wait-min takes whole minutes" ;; esac

  local deadline=$(( $(date +%s) + wait_min * 60 )) told=0
  until take_slot "$what" "$udid"; do
    if [ "$(date +%s)" -ge "$deadline" ]; then
      printf 'native-slot: still held after %s min: %s\n' "$wait_min" "$(describe_holder)" >&2
      exit 3
    fi
    if [ $(( $(date +%s) - told )) -ge 60 ]; then
      printf 'native-slot: waiting for %s\n' "$(describe_holder)" >&2
      told="$(date +%s)"
    fi
    sleep "$POLL"
  done
  # EXIT only: a trap on EXIT INT TERM runs twice, per references/dev-server-hygiene.md.
  trap release_slot EXIT
  "$@"
  local status=$?
  release_slot
  trap - EXIT
  exit "$status"
}

sims_lock() {
  local n=0
  mkdir -p "$DIR" || die "cannot create $DIR"
  until mkdir "$SIMS_LOCK" 2>/dev/null; do
    n=$((n + 1))
    [ "$n" -gt 50 ] && { rm -rf "$SIMS_LOCK"; n=0; }   # a lock held for 5 s is a dead writer
    sleep 0.1
  done
}
sims_unlock() { rm -rf "$SIMS_LOCK"; }

# Rows whose workspace is gone belong to a session that ended without releasing.
sims_reconcile() {
  [ -f "$SIMS" ] || return 0
  local tmp="$SIMS.tmp.$$" udid who where since what
  : > "$tmp"
  while IFS="$TAB" read -r udid who where since what; do
    [ -n "$udid" ] || continue
    [ -d "$where" ] && printf '%s\t%s\t%s\t%s\t%s\n' "$udid" "$who" "$where" "$since" "$what" >> "$tmp"
  done < "$SIMS"
  mv "$tmp" "$SIMS"
}

cmd_claim_sim() {
  local udid="${1:-}" what=""
  [ -n "$udid" ] || die "claim-sim: a simulator id is required"
  shift
  [ "${1:-}" = "--for" ] && what="${2:-}"
  sims_lock
  sims_reconcile
  local owner
  owner="$(awk -F"$TAB" -v u="$udid" '$1 == u { print $2 }' "$SIMS" 2>/dev/null | head -1)"
  if [ -n "$owner" ] && [ "$owner" != "$(session)" ]; then
    sims_unlock
    printf 'native-slot: simulator %s is registered to session %s\n' "$udid" "$owner" >&2
    exit 3
  fi
  if [ -z "$owner" ]; then
    printf '%s\t%s\t%s\t%s\t%s\n' "$udid" "$(session)" "$(workspace)" "$(date +%s)" "$what" >> "$SIMS"
  fi
  sims_unlock
  printf 'Registered: %s  (session %s)\n' "$udid" "$(session)"
}

cmd_release_sim() {
  local udid="${1:-}" me tmp
  [ -n "$udid" ] || die "release-sim: a simulator id is required"
  me="$(session)"
  sims_lock
  if [ -f "$SIMS" ]; then
    tmp="$SIMS.tmp.$$"
    awk -F"$TAB" -v u="$udid" -v s="$me" '!($1 == u && $2 == s)' "$SIMS" > "$tmp" && mv "$tmp" "$SIMS"
  fi
  sims_unlock
  printf 'Released: %s\n' "$udid"
}

# simctl can hang on a loaded machine, so it gets a bounded wait and no more.
booted_sims() {
  command -v xcrun >/dev/null 2>&1 || return 0
  local out="$DIR/booted.$$" pid n=0
  ( xcrun simctl list devices booted 2>/dev/null > "$out" ) &
  pid=$!
  while alive "$pid" && [ "$n" -lt $(( SIMCTL_SEC * 10 )) ]; do sleep 0.1; n=$((n + 1)); done
  if alive "$pid"; then
    kill "$pid" 2>/dev/null
    rm -f "$out"
    printf 'UNKNOWN\tsimctl did not answer in %s s\n' "$SIMCTL_SEC"
    return 0
  fi
  sed -n 's/^ *\(.*\) (\([0-9A-F-]\{36\}\)) (Booted).*$/\2\t\1/p' "$out"
  rm -f "$out"
}

cmd_list() {
  mkdir -p "$DIR" 2>/dev/null
  reap_stale_slot
  if [ -d "$SLOT" ]; then
    printf 'Native slot held: %s\n' "$(describe_holder)"
  else
    printf 'Native slot free.\n'
  fi
  sims_lock; sims_reconcile; sims_unlock
  local booted udid name who where since what state shown=""
  booted="$(booted_sims)"
  if [ -s "$SIMS" ]; then
    printf 'Registered simulators:\n'
    while IFS="$TAB" read -r udid who where since what; do
      state="shut down"
      printf '%s\n' "$booted" | grep -q "^$udid$TAB" && state="BOOTED"
      printf '  %s  %-10s %s  %s\n' "$udid" "$state" "$who" "${what:-}"
      shown="$shown $udid"
    done < "$SIMS"
  fi
  printf '%s\n' "$booted" | while IFS="$TAB" read -r udid name; do
    [ -n "$udid" ] || continue
    case " $shown " in *" $udid "*) continue ;; esac
    if [ "$udid" = "UNKNOWN" ]; then
      printf 'Booted simulators: %s\n' "$name"
    else
      printf 'Booted, registered to nobody: %s  %s\n' "$udid" "$name"
    fi
  done
}

cmd_jobs() {
  local cores
  cores="$(sysctl -n hw.ncpu 2>/dev/null || getconf _NPROCESSORS_ONLN 2>/dev/null || echo 4)"
  local half=$(( cores / 2 ))
  [ "$half" -lt 2 ] && half=2
  printf '%s\n' "$half"
}

case "${1:-}" in
  run) shift; cmd_run "$@" ;;
  list) cmd_list ;;
  claim-sim) shift; cmd_claim_sim "$@" ;;
  release-sim) shift; cmd_release_sim "$@" ;;
  jobs) cmd_jobs ;;
  whoami) printf 'session: %s\nworkspace: %s\n' "$(session)" "$(workspace)" ;;
  *) die "usage: native-slot.sh run|list|claim-sim|release-sim|jobs|whoami (see the header)" ;;
esac
