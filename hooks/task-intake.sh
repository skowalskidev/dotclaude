#!/usr/bin/env bash
# Task-intake gate. Three hook events, one state file.
#
# WHAT IT IS FOR
# You should never have to remember which skill, rule or reference fits the task you are about to
# hand over. And when you hand one over and walk away, you want the proposal — what Claude will do
# and what it will use — BEFORE any of it starts, with a real stop to answer, not a question asked
# into the void while sub-agents are already burning tokens on the wrong plan.
#
# HOW IT WORKS (the instruction alone is not enough — an instruction is advisory, a hook is not)
#   UserPromptSubmit  -> new substantive task? inject the intake protocol, arm the gate.
#   PreToolUse        -> Agent/Task/Workflow while the gate is armed: DENY. This is the part that
#                        actually stops a runaway fan-out; the injected text only asks nicely.
#   PostToolUse       -> AskUserQuestion returned, so the user has answered: disarm.
#
# WHY IT DOES NOT FIRE CONSTANTLY
# Compliance decays as instruction count rises, so a gate that nags every turn trains you to ignore
# it. It arms on a task OPENING and stays quiet for the follow-ups inside that task.
#
# FAIL-SAFE, DELIBERATELY
# It disarms itself whenever a stop would be wrong rather than merely annoying: an explicit standing
# authorization in the prompt ("I'll be asleep, don't ask me"), CLAUDE_INTAKE_GATE=off, or too many
# denials in one session. A gate that deadlocks a headless run is worse than no gate.
#
# THE HEADLESS DEADLOCK, AND WHY THE FIX IS NOT AUTO-DETECTION (2026-08-06)
# This header used to claim it disarmed on "a non-interactive run". It did not — there was no such
# check, and the claim was false for two years. A benchmark run cost $2.59 and produced nothing: all
# four Agent calls were denied, and `AskUserQuestion` does not exist in a `claude -p` session, so the
# gate could never be disarmed. The same wall kills fan-out from background agents, scheduled tasks,
# CI and the Agent SDK, and it fails AFTER the model has done the reading, so it burns the tokens first.
#
# Auto-detection was tried and does not work. Measured on this machine, inside an ordinary interactive
# Conductor session: `CLAUDE_CODE_CHILD_SESSION=1` and `tty` reports "not a tty" — identical to what a
# headless run shows. `CLAUDE_CODE_ENTRYPOINT` is `cli` for BOTH `claude -p` and interactive `claude`.
# There is no env signal that separates them, so anything built on one would silently disable the gate
# everywhere. Hence two real layers instead:
#   1. The DISPATCHER sets CLAUDE_INTAKE_GATE=off on every headless slice it launches. /sk:work-superspeed
#      does this for every slice, which covers the case that actually broke.
#   2. This gate FAILS OPEN after MAX_DENIALS refusals in one session. An interactive Claude needs one
#      denial to get the message; a headless one now loses a few tool calls instead of the whole run.
#
# Invoked as: task-intake.sh submit | guard | answered   (wired in settings.json)

set -uo pipefail

MODE="${1:-submit}"
STATE_DIR="$HOME/.claude/.session-intake"
INPUT="$(cat)"

# Off-switch, checked in every mode so it disables the whole mechanism, not just the arming.
[ "${CLAUDE_INTAKE_GATE:-on}" = "off" ] && exit 0

json_field() {
  # $1 = jq path. Falls back to a sed extraction so the gate still works without jq.
  if command -v jq >/dev/null 2>&1; then
    printf '%s' "$INPUT" | jq -r "$1 // empty" 2>/dev/null
  else
    printf '%s' "$INPUT" | sed -n "s/.*\"${1##*.}\"[[:space:]]*:[[:space:]]*\"\([^\"]*\)\".*/\1/p" | head -1
  fi
}

SESSION_ID="$(json_field '.session_id')"
[ -z "$SESSION_ID" ] && exit 0
# Never let a crafted session_id escape the state dir.
SESSION_ID="$(printf '%s' "$SESSION_ID" | tr -cd '[:alnum:]._-')"
[ -z "$SESSION_ID" ] && exit 0
MARKER="$STATE_DIR/$SESSION_ID.armed"

case "$MODE" in

