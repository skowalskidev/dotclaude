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
# SHIP GATE (backs rules/process.md "Prove every point of the ask was built")
# A `git push` of a non-default branch from a repo other than ~/.claude is recorded in session state
# (PostToolUse). Stop blocks once per set of open pushes until `gate` records the harness result for
# the pushed head. The written rule is primary; this is the mechanical backstop for a push that
# skipped it.
#
# Modes:  submit                  UserPromptSubmit — append the ask verbatim
#         note <kind> <file>      called by the model — append sources|plan|pivot|reconcile
#         push                    PostToolUse (Bash) — record a pushed non-default branch and its head
#         gate <branch> <sha|HEAD> <PASS|BLOCKED|N/A> [light|standard|deep] [reason]
#                                 called by the model — record the landing-gate result for that head
#         stop                    Stop — require reconciliation after the newest recorded input, then
#                                 a gate record for every pushed branch head

set -uo pipefail

MODE="${1:-submit}"
REL=".context/intent-ledger.md"
STATE="$HOME/.claude/.intent-ledger"
CFG_ROOT="${CLAUDE_CONFIG_ROOT:-$HOME/.claude}"
LOGDIR="$HOME/.claude/logs"
LOCK_TRIES=20   # x 50ms = a 1s ceiling, because this sits on the user-prompt path
# Identical to dotfiles/secret-scan.sh's fallback gate. contracts/config_contracts.py pins the sync;
# a divergent copy of a secret regex is exactly the drift one-owner-per-concern exists to stop.
CRED_RE='(-----BEGIN [A-Z0-9 ]*PRIVATE KEY-----|AKIA[0-9A-Z]{16}|ghp_[A-Za-z0-9]{36}|gho_[A-Za-z0-9]{36}|sk-ant-[A-Za-z0-9-]{20,}|AIza[0-9A-Za-z_-]{35}|xox[baprs]-[A-Za-z0-9-]{10,})'

# Off-switches, checked before anything else so they disable the whole mechanism. CLAUDE_INTENT_LEDGER=off
# is the manual kill switch. AGENT_DELEGATED_WORKER=1 is set by the -p/exec launchers and the superspeed
# dispatcher on every headless worker: a machine-written worker prompt landing in a log whose value is
# that it is your words verbatim would be a forgery the reconciliation later judges against, and the
# supervisor owns this ledger.
[ "${CLAUDE_INTENT_LEDGER:-on}" = "off" ] && exit 0
[ "${AGENT_DELEGATED_WORKER:-}" = "1" ] && exit 0

# No sed fallback here, unlike task-intake.sh. sed cannot decode \n escapes, so it would write a
# corrupted record while claiming to be verbatim, which is worse than writing nothing.
command -v jq >/dev/null 2>&1 || exit 0

INPUT=""
case "$MODE" in note|gate) ;; *) INPUT="$(cat 2>/dev/null)" ;; esac
[ -n "$INPUT" ] || INPUT='{}'

jf() { printf '%s' "$INPUT" | jq -r "$1 // empty" 2>/dev/null; }

SID="$(jf '.session_id' | tr -cd '[:alnum:]._-')"
# `note` runs from the session's own shell with no payload, so it reads the id from the environment.
[ -n "$SID" ] || SID="$(printf '%s' "${CLAUDE_CODE_SESSION_ID:-}" | tr -cd '[:alnum:]._-')"
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
  # One session, one ledger: a shell that moved into a worktree nested under the session's own root
  # still belongs to that root. bin/session-root.sh owns the rule; task-intake.sh asks it too.
  if [ "$SID" != "unknown" ] && [ -x "$CFG_ROOT/bin/session-root.sh" ]; then
    kept="$("$CFG_ROOT/bin/session-root.sh" "$SID" "$cwd" 2>/dev/null)"
    [ -n "$kept" ] && [ -d "$kept" ] && root="$kept"
  fi
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

