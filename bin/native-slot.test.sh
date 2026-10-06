#!/usr/bin/env bash
# native-slot.test.sh
# Runs bin/native-slot.sh against a temp record directory. No simulator, no xcodebuild: the slot is
# exercised with `sleep`, and the simulator ledger with made-up ids.
# Usage: bash bin/native-slot.test.sh   (exit 0 = every check passed)
set -u
HERE="$(cd "$(dirname "$0")" && pwd)"
NS="$HERE/native-slot.sh"
TMP="$(mktemp -d)"
export NATIVE_SLOT_DIR="$TMP/slot"
export NATIVE_SLOT_POLL_SEC=1
FAILS=0
trap 'rm -rf "$TMP"' EXIT

check() { # $1 = name, $2 = expected, $3 = actual
  if [ "$2" = "$3" ]; then printf 'ok   %s\n' "$1"; else
    printf 'FAIL %s\n     expected: %s\n     actual:   %s\n' "$1" "$2" "$3"; FAILS=$((FAILS + 1)); fi
}

# 1. run executes the command, passes its status through, and releases the slot.
CLAUDE_NATIVE_SESSION=alpha "$NS" run --for "unit tests" -- sh -c 'exit 7'
check "run passes the command's exit status through" 7 $?
check "the slot is free after the command ends" "Native slot free." "$("$NS" list | head -1)"

# 2. a second session waits while the first holds, and gives up with exit 3 when the wait runs out.
CLAUDE_NATIVE_SESSION=alpha "$NS" run --for "long build" --udid AAAA -- sleep 4 &
HOLDER=$!
sleep 1
LISTED="$("$NS" list | head -1)"
case "$LISTED" in "Native slot held: alpha  long build"*"simulator AAAA"*) HELD=yes ;; *) HELD="$LISTED" ;; esac
check "list names the holder, what it runs and its simulator" yes "$HELD"
CLAUDE_NATIVE_SESSION=beta "$NS" run --for "other build" --wait-min 0 -- touch "$TMP/ran-too-early" 2>/dev/null
check "a second session that cannot wait exits 3" 3 $?
check "and its command never ran" no "$([ -e "$TMP/ran-too-early" ] && echo yes || echo no)"

# 3. with time to wait, the second session runs after the first releases.
CLAUDE_NATIVE_SESSION=beta "$NS" run --for "other build" --wait-min 1 -- touch "$TMP/ran-after" 2>/dev/null
check "a waiting session runs once the slot is released" 0 $?
wait "$HOLDER"
check "its command ran" yes "$([ -e "$TMP/ran-after" ] && echo yes || echo no)"

# 4. a holder whose process is gone does not block anyone.
mkdir -p "$NATIVE_SLOT_DIR/slot.d"
printf '999999\tghost\t/tmp\t%s\tdead build\t\n' "$(date +%s)" > "$NATIVE_SLOT_DIR/slot.d/holder"
CLAUDE_NATIVE_SESSION=beta "$NS" run --for "after a crash" --wait-min 0 -- true
check "a slot left by a dead process is taken over" 0 $?

# 5. the simulator ledger: one owner per device, and only the owner releases.
CLAUDE_NATIVE_SESSION=alpha "$NS" claim-sim SIM-ONE --for "PR 1 tests" >/dev/null
check "a session registers a simulator" 0 $?
CLAUDE_NATIVE_SESSION=beta "$NS" claim-sim SIM-ONE >/dev/null 2>&1
check "another session cannot register the same simulator" 3 $?
CLAUDE_NATIVE_SESSION=beta "$NS" release-sim SIM-ONE >/dev/null
check "another session's release leaves the row" 1 "$(grep -c SIM-ONE "$NATIVE_SLOT_DIR/sims.tsv")"
CLAUDE_NATIVE_SESSION=alpha "$NS" release-sim SIM-ONE >/dev/null
check "the owner's release removes the row" 0 "$(grep -c SIM-ONE "$NATIVE_SLOT_DIR/sims.tsv")"

# 6. a row whose workspace was deleted is dropped on the next read.
GONE="$TMP/gone-workspace"; mkdir -p "$GONE"
printf 'SIM-TWO\tgamma\t%s\t%s\told tests\n' "$GONE" "$(date +%s)" >> "$NATIVE_SLOT_DIR/sims.tsv"
rmdir "$GONE"
"$NS" list >/dev/null
check "a simulator row whose workspace is gone is dropped" 0 "$(grep -c SIM-TWO "$NATIVE_SLOT_DIR/sims.tsv")"

# 7. usage errors exit 2 and run nothing.
"$NS" run -- true 2>/dev/null
check "run without --for exits 2" 2 $?
JOBS="$("$NS" jobs)"
check "jobs prints a whole number of at least 2" yes "$([ "$JOBS" -ge 2 ] 2>/dev/null && echo yes || echo no)"

[ "$FAILS" -eq 0 ] && { echo "ALL PASSED"; exit 0; }
echo "$FAILS FAILED"; exit 1