answered)
  # The user answered an AskUserQuestion. The gate has done its job for this task.
  rm -f "$MARKER" "$MARKER.denials" 2>/dev/null
  exit 0
  ;;

guard)
  # A fan-out tool wants to start. Deny only while the gate is armed.
  [ -f "$MARKER" ] || exit 0

  # Staleness escape hatch. The `answered` disarm depends on the PostToolUse matcher in
  # settings.json actually matching whatever AskUserQuestion tool the session has — and in a
  # Conductor session the ONLY variant is `mcp__conductor__AskUserQuestion`, which the original
  # literal `AskUserQuestion` matcher never caught. The gate armed and could never be disarmed, so
  # every Agent/Workflow call was denied for the rest of the session even though the user had answered.
  # (2026-08-03, XCAL-284: cost a whole run's parallelism.)
  #
  # The matcher is fixed, but the failure mode is silent and total, so it does not get to recur:
  # this gate is meant to stop a fan-out that starts BEFORE the proposal, which is a
  # seconds-to-minutes window. A marker still armed 30 minutes later means the disarm is broken, not
  # that the user is still deciding — and per the FAIL-SAFE note above, a gate that deadlocks is worse
  # than no gate.
  if [ -n "$(find "$MARKER" -mmin +30 2>/dev/null)" ]; then
    rm -f "$MARKER" "$MARKER.denials" 2>/dev/null
    exit 0
  fi

  TOOL="$(json_field '.tool_name')"
  case "$TOOL" in
    Agent|Task|Workflow) ;;
    *) exit 0 ;;
  esac

  # FAIL OPEN after repeated denials. See the headless note in the header: there is no env signal that
  # distinguishes a `claude -p` run from an interactive one, so the gate cannot know whether anyone is
  # able to answer. One denial is all an interactive Claude needs to read the reason and comply. A
  # session that keeps hitting this is one that CANNOT comply, and denying it forever is the deadlock.
  MAX_DENIALS=3
  COUNT_FILE="$MARKER.denials"
  COUNT="$(cat "$COUNT_FILE" 2>/dev/null || echo 0)"
  case "$COUNT" in ''|*[!0-9]*) COUNT=0 ;; esac
  if [ "$COUNT" -ge "$MAX_DENIALS" ]; then
    rm -f "$MARKER" "$COUNT_FILE" 2>/dev/null
    exit 0
  fi
  printf '%s' "$((COUNT + 1))" > "$COUNT_FILE" 2>/dev/null
  REASON="Task-intake gate is armed: this prompt opened new substantive work and the user has not yet \
confirmed the approach. ${TOOL} would spawn background sub-processes that keep running after the \
question is asked, which is exactly what they asked to be gated.

Do this first, in one turn:
  1. Say what you understand the task to be, in one or two lines.
  2. List the skills, rules and references you propose to use, and why each one.
  3. Ask for anything you will predictably need from him later (auth, credentials, prod approval,
     any decision that forks the work) — all of it now, in ONE block.
  4. Call AskUserQuestion to confirm or redirect. That blocks for a real answer and disarms this
     gate. Nothing else disarms it.

If he has already given standing authorization to proceed without him, say so and re-run with \
CLAUDE_INTAKE_GATE=off rather than working around this."
  if command -v jq >/dev/null 2>&1; then
    jq -cn --arg r "$REASON" \
      '{hookSpecificOutput:{hookEventName:"PreToolUse",permissionDecision:"deny",permissionDecisionReason:$r}}'
  else
    printf '%s\n' "$REASON" >&2
    exit 2
  fi
  exit 0
  ;;

