#!/usr/bin/env bash
# Intent ledger. A per-worktree record of what you actually asked for, and whether it got built.
#
# WHAT IT IS FOR
# Source tickets and the plan that gets built diverge: facts get verified mid-run, parts get refuted,
# you redirect. By hand-back nothing on disk holds the version that was actually agreed, so the
# end report judges shipped work against a baseline missing the half that changed. This file is that
# missing half, written where the branch it describes lives.
#
# WHY IT IS THE ONLY HOOK THAT WRITES INTO A PROJECT
# Every other hook keeps state under ~/.claude. This one deliberately does not: the record has to sit
# beside the branch or the next session in this worktree cannot find it. That inversion is the whole
# risk, so the refusal list IS the contract, not a nicety.
#
# WHY IT IS THE ONLY WRITER
# Conductor allows several chats per workspace. A model Edit is a whole-file read-modify-write, so a
# second chat rewriting this file from a stale copy silently deletes asks appended since. The model
# therefore never edits it: it writes a scratch file and calls `note`, which appends under the lock.
#
# PRIVACY, STATED, BECAUSE IT INVERTS A NEIGHBOUR
# hooks/retro-trigger-log.sh records counts and signature names only, never prompt text. This hook
# inverts that on purpose and pays for it three ways: the refusals below, credential redaction at
# capture, and the standing ban on promoting verbatim prompt text out of the worktree
# (references/planning-and-tracking.md). The cross-run log it writes at logs/intent-reconcile.jsonl
# keeps the ORIGINAL posture: counts and enums only, never prompt text.
#
# Modes:  submit                  UserPromptSubmit — append the ask verbatim
#         note <kind> <file>      called by the model — append sources|plan|pivot|reconcile
#         stop                    Stop — block the finish when a ratified plan has no reconciliation

set -uo pipefail

MODE="${1:-submit}"
REL=".context/intent-ledger.md"
STATE="$HOME/.claude/.intent-ledger"
CFG_ROOT="${CLAUDE_CONFIG_ROOT:-$HOME/.claude}"
LOGDIR="$HOME/.claude/logs"
MAX_PROMPT=6000
LOCK_TRIES=20   # x 50ms = a 1s ceiling, because this sits on the user-prompt path
# Identical to dotfiles/secret-scan.sh's fallback gate. contracts/config_contracts.py pins the sync;
# a divergent copy of a secret regex is exactly the drift one-owner-per-concern exists to stop.
CRED_RE='(-----BEGIN [A-Z0-9 ]*PRIVATE KEY-----|AKIA[0-9A-Z]{16}|ghp_[A-Za-z0-9]{36}|gho_[A-Za-z0-9]{36}|sk-ant-[A-Za-z0-9-]{20,}|AIza[0-9A-Za-z_-]{35}|xox[baprs]-[A-Za-z0-9-]{10,})'

# Off-switch, checked before anything else so it disables the whole mechanism. /sk:work-superspeed's
# dispatcher sets this on every slice: a machine-written slice prompt landing in a log whose value is
# that it is your words verbatim would be a forgery the reconciliation later judges against.
[ "${CLAUDE_INTENT_LEDGER:-on}" = "off" ] && exit 0

# No sed fallback here, unlike task-intake.sh. sed cannot decode \n escapes, so it would write a
# corrupted record while claiming to be verbatim, which is worse than writing nothing.
command -v jq >/dev/null 2>&1 || exit 0

INPUT=""
[ "$MODE" = "note" ] || INPUT="$(cat 2>/dev/null)"
[ -n "$INPUT" ] || INPUT='{}'

jf() { printf '%s' "$INPUT" | jq -r "$1 // empty" 2>/dev/null; }

SID="$(jf '.session_id' | tr -cd '[:alnum:]._-')"
[ -n "$SID" ] || SID="unknown"

LEDGER=""
REDIRECTED=0

# emit_once KEY MSG — at most one additionalContext line per session per reason. Speak only when the
# state is dangerous or fixable; a hook that talks every turn trains the model to skim the channel
# task-intake.sh depends on.
emit_once() {
  mkdir -p "$STATE" 2>/dev/null || return 0
  m="$STATE/$SID.$1"
  [ -e "$m" ] && return 0
  : > "$m" 2>/dev/null || return 0
  jq -cn --arg c "$2" \
    '{hookSpecificOutput:{hookEventName:"UserPromptSubmit",additionalContext:$c}}'
  find "$STATE" -type f -mtime +7 -delete 2>/dev/null
}

