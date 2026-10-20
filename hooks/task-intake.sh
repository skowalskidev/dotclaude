#!/usr/bin/env bash
# UserPromptSubmit advisory: initialize/reuse one session plan and point at task routing.
# Authorization comes from the user and standing rules, never from a marker or a tool callback.
# CLAUDE_INTAKE_GATE=off retains the headless dispatcher's plan-initialization opt-out.
set -uo pipefail
[ "${1:-submit}" = "submit" ] || exit 0
[ "${CLAUDE_INTAKE_GATE:-on}" = "off" ] && exit 0
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
LOWER="$(printf '%s' "$PROMPT" | tr '[:upper:]' '[:lower:]')"
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
Apply rules/living-plan.md: initialize the task in this record or reconcile new requests into its existing work, then regenerate its dashboard. Read references/skill-stack.md and use the matching installed skill. Use existing explicit or standing authorization and continue the authorized work. Ask only for unresolved consequential choices, missing access, production writes or paid calls. No generic confirmation or AskUserQuestion callback is required. Keep engine=current and gauntlet=false unless another mode was requested."
printf '%s' "$CONTEXT" | /usr/bin/python3 -c 'import json,sys; print(json.dumps({"hookSpecificOutput":{"hookEventName":"UserPromptSubmit","additionalContext":sys.stdin.read()}}))'