submit)
  PROMPT="$(json_field '.prompt')"
  [ -z "$PROMPT" ] && exit 0
  LOWER="$(printf '%s' "$PROMPT" | tr '[:upper:]' '[:lower:]')"
  LEN=${#PROMPT}

  # 1. Standing authorization to run unattended. The user says this when handing the session over
  #    for the night; stopping to ask would defeat the whole point of them saying it.
  # The phrasings below are collected from real handovers, not imagined. "i wont be here to answer
  # qs" was added on 2026-08-03 after the gate armed on exactly that sentence and would have
  # deadlocked the session it was written for. Add to this list whenever a live one slips through.
  if printf '%s' "$LOWER" | grep -qE "don'?t ask me|do not ask me|no questions|without asking|answer (all of )?(your|the) (own )?questions|ask and answer (by )?your ?self|i('| a)?m going to sleep|i will be sleeping|i'?ll be sleeping|while i sleep|don'?t stop to ask|proceed without|no need to ask|won'?t be (here|around|available)|wont be (here|around|available)|not (be )?(here|around|available) to answer|to answer (any )?(qs|questions)|unattended|go until you exhaust|until (you )?(exhaust|run out)"; then
    rm -f "$MARKER" "$MARKER.denials" 2>/dev/null
    exit 0
  fi

  # 2. Short replies and continuations are follow-ups inside a task that was already gated.
  if [ "$LEN" -lt 180 ] && printf '%s' "$LOWER" | grep -qE '^[[:space:]]*(y|n|yes|no|ok|okay|sure|go|go ahead|do it|proceed|continue|carry on|keep going|next|approved?|confirm(ed)?|sounds good|lgtm|ship it|option [0-9]|[0-9]+|thanks|thank you|ty|please do|yep|yeah|nope|correct|right|exactly|both|all|neither|stop|wait|hold on)[[:space:][:punct:]]*$'; then
    exit 0
  fi

  # 3. Arm on a task OPENING. Either it is long enough to be a brief, or it starts with a work verb.
  ARM=0
  [ "$LEN" -ge 180 ] && ARM=1
  printf '%s' "$LOWER" | grep -qE '^[[:space:]]*(please[[:space:]]+)?(add|build|implement|create|write|refactor|migrate|fix|debug|investigate|audit|review|clean ?up|reorganis|reorganiz|optimis|optimiz|upgrade|update|remove|delete|rename|extract|centralis|centraliz|test|deploy|ship|set up|setup|integrate|port|convert|rewrite|redesign|research|plan|design)\b' && ARM=1
  [ "$ARM" -eq 0 ] && exit 0

  mkdir -p "$STATE_DIR" 2>/dev/null || exit 0
  : > "$MARKER" 2>/dev/null || exit 0
  rm -f "$MARKER.denials" 2>/dev/null

  # Prune markers from sessions that ended days ago so this never becomes an unbounded directory.
  find "$STATE_DIR" -name '*.armed' -mtime +2 -delete 2>/dev/null
  find "$STATE_DIR" -name '*.armed.denials' -mtime +2 -delete 2>/dev/null

  CONTEXT="TASK INTAKE GATE (armed for this prompt — Agent/Task/Workflow are BLOCKED until you clear it).

You do not want to have to remember which skill fits a task, and you may hand this session over
and walk away. So before any work starts, in THIS turn:

  1. State what you take the task to be, in one or two lines.
  2. Survey what is available and propose what you will use, with a reason each. READ
     ~/.claude/references/skill-stack.md — it maps task shapes to the right spine skill and to what
     genuinely stacks on top, so you do not have to guess from names alone. It covers:
       - your own skills (/sk:*, and your work-skills plugin, e.g. /sk-work:*) as the spine
       - third-party packs worth stacking — label the repo ([gstack], [impeccable], …)
       - the always-on rules and on-demand reference catalogs that bear on this task
     If nothing fits, say that plainly. Do not force a skill on; one that fits beats three that
     half-fit.
     Also decide HOW to run it, not just what with: does the work split into independent pieces that
     can run at once? Parallelise independent work by default. If it divides into ~3-5+ genuinely
     independent slices, propose /sk:work-superspeed; for a smaller independent fan-out, parallel
     in-session agents. Don't overdo it — superspeed only earns its harness at 3-5+ real slices, and
     serial is right for work that does not divide (references/parallelization.md).
  3. Front-load every predictable ask in ONE block: auth or logins, credentials, prod approval,
     billable API calls, and any decision where guessing wrong wastes the work.
  4. Call AskUserQuestion to confirm or redirect. It blocks for a real answer, and it is the only
     thing that disarms this gate.

Keep it to a few lines. This is a go/no-go, not a plan document — the plan comes after he says go."

  if command -v jq >/dev/null 2>&1; then
    jq -cn --arg c "$CONTEXT" \
      '{hookSpecificOutput:{hookEventName:"UserPromptSubmit",additionalContext:$c}}'
  else
    printf '%s\n' "$CONTEXT"
  fi
  exit 0
  ;;

*)
  exit 0
  ;;
esac
