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
# STAGE RECEIPTS (the harness's "every stage ran as its own skill on this head", made mechanical)
# Each invocation of a ship stage skill (Skill tool, a typed /sk:<stage> prompt, or a Codex read of
# its SKILL.md mapped by bin/agent_runtime.py) appends `receipt: <skill> <branch> <head>` to the
# ledger, head = HEAD of the checkout the work runs in (work_checkout below). `gate PASS` refuses unless the tier's every stage
# has a receipt on the gated sha; a receipt on an older head never counts. The list below is the
# one home of which stages each tier requires.
#
# Modes:  submit                  UserPromptSubmit — append the ask verbatim (and a receipt for a
#                                 typed /sk:<stage> command)
#         note <kind> <file>      called by the model — append sources|plan|pivot|reconcile
#         push                    PostToolUse (Bash) — record a pushed non-default branch and its head
#         skill                   PostToolUse (Skill) — record a stage receipt for the HEAD of the checkout
#                                 the work runs in: a subagent's (agent_id) last explicit Bash checkout,
#                                 else the payload cwd
#         receipt <stage> [dir]   called by a delegated worker from its OWN checkout — record a stage
#                                 receipt for the HEAD of <dir> (default: the shell's cwd), in the
#                                 session's ledger. The fallback when a Skill receipt missed its checkout
#                                 (a subagent that never ran a Bash `cd`/`git -C` into it).
#         stages <tier> [sha|HEAD]
#                                 read-only — print the tier's required stage skills; with a sha,
#                                 print "All stages ran" (exit 0) or "Not run: <stage>, ..." (exit 1)
#         gate <branch> <sha|HEAD> <PASS|BLOCKED|N/A> [light|standard|deep] [reason]
#                                 called by the model — record the landing-gate result for that head;
#                                 a PASS names its tier and every stage that tier requires has a
#                                 receipt on <sha>, else exit 2 printing "Not run: <stage>, ...";
#                                 a standard or deep BLOCKED reason holds "All stages ran" or
#                                 "Not run: <stage>, <stage>" naming every stage with no receipt;
#                                 "All stages ran" at any tier needs the receipts; a standard or
#                                 deep PASS reason holds "All stages ran" and no "Not run:" list
#                                 (exit 2 otherwise);
#                                 PASS for a branch with an open PR records only when
#                                 bin/pr-landing-gate.py passes on the fetched PR and
#                                 bin/pr-ci-wait.py --once finds every check green on <sha>
#                                 (exit 1 otherwise)
#         latest-ask [--since <ts>]
#                                 PreToolUse helper — print this session's newest recorded ask, verbatim
#                                 (stdin payload: session_id, cwd); prints nothing when none. Read-only.
#                                 With --since (UTC, YYYY-MM-DDTHH:MM:SSZ) it prints EVERY ask recorded
#                                 at or after that second, oldest first, separated by an ASCII RS (\036).
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
case "$MODE" in note|gate|stages|receipt) ;; *) INPUT="$(cat 2>/dev/null)" ;; esac
[ -n "$INPUT" ] || INPUT='{}'

jf() { printf '%s' "$INPUT" | jq -r "$1 // empty" 2>/dev/null; }

SID="$(jf '.session_id' | tr -cd '[:alnum:]._-')"
# `note` and `gate` run from the session's own shell with no payload, so they read the id from the
# environment. Every other mode takes it from its payload only: a test or tool subprocess inherits the
# live session's CLAUDE_CODE_SESSION_ID, and reading it there let a temp-repo test re-anchor the live
# session's record (the fix for a nested-worktree ask that opened a second ledger and hid a standing merge).
case "$MODE" in note|gate|stages|receipt)
  [ -n "$SID" ] || SID="$(printf '%s' "${CLAUDE_CODE_SESSION_ID:-}" | tr -cd '[:alnum:]._-')" ;;
esac
[ -n "$SID" ] || SID="unknown"

LEDGER=""
REDIRECTED=0