LOCK=""
acquire() {
  LOCK="$1.lock"
  i=0
  while ! mkdir "$LOCK" 2>/dev/null; do
    i=$((i + 1))
    if [ "$i" -gt "$LOCK_TRIES" ]; then
      # A lock older than 2 min belonged to a process that died holding it. Break it; the
      # alternative is a ledger permanently unwritable after one crash.
      if [ -n "$(find "$LOCK" -maxdepth 0 -mmin +2 2>/dev/null)" ]; then
        rm -rf "$LOCK" 2>/dev/null; i=0; continue
      fi
      LOCK=""; return 1
    fi
    sleep 0.05
  done
  # EXIT only, and capture the real status FIRST — both lessons from bin/port-registry.sh. A trap on
  # EXIT INT TERM runs twice and can release a lock another process has since taken.
  trap 'rc__=$?; [ -n "$LOCK" ] && rm -rf "$LOCK" 2>/dev/null; exit $rc__' EXIT
  return 0
}

# A prompt routinely CONTAINS a triple backtick. CommonMark requires the fence be longer than any run
# inside it, so compute it. Indenting instead would mutate the text, and this file's only claim is
# that it is verbatim.
fence_for() {
  n="$(printf '%s' "$1" | grep -oE '`+' 2>/dev/null | awk '{ if (length($0) > m) m = length($0) } END { print m+0 }')"
  [ -z "$n" ] && n=0
  if [ "$n" -lt 3 ]; then n=3; else n=$((n + 1)); fi
  printf '%*s' "$n" '' | tr ' ' '`'
}

# resolve — set LEDGER, or return 1 after emitting (or not). The five outcomes ARE the safety
# contract; see the table in references/planning-and-tracking.md.
resolve() {
  cwd="$(jf '.cwd')"
  [ -n "$cwd" ] || cwd="${CLAUDE_PROJECT_DIR:-$PWD}"
  [ -d "$cwd" ] || return 1

  root="$(git -C "$cwd" rev-parse --show-toplevel 2>/dev/null)" || return 1
  [ -n "$root" ] || return 1                                  # not a git repo: routine, no fix
  root="$(cd -P "$root" 2>/dev/null && pwd -P)" || return 1
  [ "$root" = "$(cd -P "$HOME" 2>/dev/null && pwd -P)" ] && return 1   # $HOME is not a project

  # The config repo is PUSHED to GitHub, and `git check-ignore` returns 0 for any path inside it
  # because its .gitignore is an allowlist (`/*`). So the ignore test below is NOT the control here,
  # and this case must be caught by path. Redirect rather than disable: config work deserves a
  # reconciliation too, it just cannot live in the tracked tree.
  cfg="$(cd -P "$CFG_ROOT" 2>/dev/null && pwd -P)"
  case "$root/" in "$cfg"/*)
    slug="$(printf '%s' "$root" | tr -cs '[:alnum:]' '-' | sed 's/^-*//; s/-*$//')"
    mkdir -p "$STATE" 2>/dev/null || return 1
    LEDGER="$STATE/$slug.md"
    REDIRECTED=1
    return 0 ;;
  esac

  # Tracked beats ignored: a tracked path is published by the next commit no matter what the ignore
  # rules say, so this is checked first and named separately rather than left to check-ignore.
  if git -C "$root" ls-files --error-unmatch -- "$REL" >/dev/null 2>&1; then
    emit_once tracked "INTENT LEDGER DISABLED: $REL is git-TRACKED here, so appending prompts to it \
would publish them on the next commit. Nothing was written. Fix, then restart the session:
  git -C $root rm --cached $REL"
    return 1
  fi

  if ! git -C "$root" check-ignore -q -- "$REL" 2>/dev/null; then
    ex="$(git -C "$root" rev-parse --path-format=absolute --git-common-dir 2>/dev/null)/info/exclude"
    emit_once notignored "INTENT LEDGER DISABLED: $REL is not git-ignored here, so it would get \
committed. Nothing was written. Fix, then restart the session:
  printf '.context/\\n' >> $ex
(Or add .context/ to ~/.gitignore_global once, which covers every repo.)"
    return 1
  fi

  mkdir -p "$root/.context" 2>/dev/null || return 1           # unwritable: routine, no in-session fix
  LEDGER="$root/$REL"
  return 0
}

