#!/usr/bin/env bash
#
# Regression test for superspeed-dispatch.sh.
#
# It asserts TWO things, each because that exact thing went wrong once:
#   1. The dispatcher must EXIT once its slices have exited (the bare-wait deadlock, below).
#   2. It must REFUSE to dispatch a slice whose `verify` it cannot run, BEFORE spending anything.
#      On 2026-08-08 all four slices of one run reached for `npx vitest` against an allowlist of
#      `npm run *` and were refused 24 times between them. Two found the allowlisted form and
#      verified; two never verified at all, and one of those shipped two tests that failed with
#      zero mock calls while its DONE.md said "verified by careful inspection instead". A check
#      nobody can execute is worse than no check, because it reads as one.
#
# Why this test and not a broader one. On 2026-08-08 a real run deadlocked and every other signal
# looked perfect: all four slices finished, each wrote DONE.md and result.json, every exit code was
# zero, and the analyser would have scored the run healthy. The bug was a bare `wait` that also
# waited on the concurrency sampler, an infinite loop killed only after that wait. So the failure had
# no error, no stack, no bad artifact, and no unhappy slice. It presented as slow work and cost about
# twelve minutes before someone noticed by eye. A hang is invisible to every check except a clock.
#
# `claude` is stubbed, so this spends nothing and needs no network.
#
# Usage: bash ~/.claude/bin/superspeed-dispatch.test.sh
set -uo pipefail

DISPATCH="$HOME/.claude/bin/superspeed-dispatch.sh"
TIMEOUT_S=90
FAILED=0

pass() { printf '  ok   %s\n' "$1"; }
fail() { printf '  FAIL %s\n' "$1"; FAILED=1; }

TMP="$(mktemp -d)"
trap 'rm -rf "$TMP"; pkill -f "$TMP" 2>/dev/null || true' EXIT

# ---- a fake `claude` that returns instantly -------------------------------------------------------
# Shaped like the real thing's --output-format json so the dispatcher's jq parsing is exercised
# rather than bypassed. It also writes DONE.md, so a green run is a genuinely green run and the
# test would notice if the artifact check regressed too.
mkdir -p "$TMP/bin"
cat > "$TMP/bin/claude" <<'STUB'
#!/usr/bin/env bash
# The dispatcher passes the prompt positionally after -p; the slice dir is named inside it.
SD="$(printf '%s\n' "$@" | grep -oE '/[^ ]*/slices/[a-zA-Z0-9_-]+' | head -1)"
[ -n "$SD" ] && mkdir -p "$SD" && printf '# done\nstub\n' > "$SD/DONE.md"
printf '{"is_error":false,"num_turns":1,"duration_ms":10,"session_id":"stub","usage":{}}\n'
exit 0
STUB
chmod +x "$TMP/bin/claude"

# ---- a throwaway repo and a two-slice spec --------------------------------------------------------
mkdir -p "$TMP/repo"
git -C "$TMP/repo" init -q 2>/dev/null
printf 'placeholder\n' > "$TMP/repo/a.txt"

cat > "$TMP/spec.json" <<EOF
{
  "task": "dispatcher exit regression",
  "repo": "$TMP/repo",
  "gate": "true",
  "setup": "none",
  "model": "claude-sonnet-4-6",
  "slices": [
    { "name": "alpha", "owns": ["a.txt"], "accept": "exists", "verify": "none", "prompt": "do nothing" },
    { "name": "beta",  "owns": ["b.txt"], "accept": "exists", "verify": "none", "prompt": "do nothing" }
  ]
}
EOF

# ---- run it under a portable timeout --------------------------------------------------------------
# `timeout` is GNU and absent on a stock macOS, so poll instead of depending on coreutils.
PATH="$TMP/bin:$PATH" bash "$DISPATCH" "$TMP/spec.json" "$TMP/repo/.superspeed/run" > "$TMP/out.log" 2>&1 &
DPID=$!

WAITED=0
while kill -0 "$DPID" 2>/dev/null && [ "$WAITED" -lt "$TIMEOUT_S" ]; do
  sleep 1
  WAITED=$((WAITED + 1))
done

echo "superspeed-dispatch.sh"

