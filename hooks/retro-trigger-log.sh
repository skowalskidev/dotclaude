#!/usr/bin/env bash
# retro-trigger-log.sh
# SessionEnd hook: records, one line per session, the mechanically-detectable moments where the
# config got in the way. DETECTION AND REPORTING ONLY — it writes a log line and nothing else.
# It never proposes, never prompts, never edits. Same hard separation as orphan-worker-sweep.sh:
# an unattended hook that ACTS is what rules/security.md forbids.
#
# Why SessionEnd and not Stop:
#   A Stop hook can inject a "you forgot to retrospect" prompt, but only by BLOCKING the turn, and
#   blocking Stop hooks are a documented session-burner (anthropics/claude-code#55754, ~50 minutes).
#   Worse, its marker would have to be model-set: the model that forgot to retrospect is the model
#   that must remember to arm the reminder telling it to remember. task-intake.sh already deadlocked
#   a whole session on that exact marker-set/marker-cleared shape (XCAL-284, 2026-08-03).
#   SessionEnd structurally cannot inject context or block, which is precisely why it is safe here.
#
# What the log is FOR:
#   rules/self-healing-config.md fires per-task and sees one occurrence, so it can only ever judge
#   durability from a sample of one. This log is the class-level view: "this guard denied me nine
#   times across four projects this month" is a finding the per-task path structurally cannot
#   produce. /sk:claude-config-self-development-research reads it as an evidence surface.
#   This is rules/process.md's "fix the CLASS of failure, not the one instance" applied to the config.
#
# Privacy: records COUNTS and matched signature names. Never prompt text, never file contents.

set -uo pipefail

LOG_DIR="$HOME/.claude/logs"
LOG="$LOG_DIR/retro-triggers.jsonl"

payload="$(cat 2>/dev/null || true)"
[ -n "$payload" ] || exit 0

command -v jq >/dev/null 2>&1 || exit 0

transcript="$(printf '%s' "$payload" | jq -r '.transcript_path // empty' 2>/dev/null)"
session="$(printf '%s' "$payload" | jq -r '.session_id // "unknown"' 2>/dev/null)"
reason="$(printf '%s' "$payload" | jq -r '.reason // "other"' 2>/dev/null)"
cwd="$(printf '%s' "$payload" | jq -r '.cwd // empty' 2>/dev/null)"

# No transcript, nothing to count. Exit silently rather than write an empty row.
[ -n "$transcript" ] && [ -f "$transcript" ] || exit 0

# Signatures, each a fixed string emitted by one of the guards. Counted, not quoted.
# Keep these in sync with the guards' own deny messages; a renamed message silently zeroes a count,
# which is why the count is reported per-signature rather than as one total.
#
# `grep -c` PRINTS 0 and EXITS 1 on no-match, so a `|| echo 0` fallback emits "0\n0" and every
# arithmetic use downstream then dies. Use `|| true` and default the empty (unreadable-file) case.
count() { local n; n="$(grep -c "$1" "$transcript" 2>/dev/null || true)"; printf '%s' "${n:-0}"; }

blocked_work=$(count 'Blocked: ')
blocked_crown=$(count 'crown-jewel')
intake_denied=$(count 'TASK INTAKE GATE')
perm_denied=$(count 'permissionDecision":"deny')

total=$((blocked_work + blocked_crown + intake_denied + perm_denied))
# Nothing worth recording. Silence keeps the log signal-dense.
[ "$total" -gt 0 ] || exit 0

# Built with jq so a path or reason containing a quote cannot corrupt the line.
line="$(jq -n -c \
  --arg ts "$(date -u +%Y-%m-%dT%H:%M:%SZ)" \
  --arg session "$session" \
  --arg reason "$reason" \
  --arg cwd "$cwd" \
  --argjson guard_denials "$blocked_work" \
  --argjson crown_denials "$blocked_crown" \
  --argjson intake_gate "$intake_denied" \
  --argjson permission_denials "$perm_denied" \
  '{ts:$ts, session:$session, end_reason:$reason, cwd:$cwd,
    guard_denials:$guard_denials, crown_denials:$crown_denials,
    intake_gate:$intake_gate, permission_denials:$permission_denials}' 2>/dev/null)"
[ -n "$line" ] || exit 0

# ONE home: route through the shared writer, which lands it in the dotclaude `retro_triggers`
# collection, or the local outbox when no project is configured (zero-setup still works, never both).
PY="$HOME/.config/claude-metrics-venv/bin/python"; [ -x "$PY" ] || PY="$(command -v python3 || true)"
if [ -n "$PY" ] && [ -f "$HOME/.claude/bin/dotclaude-log.py" ]; then
  printf '%s' "$line" | "$PY" "$HOME/.claude/bin/dotclaude-log.py" retro_triggers >/dev/null 2>&1 || true
else
  # No interpreter/writer available: fall back to the legacy local line so nothing is lost.
  mkdir -p "$LOG_DIR" 2>/dev/null && printf '%s\n' "$line" >> "$LOG" 2>/dev/null || true
fi

exit 0