# Ship gate state. Pushes live in session state (tab-separated root, branch, head per push; the
# newest line per root+branch wins). Gate records live in the ledger as `gate: <branch> <sha> <STATUS>
# <reason>` lines under a "gate" heading, read fence-aware so a quoted prompt cannot forge one.
PUSHES="$STATE/$SID.pushes"

sha_match() { # two shas name one commit when the shorter (7+ chars) prefixes the longer
  [ "${#1}" -ge 7 ] && [ "${#2}" -ge 7 ] || return 1
  case "$1" in "$2"*) return 0 ;; esac
  case "$2" in "$1"*) return 0 ;; esac
  return 1
}

push_branch() { # push_branch ROOT DST — print the pushed branch, or fail when it does not count
  dst="${2#+}"
  cur="$(git -C "$1" symbolic-ref -q --short HEAD 2>/dev/null)"
  [ -n "$dst" ] || dst="$cur"
  [ "$dst" = HEAD ] && dst="$cur"
  case "$dst" in refs/heads/*) dst="${dst#refs/heads/}" ;; refs/*) return 1 ;; esac
  case "$dst" in ""|main|master) return 1 ;; esac
  printf '%s' "$dst"
}

record_push() { # record_push ROOT SRC DST
  b="$(push_branch "$1" "$3")" || return 0
  src="${2#+}"; [ -n "$src" ] || src=HEAD
  sha="$(git -C "$1" rev-parse --verify -q "$src^{commit}" 2>/dev/null)" || return 0
  printf '%s\t%s\t%s\n' "$1" "$b" "$sha" >> "$PUSHES" 2>/dev/null
}

gate_pairs() { # branch and sha of every recorded gate, outside prompt fences
  awk '
    { line=$0; sub(/^ */, "", line)
      if (line ~ /^(```|~~~)/) { mark=substr(line,1,1); match(line, "^" mark "+"); width=RLENGTH
        tail=substr(line,width+1)
        if (!fence) { fence=width; delimiter=mark; next }
        if (mark == delimiter && width >= fence && tail ~ /^[[:space:]]*$/) { fence=0; next } } }
    !fence && /^## [0-9][0-9][0-9][0-9]-/ { ingate = ($0 ~ / · gate$/) }
    !fence && ingate && /^gate: [^ ]+ [0-9a-f]+ (PASS|BLOCKED|N\/A)( |$)/ { print $2, $3 }
  ' "$1"
}

# Print "root<TAB>branch<TAB>sha" for each pushed branch head that has no gate record.
open_pushes() {
  [ -s "$PUSHES" ] || return 0
  gates="$(gate_pairs "$LEDGER")"
  awk -F'\t' '{ k=$1 FS $2; if (!(k in v)) order[++n]=k; v[k]=$3 }
    END { for (i=1;i<=n;i++) print order[i] FS v[order[i]] }' "$PUSHES" |
  while IFS="$(printf '\t')" read -r root branch sha; do
    found=0
    while read -r gb gs; do
      [ -n "$gb" ] || continue
      if [ "$gb" = "$branch" ] && sha_match "$gs" "$sha"; then found=1; break; fi
    done <<GATES
$gates
GATES
    [ "$found" -eq 1 ] || printf '%s\t%s\t%s\n' "$root" "$branch" "$sha"
  done
}

run_mode() {
case "$MODE" in

submit)
  prompt="$(jf '.prompt')"
  [ -n "$prompt" ] || exit 0

  # Harness-injected prompts are not Simon's asks: a background-task completion arrives as a
  # UserPromptSubmit whose entire body is a <task-notification> block, and some prompts are only a
  # <system-reminder> banner (e.g. a worktree notice). Recording either as an "ask" would emit a
  # GAUNTLET UPDATE and re-arm the Stop reconciliation check for something Simon never said. Strip
  # both block kinds (non-greedy, spanning newlines — jq's dotall flag is "m", not "s") and trim; if
  # nothing is left, this prompt is 100% harness output, so skip it silently before `resolve` even
  # runs, so no ledger is created for a skipped prompt. A real ask sitting behind a reminder banner
  # still has text left after stripping and is recorded below, ORIGINAL AND UNSTRIPPED, blocks
  # included — only this gate's decision uses the stripped copy.
  stripped="$(printf '%s' "$INPUT" | jq -r '(.prompt // "")
    | gsub("<task-notification>.*?</task-notification>"; ""; "mg")
    | gsub("<system-reminder>.*?</system-reminder>"; ""; "mg")
    | gsub("^\\s+|\\s+$"; "")' 2>/dev/null)"
  [ -n "$stripped" ] || exit 0

  resolve || exit 0

  redacted=0
  if printf '%s' "$prompt" | grep -qiE "$CRED_RE" 2>/dev/null; then
    prompt="$(printf '%s' "$prompt" | sed -E "s/$CRED_RE/[REDACTED CREDENTIAL]/g")"
    redacted=1
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
Mechanics: ~/.claude/references/planning-and-tracking.md. The Stop hook checks for reconciliation
after the newest recorded input. After a push to a non-default branch, run /sk:ship-full-detailed-workflow
on it and record the result with
  ~/.claude/hooks/intent-ledger.sh gate <branch> <sha|HEAD> PASS|BLOCKED|N/A [light|standard|deep] [reason]
or Stop blocks once for the missing gate."
  jq -cn --arg c "GAUNTLET UPDATE: read the new ask in $target and the existing living plan. Apply \
references/workflow-loops.md section Continuous request reconciliation before continuing: capture \
every added requirement, preserve unfinished items and the return point, then refresh the dashboard. \
Keep one deferred after-run analysis for the task batch per references/session-performance.md; run it \
after the requested work without waiting for peers. Apply rules/self-healing-config.md automatically \
for evidenced repairs and their sync/cleanup; no manual skill invocation is required. An answer or status question does not cancel \
older work. Recording an ask does not grant approval." \
    '{hookSpecificOutput:{hookEventName:"UserPromptSubmit",additionalContext:$c}}'
  exit 0
  ;;

note)
  kind="${2:-}"; src="${3:-}"
  case "$kind" in sources|plan|pivot|reconcile) ;; *)
    echo "note: kind must be sources|plan|pivot|reconcile" >&2; exit 2 ;;
  esac
  [ -f "$src" ] || { echo "note: no such file: $src" >&2; exit 2; }
  resolve || { echo "note: no ledger for this worktree (see the session's ledger notice)" >&2; exit 2; }
  # The source must never be the ledger. `cat ledger >> ledger` reads what it is appending, never
  # reaches end of file, and once grew a ledger to 170 GB. `-ef` is true for the same inode, so a
  # symlink, a hardlink or a relative spelling of the ledger is caught too, not only an equal string.
  # Checked before the lock and before any write; the refusal must also spare `rm -f "$src"` below,
  # which would otherwise delete the ledger.
  if [ "$src" -ef "$LEDGER" ]; then
    echo "note: refusing: $src is the ledger itself. Write the note to a scratch file and pass that." >&2
    exit 2
  fi
  # `rm -f "$src"` below consumes the source, so a durable record passed here is destroyed: a living
  # plan given as a reconcile source was appended and deleted, and the next intake recreated a blank
  # skeleton. Refuse any plan or dashboard under a `.context/` before writing anything.
  case "$src" in
    */.context/*-plan.md|.context/*-plan.md|*/.context/*-dashboard.html|.context/*-dashboard.html)
      echo "note: refusing: $src is a living plan or dashboard, and note deletes its source. Write the note to a scratch file and pass that." >&2
      exit 2 ;;
  esac
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
    rline="$(jq -n -c \
      --arg ts "$(date -u +%Y-%m-%dT%H:%M:%SZ)" \
      --arg repo "$(basename "$(dirname "$(dirname "$LEDGER")")")" \
      --argjson asks "$c_asks" --argjson sources "$c_src" --argjson pivots "$c_piv" \
      --argjson forced "$forced" \
      '{ts:$ts,repo:$repo,asks:$asks,sources:$sources,pivots:$pivots,stop_forced:$forced}' 2>/dev/null)"
    # ONE home: route through the shared writer (metrics store, else local outbox), never both.
    RPY="$HOME/.config/claude-metrics-venv/bin/python"; [ -x "$RPY" ] || RPY="$(command -v python3 || true)"
    if [ -n "$rline" ] && [ -n "$RPY" ] && [ -f "$HOME/.claude/bin/dotclaude-log.py" ]; then
      printf '%s' "$rline" | "$RPY" "$HOME/.claude/bin/dotclaude-log.py" intent_reconcile >/dev/null 2>&1 || true
    elif [ -n "$rline" ]; then
      mkdir -p "$LOGDIR" 2>/dev/null && printf '%s\n' "$rline" >> "$LOGDIR/intent-reconcile.jsonl" 2>/dev/null || true
    fi
  fi

  echo "Appended $kind to $LEDGER"
  exit 0
  ;;

push)
  # PostToolUse for Bash: runs only after a successful tool call. Handles `cd X && git -C Y push
  # origin branch`, several pushes in one command and refspecs; a delete, --tags, --all or --mirror
  # push, a push to main or master, and any repo inside the config repo record nothing.
  [ "$(jf '.tool_name')" = "Bash" ] || exit 0
  cmd="$(jf '.tool_input.command')"
  case "$cmd" in *push*) ;; *) exit 0 ;; esac
  cwd="$(jf '.cwd')"
  [ -n "$cwd" ] || cwd="${CLAUDE_PROJECT_DIR:-$PWD}"
  [ -d "$cwd" ] || exit 0
  cfg="$(cd -P "$CFG_ROOT" 2>/dev/null && pwd -P)"
  mkdir -p "$STATE" 2>/dev/null || exit 0
  dir="$cwd"
  printf '%s\n' "$cmd" | sed -E 's/(&&|\|\||[;|&])/\
/g' | while IFS= read -r seg; do
    read -ra w <<< "$seg"
    n=${#w[@]}
    [ "$n" -gt 0 ] || continue
    k=0
    while [ "$k" -lt "$n" ]; do w[$k]="${w[$k]//[\"\']/}"; k=$((k + 1)); done
    i=0
    while [ "$i" -lt "$n" ] && [[ "${w[$i]}" == *=* ]] && [[ "${w[$i]}" != -* ]]; do i=$((i + 1)); done
    [ "$i" -lt "$n" ] || continue
    if [ "${w[$i]}" = cd ]; then
      t="${w[$((i + 1))]:-}"; t="${t/#\~/$HOME}"
      if [ -n "$t" ] && nd="$(cd "$dir" 2>/dev/null && cd "$t" 2>/dev/null && pwd -P)"; then dir="$nd"; fi
      continue
    fi
    [ "${w[$i]}" = git ] || continue
    i=$((i + 1)); gdir="$dir"
    while [ "$i" -lt "$n" ]; do
      case "${w[$i]}" in
        -C) t="${w[$((i + 1))]:-}"; t="${t/#\~/$HOME}"
            if nd="$(cd "$gdir" 2>/dev/null && cd "$t" 2>/dev/null && pwd -P)"; then gdir="$nd"; fi
            i=$((i + 2)) ;;
        -c|--git-dir|--work-tree|--namespace) i=$((i + 2)) ;;
        -*) i=$((i + 1)) ;;
        *) break ;;
      esac
    done
    [ "${w[$i]:-}" = push ] || continue
    i=$((i + 1)); skip=0; pos=()
    while [ "$i" -lt "$n" ]; do
      case "${w[$i]}" in
        --delete|-d|--tags|--all|--mirror) skip=1 ;;
        --repo|-o|--push-option|--receive-pack|--exec) i=$((i + 1)) ;;
        -*) ;;
        *) pos+=("${w[$i]}") ;;
      esac
      i=$((i + 1))
    done
    [ "$skip" -eq 0 ] || continue
    root="$(git -C "$gdir" rev-parse --show-toplevel 2>/dev/null)" || continue
    root="$(cd -P "$root" 2>/dev/null && pwd -P)" || continue
    case "$root/" in "$cfg"/*) continue ;; esac
    if [ "${#pos[@]}" -le 1 ]; then
      cur="$(git -C "$root" symbolic-ref -q --short HEAD 2>/dev/null)"
      m="$(git -C "$root" config "branch.$cur.merge" 2>/dev/null)"
      record_push "$root" HEAD "${m:-$cur}"
    else
      for spec in "${pos[@]:1}"; do
        case "$spec" in
          :*) ;;   # empty source deletes the remote branch
          *:*) record_push "$root" "${spec%%:*}" "${spec#*:}" ;;
          *) record_push "$root" "$spec" "$spec" ;;
        esac
      done
    fi
  done
  find "$STATE" -type f -mtime +7 -delete 2>/dev/null
  exit 0
  ;;

gate)
  branch="${2:-}"; ref="${3:-}"; status="$(printf '%s' "${4:-}" | tr '[:lower:]' '[:upper:]')"
  # Optional tier (references/testing-strategy.md, Size the checks to the change). A light or
  # standard PASS skipped stages, so it needs a reason naming its trigger and the skips.
  tier="$(printf '%s' "${5:-}" | tr '[:upper:]' '[:lower:]')"
  case "$tier" in light|standard|deep) reason="${*:6}" ;; *) tier=""; reason="${*:5}" ;; esac
  usage="gate: usage: gate <branch> <sha|HEAD> <PASS|BLOCKED|N/A> [light|standard|deep] [reason]"
  case "$status" in PASS|BLOCKED|N/A) ;; *) echo "$usage" >&2; exit 2 ;; esac
  if [ -z "$branch" ] || [ -z "$ref" ]; then echo "$usage" >&2; exit 2; fi
  if [ "$status" != PASS ] && [ -z "$reason" ]; then
    echo "gate: $status needs a reason (the blocker, or why the harness does not apply)" >&2; exit 2
  fi
  if [ "$status" = PASS ] && [ -z "$reason" ] && { [ "$tier" = light ] || [ "$tier" = standard ]; }; then
    echo "gate: a $tier PASS needs a reason: its trigger and the stages it skipped" >&2; exit 2
  fi
  [ -n "$tier" ] && reason="$tier${reason:+ $reason}"
  sha="$(git rev-parse --verify -q "$ref^{commit}" 2>/dev/null)" || sha="$(printf '%s' "$ref" | tr '[:upper:]' '[:lower:]')"
  case "$sha" in *[!0-9a-f]*|"") echo "gate: cannot resolve $ref to a commit" >&2; exit 2 ;; esac
  [ "${#sha}" -ge 7 ] || { echo "gate: sha needs 7+ characters" >&2; exit 2; }
  resolve || { echo "gate: no ledger for this worktree (see the session's ledger notice)" >&2; exit 2; }
  acquire "$LEDGER" || { echo "gate: could not acquire the ledger lock" >&2; exit 2; }
  header_if_new "$LEDGER"
  {
    printf '\n## %s · gate\n\n' "$(date -u +%Y-%m-%dT%H:%M:%SZ)"
    printf 'gate: %s %s %s %s\n' "$branch" "$sha" "$status" "$reason"
  } >> "$LEDGER"
  echo "Recorded $status gate for $branch at ${sha:0:7} in $LEDGER"
  exit 0
  ;;

stop)
  # Loop safety, three independent guards. A Stop hook that re-blocks the finish it just caused is an
  # unbreakable session, which is the failure task-intake.sh documents for a different hook.
  #   1. stop_hook_active — the payload's own "you are already continuing because of a stop hook".
  #      Nothing blocks on it, with one bounded exception: the after-run block may follow THIS
  #      hook's own reconciliation block for the same request, so a reconciled task still gets its
  #      analysis. Each kind is single-use per request, so a request sees at most two blocks.
  #   2. markers for the exact ledger snapshot and the request, so unchanged work cannot re-block.
  #   3. a reason that names the exact command satisfying it, so there is always a way out.
  active="$(jf '.stop_hook_active')"
  mkdir -p "$STATE" 2>/dev/null || exit 0
  resolve || exit 0
  [ -f "$LEDGER" ] || exit 0

  # The reconciliation and after-run checks, unchanged. Run in a subshell so every exit 0 inside it
  # only ends this check and the ship gate below still runs after it.
  stop_ledger() {
  # Parse only actual entry headings, never a fake reconcile header inside a quoted prompt.
  # A reconciliation predating a later ask/plan/pivot cannot close that newer work.
  pending="$(awk '
    {
      line=$0; sub(/^ */, "", line)
      if (line ~ /^(```|~~~)/) {
        mark=substr(line,1,1)
        match(line, "^" mark "+"); width=RLENGTH
        tail=substr(line,width+1)
        if (!fence) { fence=width; delimiter=mark; next }
        if (mark == delimiter && width >= fence && tail ~ /^[[:space:]]*$/) { fence=0; next }
      }
    }
    !fence && /^## [0-9][0-9][0-9][0-9]-.* · (ask · session .+|plan|pivot)$/ { pending=1 }
    !fence && /^## [0-9][0-9][0-9][0-9]-.* · reconcile$/ { pending=0 }
    END { print pending+0 }
  ' "$LEDGER")"
  fence_ts() { awk -v kind="$1" '
    { line=$0; sub(/^ */, "", line)
      if (line ~ /^(```|~~~)/) { mark=substr(line,1,1); match(line, "^" mark "+"); width=RLENGTH
        tail=substr(line,width+1)
        if (!fence) { fence=width; delimiter=mark; next }
        if (mark == delimiter && width >= fence && tail ~ /^[[:space:]]*$/) { fence=0; next } } }
    !fence && $0 ~ ("^## [0-9][0-9][0-9][0-9]-[^ ]*Z · " kind) { ts=$2 }
    END { print ts }' "$LEDGER"; }
  ask_ts="$(fence_ts 'ask · session ')"
  reconciled="$(fence_ts 'reconcile$')"
  # Unreconciled work comes first: the turn is mid-task, so the after-run analysis waits for a
  # boundary and only the reconciliation below can block.
  if [ "$pending" != 1 ]; then
    # After-run analysis, run automatically. The helper owns the decision from facts the model does
    # not set: published reports (their publish time is the watermark, so a window is never analysed
    # twice), new tool calls, failures and corrections since that watermark, this turn's own work,
    # running background tasks, a pending wakeup and a closing question. It blocks the stop at most
    # once per user request (the marker below, written before speaking) and on a stop_hook_active
    # continuation only when this hook's own reconciliation block caused it, so it cannot loop.
    [ -n "$ask_ts" ] || exit 0
    [ "$(cat "$STATE/$SID.afterrun" 2>/dev/null)" = "$ask_ts" ] && exit 0
    if [ "$active" = "true" ] && [ "$(cat "$STATE/$SID.reconblock" 2>/dev/null)" != "$ask_ts" ]; then
      exit 0
    fi
    verdict="$(printf '%s' "$INPUT" | /usr/bin/python3 "$CFG_ROOT/bin/session-performance.py" due \
      --workspace "$root" --since "$ask_ts" --stop-payload - \
      ${reconciled:+--reconciled-at "$reconciled"} 2>/dev/null)"
    [ "$(printf '%s' "$verdict" | jq -r '.due' 2>/dev/null)" = "true" ] || exit 0
    printf '%s\n' "$ask_ts" > "$STATE/$SID.afterrun" 2>/dev/null || exit 0
    jq -cn --arg r "Run the after-run analysis now, before finishing: \
$(printf '%s' "$verdict" | jq -r '"\(.windowToolCalls) tool calls, \(.problems) failures or corrections"' 2>/dev/null) \
since this workspace's last published report. Invoke /sk:claude-config-self-optimize-analysis-after-run \
on that window's own evidence and publish it with bin/session-performance.py; a short no-finding or \
evidence-gap report counts. Publishing moves the watermark, so this window is never analysed twice." \
      '{decision:"block",reason:$r}'
    exit 0
  fi
  [ "$active" = "true" ] && exit 0
  snapshot="$(cksum < "$LEDGER")"
  [ "$(cat "$STATE/$SID.stopblock" 2>/dev/null)" = "$snapshot" ] && exit 0
  printf '%s\n' "$snapshot" > "$STATE/$SID.stopblock" 2>/dev/null || exit 0
  printf '%s\n' "$ask_ts" > "$STATE/$SID.reconblock" 2>/dev/null
  jq -cn --arg r "This worktree has recorded input newer than its last reconciliation. Before \
finishing: re-read $LEDGER and the living gauntlet plan, account for every request and remaining \
item, continue ready authorized work, and append the current outcomes with
  ~/.claude/hooks/intent-ledger.sh note reconcile <scratch.md>