# emit_once KEY MSG — at most one additionalContext line per session per reason. Speak only when the
# state is dangerous or fixable; a hook that talks every turn trains the model to skim the channel
# task-intake.sh depends on.
emit_once() {
  [ "${QUIET:-0}" = "1" ] && return 0
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

  # One session, one ledger, keyed by session id and anchored where the session started: a shell
  # that moved anywhere, a nested worktree included, still reads and writes that root's ledger.
  # bin/session-root.sh owns the rule; task-intake.sh and workflow-dashboard.py ask it too.
  root=""
  if [ "$SID" != "unknown" ] && [ -x "$CFG_ROOT/bin/session-root.sh" ]; then
    root="$("$CFG_ROOT/bin/session-root.sh" "$SID" "$cwd" 2>/dev/null)"
  fi
  [ -n "$root" ] && [ -d "$root" ] || root="$cwd"
  root="$(git -C "$root" rev-parse --show-toplevel 2>/dev/null)" || return 1
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
  # The remote branch is the pushed head. A delegated shell that cd'ed in an earlier call reports the
  # session's cwd, so a local rev-parse can name another checkout's commit; the local ref is only the
  # fallback when the remote cannot be read.
  sha="$(GIT_TERMINAL_PROMPT=0 git -C "$1" ls-remote origin "refs/heads/$b" 2>/dev/null | cut -f1 | head -n 1)"
  [ -n "$sha" ] || sha="$(git -C "$1" rev-parse --verify -q "$src^{commit}" 2>/dev/null)" || return 0
  printf '%s\t%s\t%s\n' "$1" "$b" "$sha" >> "$PUSHES" 2>/dev/null
}

# landing_check BRANCH SHA — 0 when the branch has no open PR on a GitHub origin, or when
# bin/pr-landing-gate.py passes on that PR AND bin/pr-ci-wait.py --once finds every check on SHA
# succeeded or skipped. Otherwise prints why and fails, so `gate PASS` records nothing. A PR that
# cannot be looked up or fetched fails: a fetch failure never passes. No reason text bypasses red CI.
landing_check() {
  url="$(git remote get-url origin 2>/dev/null)" || return 0
  repo="$(printf '%s' "$url" | sed -nE 's#^(https://([^@/]+@)?|ssh://git@|git@)github\.com[:/]([^/]+/[^/]+)$#\3#p')"
  repo="${repo%/}"; repo="${repo%.git}"
  [ -n "$repo" ] || return 0                                  # not a GitHub origin: no PR to check
  if ! command -v gh >/dev/null 2>&1; then
    echo "gate: PASS refused: gh is missing, so open PRs for $1 on $repo cannot be checked" >&2
    return 1
  fi
  prs="$(gh pr list --repo "$repo" --head "$1" --state open --json number,url 2>/dev/null)" || {
    echo "gate: PASS refused: gh pr list failed for $1 on $repo (a fetch failure never passes)" >&2
    return 1; }
  num="$(printf '%s' "$prs" | jq -r '.[0].number // empty' 2>/dev/null)"
  [ -n "$num" ] || return 0                                   # no open PR: unchanged behaviour
  out="$(python3 "$CFG_ROOT/bin/pr-landing-gate.py" --repo "$repo" --pr "$num" 2>&1)" || {
    printf '%s\n' "$out" >&2
    echo "gate: PASS refused for $1: $repo#$num fails the landing gate above. Post each missing \
row to the PR body, then rerun gate PASS; or record BLOCKED with the blocker." >&2
    return 1; }
  printf '%s\n' "$out"
  # SHA is the full id when this checkout has the commit; pr-ci-wait also matches a 7+ hex prefix.
  ci="$(python3 "$CFG_ROOT/bin/pr-ci-wait.py" --repo "$repo" --pr "$num" --sha "$2" --once 2>&1)"
  rc=$?
  if [ "$rc" -ne 0 ]; then
    printf '%s\n' "$ci" >&2
    echo "gate: PASS refused for $1: CI on $repo#$num at ${2:0:12} is not all green (pr-ci-wait exit $rc). \
Fix the failing check in this PR, or wait for the pending one, then rerun gate PASS; a check failing \
\"by design\" is a finding, never a PASS. Otherwise record BLOCKED with the blocker." >&2
    return 1
  fi
  printf '%s\n' "$ci"
  return 0
}

