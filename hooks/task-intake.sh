#!/usr/bin/env bash
# UserPromptSubmit advisory: initialize/reuse one session plan and point at task routing.
# Authorization comes from the user and standing rules, never from a marker or a tool callback.
# CLAUDE_INTAKE_GATE=off is the manual kill switch. AGENT_DELEGATED_WORKER=1 (set by the -p/exec
# launchers) marks a headless worker: it never initializes or touches the supervisor's plan, and gets
# a one-line boundary notice instead, because the always-on living-plan rule still loads for it.
set -uo pipefail
[ "${1:-submit}" = "submit" ] || exit 0
[ "${CLAUDE_INTAKE_GATE:-on}" = "off" ] && exit 0
if [ "${AGENT_DELEGATED_WORKER:-}" = "1" ]; then
  # Its first prompt is a supervisor's brief, never Simon's words: record the session as learned-from
  # (`empty`) now, so the end-of-session learning queue never waits on it (bin/session_learning.py).
  _wsid="$(/usr/bin/python3 -c 'import json,sys
try: print(str(json.load(sys.stdin).get("session_id") or ""))
except (ValueError,TypeError,AttributeError): pass' 2>/dev/null | tr -cd '[:alnum:]._-')"
  [ -n "$_wsid" ] && /usr/bin/python3 "${CLAUDE_CONFIG_ROOT:-$HOME/.claude}/bin/session_learning.py" record "$_wsid" \
    --verdict empty --source "delegated worker: its prompts are a supervisor's brief" >/dev/null 2>&1
  printf '%s' '{"hookSpecificOutput":{"hookEventName":"UserPromptSubmit","additionalContext":"DELEGATED WORKER (AGENT_DELEGATED_WORKER=1): your supervisor owns the session plan, dashboard and intent ledger. Do not create, edit, update or reconcile any of them; return your result in your final message."}}'
  exit 0
fi
# The by-hand resume continues a stopped main session with a fixed
# machine prompt: the session keeps its own plan, and that prompt is never a new ask.
if [ "${AGENT_SESSION_RESUMED:-}" = "1" ]; then
  printf '%s' '{"hookSpecificOutput":{"hookEventName":"UserPromptSubmit","additionalContext":"AUTO-RESUMED SESSION (AGENT_SESSION_RESUMED=1): the hourly watchdog sent this prompt, not Simon. Keep your existing living plan and ledger, record no new ask, and continue the unfinished work."}}'
  exit 0
fi
CFG_ROOT="${CLAUDE_CONFIG_ROOT:-$HOME/.claude}"
INPUT="$(cat)"
json_field() {
  printf '%s' "$INPUT" | /usr/bin/python3 -c 'import json,sys
try:
 value=json.load(sys.stdin).get(sys.argv[1], "")
 print(value if isinstance(value,str) else "")
except (ValueError,TypeError): pass' "$1" 2>/dev/null
}
SESSION_ID="$(json_field session_id)"
SESSION_ID="$(printf '%s' "$SESSION_ID" | tr -cd '[:alnum:]._-')"
[ -n "$SESSION_ID" ] || exit 0
PROMPT="$(json_field prompt)"
[ -n "$PROMPT" ] || exit 0
# A prompt that is not Simon's own words opens no plan: a peer's <agent-message> or <cross-session-message>,
# a <task-notification> completion or a bare <system-reminder> banner is data for the existing record.
# Strip every such block (the same set hooks/intent-ledger.sh strips); nothing left means the whole
# prompt was harness output, so skip silently. A real ask behind a banner still initializes.
STRIPPED="$(printf '%s' "$PROMPT" | /usr/bin/python3 -c 'import re,sys
text=sys.stdin.read()
for tag in ("agent-message","cross-session-message","task-notification","system-reminder"):
    text=re.sub(r"<"+tag+r"\b[^>]*>.*?</"+tag+r">","",text,flags=re.S|re.I)
