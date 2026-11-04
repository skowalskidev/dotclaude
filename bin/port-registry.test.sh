#!/usr/bin/env bash
# Offline tests for port-registry.sh reconcile. Uses a temporary registry file and ports that nothing
# listens on; touches no real claim and starts no server.
set -u
HERE="$(cd "$(dirname "$0")" && pwd)"
PR="$HERE/port-registry.sh"
TMP="$(mktemp -d)"
TMP="$(cd "$TMP" && pwd -P)"
export PORT_REGISTRY_FILE="$TMP/registry.md"
FAILS=0
trap 'rm -rf "$TMP"' EXIT
check() {
  if [ "$2" = "$3" ]; then printf 'ok   %s\n' "$1"; else
    printf 'FAIL %s: expected [%s], got [%s]\n' "$1" "$2" "$3"; FAILS=$((FAILS + 1)); fi
}

# seed PORT SESSION WORKSPACE CLAIMED_UTC — write one Held row into an otherwise empty registry.
seed() {
  printf '## Held\n\n| Port | Session | Workspace | What | Claimed (UTC) | PID |\n| --- | --- | --- | --- | --- | --- |\n' > "$PORT_REGISTRY_FILE"
  while [ "$#" -ge 4 ]; do
    printf '| %s | %s | %s | web | %s | - |\n' "$1" "$2" "$3" "$4" >> "$PORT_REGISTRY_FILE"
    shift 4
  done
  printf '\n## Waiting\n\n| Port | Session | Workspace | Since (UTC) |\n| --- | --- | --- | --- |\n' >> "$PORT_REGISTRY_FILE"
}
ports() { "$PR" list --tsv 2>/dev/null | cut -f1 | tr '\n' ' ' | sed 's/ $//'; }

# Pick two ports with no listener.
free_port() {
  p="$1"
  while lsof -nP -iTCP:"$p" -sTCP:LISTEN -t >/dev/null 2>&1; do p=$((p + 1)); done
  printf '%s' "$p"
}
P1="$(free_port 47310)"
P2="$(free_port $((P1 + 1)))"
P3="$(free_port $((P2 + 1)))"
NOW="$(TZ=UTC date +%Y-%m-%dT%H:%M:%SZ)"
OLD="2020-01-01T00:00:00Z"
LIVE_WS="$TMP/live-workspace"
mkdir -p "$LIVE_WS"

# Confirmed-deleted workspace, no listener: dropped on list, even inside the grace window.
seed "$P1" wt-e2e "$TMP/deleted/.context/wt-e2e" "$NOW"
check 'a deleted workspace with no listener is dropped on list, inside the grace window' '' "$(ports)"
seed "$P1" after "$TMP/deleted/.context/agents/after" "$OLD"
check 'a deleted workspace with no listener is dropped on list, past the grace window' '' "$(ports)"

# Existing workspace, fresh claim: a claim made just before boot is kept.
seed "$P2" boot "$LIVE_WS" "$NOW"
check 'a claim for an existing workspace inside the grace window is kept' "$P2" "$(ports)"

# Mixed registry: only the deleted workspace's row goes.
seed "$P1" gone "$TMP/deleted/x" "$NOW" "$P2" boot "$LIVE_WS" "$NOW"
check 'only the deleted workspace row is dropped from a mixed registry' "$P2" "$(ports)"

# Unknown is not deleted: a relative workspace path keeps the claim.
seed "$P3" odd "relative/path" "$NOW"
check 'an unverifiable workspace path keeps its claim' "$P3" "$(ports)"

# A listener is always held, even when its workspace is gone.
if command -v python3 >/dev/null 2>&1; then
  LP="$(free_port 47400)"
  python3 -I -c "import socket,time;s=socket.socket();s.setsockopt(socket.SOL_SOCKET,socket.SO_REUSEADDR,1);s.bind(('127.0.0.1',$LP));s.listen(1);time.sleep(30)" &
  SRV=$!
  for _ in 1 2 3 4 5 6 7 8 9 10 11 12 13 14 15 16 17 18 19 20; do
    lsof -nP -iTCP:"$LP" -sTCP:LISTEN -t >/dev/null 2>&1 && break
    sleep 0.25
  done
  seed "$LP" gone "$TMP/deleted/y" "$OLD"
  check 'a bound port is held even when its workspace is gone' "$LP" "$(ports)"
  kill "$SRV" 2>/dev/null; wait "$SRV" 2>/dev/null
fi

[ "$FAILS" -eq 0 ] && echo 'all port-registry checks passed' || echo "$FAILS port-registry check(s) failed"
[ "$FAILS" -eq 0 ]
