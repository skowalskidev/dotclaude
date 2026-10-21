#!/usr/bin/env bash
# Offline compatibility tests. No simulator is booted and no native build runs.
set -u
HERE="$(cd "$(dirname "$0")" && pwd)"
NS="$HERE/native-slot.sh"
TMP="$(mktemp -d)"
TMP="$(cd "$TMP" && pwd -P)"
export LOCAL_CAPACITY_ROOT="$TMP/capacity"
export NATIVE_SLOT_DIR="$TMP/legacy"
export LOCAL_CAPACITY_SIMCTL_JSON="$LOCAL_CAPACITY_ROOT/booted.json"
export LOCAL_CAPACITY_PRESSURE_JSON="$LOCAL_CAPACITY_ROOT/pressure.json"
export LOCAL_CAPACITY_HOST_JSON="$LOCAL_CAPACITY_ROOT/host.json"
mkdir -p "$LOCAL_CAPACITY_ROOT" "$NATIVE_SLOT_DIR"
printf '{"devices":{}}\n' > "$LOCAL_CAPACITY_SIMCTL_JSON"
printf '{"load":0,"cores":8}\n' > "$LOCAL_CAPACITY_PRESSURE_JSON"
printf '{}\n' > "$LOCAL_CAPACITY_HOST_JSON"
FAILS=0
trap 'rm -rf "$TMP"' EXIT
check() {
  if [ "$2" = "$3" ]; then printf 'ok   %s\n' "$1"; else
    printf 'FAIL %s: expected [%s], got [%s]\n' "$1" "$2" "$3"; FAILS=$((FAILS + 1)); fi
}
SIM=AAAAAAAA-BBBB-CCCC-DDDD-EEEEEEEEEEEE
SIM2=11111111-2222-3333-4444-555555555555

check 'empty status uses the shared gate' 'heavy slot 1 of 3: free' "$("$NS" list | head -1)"
CLAUDE_NATIVE_SESSION=alpha "$NS" run --for 'unit tests' -- sh -c 'exit 7' >/dev/null
check 'run passes child status' 7 "$?"
check 'run releases completed command' 'heavy slot 1 of 3: free' "$("$NS" list | head -1)"

CLAUDE_NATIVE_SESSION=alpha "$NS" claim-sim "$SIM" --for 'iOS tests' >/dev/null
check 'claim visible through shared status' yes "$("$NS" list | grep -q "simulator claim: $SIM owner=alpha" && echo yes || echo no)"
CLAUDE_NATIVE_SESSION=beta "$NS" claim-sim "$SIM" >/dev/null 2>&1
check 'another owner cannot claim simulator' 75 "$?"
CLAUDE_NATIVE_SESSION=beta "$NS" release-sim "$SIM" >/dev/null 2>&1
check 'another owner cannot release simulator' 1 "$?"
CLAUDE_NATIVE_SESSION=beta "$NS" claim-sim "$SIM2" >/dev/null 2>&1
check 'a second simulator is refused machine-wide while one is claimed' 75 "$?"
CLAUDE_NATIVE_SESSION=beta "$NS" run --for 'second sim' --udid "$SIM2" -- true >/dev/null 2>&1
check 'a second simulator run is refused before its command starts' 75 "$?"
check 'status names the simulator cap' yes "$("$NS" list | grep -q "simulators in use: 1 of 1" && echo yes || echo no)"
CLAUDE_NATIVE_SESSION=alpha "$NS" release-sim "$SIM" >/dev/null
check 'owner releases shut-down simulator' 0 "$?"