if kill -0 "$DPID" 2>/dev/null; then
  kill -9 "$DPID" 2>/dev/null
  pkill -f "$TMP" 2>/dev/null
  fail "dispatcher exits after its slices finish (still running after ${TIMEOUT_S}s: the bare-wait deadlock is back)"
else
  wait "$DPID" 2>/dev/null
  pass "dispatcher exits after its slices finish (${WAITED}s)"
fi

# ---- the sampler must not outlive the run ---------------------------------------------------------
# Same root cause seen from the other side: the loop that deadlocked the wait is also the loop that
# would burn a core forever if the kill were dropped. rules/process.md requires verifying it is gone.
if [ -f "$TMP/repo/.superspeed/run/concurrency.log" ]; then
  A=$(wc -l < "$TMP/repo/.superspeed/run/concurrency.log"); sleep 2; B=$(wc -l < "$TMP/repo/.superspeed/run/concurrency.log")
  [ "$A" = "$B" ] && pass "concurrency sampler stopped" \
                  || fail "concurrency sampler still writing after the run ($A -> $B lines)"
else
  fail "no concurrency.log written"
fi

# ---- the visibility the run is supposed to print --------------------------------------------------
grep -q "slice done: alpha" "$TMP/out.log" && pass "logs each slice as it finishes" \
  || fail "no per-slice completion line (visibility regression)"
grep -q "parallel picture:" "$TMP/out.log" && pass "prints the parallel summary" \
  || fail "no parallel summary printed"

# ---- each slice records its own verdict, so a killed run still has the truth --------------------
# The regression this guards: statuses used to be written in a loop AFTER the barrier, so killing a
# hung dispatcher reported four successful slices as four failures.
for n in alpha beta; do
  f="$TMP/repo/.superspeed/run/slices/$n/status"
  if [ -f "$f" ]; then
    [ "$(cat "$f")" = ok ] && pass "slice $n wrote its own status (ok)" \
                           || fail "slice $n status is $(cat "$f"), expected ok"
  else
    fail "slice $n wrote no status file"
  fi
done

# ---- an unrunnable `verify` stops the run BEFORE spending ---------------------------------------
# The guard is only worth having if it fires, and its whole value is that it fires EARLY: the
# failure it replaces was silent and only surfaced at the reconciler, one slice's cost later.
# Two cases, because a missing field and a present-but-refused one fail for different reasons.
mkdir -p "$TMP/repo/.claude"
cat > "$TMP/repo/.claude/settings.local.json" <<'ALLOW'
{ "permissions": { "allow": ["Bash(npm run *)"] } }
ALLOW

check_stop() {  # $1 = label, $2 = the slices[] JSON
  cat > "$TMP/spec-bad.json" <<EOF
{ "task": "t", "repo": "$TMP/repo", "setup": "none", "slices": [ $2 ] }
EOF
  OUT_BAD="$TMP/repo/.superspeed/bad-$RANDOM"
  PATH="$TMP/bin:$PATH" bash "$DISPATCH" "$TMP/spec-bad.json" "$OUT_BAD" > "$TMP/bad.log" 2>&1
  RC=$?
  # The assertion is that nothing was DISPATCHED, not that no directory exists: the run dir is
  # laid out before any check runs, so its presence proves nothing either way. A result.json is
  # the artifact only a real `claude -p` writes, which makes it the honest evidence of spend.
  SPENT="$(find "$OUT_BAD" -name result.json 2>/dev/null | wc -l | tr -d ' ')"
  if [ "$RC" = 4 ] && [ "$SPENT" = 0 ]; then
    pass "$1"
  else
    fail "$1 (exit $RC, expected 4; $SPENT slice(s) were dispatched, expected 0)"
  fi
}

check_stop "stops when a slice declares no verify" \
  '{ "name": "x", "owns": ["a.txt"], "accept": "e", "prompt": "p" }'
check_stop "stops when a slice's verify is not allowlisted" \
  '{ "name": "x", "owns": ["a.txt"], "accept": "e", "verify": "npx vitest run a", "prompt": "p" }'

[ "$FAILED" = 0 ] && echo "PASS" || echo "FAIL"
exit "$FAILED"
