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
# These fixtures emulate Claude, independent of the host running the test suite.
unset CODEX_THREAD_ID CODEX_SESSION_ID CLAUDECODE AGENT_MODEL_PROVIDER AGENT_SETUP CLAUDE_CONFIG_DIR

SCRIPT_DIR="$(cd "$(dirname "$0")" && pwd)"
DISPATCH="$SCRIPT_DIR/superspeed-dispatch.sh"
TIMEOUT_S=90
FAILED=0

pass() { printf '  ok   %s\n' "$1"; }
fail() { printf '  FAIL %s\n' "$1"; FAILED=1; }

TMP="$(mktemp -d)"
trap 'rm -rf "$TMP"; pkill -f "$TMP" 2>/dev/null || true' EXIT
export HOME="$TMP/home"
mkdir -p "$HOME"

# ---- a fixture OpenAI model cache, so agent_setup.py's live tier resolver has something to rank ---
# Priority 1 is the top-tier orchestrator (mirrors the real "Astra" slot), priority 2 the mid/worker
# tier used throughout these specs, priority 3 a spare small tier. No real ~/.codex is touched: HOME
# is redirected above and CODEX_HOME below both point inside $TMP.
mkdir -p "$HOME/.codex"
export CODEX_HOME="$HOME/.codex"
printf '%s\n' '{"auth_mode":"chatgpt","tokens":{"access_token":"fixture-only"}}' > "$HOME/.codex/auth.json"
cat > "$CODEX_HOME/models_cache.json" <<'EOF'
{
  "fetched_at": "2026-09-24T08:16:41.342528Z",
  "models": [
    { "slug": "gpt-6-astra", "visibility": "list", "priority": 1, "upgrade": null },
    { "slug": "gpt-5.6-sol", "visibility": "list", "priority": 2, "upgrade": null },
    { "slug": "gpt-mini", "visibility": "list", "priority": 3, "upgrade": null }
  ]
}
EOF

# ---- a fake `claude` that returns instantly -------------------------------------------------------
# Shaped like the real thing's --output-format json so the dispatcher's jq parsing is exercised
# rather than bypassed. It also writes DONE.md, so a green run is a genuinely green run and the
# test would notice if the artifact check regressed too.
mkdir -p "$TMP/bin"
cat > "$TMP/bin/claude" <<'STUB'
#!/usr/bin/env bash
if [ "${1:-}" = "--version" ]; then printf 'claude fixture\n'; exit 0; fi
# The dispatcher passes the prompt positionally after -p; the slice dir is named inside it.
SD="$(printf '%s\n' "$@" | grep -oE '/[^ ]*/slices/[a-zA-Z0-9_-]+' | head -1)"
[ "${FIXTURE_CLAUDE_FAIL:-}" = 1 ] && exit 7
[ -n "$SD" ] && mkdir -p "$SD" && printf '# done\nstub\n' > "$SD/DONE.md"
[ -n "${FIXTURE_CLAUDE_CALLS:-}" ] && printf 'args=%s\napi_key=%s\nauth_token=%s\ncross_provider=%s\nfoundry=%s\n' "$*" "${ANTHROPIC_API_KEY-unset}" "${ANTHROPIC_AUTH_TOKEN-unset}" "${AGENT_ALLOW_CROSS_PROVIDER-unset}" "${CLAUDE_CODE_USE_FOUNDRY-unset}" >> "$FIXTURE_CLAUDE_CALLS"
printf '{"is_error":false,"num_turns":1,"duration_ms":10,"session_id":"stub","usage":{}}\n'
exit 0
STUB
chmod +x "$TMP/bin/claude"
export AGENT_CLAUDE_BIN="$TMP/bin/claude"

cat > "$TMP/bin/codex" <<'STUB'
#!/usr/bin/env bash
if [ "${1:-}" = "--version" ]; then printf 'codex 0.1\n'; exit 0; fi
PROMPT="$(cat)"
SD="$(printf '%s\n' "$PROMPT" | grep -oE '/[^ ]*/slices/[a-zA-Z0-9_-]+' | head -1)"
[ -n "$SD" ] && printf '# done\nstub\n' > "$SD/DONE.md"
printf '{"type":"thread.started","thread_id":"stub"}\n{"type":"turn.completed","usage":{}}\n'
STUB
chmod +x "$TMP/bin/codex"
export AGENT_CODEX_BIN="$TMP/bin/codex"