print(text.strip())')"
[ -n "$STRIPPED" ] || exit 0
LOWER="$(printf '%s' "$STRIPPED" | tr '[:upper:]' '[:lower:]')"
if printf '%s' "$LOWER" | grep -qE 'system notification - not user input|<task-notification>|automated background-task event|stop hook feedback'; then exit 0; fi
if printf '%s' "$LOWER" | grep -qE '^[[:space:]]*(y|n|yes|no|ok|okay|sure|go|go ahead|do it|proceed|continue|carry on|keep going|next|approved?|confirm(ed)?|sounds good|lgtm|ship it|option [0-9]|[0-9]+|thanks|thank you|ty|please do|yep|yeah|nope|correct|right|exactly|both|all|neither|stop|wait|hold on)[[:space:][:punct:]]*$'; then exit 0; fi
TASK_CWD="$(json_field cwd)"
[ -d "$TASK_CWD" ] || TASK_CWD="${CLAUDE_PROJECT_DIR:-$PWD}"
if [ -x "$CFG_ROOT/bin/session-root.sh" ]; then
  KEPT_ROOT="$("$CFG_ROOT/bin/session-root.sh" "$SESSION_ID" "$TASK_CWD" 2>/dev/null)"
  [ -n "$KEPT_ROOT" ] && [ -d "$KEPT_ROOT" ] && TASK_CWD="$KEPT_ROOT"
fi
DASHBOARD_CONTEXT="Dashboard initialization unavailable; locate the existing session plan."
if [ -f "$CFG_ROOT/bin/workflow-dashboard.py" ]; then
  INIT_OUTPUT="$(/usr/bin/python3 "$CFG_ROOT/bin/workflow-dashboard.py" init --root "$TASK_CWD" --slug "session-$SESSION_ID" 2>&1)"
  if [ "$?" -eq 0 ]; then
    DASHBOARD_PATH="$(printf '%s\n' "$INIT_OUTPUT" | sed -n 's/^DASHBOARD_PATH=//p' | tail -1)"
    PLAN_PATH="$(printf '%s\n' "$INIT_OUTPUT" | sed -n 's/^PLAN_PATH=//p' | tail -1)"
    DASHBOARD_CONTEXT="Session record ready. PLAN_PATH=$PLAN_PATH DASHBOARD_PATH=$DASHBOARD_PATH"
  else
    DASHBOARD_CONTEXT="Dashboard initialization failed: $INIT_OUTPUT"
  fi
fi
CONTEXT="TASK ROUTING
$DASHBOARD_CONTEXT
Apply rules/living-plan.md: initialize the task in this record or reconcile new requests into its existing work, then regenerate its dashboard. For a task that produces a change, run /sk:work-full-detailed-workflow as the spine, with the matching installed skill from references/skill-stack.md as a stage inside it; its final stage runs /sk:ship-full-detailed-workflow on every PR the work opened or pushed. Use existing explicit or standing authorization and continue the authorized work. Ask only for unresolved consequential choices, missing access, production writes or paid calls. No generic confirmation or AskUserQuestion callback is required. Keep engine=current and gauntlet=false unless another mode was requested."
# Open monitoring-only PRs (bin/monitoring_only.py owns the class): one gh call per session, only in a
# repo whose overlay declares the paths, silent when there are none or gh fails. Event-driven pickup,
# never a watcher (references/git-pr-deploy.md § Monitoring-only changes).
# bash's SECONDS counts from the hook's start: with under 6 s of the 10 s hook left, the listing waits for
# the next prompt rather than risk the whole routing context.
if [ -f "$CFG_ROOT/bin/monitoring_only.py" ] && [ "${SECONDS:-0}" -le 3 ]; then
  MONITORING_LINE="$(/usr/bin/python3 "$CFG_ROOT/bin/monitoring_only.py" pending --cwd "$TASK_CWD" --session "$SESSION_ID" 2>/dev/null)"
  [ -n "$MONITORING_LINE" ] && CONTEXT="$CONTEXT
$MONITORING_LINE"
fi
printf '%s' "$CONTEXT" | /usr/bin/python3 -c 'import json,sys; print(json.dumps({"hookSpecificOutput":{"hookEventName":"UserPromptSubmit","additionalContext":sys.stdin.read()}}))'