Apply rules/self-healing-config.md; the after-run analysis is triggered separately once the work is reconciled. \
Record evidence for completed work and the next action for every real blocker or pause (not hypothetical checks; see rules/communication.md Close the session). An unapproved \
proposal remains recorded, not permission to implement. When nothing is left, end the final message with \
the archive line from rules/communication.md; with CI running, a session PR awaiting Simon's merge or a \
promised smoke or reply open, end with the merge list instead. This fires at most once per ledger snapshot." \
    '{decision:"block",reason:$r}'
  exit 0
  }
  out="$(stop_ledger)"
  if [ -n "$out" ]; then printf '%s\n' "$out"; exit 0; fi

  # Ship gate: every pushed branch head needs a gate record. It runs even on a stop_hook_active
  # continuation (a reconciliation block must not hide it) and is bounded by a marker on the exact
  # set of open pushes, so only a new push or a newer head re-opens it.
  open="$(open_pushes)"
  [ -n "$open" ] || exit 0
  gsnap="$(printf '%s' "$open" | cksum)"
  [ "$(cat "$STATE/$SID.shipgate" 2>/dev/null)" = "$gsnap" ] && exit 0
  printf '%s\n' "$gsnap" > "$STATE/$SID.shipgate" 2>/dev/null || exit 0
  list="$(printf '%s\n' "$open" | awk -F'\t' '{ printf "  %s (%s) at %s\n", $2, $1, substr($3,1,7) }')"
  msg="This session pushed these branches and recorded no ship-gate result for the pushed head:
$list
Before finishing, run /sk:ship-full-detailed-workflow on each at its tier (references/testing-strategy.md, \
Size the checks to the change; rules/process.md, Prove every point of the ask was built), then record it:
  ~/.claude/hooks/intent-ledger.sh gate <branch> <sha|HEAD> PASS|BLOCKED|N/A [light|standard|deep] [reason]
BLOCKED, N/A and a light or standard PASS need a reason: the exact blocker, why the harness does not \
apply to this push, or the tier's trigger and skipped stages. A gate \
recorded for an older head does not count once a newer head is pushed. This fires at most once per set of open pushes."
  jq -cn --arg r "$msg" '{decision:"block",reason:$r}'
  exit 0
  ;;

*) exit 0 ;;
esac
}

# Native hosts parse one JSON document. Several notices can fire on the first prompt
# (active, redaction, redirect, update); combine them without losing any message.
if [ "$MODE" = submit ]; then
  run_mode "$@" | jq -sc 'if length == 0 then empty else
    {hookSpecificOutput:{hookEventName:"UserPromptSubmit",additionalContext:
      (map(.hookSpecificOutput.additionalContext) | join("\n\n"))}} end'
else
  run_mode "$@"
fi