header_if_new() {
  [ -s "$1" ] && return 0
  printf '%s\n' \
'# Intent ledger

Every ask verbatim, the plan that was actually approved, each pivot, and the end-of-work
reconciliation of asked against built.

Written ONLY by ~/.claude/hooks/intent-ledger.sh. Never hand-edit it: a whole-file rewrite from
another chat in this workspace deletes asks appended since it was read. Append with
`~/.claude/hooks/intent-ledger.sh note sources|plan|pivot|reconcile <scratch.md>`.

Git-ignored, and it dies with this worktree. Promote what only it holds before teardown, per
~/.claude/references/planning-and-tracking.md. Never promote the verbatim prompts.
' >> "$1" 2>/dev/null
}

case "$MODE" in

submit)
  prompt="$(jf '.prompt')"
  [ -n "$prompt" ] || exit 0
  resolve || exit 0

  redacted=0
  if printf '%s' "$prompt" | grep -qiE "$CRED_RE" 2>/dev/null; then
    prompt="$(printf '%s' "$prompt" | sed -E "s/$CRED_RE/[REDACTED CREDENTIAL]/g")"
    redacted=1
  fi

  orig=${#prompt}; trunc=""
  if [ "$orig" -gt "$MAX_PROMPT" ]; then
    prompt="$(printf '%s' "$prompt" | cut -c1-"$MAX_PROMPT")"
    trunc="Truncated at $MAX_PROMPT of $orig characters. The ask is in the opening; the full paste is \
in the session transcript."
  fi

  target="$LEDGER"
  if ! acquire "$LEDGER"; then
    target="${LEDGER%.md}.$SID.md"   # never lose a prompt to contention
    emit_once lockfail "INTENT LEDGER: another session holds the lock, so this one is appending to \
$(basename "$target"). Fold it back into intent-ledger.md before teardown."
  fi

  header_if_new "$target"
  fence="$(fence_for "$prompt")"
  {
    printf '\n## %s · ask · session %s\n\n' "$(date -u +%Y-%m-%dT%H:%M:%SZ)" "$SID"
    [ "$redacted" -eq 1 ] && printf '> A credential-shaped value was REDACTED from this record.\n\n'
    [ -n "$trunc" ] && printf '> %s\n\n' "$trunc"
    printf '%s\n%s\n%s\n' "$fence" "$prompt" "$fence"
  } >> "$target" 2>/dev/null || exit 0

  [ "$redacted" -eq 1 ] && emit_once redacted "INTENT LEDGER: a credential-shaped value was redacted \
from a recorded prompt. Never re-paste it into a PR body, ticket, commit or log."
  [ "$REDIRECTED" -eq 1 ] && emit_once redirect "INTENT LEDGER: this worktree is inside the ~/.claude \
config repo, which is pushed to GitHub, so the ledger was redirected OUT of the tracked tree to \
$target. Nothing was written inside the repo."

  # ACTIVE is announced only AFTER a record is durably on disk. Every silent refusal above is safe
  # only because of that ordering: no announcement means no ledger, and the rule says do not create
  # one by hand.
  emit_once active "INTENT LEDGER ACTIVE for this worktree: $target
Every prompt is appended verbatim by the hook. Four sections are YOURS, and you add them only with
  ~/.claude/hooks/intent-ledger.sh note sources|plan|pivot|reconcile <scratch.md>
never with Edit or Write.
  sources   every ticket or source this work is judged against, by link; 'prompt-derived' when none.
  plan      the approach as approved, its delta from those sources, and what ratified it.
  pivot     each redirection, written when it lands, not reconstructed at the end.
  reconcile at hand-back on substantive work: one verdict per ask, tagged with its source.
Mechanics: ~/.claude/references/planning-and-tracking.md. A Stop hook will not let a ratified plan
finish without a reconciliation."
  exit 0
  ;;

note)
  kind="${2:-}"; src="${3:-}"
  case "$kind" in sources|plan|pivot|reconcile) ;; *)
    echo "note: kind must be sources|plan|pivot|reconcile" >&2; exit 2 ;;
  esac
  [ -f "$src" ] || { echo "note: no such file: $src" >&2; exit 2; }
  resolve || { echo "note: no ledger for this worktree (see the session's ledger notice)" >&2; exit 2; }
  acquire "$LEDGER" || { echo "note: could not acquire the ledger lock" >&2; exit 2; }
  header_if_new "$LEDGER"
  { printf '\n## %s · %s\n\n' "$(date -u +%Y-%m-%dT%H:%M:%SZ)" "$kind"; cat "$src"; printf '\n'; } \
    >> "$LEDGER"
  rm -f "$src"

  # Cross-run ratchet. Counts and enums only, never prompt text — the retro log's posture, kept.
  # One recurring shortfall across runs is a config defect; one in a single run is not.
  if [ "$kind" = "reconcile" ]; then
    # `grep -c` prints 0 AND exits 1 on no match, so a `|| echo 0` fallback emits TWO lines and
    # --argjson rejects it. Take the first line and keep digits only.
    count() { grep -c "$1" "$LEDGER" 2>/dev/null | head -1 | tr -dc '0-9'; }
    c_asks="$(count '· ask · session')";  [ -n "$c_asks" ] || c_asks=0
    c_src="$(count '· sources$')";        [ -n "$c_src" ] || c_src=0
    c_piv="$(count '· pivot$')";          [ -n "$c_piv" ] || c_piv=0
    forced=false; [ -e "$STATE/$SID.stopblock" ] && forced=true
    mkdir -p "$LOGDIR" 2>/dev/null && jq -n -c \
      --arg ts "$(date -u +%Y-%m-%dT%H:%M:%SZ)" \
      --arg repo "$(basename "$(dirname "$(dirname "$LEDGER")")")" \
      --argjson asks "$c_asks" --argjson sources "$c_src" --argjson pivots "$c_piv" \
      --argjson forced "$forced" \
      '{ts:$ts,repo:$repo,asks:$asks,sources:$sources,pivots:$pivots,stop_forced:$forced}' \
      >> "$LOGDIR/intent-reconcile.jsonl" 2>/dev/null || true
  fi

  echo "Appended $kind to $LEDGER"
  exit 0
  ;;

