#!/usr/bin/env bash
# Compatibility CLI for the single machine-wide local-capacity engine.
set -u

HERE="$(cd "$(dirname "$0")" && pwd)"
ENGINE="$HERE/local-capacity.py"
export LOCAL_CAPACITY_LEGACY_SLOT_DIR="${NATIVE_SLOT_DIR:-$HOME/.claude/native-slot}"
ROOT=()
[ -z "${LOCAL_CAPACITY_ROOT:-}" ] || ROOT=(--root "$LOCAL_CAPACITY_ROOT")

die() { printf 'native-slot: %s\n' "$*" >&2; exit 2; }
workspace() { git rev-parse --show-toplevel 2>/dev/null || pwd; }
session() {
  if [ -n "${CLAUDE_NATIVE_SESSION:-}" ]; then printf '%s' "$CLAUDE_NATIVE_SESSION"; return; fi
  basename "$(workspace)"
}
engine() { python3 "$ENGINE" "${ROOT[@]}" "$@"; }

case "${1:-}" in
  run)
    shift
    what=""; udid=""; max_min=60; wait_min=0
    while [ "$#" -gt 0 ]; do
      case "$1" in
        --for) [ "$#" -ge 2 ] || die '--for needs a label'; what="$2"; shift 2 ;;
        --udid) [ "$#" -ge 2 ] || die '--udid needs a UUID'; udid="$2"; shift 2 ;;
        --max-min) [ "$#" -ge 2 ] || die '--max-min needs minutes'; max_min="$2"; shift 2 ;;
        --wait-min) [ "$#" -ge 2 ] || die '--wait-min needs minutes'; wait_min="$2"; shift 2 ;;
        --) shift; break ;;
        *) die "unknown run option $1" ;;
      esac
    done
    [ -n "$what" ] || die 'run needs --for LABEL'
    [ "$#" -gt 0 ] || die 'run needs a foreground command after --'
    [ "$wait_min" = 0 ] || { printf 'native-slot: automatic waiting is retired; retry at a task boundary after exit 75\n' >&2; exit 75; }
    if [ -n "$udid" ]; then
      engine run --owner "$(session)" --simulator "$udid" --max-min "$max_min" -- "$@"
    else
      engine run --owner "$(session)" --max-min "$max_min" -- "$@"
    fi
    ;;
  list|status) engine status ;;
  claim-sim)
    shift
    [ "$#" -gt 0 ] || die 'claim-sim needs a UUID'
    udid="$1"; shift
    if [ "$#" -gt 0 ]; then
      [ "$#" -eq 2 ] && [ "$1" = --for ] || die 'claim-sim accepts only --for LABEL'
    fi
    engine claim-sim --udid "$udid" --owner "$(session)"
    ;;
  release-sim)
    shift
    [ "$#" -eq 1 ] || die 'release-sim needs a UUID'
    engine release-sim --udid "$1" --owner "$(session)"
    ;;
  jobs)
    cores="$(sysctl -n hw.ncpu 2>/dev/null || getconf _NPROCESSORS_ONLN 2>/dev/null || echo 2)"
    jobs=$(( cores / 2 )); [ "$jobs" -ge 1 ] || jobs=1
    [ "$jobs" -le 4 ] || jobs=4
    printf '%s\n' "$jobs"
    ;;
  whoami) printf 'session: %s\nworkspace: %s\n' "$(session)" "$(workspace)" ;;
  *) die 'usage: native-slot.sh run|list|claim-sim|release-sim|jobs|whoami' ;;
esac