section_lines() { # section_lines KIND FILE — every line under a "## <ts> · KIND" heading, outside prompt fences
  awk -v kind="$1" '
    { line=$0; sub(/^ */, "", line)
      if (line ~ /^(```|~~~)/) { mark=substr(line,1,1); match(line, "^" mark "+"); width=RLENGTH
        tail=substr(line,width+1)
        if (!fence) { fence=width; delimiter=mark; next }
        if (mark == delimiter && width >= fence && tail ~ /^[[:space:]]*$/) { fence=0; next } } }
    !fence && /^## [0-9][0-9][0-9][0-9]-/ { insec = ($0 ~ (" · " kind "$")); next }
    !fence && insec { print }
  ' "$2"
}

gate_pairs() { # branch and sha of every recorded gate, outside prompt fences
  section_lines gate "$1" | awk '/^gate: [^ ]+ [0-9a-f]+ (PASS|BLOCKED|N\/A)( |$)/ { print $2, $3 }'
}

# The stage skills each tier requires on the recorded head: the ONE home of this list. The gate, the
# Stop message, `stages` and the receipt recorder read it; skills/sk/skills/ship-full-detailed-workflow
# runs the stages and references/testing-strategy.md § Size the checks to the change sizes them.
# Conditional legs (/security-review, test-eyeball, test-copilot) are not required stages.
STAGES_LIGHT="sk:ship-resolve-pr-comments sk:ship-screenshot-changes sk:ship-pr"
STAGES_STANDARD="sk:plan-stable-persistent-dynamic-complete-full-plan sk:ship-check-merge-readiness \
sk:ship-review sk:ship-resolve-pr-comments sk:ship-report-and-ensure-correct-user-system-journey \
sk:ship-screenshot-changes sk:ship-pr"
STAGES_DEEP="$STAGES_STANDARD sk:test-automated-full-matrix sk:ship-verify-with-prod-data"

tier_stages() {
  case "$1" in light) echo "$STAGES_LIGHT" ;; standard) echo "$STAGES_STANDARD" ;; deep) echo "$STAGES_DEEP" ;; esac
}

stage_name() { # stage_name NAME — print the canonical stage skill for a Skill name or typed command, or fail
  n="$(printf '%s' "$1" | tr -d '[:space:]')"; n="${n#/}"
  case "$n" in *:*) ;; *) n="sk:$n" ;; esac
  case " $STAGES_DEEP " in *" $n "*) printf '%s' "$n"; return 0 ;; esac
  return 1
}

receipt_pairs() { # skill and head of every recorded receipt, outside prompt fences
  section_lines receipt "$1" | awk '/^receipt: sk:[a-z0-9-]+ [^ ]+ [0-9a-f]+$/ && length($4) >= 7 { print $2, $4 }'
}

# missing_stages TIER SHA — the tier's stages with no receipt on SHA, comma-separated; needs LEDGER.
missing_stages() {
  have=""; [ -f "$LEDGER" ] && have="$(receipt_pairs "$LEDGER")"
  miss=""
  for s in $(tier_stages "$1"); do
    ok=0
    while read -r rs rh; do
      [ -n "$rs" ] || continue
      if [ "$rs" = "$s" ] && sha_match "$rh" "$2"; then ok=1; break; fi
    done <<HAVE
$have
HAVE
    [ "$ok" -eq 1 ] || miss="${miss:+$miss, }$s"
  done
  printf '%s' "$miss"
}

# receipt_record SKILL DIR — print the ledger entry for SKILL run on DIR's HEAD; the caller holds the lock.
receipt_record() {
  [ -d "$2" ] || return 1
  head="$(git -C "$2" rev-parse --verify -q 'HEAD^{commit}' 2>/dev/null)" || return 1
  br="$(git -C "$2" symbolic-ref -q --short HEAD 2>/dev/null)"; [ -n "$br" ] || br="(detached)"
  printf '\n## %s · receipt\n\nreceipt: %s %s %s\n' "$(date -u +%Y-%m-%dT%H:%M:%SZ)" "$1" "$br" "$head"
}

# A subagent's hook payload carries the SESSION's start directory as cwd, because its Bash cwd resets
# between calls, so a Skill run in a subagent working in its own worktree would receipt the coordinator's
# HEAD. The Bash recorder therefore keeps, per subagent (agent_id), the checkout its last command
# explicitly ran in, and work_checkout reads it (the fix for a delegated PR agent whose stage receipts
# landed on the main checkout's head and had to be recorded by hand).
checkout_file() { printf '%s/%s.agent-%s.checkout' "$STATE" "$SID" "$1"; }

# bash_checkout CMD DIR — print the git toplevel CMD ran in, starting from DIR: its last `cd` target,
# else its last `git -C` target; fail when it named no directory or that is no checkout.
bash_checkout() {
  printf '%s\n' "$1" | sed -E 's/(&&|\|\||[;|&])/\
/g' | {
    dir="$2"; cdd=""; gd=""
    while IFS= read -r seg; do
      read -ra w <<< "$seg"
      n=${#w[@]}
      [ "$n" -gt 0 ] || continue
      k=0
      while [ "$k" -lt "$n" ]; do w[$k]="${w[$k]//[\"\']/}"; w[$k]="${w[$k]#(}"; k=$((k + 1)); done
      i=0
      while [ "$i" -lt "$n" ] && [[ "${w[$i]}" == *=* ]] && [[ "${w[$i]}" != -* ]]; do i=$((i + 1)); done
      [ "$i" -lt "$n" ] || continue
      case "${w[$i]}" in
        cd) t="${w[$((i + 1))]:-}"; t="${t/#\~/$HOME}"
            if [ -n "$t" ] && nd="$(cd "$dir" 2>/dev/null && cd "$t" 2>/dev/null && pwd -P)"; then dir="$nd"; cdd="$nd"; fi ;;
        git) if [ "${w[$((i + 1))]:-}" = -C ]; then
               t="${w[$((i + 2))]:-}"; t="${t/#\~/$HOME}"
               if [ -n "$t" ] && nd="$(cd "$dir" 2>/dev/null && cd "$t" 2>/dev/null && pwd -P)"; then gd="$nd"; fi
             fi ;;
      esac
    done
    t="${cdd:-$gd}"
    [ -n "$t" ] || exit 1
    git -C "$t" rev-parse --show-toplevel 2>/dev/null
  }
}

# work_checkout — print the checkout a Skill call runs in: the subagent's recorded checkout when the
# payload names an agent_id and one was recorded, else the payload cwd (which follows `cd` in the
# main session).
work_checkout() {
  wc="$(jf '.cwd')"; [ -n "$wc" ] || wc="${CLAUDE_PROJECT_DIR:-$PWD}"
  aid="$(jf '.agent_id' | tr -cd '[:alnum:]._-')"
  if [ -n "$aid" ] && [ -f "$(checkout_file "$aid")" ]; then
    wd="$(head -n 1 "$(checkout_file "$aid")" 2>/dev/null)"
    [ -n "$wd" ] && [ -d "$wd" ] && wc="$wd"
  fi
  printf '%s' "$wc"
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
  # A peer's message (a subagent's <agent-message> report or another session's <cross-session-message>)
  # is Claude-authored data, not Simon's words. Record it as a `peer` entry so reconciliation still sees
  # it, but `latest-ask` (the merge guard's source of Simon's own words) and the turn's ask time
  # never read it (the fix for a subagent report recorded as the newest "ask", which the merge guard
  # then judged instead of Simon's own message).
  kind=ask
  own="$(printf '%s' "$stripped" | jq -Rrs '
    gsub("<(agent-message|cross-session-message)\\b[^>]*>.*?</(agent-message|cross-session-message)>"; ""; "mgi")
    | gsub("Another Claude session sent a message:"; ""; "g")
    | gsub("^\\s+|\\s+$"; "")' 2>/dev/null)"
  [ -n "$own" ] || kind=peer

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
    printf '\n## %s · %s · session %s\n\n' "$(date -u +%Y-%m-%dT%H:%M:%SZ)" "$kind" "$SID"
    [ "$redacted" -eq 1 ] && printf '> A credential-shaped value was REDACTED from this record.\n\n'
    printf '%s\n%s\n%s\n' "$fence" "$prompt" "$fence"
  } >> "$target" 2>/dev/null || exit 0

  # A typed /sk:<stage> command runs that stage skill, so it earns the receipt a Skill tool call does.
  # Only the leading command counts; the rest of the line is its arguments.
  if [ "$kind" = ask ] && [ "$target" = "$LEDGER" ]; then
    typed="$(printf '%s\n' "$stripped" | awk 'NR == 1 { print $1 }')"
    case "$typed" in /*)
      if st="$(stage_name "$typed")"; then
        rcwd="$(jf '.cwd')"; [ -n "$rcwd" ] || rcwd="${CLAUDE_PROJECT_DIR:-$PWD}"
        receipt_record "$st" "$rcwd" >> "$LEDGER" 2>/dev/null
      fi ;;
    esac
  fi

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
  reconcile at hand-back on substantive work: one verdict per clause of each ask, tagged with its source.
Mechanics: ~/.claude/references/planning-and-tracking.md. The Stop hook checks for reconciliation
after the newest recorded input. After a push to a non-default branch, run /sk:ship-full-detailed-workflow
on it and record the result with
  ~/.claude/hooks/intent-ledger.sh gate <branch> <sha|HEAD> PASS|BLOCKED|N/A [light|standard|deep] [reason]
(a standard or deep PASS holds \"All stages ran\"; a BLOCKED holds it or \"Not run: <stage>, <stage>\")
or Stop blocks once for the missing gate. A PASS names its tier and needs a receipt on that head for
every stage the tier requires; each Skill-tool run of a stage records one for the HEAD of the checkout
the work runs in (a subagent's: the one its last Bash cd'd into).
  ~/.claude/hooks/intent-ledger.sh stages <tier> HEAD   lists the stages still missing there."
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
  # Gate and receipt entries are written only by `gate` and the receipt recorder. A note carrying
  # their heading would open such a section and forge a record the ship gate trusts.
  if grep -qE '^## [0-9]{4}-.* · (gate|receipt)$' "$src" 2>/dev/null; then
    echo "note: refusing: $src holds a '## <time> · gate' or '· receipt' heading, which only the gate and the stage-receipt recorder write. Reword that line." >&2
    exit 2
  fi
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
  cwd="$(jf '.cwd')"
  [ -n "$cwd" ] || cwd="${CLAUDE_PROJECT_DIR:-$PWD}"
  [ -d "$cwd" ] || exit 0
  # A subagent's checkout for its next stage receipt: the directory its command explicitly ran in.
  aid="$(jf '.agent_id' | tr -cd '[:alnum:]._-')"
  if [ -n "$aid" ]; then
    case "$cmd" in *cd\ *|*-C\ *)
      if wd="$(bash_checkout "$cmd" "$cwd")" && [ -n "$wd" ] && mkdir -p "$STATE" 2>/dev/null; then
        printf '%s\n' "$wd" > "$(checkout_file "$aid")" 2>/dev/null
      fi ;;
    esac
  fi
  case "$cmd" in *push*) ;; *) exit 0 ;; esac
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

skill)
  # PostToolUse for Skill: runs only after the skill loaded. A ship stage skill earns a receipt for
  # the HEAD of the checkout the work runs in (work_checkout); every other skill records nothing.
  # The receipt still goes to the session's ledger. Silent either way.
  [ "$(jf '.tool_name')" = "Skill" ] || exit 0
  st="$(stage_name "$(jf '.tool_input.skill')")" || exit 0
  rec="$(receipt_record "$st" "$(work_checkout)")" || exit 0
  resolve || exit 0
  acquire "$LEDGER" || exit 0
  header_if_new "$LEDGER"
  printf '%s\n' "$rec" >> "$LEDGER" 2>/dev/null
  exit 0
  ;;

receipt)
  # Explicit-checkout receipt: the fallback for a Skill run whose receipt still missed its checkout
  # (a subagent that never ran a Bash `cd`/`git -C` into it). Run from the PR checkout after the
  # stage; the receipt records that checkout's HEAD, which the gate then matches.
  st="$(stage_name "${2:-}")" || { echo "receipt: usage: receipt <stage skill, e.g. sk:ship-review> [dir]" >&2; exit 2; }
  rdir="${3:-$PWD}"
  rec="$(receipt_record "$st" "$rdir")" || { echo "receipt: $rdir is not a git checkout with a commit" >&2; exit 2; }
  resolve || { echo "receipt: no ledger for this session (see the session's ledger notice)" >&2; exit 2; }
  acquire "$LEDGER" || { echo "receipt: could not lock the ledger" >&2; exit 2; }
  header_if_new "$LEDGER"
  printf '%s\n' "$rec" >> "$LEDGER" 2>/dev/null
  echo "receipt: $st recorded on $(git -C "$rdir" rev-parse --short HEAD)"
  exit 0
  ;;

stages)
  tier="$(printf '%s' "${2:-}" | tr '[:upper:]' '[:lower:]')"
  case "$tier" in light|standard|deep) ;; *)
    echo "stages: usage: stages <light|standard|deep> [sha|HEAD]" >&2; exit 2 ;;
  esac
  [ -n "${3:-}" ] || { tier_stages "$tier"; exit 0; }
  sha="$(git rev-parse --verify -q "$3^{commit}" 2>/dev/null)" || sha="$(printf '%s' "$3" | tr '[:upper:]' '[:lower:]')"
  case "$sha" in *[!0-9a-f]*|"") echo "stages: cannot resolve $3 to a commit" >&2; exit 2 ;; esac
  QUIET=1
  resolve || { echo "stages: no ledger for this worktree (see the session's ledger notice)" >&2; exit 2; }
  miss="$(missing_stages "$tier" "$sha")"
  if [ -n "$miss" ]; then echo "Not run: $miss"; exit 1; fi
  echo "All stages ran"
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
  # A PASS names its tier, because the tier decides which stage receipts it needs; an untiered PASS
  # would skip that check.
  if [ "$status" = PASS ] && [ -z "$tier" ]; then
    echo "gate: a PASS names its tier (light|standard|deep), which decides the stage receipts it needs" >&2; exit 2
  fi
  if [ "$status" = PASS ] && [ -z "$reason" ] && { [ "$tier" = light ] || [ "$tier" = standard ]; }; then
    echo "gate: a $tier PASS needs a reason: its trigger and the stages it skipped" >&2; exit 2
  fi
  # A standard or deep PASS means every stage the tier requires ran as its own skill on this head.
  # "Not run:" lists required stages, so it belongs to BLOCKED only; a stage the tier itself skips
  # goes in the tier's skip line ("skipped: <stages>"), never under "Not run:".
  if { [ "$tier" = standard ] || [ "$tier" = deep ]; } && [ "$status" = PASS ]; then
    lower="$(printf '%s' "$reason" | tr '[:upper:]' '[:lower:]')"
    case "$lower" in *"not run:"*|*"ran on earlier head"*|*"ran on an earlier head"*|*"ran on an older head"*)
      echo "gate: a $tier PASS refused: its reason lists stages that did not run on this head. Invoke \
each one as its own skill on this head (/sk:ship-full-detailed-workflow), then record PASS with \
\"All stages ran\"; or record BLOCKED with the \"Not run:\" list. A stage the tier skips goes \
in \"skipped: <stages>\", not \"Not run:\"." >&2; exit 2 ;;
    esac
  fi
  # A standard or deep result names every stage not invoked as its own skill on this head, so an
  # unrun stage cannot hide behind BLOCKED or PASS. N/A and light keep their own reason rules.
  if { [ "$tier" = standard ] || [ "$tier" = deep ]; } && [ "$status" != N/A ]; then
    case "$reason" in *"All stages ran"*|*"Not run:"*) ;; *)
      echo "gate: a $tier $status reason needs \"All stages ran\" or \"Not run: <stage>, <stage>\"" >&2; exit 2 ;;
    esac
  fi
  sha="$(git rev-parse --verify -q "$ref^{commit}" 2>/dev/null)" || sha="$(printf '%s' "$ref" | tr '[:upper:]' '[:lower:]')"
  case "$sha" in *[!0-9a-f]*|"") echo "gate: cannot resolve $ref to a commit" >&2; exit 2 ;; esac
  [ "${#sha}" -ge 7 ] || { echo "gate: sha needs 7+ characters" >&2; exit 2; }
  resolve || { echo "gate: no ledger for this worktree (see the session's ledger notice)" >&2; exit 2; }
  # Stage receipts on this exact head back the stage statement, so neither a PASS nor "All stages ran"
  # rests on reason text alone. A receipt on an older head never counts.
  if [ -n "$tier" ] && [ "$status" != N/A ]; then
    miss="$(missing_stages "$tier" "$sha")"
    fix="Invoke each with the Skill tool (e.g. Skill sk:ship-review) while the session's working \
directory (a subagent: the directory its last Bash cd'd into) is the checkout at ${sha:0:7}; each run \
records a receipt for that head. Check with
  ~/.claude/hooks/intent-ledger.sh stages $tier ${sha:0:7}"
    if [ -n "$miss" ] && [ "$status" = PASS ]; then
      echo "gate: a $tier PASS refused for $branch at ${sha:0:7}: these required stages have no receipt on this head.
Not run: $miss
$fix
then rerun gate PASS; or record BLOCKED with that \"Not run:\" list." >&2; exit 2
    fi
    if [ -n "$miss" ]; then
      case "$reason" in *"All stages ran"*)
        echo "gate: a $tier $status reason says \"All stages ran\" but these stages have no receipt on ${sha:0:7}.
Not run: $miss
$fix
or replace \"All stages ran\" with that \"Not run:\" list." >&2; exit 2 ;;
      esac
      if [ "$tier" = standard ] || [ "$tier" = deep ]; then
        unnamed=""
        for s in $(printf '%s' "$miss" | tr ',' ' '); do
          printf '%s' "$reason" | grep -qE "(^|[^a-z0-9-])$s([^a-z0-9-]|\$)" || unnamed="${unnamed:+$unnamed, }$s"
        done
        if [ -n "$unnamed" ]; then
          echo "gate: a $tier $status reason names every stage with no receipt on ${sha:0:7}; it omits: $unnamed
Use \"Not run: $miss\"." >&2; exit 2
        fi
      fi
    fi
  fi
  [ -n "$tier" ] && reason="$tier${reason:+ $reason}"
  if [ "$status" = PASS ]; then landing_check "$branch" "$sha" || exit 1; fi
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
    !fence && /^## [0-9][0-9][0-9][0-9]-.* · ((ask|peer) · session .+|plan|pivot)$/ { pending=1 }
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
proposal remains recorded, not permission to implement. Open the final message by answering each question \
and point of the prompt that started this work, in its order, before any status (rules/communication.md \
Answer first). When nothing is left, end the final message with \
the archive line from rules/communication.md; with CI running, a session PR awaiting Simon's merge or a \
promised smoke or reply open, end with the merge list instead. When this turn began from a background \
notification or this hook and brings no new outcome, decision or ask, write nothing or one line naming \
the new fact: rules/communication.md forbids re-printing an unchanged block. This fires at most once per ledger snapshot." \
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
  # Each head's missing stages come from its receipts, per tier, so the agent invokes exactly those.
  list="$(printf '%s\n' "$open" | while IFS="$(printf '\t')" read -r oroot obranch osha; do
    printf '  %s (%s) at %s\n' "$obranch" "$oroot" "${osha:0:7}"
    for t in light standard deep; do
      m="$(missing_stages "$t" "$osha")"
      printf '    %s: %s\n' "$t" "${m:+Not run: $m}"
    done | sed 's/: $/: All stages ran/'
  done)"
  msg="This session pushed these branches and recorded no ship-gate result for the pushed head:
$list
Before finishing, run /sk:ship-full-detailed-workflow on each at its tier (references/testing-strategy.md, \
Size the checks to the change; rules/process.md, Prove every point of the ask was built): invoke each \
stage listed under that tier above with the Skill tool, from the checkout at that head (each run records \
its receipt; a receipt on an older head does not count), then record it:
  ~/.claude/hooks/intent-ledger.sh gate <branch> <sha|HEAD> PASS|BLOCKED|N/A [light|standard|deep] [reason]
BLOCKED, N/A and a light or standard PASS need a reason: the exact blocker, why the harness does not \
apply to this push, or the tier's trigger and skipped stages. A standard or deep BLOCKED \
reason holds \"All stages ran\" or \"Not run: <stage>, <stage>\" naming each stage not invoked as its own \
skill on that head; a standard or deep PASS holds \"All stages ran\" and is refused with any \"Not run:\" list. \
A PASS names its tier and is refused while any stage that tier requires has no receipt on the head. \
Run every stage the tier requires first, on the newest head, unprompted, even when an external blocker makes it BLOCKED. A gate \
recorded for an older head does not count once a newer head is pushed. This fires at most once per set of open pushes."
  jq -cn --arg r "$msg" '{decision:"block",reason:$r}'
  exit 0
  ;;

latest-ask)
  # The merge guard (hooks/git-commit-guard.py) asks this for Simon's own words, so a merge is
  # authorized by what he typed, never by a flag the model can set. Same resolution as `submit`,
  # silent, read-only; no ledger or no ask for this session prints nothing, which the guard denies.
  # `--since <ts>` returns every ask from that second on: the guard passes the second the current
  # turn opened, so a merge ask followed by a queued clarification keeps its authority.
  QUIET=1
  since=""
  if [ "${2:-}" = "--since" ]; then
    since="${3:-}"
    case "$since" in
      [0-9][0-9][0-9][0-9]-[0-9][0-9]-[0-9][0-9]T[0-9][0-9]:[0-9][0-9]:[0-9][0-9]Z) ;;
      *) exit 0 ;;
    esac
  fi
  resolve || exit 0
  [ -f "$LEDGER" ] || exit 0
  awk -v sid="$SID" -v since="$since" '
    index($0, "## ") == 1 && index($0, " · ask · session " sid) > 0 &&
      substr($0, length($0) - length(sid) + 1) == sid { cap = 1; fence = ""; buf = ""; ts = $2; next }
    cap && fence == "" && $0 ~ /^`{3,}$/ { fence = $0; next }
    cap && fence != "" && $0 == fence {
      cap = 0; last = buf
      if (since != "" && (ts "") >= (since "")) { out = out (n++ ? "\036" : "") buf }
      next }
    cap && fence != "" { buf = buf $0 "\n"; next }
    cap && index($0, "## ") == 1 { cap = 0 }
    END { if (since == "") printf "%s", last; else printf "%s", out }
  ' "$LEDGER"
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