stop)
  # Loop safety, three independent guards. A Stop hook that re-blocks the finish it just caused is an
  # unbreakable session, which is the failure task-intake.sh documents for a different hook.
  #   1. stop_hook_active — the payload's own "you are already continuing because of a stop hook".
  #   2. a once-per-session marker, so a second fire is impossible even if that flag is absent.
  #   3. a reason that names the exact command satisfying it, so there is always a way out.
  [ "$(jf '.stop_hook_active')" = "true" ] && exit 0
  mkdir -p "$STATE" 2>/dev/null || exit 0
  [ -e "$STATE/$SID.stopblock" ] && exit 0

  resolve || exit 0
  [ -f "$LEDGER" ] || exit 0

  # Only a RATIFIED plan is a baseline. No plan means a conversational or exploratory session, and
  # nothing to reconcile against.
  grep -q '^## .* · plan$' "$LEDGER" 2>/dev/null || exit 0
  grep -qi '^ratified' "$LEDGER" 2>/dev/null || exit 0
  grep -q '^## .* · reconcile$' "$LEDGER" 2>/dev/null && exit 0

  : > "$STATE/$SID.stopblock" 2>/dev/null || exit 0
  jq -cn --arg r "This worktree's intent ledger has a ratified plan and no reconciliation, so the \
end-of-work comparison has not been done. Before finishing: re-read $LEDGER, give one verdict per \
recorded ask tagged with its source, and append it with
  ~/.claude/hooks/intent-ledger.sh note reconcile <scratch.md>
Anything asked and not built that was NEVER ratified is a proposal for the questions block, not work \
to start now. This fires at most once per session." \
    '{decision:"block",reason:$r}'
  exit 0
  ;;

*) exit 0 ;;
esac
