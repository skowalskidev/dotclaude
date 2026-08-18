#!/usr/bin/env bash
# config-metrics-log.sh
# SessionEnd hook: hand the ended session's transcript to the metrics recorder, which parses it into
# minimized per-part events and writes them to the dotclaude-metrics store (or the local outbox when
# no project is configured). DETECTION AND REPORTING ONLY — it records data and nothing else: never
# proposes, never prompts, never edits. Same hard separation as retro-trigger-log.sh.
#
# Thin on purpose: grep can't extract complete raw events, so the real work is in
# bin/config-metrics-record.py. This hook only resolves the interpreter and pipes the payload.
#
# Interpreter: prefer the metrics venv (has firebase-admin, so it can flush to Firestore); fall back
# to system python3, which still works — the writer just no-ops to the local outbox, losing nothing.
#
# Privacy: the recorder redacts secrets + PII and drops content before anything is stored, and drops
# work-session request text entirely. This hook passes the payload through untouched; the recorder
# owns minimization.

set -uo pipefail

payload="$(cat 2>/dev/null || true)"
[ -n "$payload" ] || exit 0

REC="$HOME/.claude/bin/config-metrics-record.py"
[ -f "$REC" ] || exit 0

PY="$HOME/.config/claude-metrics-venv/bin/python"
[ -x "$PY" ] || PY="$(command -v python3 || true)"
[ -n "$PY" ] || exit 0

# Never let recording block or fail the session end.
printf '%s' "$payload" | "$PY" "$REC" >/dev/null 2>&1 || true
exit 0
