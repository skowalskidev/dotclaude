#!/usr/bin/env bash
# SessionStart hook: connector precheck. Harness-agnostic (Claude app, CLI, Conductor). EVENT-DRIVEN —
# runs at session start; NO timers, NO cron, NO `claude mcp list` (slow). Fast (<100ms), no-network.
#
# Two things, scoped to THIS project's manifest, and CAREFUL not to mislead:
#   (a) NEEDS RE-AUTH — a connector that IS available this session (present in ANY scope: local + user +
#       the committed .mcp.json) AND is flagged in ~/.claude/mcp-needs-auth-cache.json -> surface it up
#       front with the numbered step (auth-gate). Only ever flags a server that actually exists this
#       session, so it can't tell Claude a working connector is broken.
#   (b) NOT SET UP — a manifest MCP server genuinely absent from EVERY scope this session -> note it and
#       point to /sk:setup-connectors. Informational + conditional; it does NOT auto-provision, does NOT
#       order a restart, and does NOT claim an available server is missing.
# See rules/connectors.md (behavior) + references/connectors-setup.md (system).
set -u

PROVISION="$HOME/.claude/bin/connectors-provision.sh"
AUTHC="$HOME/.claude/mcp-needs-auth-cache.json"

command -v jq >/dev/null 2>&1 || exit 0
[ -x "$PROVISION" ] || exit 0

payload="$(cat 2>/dev/null)"
cwd="$(printf '%s' "$payload" | jq -r '.cwd // empty' 2>/dev/null)"
[ -n "$cwd" ] || cwd="$PWD"

manifest="$("$PROVISION" --manifest "$cwd" 2>/dev/null)"
[ -n "$manifest" ] && [ -f "$manifest" ] || exit 0

auth_step_for() { jq -r --arg n "$1" '.connectors[]? | select(.name==$n) | (.auth.steps[0] // "run /mcp and re-authenticate")' "$manifest" 2>/dev/null; }

# Classify from --check (availability is all-scopes): which servers are available vs genuinely not set up.
available=""; notset=""
while IFS="$(printf '\t')" read -r name kind env status; do
  [ -n "$name" ] || continue
  case "$status" in registered*) available="${available}${name}
" ;; esac
  # only a plain "missing" (not "on-demand", not "registered") counts as not-set-up, and only for MCP kinds
  case "$kind" in mcp-*) case "$status" in missing*) notset="${notset}${name} " ;; esac ;; esac
done <<EOF
$("$PROVISION" --check "$cwd" 2>/dev/null)
EOF

# (a) NEEDS RE-AUTH — only for servers that ARE available this session AND flagged needing auth.
needs=""
if [ -f "$AUTHC" ]; then
  flagged="$(jq -r 'keys[]?' "$AUTHC" 2>/dev/null)"
  while IFS= read -r n; do
    [ -n "$n" ] || continue
    printf '%s\n' "$available" | grep -qxF "$n" || continue
    printf '%s\n' "$flagged" | grep -qxF "$n" || continue
    needs="${needs}  - ${n} — $(auth_step_for "$n")
"
  done <<EOF
$(jq -r '.connectors[]?.name' "$manifest" 2>/dev/null)
EOF
fi

[ -z "$needs" ] && [ -z "$notset" ] && exit 0

msg="CONNECTOR PRECHECK for this project."
if [ -n "$needs" ]; then
  msg="${msg}

NEEDS RE-AUTHENTICATION (these ARE configured but the OAuth token is expired/absent — ONLY the user can fix it via /mcp; a hook/agent cannot). If the task uses one of these, ask the user FIRST with the numbered step, then WAIT; do not work around it or defer it to the end:
${needs}"
fi
if [ -n "$notset" ]; then
  msg="${msg}

NOT SET UP for this project this session (no tools are loaded for these): ${notset}
This matters ONLY if the task actually needs one of them. If it does, tell the user up front to run /sk:setup-connectors (it provisions them + reports any manual steps), then restart. Do NOT claim you can't do something that a DIFFERENT, already-loaded connector CAN do, and do NOT fabricate access. If a connector you need already works, just use it."
fi

jq -cn --arg c "$msg" '{hookSpecificOutput:{hookEventName:"SessionStart",additionalContext:$c}}'
exit 0