# ---- a throwaway repo and a two-slice spec --------------------------------------------------------
mkdir -p "$TMP/repo"
git -C "$TMP/repo" init -q 2>/dev/null
printf 'placeholder\n' > "$TMP/repo/a.txt"

cat > "$TMP/spec.json" <<EOF
{
  "task": "dispatcher exit regression",
  "agent_setup": "full-claude",
  "orchestrator_model": "claude-opus-5-5",
  "repo": "$TMP/repo",
  "gate": "true",
  "setup": "none",
  "model": "sonnet",
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
{ "task": "t", "agent_setup": "full-claude", "orchestrator_model": "claude-opus-5-5", "repo": "$TMP/repo", "setup": "none", "slices": [ $2 ] }
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

# ---- the existing Full Claude route preserves its environment -------------------------------------
CLAUDE_CALLS="$TMP/claude-calls.log"
FIXTURE_CLAUDE_CALLS="$CLAUDE_CALLS" ANTHROPIC_API_KEY=fixture ANTHROPIC_AUTH_TOKEN=fixture \
  CLAUDE_CODE_USE_FOUNDRY=fixture PATH="$TMP/bin:$PATH" \
  bash "$DISPATCH" "$TMP/spec.json" "$TMP/repo/.superspeed/claude-env" > "$TMP/claude-env.log" 2>&1
RC=$?
if [ "$RC" = 0 ] && grep -q -- '--model sonnet' "$CLAUDE_CALLS" \
    && grep -q '^api_key=fixture$' "$CLAUDE_CALLS" && grep -q '^auth_token=fixture$' "$CLAUDE_CALLS" \
    && grep -q '^cross_provider=unset$' "$CLAUDE_CALLS" && grep -q '^foundry=fixture$' "$CLAUDE_CALLS"; then
  pass "Full Claude route keeps its prior environment"
else
  fail "Full Claude route must not inherit the design-route environment (exit $RC)"
fi

# ---- OpenAI design slices use Claude Fable without API billing or a Codex fallback ----------------
cat > "$TMP/spec-design.json" <<EOF
{
  "task": "design route regression",
  "agent_setup": "full-openai",
  "orchestrator_model": "gpt-5.6-sol",
  "repo": "$TMP/repo",
  "gate": "true",
  "setup": "none",
  "model": "gpt-5.6-sol",
  "slices": [
    { "name": "screen", "model_route": "design", "owns": ["screen.txt"], "accept": "exists", "verify": "none", "prompt": "do design work" }
  ]
}
EOF
DESIGN_CALLS="$TMP/design-calls.log"
FIXTURE_CLAUDE_CALLS="$DESIGN_CALLS" ANTHROPIC_API_KEY=fixture ANTHROPIC_AUTH_TOKEN=fixture CLAUDE_CODE_USE_FOUNDRY=fixture PATH="$TMP/bin:$PATH" \
  bash "$DISPATCH" "$TMP/spec-design.json" "$TMP/repo/.superspeed/design" > "$TMP/design.log" 2>&1
RC=$?
if [ "$RC" = 0 ] && grep -q -- '--model fable' "$DESIGN_CALLS" \
    && grep -q '^api_key=unset$' "$DESIGN_CALLS" && grep -q '^auth_token=unset$' "$DESIGN_CALLS" \
    && grep -q '^cross_provider=1$' "$DESIGN_CALLS" && grep -q '^foundry=unset$' "$DESIGN_CALLS"; then
  pass "OpenAI design slice uses Fable with no Claude API key"
else
  fail "OpenAI design slice must use Fable without API billing (exit $RC)"
fi

FIXTURE_CLAUDE_FAIL=1 PATH="$TMP/bin:$PATH" \
  bash "$DISPATCH" "$TMP/spec-design.json" "$TMP/repo/.superspeed/design-failure" > "$TMP/design-failure.log" 2>&1
RC=$?
if [ "$RC" -ne 0 ] && [ "$(cat "$TMP/repo/.superspeed/design-failure/slices/screen/status")" != ok ]; then
  pass "Fable failure stops the design slice without fallback"
else
  fail "Fable failure must not become an OpenAI design worker (exit $RC)"
fi

sed 's/"full-openai"/"full-astra"/; s/"orchestrator_model": "gpt-5.6-sol"/"orchestrator_model": "gpt-6-astra"/' "$TMP/spec-design.json" > "$TMP/spec-astra-design.json"
ASTRA_DESIGN_CALLS="$TMP/astra-design-calls.log"
FIXTURE_CLAUDE_CALLS="$ASTRA_DESIGN_CALLS" PATH="$TMP/bin:$PATH" \
  bash "$DISPATCH" "$TMP/spec-astra-design.json" "$TMP/repo/.superspeed/astra-design" > "$TMP/astra-design.log" 2>&1
RC=$?
if [ "$RC" = 0 ] && grep -q -- '--model fable' "$ASTRA_DESIGN_CALLS"; then
  pass "Astra design slice uses Fable"
else
  fail "Astra design slice must use Fable (exit $RC)"
fi

# ---- static Claude Bash permissions apply to the effective worker in all settings scopes ---------
permission_case() { # label, setup, route, verify, user, project, local, expected, optional diagnostic
  local label="$1" setup="$2" route="$3" verify="$4" user="$5" project="$6" local_settings="$7" expected="$8"
  local diagnostic="${9:-}"
  local spec="$TMP/permission-spec.json" out="$TMP/repo/.superspeed/permission-$RANDOM" rc spent calls
  mkdir -p "$HOME/.claude" "$TMP/repo/.claude"
  rm -f "$HOME/.claude/settings.json" "$TMP/repo/.claude/settings.json" "$TMP/repo/.claude/settings.local.json"
  [ "$user" = absent ] || printf '%s\n' "$user" > "$HOME/.claude/settings.json"
  [ "$project" = absent ] || printf '%s\n' "$project" > "$TMP/repo/.claude/settings.json"
  [ "$local_settings" = absent ] || printf '%s\n' "$local_settings" > "$TMP/repo/.claude/settings.local.json"
  if [ "$setup" = full-claude ]; then
    jq -n --arg repo "$TMP/repo" --arg route "$route" --arg verify "$verify" \
      '{task:"permission test",agent_setup:"full-claude",orchestrator_model:"claude-opus-5-5",repo:$repo,setup:"none",slices:[{name:"x",model_route:$route,owns:["a.txt"],accept:"exists",verify:$verify,prompt:"stub"}]}' > "$spec"
  else
    jq -n --arg repo "$TMP/repo" --arg route "$route" --arg verify "$verify" \
      '{task:"permission test",agent_setup:"full-openai",orchestrator_model:"gpt-5.6-sol",repo:$repo,setup:"none",slices:[{name:"x",model_route:$route,owns:["a.txt"],accept:"exists",verify:$verify,prompt:"stub"}]}' > "$spec"
  fi
  calls="$TMP/permission-calls-$RANDOM"
  FIXTURE_CLAUDE_CALLS="$calls" PATH="$TMP/bin:$PATH" bash "$DISPATCH" "$spec" "$out" > "$TMP/permission.log" 2>&1
  rc=$?
  spent="$(find "$out" -name result.json 2>/dev/null | wc -l | tr -d ' ')"
  if [ "$expected" = blocked ]; then
    [ "$rc" = 4 ] && [ "$spent" = 0 ] && [ ! -s "$calls" ] \
      && { [ -z "$diagnostic" ] || grep -qF -- "$diagnostic" "$TMP/permission.log"; } && pass "$label" \
      || fail "$label (exit $rc, results $spent; $(tail -2 "$TMP/permission.log" | tr '\n' ' '))"
  elif [ "$setup" = full-openai ] && [ "$route" = design ]; then
    [ "$rc" = 0 ] && [ "$spent" = 1 ] && grep -q -- '--model fable' "$calls" && pass "$label" \
      || fail "$label (exit $rc, results $spent; $(tail -2 "$TMP/permission.log" | tr '\n' ' '))"
  elif [ "$setup" = full-openai ]; then
    [ "$rc" = 0 ] && [ "$spent" = 1 ] && [ ! -s "$calls" ] && pass "$label" \
      || fail "$label (exit $rc, results $spent; $(tail -2 "$TMP/permission.log" | tr '\n' ' '))"
  else
    [ "$rc" = 0 ] && [ "$spent" = 1 ] && [ -s "$calls" ] && pass "$label" \
      || fail "$label (exit $rc, results $spent; $(tail -2 "$TMP/permission.log" | tr '\n' ' '))"
  fi
}

permission_case "full Claude exact allow in user settings" full-claude general 'printf ok' \
  '{"permissions":{"allow":["Bash(printf ok)"]}}' absent absent allowed
permission_case "full Claude prefix allow in project settings" full-claude general 'printf ok' \
  absent '{"permissions":{"allow":["Bash(printf *)"]}}' absent allowed
permission_case "full Claude legacy prefix allow in local settings" full-claude general 'printf ok' \
  absent absent '{"permissions":{"allow":["Bash(printf:*)"]}}' allowed
permission_case "full Claude whole Bash allow" full-claude general 'printf ok' \
  '{"permissions":{"allow":["Bash"]}}' absent absent allowed
permission_case "OpenAI design denied before Fable starts" full-openai design 'printf ok' \
  absent absent absent blocked
permission_case "OpenAI design allowed as Fable" full-openai design 'printf ok' \
  '{"permissions":{"allow":["Bash(printf ok)"]}}' absent absent allowed
permission_case "user deny overrides project allow" full-claude general 'printf ok' \
  '{"permissions":{"deny":["Bash(printf ok)"]}}' '{"permissions":{"allow":["Bash(printf *)"]}}' absent blocked 'blocked by permissions.deny'
permission_case "local ask overrides user allow" full-claude general 'printf ok' \
  '{"permissions":{"allow":["Bash(printf *)"]}}' absent '{"permissions":{"ask":["Bash(printf ok)"]}}' blocked 'blocked by permissions.ask'
permission_case "missing settings does not imply allow" full-claude general 'printf ok' \
  absent absent absent blocked 'no applicable Bash allow rule matches'
permission_case "unrelated Bash allow does not imply allow" full-claude general 'printf ok' \
  '{"permissions":{"allow":["Bash(npm run *)"]}}' absent absent blocked
permission_case "malformed JSON blocks Claude" full-claude general 'printf ok' \
  '{bad json' absent absent blocked
permission_case "malformed permission type blocks Claude" full-claude general 'printf ok' \
  '{"permissions":{"allow":"Bash(printf ok)"}}' absent absent blocked
permission_case "unsupported Bash wildcard blocks Claude" full-claude general 'printf ok' \
  '{"permissions":{"allow":["Bash(printf * ok)"]}}' absent absent blocked 'permission unknown'
permission_case "unrelated unsupported Bash wildcard does not block" full-claude general 'printf ok' \
  '{"permissions":{"allow":["Bash(printf ok)"],"ask":["Bash(git * main)"]}}' absent absent allowed
permission_case "compound verify cannot reuse prefix allow" full-claude general 'printf ok && printf unsafe' \
  '{"permissions":{"allow":["Bash(printf *)"]}}' absent absent blocked
permission_case "quoted operator is a literal argument" full-claude general "printf '&&'" \
  '{"permissions":{"allow":["Bash(printf *)"]}}' absent absent allowed
permission_case "single-quoted substitution is a literal argument" full-claude general "printf '\$(printf inert)'" \
  '{"permissions":{"allow":["Bash(printf *)"]}}' absent absent allowed
permission_case "nested shell body stays unknown" full-claude general "bash -c 'printf ok && printf unsafe'" \
  '{"permissions":{"allow":["Bash"]}}' absent absent blocked
permission_case "command substitution stays unknown" full-claude general 'printf "$(printf unsafe)"' \
  '{"permissions":{"allow":["Bash"]}}' absent absent blocked
permission_case "dynamic shell expansion stays unknown" full-claude general 'printf "$COMMAND"' \
  '{"permissions":{"allow":["Bash"]}}' absent absent blocked
permission_case "apostrophe inside double quotes remains literal" full-claude general "printf \"it's ok\"" \
  '{"permissions":{"allow":["Bash(printf *)"]}}' absent absent allowed
permission_case "unquoted glob stays unknown" full-claude general 'printf *' \
  '{"permissions":{"allow":["Bash"]}}' absent absent blocked
permission_case "env wrapper stays unknown" full-claude general 'env TASK=ok printf ok' \
  '{"permissions":{"allow":["Bash"]}}' absent absent blocked
permission_case "whole Bash deny overrides exact allow" full-claude general 'printf ok' \
  '{"permissions":{"allow":["Bash(printf ok)"],"deny":["Bash(*)"]}}' absent absent blocked
permission_case "prefix has a command boundary" full-claude general 'printfly ok' \
  '{"permissions":{"allow":["Bash(printf *)"]}}' absent absent blocked
permission_case "OpenAI general ignores Claude settings" full-openai general 'printf ok' \
  '{bad json' absent absent allowed

[ "$FAILED" = 0 ] && echo "PASS" || echo "FAIL"
exit "$FAILED"