CLAUDE_NATIVE_SESSION=alpha "$NS" claim-sim "$SIM" >/dev/null
printf '{"sessions":["/w/alpha/apps/ios"]}\n' > "$LOCAL_CAPACITY_HOST_JSON"
"$NS" reclaim-sim "$SIM" >/dev/null 2>&1
check 'reclaim-sim refuses while the claim owner has a live session' 1 "$?"
check 'refused reclaim keeps the claim' yes "$("$NS" list | grep -q "simulator claim: $SIM owner=alpha" && echo yes || echo no)"
check 'status prints no reclaim command for a live owner' no "$("$NS" list | grep -q 'reclaim-sim' && echo yes || echo no)"
printf '{"sessions":[]}\n' > "$LOCAL_CAPACITY_HOST_JSON"
check 'status prints the reclaim command for an ended owner' yes "$("$NS" list | grep -q "reclaim it: python3 ~/.claude/bin/local-capacity.py reclaim-sim --udid $SIM" && echo yes || echo no)"
"$NS" reclaim-sim "$SIM" >/dev/null 2>&1
check 'reclaim-sim drops the claim of an ended owner' 0 "$?"
check 'reclaimed claim is gone' no "$("$NS" list | grep -q "simulator claim: $SIM" && echo yes || echo no)"
printf '{}\n' > "$LOCAL_CAPACITY_HOST_JSON"

mkdir -p "$NATIVE_SLOT_DIR/slot.d"
CLAUDE_NATIVE_SESSION=alpha "$NS" run --for 'blocked build' -- true >/dev/null 2>&1
check 'legacy slot blocks admission without reaping' 75 "$?"
check 'legacy slot still exists' yes "$([ -d "$NATIVE_SLOT_DIR/slot.d" ] && echo yes || echo no)"
rmdir "$NATIVE_SLOT_DIR/slot.d"
printf '%s\tlegacy-owner\t/missing-workspace\t1\told tests\n' "$SIM" > "$NATIVE_SLOT_DIR/sims.tsv"
CLAUDE_NATIVE_SESSION=alpha "$NS" claim-sim "$SIM" >/dev/null 2>&1
check 'unverified legacy simulator claim remains reserved' 75 "$?"
check 'legacy ledger is preserved' 1 "$(wc -l < "$NATIVE_SLOT_DIR/sims.tsv" | tr -d ' ')"

LEGACY_LOCK="$TMP/legacy.lock"
python3 - "$LOCAL_CAPACITY_ROOT/bridge.json" "$LEGACY_LOCK" <<'PY'
import json, sys
with open(sys.argv[1], 'w') as stream:
    json.dump({'lockPaths': [sys.argv[2]]}, stream)
PY
lockf -k "$LEGACY_LOCK" sleep 2 &
LOCKER=$!
sleep 0.2
CLAUDE_NATIVE_SESSION=alpha "$NS" run --for 'bridge blocked' -- true >/dev/null 2>&1
check 'old lockf holder blocks new gate' 75 "$?"
wait "$LOCKER"
CLAUDE_NATIVE_SESSION=alpha "$NS" run --for 'bridge released' -- true >/dev/null
check 'new gate runs after old lockf exits' 0 "$?"
CLAUDE_NATIVE_SESSION=alpha "$NS" run --for 'no polling' --wait-min 1 -- true >/dev/null 2>&1
check 'old waiting behavior fails with migration code' 75 "$?"

mkdir -p "$TMP/fakebin"
printf '#!/bin/sh\necho 12\n' > "$TMP/fakebin/sysctl"
chmod +x "$TMP/fakebin/sysctl"
JOBS="$(PATH="$TMP/fakebin:$PATH" "$NS" jobs)"
check '12-core host still caps native jobs at four' 4 "$JOBS"

# Regression: with no LOCAL_CAPACITY_ROOT the root array is empty, and macOS /bin/bash 3.2 reports an
# empty "${ROOT[@]}" as an unbound variable under set -u. Run under that bash with a throwaway HOME
# so the default state root stays out of the real config.
mkdir -p "$TMP/home"
OUT="$(HOME="$TMP/home" env -u LOCAL_CAPACITY_ROOT /bin/bash "$NS" list 2>&1)"
check 'empty root array works under /bin/bash' 0 "$?"
check 'empty root array reaches the engine' 'heavy slot 1 of' "$(printf '%s' "$OUT" | head -1 | cut -c1-15)"
case "$OUT" in *unbound*) check 'no unbound variable error' none unbound ;; esac

[ "$FAILS" -eq 0 ] && { echo 'ALL PASSED'; exit 0; }
echo "$FAILS FAILED"; exit 1
