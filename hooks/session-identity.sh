#!/usr/bin/env bash
# SessionStart hook: inject the work/personal identity VALUES into context every session.
#
# Why: the tracked config is generic (so it can be public), but the concrete work/personal facts must
# stay IN CONTEXT or adherence drops — a fact the model has to go open a file to find gets under-used
# (verified: lost-in-the-middle + two-hop retrieval). This hook re-surfaces the overlay's values as a
# terse, high-signal block every session, so what the model SEES is unchanged. SSOT: the values live
# once in identity.local.json; the guard reads them for enforcement, this reads them for context.
#
# CLAUDE_IDENTITY_FILE overrides the path (tests).

ID_FILE="${CLAUDE_IDENTITY_FILE:-$HOME/.claude/identity.local.json}"
command -v jq >/dev/null 2>&1 || exit 0

emit() { jq -cn --arg c "$1" '{hookSpecificOutput:{hookEventName:"SessionStart",additionalContext:$c}}'; }

if [ ! -f "$ID_FILE" ]; then
  emit "No ~/.claude/identity.local.json yet. Copy identity.example.json to it and fill in your work/personal accounts, so the work/personal boundary guard and this context work."
  exit 0
fi

wo="$(jq -r '.workOrgMatch // ""' "$ID_FILE" 2>/dev/null)"
we="$(jq -r '.workEmail // ""' "$ID_FILE" 2>/dev/null)"
pe="$(jq -r '.personalEmail // ""' "$ID_FILE" 2>/dev/null)"
wp="$(jq -r '(.workCloudProjects // []) | join(", ")' "$ID_FILE" 2>/dev/null)"
pp="$(jq -r '.personalCloudProject // ""' "$ID_FILE" 2>/dev/null)"

emit "Work/personal boundary (your identity overlay): WORK = ${we:-?}, cloud projects [${wp:-?}], git-origin match '${wo:-?}'. PERSONAL = ${pe:-?}, cloud project ${pp:-?}. Never cross work and personal resources; the guard enforces it, but keep them apart proactively."
