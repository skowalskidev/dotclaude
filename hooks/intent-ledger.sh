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
# has a receipt on the gated sha; a receipt on an older head counts only when it carries (RECEIPT
# CARRY below: a light or standard receipt, and a Light-sized delta of the PR's own commits since that
# head). The list below is the one home of which stages each tier requires.
#
# Modes:  submit                  UserPromptSubmit — append the ask verbatim (and a receipt for a
#                                 typed /sk:<stage> command)
#         note <kind> <file>      called by the model — append sources|plan|pivot|reconcile|learning.
#                                 A learning note records the end-of-session config learning: its body
#                                 holds "session learning: done" or "session learning: skipped", and it
#                                 is refused unless an ask since the previous learning note is Simon's
#                                 bare "go" or "skip" (or names the session/config learning), or the
#                                 previous learning note said done: his go stands until a skip
#         learning-count          read-only, run from the session's shell like note — print N, this
#                                 session's asks since its last learning note: the N in the hand-back's ask
#         push                    PostToolUse (Bash) — record a pushed non-default branch and its head
#         skill                   PostToolUse (Skill) — record a stage receipt for the HEAD of the checkout
#                                 the work runs in: a subagent's (agent_id) last explicit Bash checkout,
#                                 else the payload cwd
#         receipt <stage> [dir]   called by a delegated worker from its OWN checkout, or by the main session
#                                 for a branch whose checkout is not its cwd — record a stage
#                                 receipt for the HEAD of <dir> (default: the shell's cwd), in the
#                                 session's ledger. The fallback when a Skill receipt missed its checkout
#                                 (a subagent that never ran a Bash `cd`/`git -C` into it, or a sibling
#                                 worktree the session's Bash cwd cannot stay in). It still records <dir>'s HEAD.
#         stages <hotfix|light|standard|deep> [sha|HEAD] [branch]
#                                 read-only — print the tier's required stage skills; with a sha,
#                                 print "All stages ran" (exit 0; "(carried from <sha>...)" when a
#                                 light or standard receipt carried) or "Not run: <stage>, ..." (exit 1).
#                                 Receipts carry only within <branch>: default the checkout's branch
#                                 when <sha> is its HEAD, else every branch
#         gate <branch> <sha|HEAD> <PASS|BLOCKED|N/A> [hotfix|light|standard|deep] [reason]
#                                 called by the model — record the landing-gate result for that head;
#                                 a PASS names its tier and every stage that tier requires has a
#                                 receipt on <sha>, else exit 2 printing "Not run: <stage>, ...";
#                                 a standard or deep BLOCKED reason holds "All stages ran" or
#                                 "Not run: <stage>, <stage>" naming every stage with no receipt;
#                                 "All stages ran" at any tier needs the receipts; a standard or
#                                 deep PASS reason holds "All stages ran" and no "Not run:" list
#                                 (exit 2 otherwise); an N/A reason "waived by Simon: <quote>" records
#                                 only when the quote is in an ask of this ledger, and it also covers
#                                 the branch's later heads whose delta touches no Deep path;
#                                 PASS for a branch with an open PR records only when
#                                 bin/pr-landing-gate.py passes on the fetched PR and
#                                 bin/pr-ci-wait.py --once finds every check green on <sha>
#                                 (exit 1 otherwise)
#         latest-ask [--since <ts>]
#                                 PreToolUse helper — print this session's newest recorded ask, verbatim
#                                 (stdin payload: session_id, cwd); prints nothing when none. Read-only.
#                                 With --since (UTC, YYYY-MM-DDTHH:MM:SSZ) it prints EVERY ask recorded
#                                 at or after that second, oldest first, separated by an ASCII RS (\036).
#         gates                   PreToolUse helper — print "<heading time> <gate line>" for each gate THIS session recorded (stdin
#                                 payload: session_id, cwd). Read-only; silent when none; exit 3 when
#                                 no ledger resolves.
#         stop                   Stop — require reconciliation after the newest recorded input, block
#                                 an archive line while this session has asks no learning note covers,
#                                 then a gate record for every pushed branch head

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
# A session the a by-hand resume continues gets a fixed machine
# prompt. Recording it as an ask would forge Simon's words; the watchdog writes its own `note plan`
# line instead, and every other mode keeps working for the resumed session.
[ "$MODE" = "submit" ] && [ "${AGENT_SESSION_RESUMED:-}" = "1" ] && exit 0

# No sed fallback here, unlike task-intake.sh. sed cannot decode \n escapes, so it would write a
# corrupted record while claiming to be verbatim, which is worse than writing nothing.
command -v jq >/dev/null 2>&1 || exit 0

INPUT=""
case "$MODE" in note|gate|stages|receipt|learning-count) ;; *) INPUT="$(cat 2>/dev/null)" ;; esac
[ -n "$INPUT" ] || INPUT='{}'

jf() { printf '%s' "$INPUT" | jq -r "$1 // empty" 2>/dev/null; }

SID="$(jf '.session_id' | tr -cd '[:alnum:]._-')"
# `note` and `gate` run from the session's own shell with no payload, so they read the id from the
# environment. Every other mode takes it from its payload only: a test or tool subprocess inherits the
# live session's CLAUDE_CODE_SESSION_ID, and reading it there let a temp-repo test re-anchor the live
# session's record (the fix for a nested-worktree ask that opened a second ledger and hid a standing merge).
case "$MODE" in note|gate|stages|receipt|learning-count)
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
  sweep_state
}

sweep_state() { # one cleanup for every path, owned by bin/session_learning.py prune-state: a file goes once it
  # is 7 days old (30 for the recorder-failure and once-per-session listing markers) AND an end-of-session
  # learning record covers its session, so no session's state is cleaned before it was learned from
  python3 "$CFG_ROOT/bin/session_learning.py" prune-state >/dev/null 2>&1
  return 0
}

mark_unrecorded() { # a real prompt of a known session could not be read or recorded
  [ "$SID" != unknown ] || return 0
  mkdir -p "$STATE" 2>/dev/null && : > "$STATE/$SID.unrecorded" 2>/dev/null
  return 0
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

# record_pushed_output ROOT — record each branch the push's own output names under a `To <url>` line
# that is ROOT's origin. For a push whose refspec or directory the shell builds at run time (`git push
# origin HEAD:"$b"`, `cd "$wt" && git push`): its text names no branch, and the checkout the hook
# resolves may not be the one that pushed. No output (`-q`, a redirection) records nothing.
record_pushed_output() {
  origin="$(git -C "$1" remote get-url --push origin 2>/dev/null)" || return 0
  { jf '.tool_response.stderr'; jf '.tool_response.stdout'; } | awk -v o="${origin%.git}" '
    /^To / { u = substr($0, 4); sub(/\.git$/, "", u); ok = (u == o); next }
    ok && / -> / && $0 !~ /^ *!/ { d = $0; sub(/.* -> /, "", d); sub(/ .*/, "", d); print d }' |
  while IFS= read -r d; do
    case "$d" in *'$'*|*'`'*|"") continue ;; esac
    record_push "$1" "$d" "$d"
  done
}

# open_pr BRANCH — set repo (owner/name of a GitHub origin, else empty) and num (BRANCH's open PR
# there, else empty). 1 when gh is missing or its lookup failed, with the reason in open_pr_error.
open_pr() {
  repo=""; num=""; open_pr_error=""
  url="$(git remote get-url origin 2>/dev/null)" || return 0
  repo="$(printf '%s' "$url" | sed -nE 's#^(https://([^@/]+@)?|ssh://git@|git@)github\.com[:/]([^/]+/[^/]+)$#\3#p')"
  repo="${repo%/}"; repo="${repo%.git}"
  [ -n "$repo" ] || return 0                                  # not a GitHub origin: no PR
  if ! command -v gh >/dev/null 2>&1; then
    open_pr_error="gh is missing, so open PRs for $1 on $repo cannot be checked"; return 1
  fi
  prs="$(gh pr list --repo "$repo" --head "$1" --state open --json number,url 2>/dev/null)" || {
    open_pr_error="gh pr list failed for $1 on $repo (a fetch failure never passes)"; return 1; }
  num="$(printf '%s' "$prs" | jq -r '.[0].number // empty' 2>/dev/null)"
  return 0
}

# light_waivers BRANCH — the Light stages BRANCH's open PR itself stands in for, space-separated
# (references/testing-strategy.md § Size the checks to the change). sk:ship-screenshot-changes: the PR is
# open, so the landing gate checks its Screenshots section (a rendered BEFORE/AFTER pair, or a
# no-surface line with its Checked outputs clause). sk:ship-resolve-pr-comments: the open PR holds zero
# reviews, review comments and comments by a person (bin/pr-landing-gate.py --feedback-count). No
# GitHub origin, no open PR, or any failed read waives nothing.
light_waivers() {
  open_pr "$1" || return 0
  [ -n "$num" ] || return 0
  out="sk:ship-screenshot-changes"
  fb="$(python3 "$CFG_ROOT/bin/pr-landing-gate.py" --repo "$repo" --pr "$num" --feedback-count 2>/dev/null)"
  [ "$fb" = 0 ] && out="$out sk:ship-resolve-pr-comments"
  printf '%s' "$out"
}

# landing_check BRANCH SHA — 0 when the branch has no open PR on a GitHub origin, or when
# bin/pr-landing-gate.py passes on that PR AND bin/pr-ci-wait.py --once finds every check on SHA
# succeeded or skipped. Otherwise prints why and fails, so `gate PASS` records nothing. A PR that
# cannot be looked up or fetched fails: a fetch failure never passes. No reason text bypasses red CI.
landing_check() {
  open_pr "$1" || { echo "gate: PASS refused: $open_pr_error" >&2; return 1; }
  [ -n "$num" ] || return 0                                   # not a GitHub origin, or no open PR
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

# The fence rules every fence-aware reader shares: a ``` or ~~~ run opens a fence; only the same mark,
# at least as long, with nothing after it, closes it. `fence` is the open fence's width, 0 outside.
FENCE_AWK='
    { line=$0; sub(/^ */, "", line)
      if (line ~ /^(```|~~~)/) { mark=substr(line,1,1); match(line, "^" mark "+"); width=RLENGTH
        tail=substr(line,width+1)
        if (!fence) { fence=width; delimiter=mark; next }
        if (mark == delimiter && width >= fence && tail ~ /^[[:space:]]*$/) { fence=0; next } } }'

# learning_state — "<last learning ts>\t<N>\t<go>\t<stand>" for LEDGER: N counts this session's asks after the
# newest learning note (every session's when the id is unknown); go is 1 when an ask after it (any
# session) is Simon's bare go or skip ("go", "go ahead", "ok go", "skip") once harness blocks are
# stripped, as the whole ask or as one line of it (a numbered reply opening with "go"), or names the
# session or config learning. A longer "go ahead and merge" never counts, whole or as a line.
# stand is 1 while the newest learning note says "session learning: done": Simon's go stands for the
# rest of the session, so later asks are learned without asking again; a skip note ends it.
# Records are parsed with their fences, so a heading pasted inside a prompt is never a boundary.
learning_state() {
  [ -f "$LEDGER" ] || { printf '\t0\t0\t0\n'; return; }
  awk -v sid="$SID" '
    function word(t) { t = tolower(t); gsub(/[[:space:]]+/, " ", t); sub(/^ /, "", t); sub(/ $/, "", t)
      return (t ~ /^((yes|ok|okay)[ ,]+)?(go|go ahead|skip)[.! ]*$/ || index(t, "session learning") ||
        index(t, "config learning")) }
    inrec && fence == "" && $0 ~ /^`{3,}[[:space:]]*$/ { fence = $0; sub(/[[:space:]]+$/, "", fence); body = ""; lgo = 0; skip = 0; next }
    inrec && fence != "" && $0 == fence { if (isask && (lgo || word(body))) go = 1; inrec = 0; fence = ""; next }
    inrec && fence != "" {
      if (!skip && $0 ~ /<(system-reminder|system_instruction|task-notification)>/) skip = 1
      if (!skip) { body = body " " $0; if (word($0)) lgo = 1 }
      if (skip && $0 ~ /<\/(system-reminder|system_instruction|task-notification)>/) skip = 0
      next }
    /^## [0-9][0-9][0-9][0-9]-[0-9][0-9]-[0-9][0-9]T[0-9:]*Z · (ask|peer) · session / {
      inlearn = 0; inrec = 1; fence = ""; isask = (index($0, " · ask · session ") > 0)
      if (isask && (sid == "unknown" || substr($0, length($0) - length(sid) + 1) == sid)) n++
      next }
    /^## [0-9][0-9][0-9][0-9]-[0-9][0-9]-[0-9][0-9]T[0-9:]*Z · learning$/ { lts = $2; n = 0; go = 0; stand = 0; inlearn = 1; next }
    /^## [0-9][0-9][0-9][0-9]-[0-9][0-9]-[0-9][0-9]T[0-9:]*Z · / { inlearn = 0; next }
    inlearn && index($0, "session learning: done") { stand = 1 }
    END { printf "%s\t%d\t%d\t%d\n", lts, n, go, stand }
  ' "$LEDGER"
}

# The shared Haiku step (bin/haiku_judge.py) owns every judgement on Simon's words in this script; the
# regexes stay as its prefilter and, when no verdict comes back, its fallback. It is fed ask records only:
# a peer entry, a plan or any assistant text never reaches it (rules/self-healing-config.md § Safeguard
# changes, item 3). LEDGER_ASKS_PY prints {"messages": [...], "other": bool} for the asks after the newest
# "## <ts> · <since>" heading (other: a plan, pivot or peer entry follows it too), harness blocks stripped,
# fences honoured, newest 8 kept, each cut to 1500 characters.
JUDGE_PY="$(cd "$(dirname "$0")/.." 2>/dev/null && pwd)/bin/haiku_judge.py"
LEDGER_ASKS_PY='
import json, re, sys
since, path = sys.argv[1], sys.argv[2]
head = re.compile(r"^## \d{4}-\d\d-\d\dT[0-9:]*Z · (.+)$")
block = re.compile(r"<(system-reminder|system_instruction|task-notification|agent-message|cross-session-message)\b[^>]*>.*?</\1>", re.S | re.I)
asks, other, fence, cur, kind = [], False, "", None, ""
try:
    lines = open(path, encoding="utf-8", errors="replace").read().split("\n")
except OSError:
    lines = []
for line in lines:
    if fence:
        if line.rstrip() == fence:
            fence = ""
            if kind == "ask" and cur is not None:
                text = block.sub("", "\n".join(cur)).strip()
                if text:
                    asks.append(text[:1500])
            cur = None
        elif cur is not None:
            cur.append(line)
        continue
    m = head.match(line)
    if m:
        rest = m.group(1)
        kind = rest.split(" · ")[0]
        if rest == since:
            asks, other = [], False
        elif kind in ("plan", "pivot", "peer"):
            other = True
        continue
    if re.match(r"^`{3,}\s*$", line) and kind in ("ask", "peer"):
        fence, cur = line.rstrip(), []
print(json.dumps({"messages": asks[-8:], "other": other}))
'

# judged <kind> <since> <prefilter-regex>: 0 ok, 1 not ok, 3 no verdict or nothing to judge. The asks after
# the newest <since> heading go to the Haiku step only when one matches the case-insensitive prefilter.
judged() {
  local data
  [ -f "$JUDGE_PY" ] || return 3
  data="$(python3 -c "$LEDGER_ASKS_PY" "$2" "$LEDGER" 2>/dev/null)" || return 3
  printf '%s' "$data" | python3 -c 'import json,re,sys
d=json.load(sys.stdin); sys.exit(0 if d["messages"] and any(re.search(sys.argv[1], m, re.I) for m in d["messages"]) else 1)' "$3" \
    2>/dev/null || return 3
  printf '%s' "$data" | python3 "$JUDGE_PY" ask "$1" >/dev/null 2>&1
}

# learning_go — 1 when Simon's asks since the newest learning note approve or skip the end-of-session
# learning. An ask naming go, skip, learning, config or self-improvement (typos included) goes to the
# Haiku step, whose verdict decides ("go" alone on a line of a numbered reply passes, "go ahead and
# merge" does not); with no verdict the deterministic learning_state rule stands.
learning_go() {
  local rc
  judged learning-go learning '\bgo\b|skip|learn|lern|config|improv|imrpov|optimi|self'; rc=$?
  case "$rc" in 0) echo 1 ;; 1) echo 0 ;; *) learning_state | cut -f3 ;; esac
}

# status_only — true when every ask since the newest reconcile is a status question or an acknowledgement
# with no new work (the Haiku step's status-only kind). Only short ask-only stretches are asked (no plan,
# pivot or peer entry, at most 4 asks of at most 400 characters); anything else, or no verdict, is false,
# so the reconciliation block keeps its old behaviour.
status_only() {
  local data
  [ -f "$JUDGE_PY" ] || return 1
  data="$(python3 -c "$LEDGER_ASKS_PY" reconcile "$LEDGER" 2>/dev/null)" || return 1
  printf '%s' "$data" | python3 -c 'import json,sys
d=json.load(sys.stdin); m=d["messages"]
sys.exit(0 if m and not d["other"] and len(m) <= 4 and all(len(x) <= 400 for x in m) else 1)' 2>/dev/null || return 1
  printf '%s' "$data" | python3 "$JUDGE_PY" ask status-only >/dev/null 2>&1
}

asks_since_reconcile() { # this session's asks after the newest reconcile note, outside prompt fences
  [ -f "$LEDGER" ] || { echo 0; return; }
  awk -v sid="$SID" "$FENCE_AWK"'
    !fence && /^## [0-9][0-9][0-9][0-9]-.* · reconcile$/ { n = 0; next }
    !fence && /^## [0-9][0-9][0-9][0-9]-.* · ask · session / {
      if (sid == "unknown" || substr($0, length($0) - length(sid) + 1) == sid) n++ }
    END { print n + 0 }' "$LEDGER"
}

section_lines() { # section_lines KIND FILE — every line under a "## <ts> · KIND" heading, outside prompt fences
  awk -v kind="$1" "$FENCE_AWK"'
    !fence && /^## [0-9][0-9][0-9][0-9]-/ { insec = ($0 ~ (" · " kind "$")); next }
    !fence && insec { print }
  ' "$2"
}

unmet_asks() { # every verdict line of the NEWEST reconcile still open, not met or partly met (runtime: excluded)
  awk "$FENCE_AWK"'
    !fence && /^## [0-9][0-9][0-9][0-9]-/ { insec = ($0 ~ / · reconcile$/); if (insec) n=0; next }
    !fence && insec && tolower($0) ~ /(^|[^a-z])(open:|not met|partly met)/ && tolower($0) !~ /runtime:/ { buf[++n]=$0 }
    END { for (i = 1; i <= n; i++) print buf[i] }' "$1"
}

runtime_open() { # every `runtime: open` line of the NEWEST reconcile entry, outside prompt fences
  awk "$FENCE_AWK"'
    !fence && /^## [0-9][0-9][0-9][0-9]-/ { insec = ($0 ~ / · reconcile$/); if (insec) n=0; next }
    !fence && insec && /(^|[^A-Za-z])runtime: open([^A-Za-z]|$)/ { buf[++n]=$0 }
    END { for (i=1; i<=n; i++) print buf[i] }
  ' "$1"
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
# Hotfix (references/testing-strategy.md § Hotfix tier): a broken-production fix in one product file.
# bin/pr-landing-gate.py checks its PR body rows (root cause, judge, happy and paid paths, the safety
# rows the diff touches) and refuses the label on a bigger diff, so only these receipts are required.
STAGES_HOTFIX="sk:ship-resolve-pr-comments sk:ship-pr"

# LIGHT_WAIVED: the light or hotfix stages `gate` and `stages` found the open PR standing in for
# (tier_waivers); empty everywhere else, so the Stop message lists each whole list.
LIGHT_WAIVED=""
waive() { # waive LIST — LIST without the stages in LIGHT_WAIVED
  local s out=""
  for s in $1; do case " $LIGHT_WAIVED " in *" $s "*) ;; *) out="${out:+$out }$s" ;; esac; done
  echo "$out"
}
tier_stages() {
  case "$1" in
    light) waive "$STAGES_LIGHT" ;; hotfix) waive "$STAGES_HOTFIX" ;;
    standard) echo "$STAGES_STANDARD" ;; deep) echo "$STAGES_DEEP" ;;
  esac
}
# tier_waivers TIER BRANCH — the stages of TIER's list that BRANCH's open PR stands in for; light and
# hotfix only, every other tier none.
tier_waivers() {
  local s w out="" list
  case "$1" in light) list="$STAGES_LIGHT" ;; hotfix) list="$STAGES_HOTFIX" ;; *) return 0 ;; esac
  w="$(light_waivers "$2")"
  for s in $w; do case " $list " in *" $s "*) out="${out:+$out }$s" ;; esac; done
  printf '%s' "$out"
}

stage_name() { # stage_name NAME — print the canonical stage skill for a Skill name or typed command, or fail
  n="$(printf '%s' "$1" | tr -d '[:space:]')"; n="${n#/}"
  case "$n" in *:*) ;; *) n="sk:$n" ;; esac
  case " $STAGES_DEEP " in *" $n "*) printf '%s' "$n"; return 0 ;; esac
  return 1
}

receipt_pairs() { # skill, head and branch of every recorded receipt, outside prompt fences
  section_lines receipt "$1" | awk '/^receipt: sk:[a-z0-9-]+ [^ ]+ [0-9a-f]+$/ && length($4) >= 7 { print $2, $4, $3 }'
}

# RECEIPT CARRY (references/testing-strategy.md § Follow-up pushes). A light or standard receipt on an
# earlier head counts for a later head when the PR's own delta between them is Light-sized: at most
# CARRY_MAX_LINES changed product lines, no product file behind a Deep path, and no base merge that
# touched a file the PR changes. Deep receipts never carry, and a receipt carries only within the
# branch it was recorded on. Computed from git on every read, so no record can claim a carry the
# history does not show (the fix for a 120-line admin button whose test commit, review fix, clean base
# merge and icon tweak each re-ran all seven standard stages; and for a gate in a long ledger that ran
# the delta check for every other PR's receipted heads, ancestors through a main merge, and never finished).
CARRY_MAX_LINES=200
# Not product code: tests, fixtures, snapshots, docs and lockfiles.
NOT_PRODUCT_RE='(^|/)(tests?|e2e|__tests__|__snapshots__|fixtures?|docs?)/|[._-](test|spec)\.[a-z0-9]+$|_test\.[a-z0-9]+$|\.(md|snap)$|(^|/)(package-lock\.json|yarn\.lock|pnpm-lock\.yaml|deno\.lock|Cargo\.lock|Podfile\.lock|Gemfile\.lock|go\.sum|poetry\.lock|uv\.lock)$'
# A product file here may hold a Deep trigger (money, auth, stored data, native builds): it never carries.
DEEP_PATH_RE='(^|/)(migrations?|db|ios|android)/|\.sql$|pay|billing|stripe|checkout|pric|entitle|auth|purchase|subscri|refund|webhook|credit|wallet'
CARRY_DIR=""   # the checkout whose git answers carry questions; empty means the shell's cwd

# Per-invocation memos, so each commit costs one diff-tree however many candidate heads reach it:
# CARRY_MEMO holds "<newline><commit>:<product lines, or D for a Deep path>"; CARRY_BASES* the base refs.
CARRY_MEMO=""; CARRY_BASES_DIR=""; CARRY_BASES=""
NL='
'

load_bases() { # set CARRY_BASES to the default-branch refs in the carry checkout, origin's HEAD first
  local d="${CARRY_DIR:-$PWD}" out="" h r
  [ -n "$CARRY_BASES_DIR" ] && [ "$CARRY_BASES_DIR" = "$d" ] && return 0
  h="$(git -C "$d" symbolic-ref -q --short refs/remotes/origin/HEAD 2>/dev/null)"
  for r in $h origin/main origin/master main master; do
    git -C "$d" rev-parse --verify -q "$r^{commit}" >/dev/null 2>&1 || continue
    case " $out " in *" $r "*) ;; *) out="${out:+$out }$r" ;; esac
  done
  CARRY_BASES_DIR="$d"; CARRY_BASES="$out"
}

# commit_weight DIR COMMIT NPARENTS — print COMMIT's own product lines, or D when a product file it
# changes sits behind DEEP_PATH_RE (matched case-insensitively). A merge adds only its conflict
# resolution: the combined diff's lines new against both parents. NOT_PRODUCT_RE files count nothing.
commit_weight() {
  if [ "$3" -gt 1 ]; then
    git -C "$1" diff-tree --cc -p "$2" 2>/dev/null | awk '
      /^diff --cc / { f=$3; next }
      /^@@@ / { inh=1; next }
      inh && f != "" && (substr($0,1,2) ~ /\+/ || substr($0,1,2) == "--") { n[f]++ }
      END { for (k in n) print n[k] "\t" k }'
  else
    git -C "$1" diff-tree --no-commit-id --numstat -r "$2" 2>/dev/null | awk -F'\t' '
      { a=($1=="-")?0:$1; r=($2=="-")?0:$2; print a+r "\t" $3 }'
  fi | NP="$NOT_PRODUCT_RE" DP="$DEEP_PATH_RE" awk -F'\t' '
    $2 == "" { next }
    $2 ~ ENVIRON["NP"] { next }
    tolower($2) ~ ENVIRON["DP"] { deep = 1; exit }
    { lines += $1 }
    END { if (deep) print "D"; else print lines + 0 }'
}

# delta_carries FROM TO MAX [nobase] — 0 when TO descends from FROM and the PR's own commits between
# them (base commits excluded) change at most MAX product lines (-1: no cap) and no product file
# behind DEEP_PATH_RE; unless "nobase", a base merge in between must touch no file the PR changes.
# Each commit's weight is memoized in CARRY_MEMO, so candidate heads sharing history reuse it.
delta_carries() {
  local d="${CARRY_DIR:-$PWD}" bases revs lines c rest p np w first mb1 mb2 both
  git -C "$d" merge-base --is-ancestor "$1" "$2" 2>/dev/null || return 1
  load_bases; bases="$CARRY_BASES"
  # shellcheck disable=SC2086 # bases is a word list on purpose
  revs="$(git -C "$d" rev-list --parents "$2" "^$1" ${bases:+--not $bases} 2>/dev/null)" || return 1
  lines=0
  while read -r c rest; do
    [ -n "$c" ] || continue
    case "$CARRY_MEMO$NL" in
      *"$NL$c:"*) w="${CARRY_MEMO#*"$NL$c:"}"; w="${w%%"$NL"*}" ;;
      *) np=0; for p in $rest; do np=$((np + 1)); done
         w="$(commit_weight "$d" "$c" "$np")"
         CARRY_MEMO="$CARRY_MEMO$NL$c:$w" ;;
    esac
    [ "$w" = D ] && return 1
    lines=$((lines + w))
    [ "$3" -lt 0 ] || [ "$lines" -le "$3" ] || return 1   # over the cap already: no later commit can carry it
  done <<REVS
$revs
REVS
  first="${bases%% *}"
  if [ "${4:-}" != nobase ] && [ -n "$first" ]; then
    mb1="$(git -C "$d" merge-base "$1" "$first" 2>/dev/null)"; mb2="$(git -C "$d" merge-base "$2" "$first" 2>/dev/null)"
    if [ -n "$mb1" ] && [ -n "$mb2" ] && [ "$mb1" != "$mb2" ]; then
      both="$( { git -C "$d" diff --name-only "$mb1" "$mb2"; git -C "$d" diff --name-only "$mb2" "$2"; } 2>/dev/null | sort | uniq -d)"
      [ -z "$both" ] || return 1
    fi
  fi
  return 0
}

# carriable_heads SHA [BRANCH] — the earlier heads holding a receipt recorded on BRANCH whose receipts
# carry to SHA, space-separated. With no BRANCH (`stages` without one) every receipted head is a candidate.
carriable_heads() {
  [ -f "$LEDGER" ] || return 0
  local out="" h
  for h in $(receipt_pairs "$LEDGER" | awk -v b="${2:-}" 'b == "" || $3 == b { print $2 }' | awk '!seen[$0]++'); do
    sha_match "$h" "$1" && continue
    delta_carries "$h" "$1" "$CARRY_MAX_LINES" && out="${out:+$out }$h"
  done
  printf '%s' "$out"
}

# stage_status TIER SHA [BRANCH] [CARRIABLE] — line 1: the tier's stages with no receipt on SHA (any
# branch: a sha names one commit) or on a carriable head of BRANCH (never for deep), comma-separated;
# line 2: the short heads a receipt carried from. CARRIABLE defaults to carriable_heads SHA BRANCH.
stage_status() {
  local have="" carry="" miss="" from="" sfrom s ok rs rh rb h
  [ -f "$LEDGER" ] && have="$(receipt_pairs "$LEDGER")"
  [ "$1" = deep ] || carry="${4-$(carriable_heads "$2" "${3:-}")}"
  for s in $(tier_stages "$1"); do
    ok=0; sfrom=""
    while read -r rs rh rb; do
      [ -n "$rs" ] || continue
      [ "$rs" = "$s" ] || continue
      if sha_match "$rh" "$2"; then ok=1; break; fi
      [ -z "${3:-}" ] || [ "$rb" = "$3" ] || continue
      case " $carry " in *" $rh "*)
        ok=2; case " $sfrom " in *" ${rh:0:7} "*) ;; *) sfrom="${sfrom:+$sfrom }${rh:0:7}" ;; esac ;;
      esac
    done <<HAVE
$have
HAVE
    if [ "$ok" -eq 0 ]; then miss="${miss:+$miss, }$s"
    elif [ "$ok" -eq 2 ]; then
      for h in $sfrom; do
        case " $from " in *" $h "*) ;; *) from="${from:+$from }$h" ;; esac
      done
    fi
  done
  printf '%s\n%s\n' "$miss" "$from"
}

# missing_stages TIER SHA [BRANCH] — the tier's stages with no receipt on SHA or a carriable head; needs LEDGER.
missing_stages() {
  stage_status "$1" "$2" "${3:-}" | sed -n 1p | tr -d '\n'
}

# norm_text — lower-case, straighten curly quotes, collapse whitespace, so a quoted waiver matches its ask.
norm_text() {
  LC_ALL=C sed -e "s/’/'/g" -e "s/‘/'/g" -e 's/“/"/g' -e 's/”/"/g' | tr '[:upper:]' '[:lower:]' | tr -s '[:space:]' ' '
}
ask_text() { # every ask recorded in the ledger, normalized
  awk '
    index($0, "## ") == 1 && index($0, " · ask · session ") > 0 { cap = 1; fence = ""; next }
    cap && fence == "" && $0 ~ /^`{3,}$/ { fence = $0; next }
    cap && fence != "" && $0 == fence { cap = 0; next }
    cap && fence != "" { print; next }
    cap && index($0, "## ") == 1 { cap = 0 }
  ' "$LEDGER" | norm_text
}

# waiver_pairs — branch and sha of every recorded N/A gate holding Simon's waiver, outside prompt fences.
waiver_pairs() {
  section_lines gate "$1" | awk '/^gate: [^ ]+ [0-9a-f]+ N\/A .*waived by Simon:/ { print $2, $3 }'
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

# Print "root<TAB>branch<TAB>sha" for each pushed branch's LATEST head that has no gate record. Simon's
# recorded waiver on an earlier head of the same branch covers a later head whose own delta touches
# no Deep path (any size), so a waived PR's follow-up pushes do not re-block.
#
# Only a branch's latest head is judged: a gate on an older head never counts once a newer head is
# pushed, and a superseded head never blocks once that newer head is gated. The newest record per
# root+branch is the candidate; it is superseded by (1) a later record of the same branch from another
# checkout that descends from it, or (2) a gate on the same branch whose head descends from it (the
# fix for a removed temp worktree's head d334b6f blocking Stop while its descendant 0fb737289, pushed
# from another checkout, already held gate PASS). Otherwise origin's tip, read with ls-remote from
# that checkout (or the session root when the checkout is gone and holds the commit), names the head.
# The offline checks run first and ls-remote stops after LS_REMOTE_BUDGET seconds, inside Stop's 5 s.
LS_REMOTE_BUDGET="${LS_REMOTE_BUDGET:-3}"

# repo_dir DIR SHA — print a checkout that holds SHA: DIR while it exists, else the session root.
repo_dir() {
  if [ -d "$1" ]; then printf '%s' "$1"; return 0; fi
  [ -n "$SROOT" ] && git -C "$SROOT" cat-file -e "$2^{commit}" 2>/dev/null && printf '%s' "$SROOT"
}

# head_gated BRANCH SHA DIR — 0 when SHA has a gate on BRANCH, or a waiver on BRANCH carries to it.
head_gated() {
  local gb gs wb ws
  while read -r gb gs; do
    [ -n "$gb" ] && [ "$gb" = "$1" ] && sha_match "$gs" "$2" && return 0
  done <<GATES
$GATES_
GATES
  [ -n "$3" ] || return 1
  while read -r wb ws; do
    [ -n "$wb" ] && [ "$wb" = "$1" ] || continue
    CARRY_DIR="$3" delta_carries "$ws" "$2" -1 nobase && return 0
  done <<WAIVERS
$WAIVERS_
WAIVERS
  return 1
}

# descends DIR OLD NEW — 0 when NEW is a different commit that has OLD as an ancestor, in DIR.
descends() {
  [ -n "$1" ] && ! sha_match "$2" "$3" && git -C "$1" merge-base --is-ancestor "$2" "$3" 2>/dev/null
}

open_pushes() {
  [ -s "$PUSHES" ] || return 0
  SROOT="${root:-}"
  GATES_="$(gate_pairs "$LEDGER")"
  WAIVERS_="$(waiver_pairs "$LEDGER")"
  latest="$(awk -F'\t' '{ k=$1 FS $2; if (!(k in v)) order[++n]=k; v[k]=$3; at[k]=NR }
    END { for (i=1;i<=n;i++) print at[order[i]] FS order[i] FS v[order[i]] }' "$PUSHES")"
  started="$SECONDS"; seen=""
  printf '%s\n' "$latest" | while IFS="$(printf '\t')" read -r at proot branch sha; do
    [ -n "$branch" ] || continue
    head_gated "$branch" "$sha" "" && continue
    dir="$(repo_dir "$proot" "$sha")"
    head_gated "$branch" "$sha" "$dir" && continue
    newer=0
    while IFS="$(printf '\t')" read -r lat lroot lbranch lsha; do
      [ "$lbranch" = "$branch" ] && [ "$lroot" != "$proot" ] && [ "${lat:-0}" -gt "$at" ] || continue
      if descends "$dir" "$sha" "$lsha" || descends "$(repo_dir "$lroot" "$lsha")" "$sha" "$lsha"; then
        newer=1; break; fi
    done <<LATEST
$latest
LATEST
    [ "$newer" -eq 1 ] && continue
    while read -r gb gs; do
      [ -n "$gb" ] && [ "$gb" = "$branch" ] || continue
      if descends "$dir" "$sha" "$gs"; then newer=1; break; fi
    done <<GATES
$GATES_
GATES
    [ "$newer" -eq 1 ] && continue
    if [ -n "$dir" ] && [ $((SECONDS - started)) -lt "$LS_REMOTE_BUDGET" ]; then
      tip="$(GIT_TERMINAL_PROMPT=0 git -C "$dir" ls-remote origin "refs/heads/$branch" 2>/dev/null | cut -f1 | head -n 1)"
      if [ -n "$tip" ] && ! sha_match "$tip" "$sha"; then
        head_gated "$branch" "$tip" "$dir" && continue
        sha="$tip"
      fi
    fi
    case " $seen " in *" $branch@$sha "*) continue ;; esac
    seen="$seen $branch@$sha"
    printf '%s\t%s\t%s\n' "$proot" "$branch" "$sha"
  done
}

run_mode() {
case "$MODE" in

submit)
  # A prompt that cannot be read (jq fails) or recorded is marked, so the merge guard declines rather
  # than miss it: mark_unrecorded leaves <session>.unrecorded in the session state.
  # A NUL in the prompt cannot survive a shell variable (bash drops it, gluing "Actually\0wait" into
  # one word), so the recorded text would differ from what was typed: mark it unrecorded instead. Only an
  # explicit "false" from jq clears it; an error counts as a NUL.
  nul="$(printf '%s' "$INPUT" | jq -r '(.prompt // "") | tostring | test("\u0000")' 2>/dev/null)"
  [ "$nul" = "false" ] || { mark_unrecorded; exit 0; }
  prompt="$(jf '.prompt')" || { mark_unrecorded; exit 0; }
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
    | gsub("^\\s+|\\s+$"; "")' 2>/dev/null)" || { mark_unrecorded; exit 0; }
  [ -n "$stripped" ] || exit 0
  # A peer's message (a subagent's <agent-message> report or another session's <cross-session-message>)
  # is Claude-authored data, not Simon's words. Record it as a `peer` entry so reconciliation still sees
  # it, but `latest-ask` (the merge guard's source of Simon's own words) and the turn's ask time
  # never read it (the fix for a subagent report recorded as the newest "ask", which the merge guard
  # then judged instead of Simon's own message).
  # A peer relay without the envelope tags is the same data: a turn that opens with another session's
  # attribution ("From the tokyo session (PR #12), per Simon: ...", "From tokyo (session 2e47dc28), ...",
  # "Another Claude session sent a message: ...") is Claude-authored, whatever it quotes Simon as saying
  # (the fix for three tokyo relays recorded as Simon's asks). The capitalised opener is the Claude form;
  # Simon's own lowercase "from the tokyo session, merge it" stays his ask.
  kind=ask
  own="$(printf '%s' "$stripped" | jq -Rrs '
    gsub("<(agent-message|cross-session-message)\\b[^>]*>.*?</(agent-message|cross-session-message)>"; ""; "mgi")
    | gsub("^\\s+|\\s+$"; "")
    | if test("\\A(Another Claude session\\b|(From|Relayed from|Forwarded from|Message from)\\s+(the\\s+)?[A-Za-z0-9._-]+(\\s+session\\b(?![\u0027\u2019])|\\s*\\(session\\b))")
      then "" else gsub("Another Claude session sent a message:"; ""; "g") | gsub("^\\s+|\\s+$"; "") end' 2>/dev/null)" || { mark_unrecorded; exit 0; }
  [ -n "$own" ] || kind=peer

  # A real prompt that cannot be recorded (the ledger does not resolve) is marked like a failed append,
  # so the merge guard declines rather than miss it.
  resolve || { mark_unrecorded; exit 0; }

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
  } >> "$target" 2>/dev/null || {
    mark_unrecorded; exit 0; }

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
  ~/.claude/hooks/intent-ledger.sh gate <branch> <sha|HEAD> PASS|BLOCKED|N/A [hotfix|light|standard|deep] [reason]
(a standard or deep PASS holds \"All stages ran\"; a BLOCKED holds it or \"Not run: <stage>, <stage>\")
or Stop blocks once for the missing gate. A PASS names its tier and needs a receipt on that head for
every stage the tier requires; each Skill-tool run of a stage records one for the HEAD of the checkout
the work runs in (a subagent's: the one its last Bash cd'd into).
  ~/.claude/hooks/intent-ledger.sh stages <tier> HEAD   lists the stages still missing there."
  jq -cn --arg c "GAUNTLET UPDATE: read the new ask in $target and the existing living plan. Apply \
references/workflow-loops.md section Continuous request reconciliation before continuing: capture \
every added requirement, preserve unfinished items and the return point, then refresh the dashboard. \
Keep config learning for the session's end: after all task work is verified, ask Simon to say go for \
the end-of-session config learning (references/session-performance.md section End-of-session learning), \
or run it unasked once his go stands this session (intent-ledger.sh learning-count); \
fix a config defect now only when it blocks the current task. An answer or status question does not cancel \
older work. Recording an ask does not grant approval." \
    '{hookSpecificOutput:{hookEventName:"UserPromptSubmit",additionalContext:$c}}'
  exit 0
  ;;

note)
  kind="${2:-}"; src="${3:-}"
  case "$kind" in sources|plan|pivot|reconcile|learning) ;; *)
    echo "note: kind must be sources|plan|pivot|reconcile|learning" >&2; exit 2 ;;
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
  # One snapshot of the source is validated and appended, so a file replaced after the checks (while the
  # writer waits for the lock) can never put unchecked text in the ledger.
  orig_src="$src"
  snap="$(mktemp "${TMPDIR:-/tmp}/ledger-note.XXXXXX")" || { echo "note: could not snapshot $src" >&2; exit 2; }
  cat -- "$orig_src" > "$snap" || { rm -f "$snap"; echo "note: could not read $src" >&2; exit 2; }
  src="$snap"
  # Gate and receipt entries are written only by `gate` and the receipt recorder. A note carrying
  # their heading would open such a section and forge a record the ship gate trusts.
  # An unclosed fence would shift which later lines the fence-aware readers treat as prompt text. The
  # check runs the readers' own fence rules (FENCE_AWK), so what passes here reads the same there.
  if ! awk "$FENCE_AWK"' END { exit (fence ? 1 : 0) }' "$src" 2>/dev/null; then
    echo "note: refusing: $orig_src has an unclosed code fence. Close it, then rerun." >&2; rm -f "$snap"; exit 2
  fi
  if grep -qE '^##.* · (ask|peer) · session ' "$src" 2>/dev/null; then
    echo "note: refusing: $orig_src holds a '## <time> · ask · session' heading, which only the prompt recorder writes. Reword that line." >&2
    rm -f "$snap"; exit 2
  fi
  if grep -qE '^##.* · (gate|receipt|learning)$' "$src" 2>/dev/null; then
    echo "note: refusing: $orig_src holds a '## <time> · gate', '· receipt' or '· learning' heading, which only their recorders write. Reword that line." >&2
    rm -f "$snap"; exit 2
  fi
  # The end-of-session learning note is what lets the archive line through, so only Simon's own word
  # opens it: an ask since the previous learning note that says go or skip (learning_go: Haiku-judged).
  # KPIS.md ask coverage: a reconcile names a verdict for every ask it closes, one line each, so a
  # missed ask shows at the note, not when Simon notices it later (the fix for asks found missing after
  # hand-back until he ran the journey check by hand).
  if [ "$kind" = "reconcile" ]; then
    _asks="$(asks_since_reconcile)"
    _lines="$(grep -cE '[^[:space:]]' "$src" 2>/dev/null || echo 0)"
    if [ "${_asks:-0}" -gt 0 ] && [ "${_lines:-0}" -lt "${_asks:-0}" ]; then
      echo "note: refusing: $_asks asks since the last reconcile but $_lines verdict lines. Write one line per ask: '- <ask, in his words> -> <done + evidence | blocked: Simon-only reason | open: next action>' (KPIS.md ask coverage)." >&2
      rm -f "$snap"; exit 2
    fi
  fi
  if [ "$kind" = "learning" ]; then
    if ! grep -qE 'session learning: (done|skipped)' "$src" 2>/dev/null; then
      echo "note: refusing: a learning note holds \"session learning: done\" or \"session learning: skipped\"." >&2
      rm -f "$snap"; exit 2
    fi
    # A standing go (the newest learning note said done) needs no new ask; check it before the judge.
    if [ "$(learning_state | cut -f4)" != 1 ] && [ "$(learning_go)" != 1 ]; then
      echo "note: refusing: no ask since the last learning note says go or skip. Ask Simon: \"Action needed: say go to run the end-of-session config learning over your N messages in this session\"." >&2
      rm -f "$snap"; exit 2
    fi
  fi
  acquire "$LEDGER" || { rm -f "$snap"; echo "note: could not acquire the ledger lock" >&2; exit 2; }
  header_if_new "$LEDGER"
  { printf '\n## %s · %s\n\n' "$(date -u +%Y-%m-%dT%H:%M:%SZ)" "$kind"; cat "$src"; printf '\n'; } \
    >> "$LEDGER"
  rm -f "$orig_src" "$snap"
  # The learning note dies with the worktree; copy which sessions it covers to the durable record that
  # every cleanup path gates on (bin/session_learning.py).
  [ "$kind" = "learning" ] && python3 "$CFG_ROOT/bin/session_learning.py" record-ledger "$LEDGER" >/dev/null 2>&1

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
  # push, a push to main or master, and any repo inside the config repo record nothing. A refspec or
  # directory built at run time (`"$b"`, `cd "$wt"`) is read from the push's own output instead.
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
  dir="$cwd"; built=0
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
      case "$t" in *'$'*|*'`'*) built=1 ;; /*) built=0 ;; esac  # a run-time directory: the checkout is unknown
      if [ -n "$t" ] && nd="$(cd "$dir" 2>/dev/null && cd "$t" 2>/dev/null && pwd -P)"; then dir="$nd"; fi
      continue
    fi
    [ "${w[$i]}" = git ] || continue
    i=$((i + 1)); gdir="$dir"; gbuilt="$built"
    while [ "$i" -lt "$n" ]; do
      case "${w[$i]}" in
        -C) t="${w[$((i + 1))]:-}"; t="${t/#\~/$HOME}"
            case "$t" in *'$'*|*'`'*) gbuilt=1 ;; /*) gbuilt=0 ;; esac
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
    case " ${pos[*]:-} " in *'$'*|*'`'*) gbuilt=1 ;; esac
    if [ "$gbuilt" = 1 ]; then
      record_pushed_output "$root"
    elif [ "${#pos[@]}" -le 1 ]; then
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
  sweep_state
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
  case "$tier" in hotfix|light|standard|deep) ;; *)
    echo "stages: usage: stages <hotfix|light|standard|deep> [sha|HEAD] [branch]" >&2; exit 2 ;;
  esac
  [ -n "${3:-}" ] || { tier_stages "$tier"; exit 0; }
  sha="$(git rev-parse --verify -q "$3^{commit}" 2>/dev/null)" || sha="$(printf '%s' "$3" | tr '[:upper:]' '[:lower:]')"
  case "$sha" in *[!0-9a-f]*|"") echo "stages: cannot resolve $3 to a commit" >&2; exit 2 ;; esac
  QUIET=1
  resolve || { echo "stages: no ledger for this worktree (see the session's ledger notice)" >&2; exit 2; }
  sbr="${4:-}"
  if [ -z "$sbr" ] && sha_match "$(git rev-parse --verify -q 'HEAD^{commit}' 2>/dev/null)" "$sha"; then
    sbr="$(git symbolic-ref -q --short HEAD 2>/dev/null)"
  fi
  [ -n "$sbr" ] && LIGHT_WAIVED="$(tier_waivers "$tier" "$sbr")"
  st="$(stage_status "$tier" "$sha" "$sbr")"
  miss="$(printf '%s\n' "$st" | sed -n 1p)"; from="$(printf '%s\n' "$st" | sed -n 2p)"
  [ -n "$LIGHT_WAIVED" ] && echo "Stood in for by the open PR: $LIGHT_WAIVED"
  if [ -n "$miss" ]; then echo "Not run: $miss"; exit 1; fi
  if [ -n "$from" ]; then echo "All stages ran (carried from $from: a Light-sized follow-up delta)"; exit 0; fi
  echo "All stages ran"
  exit 0
  ;;

gate)
  branch="${2:-}"; ref="${3:-}"; status="$(printf '%s' "${4:-}" | tr '[:lower:]' '[:upper:]')"
  # Optional tier (references/testing-strategy.md, Size the checks to the change). A light or
  # standard PASS skipped stages, so it needs a reason naming its trigger and the skips.
  tier="$(printf '%s' "${5:-}" | tr '[:upper:]' '[:lower:]')"
  case "$tier" in hotfix|light|standard|deep) reason="${*:6}" ;; *) tier=""; reason="${*:5}" ;; esac
  usage="gate: usage: gate <branch> <sha|HEAD> <PASS|BLOCKED|N/A> [hotfix|light|standard|deep] [reason]"
  case "$status" in PASS|BLOCKED|N/A) ;; *) echo "$usage" >&2; exit 2 ;; esac
  if [ -z "$branch" ] || [ -z "$ref" ]; then echo "$usage" >&2; exit 2; fi
  # One record is one line: a line break in the branch or reason would append a second, forged gate line.
  case "$branch$reason" in *$'\n'*|*$'\r'*)
    echo "gate: the branch and reason must be one line each" >&2; exit 2 ;;
  esac
  case "$branch" in *[[:space:]]*|*[[:cntrl:]]*)
    echo "gate: the branch name holds whitespace or a control character" >&2; exit 2 ;;
  esac
  case "$reason" in *[[:cntrl:]]*)
    echo "gate: the reason holds a control character" >&2; exit 2 ;;
  esac
  if [ "$status" != PASS ] && [ -z "$reason" ]; then
    echo "gate: $status needs a reason (the blocker, or why the harness does not apply)" >&2; exit 2
  fi
  # A PASS names its tier, because the tier decides which stage receipts it needs; an untiered PASS
  # would skip that check.
  if [ "$status" = PASS ] && [ -z "$tier" ]; then
    echo "gate: a PASS names its tier (hotfix|light|standard|deep), which decides the stage receipts it needs" >&2; exit 2
  fi
  if [ "$status" = PASS ] && [ -z "$reason" ] && { [ "$tier" = light ] || [ "$tier" = standard ] || [ "$tier" = hotfix ]; }; then
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
  # Simon's waiver ("it's fine", "just merge") is an N/A whose quote is his own recorded words, so no
  # agent can waive the harness for him. It also covers the branch's later heads (open_pushes).
  case "$reason" in *"waived by Simon:"*)
    if [ "$status" != N/A ]; then
      echo "gate: a waiver is recorded as N/A: gate <branch> <sha> N/A [tier] \"waived by Simon: <his words>\"" >&2; exit 2
    fi
    quote="$(printf '%s' "${reason#*waived by Simon:}" | norm_text | sed -e 's/^[ "]*//' -e 's/[ "]*$//')"
    if [ "${#quote}" -lt 8 ] || ! ask_text | grep -qF -- "$quote"; then
      echo "gate: waiver refused: \"$quote\" is not 8+ characters of an ask Simon typed in this session's ledger. \
Quote his own words verbatim, or run the tier's stages." >&2; exit 2
    fi ;;
  esac
  # Stage receipts on this exact head back the stage statement, so neither a PASS nor "All stages ran"
  # rests on reason text alone. A receipt on an older head never counts.
  if [ -n "$tier" ] && [ "$status" != N/A ]; then
    LIGHT_WAIVED="$(tier_waivers "$tier" "$branch")"
    miss="$(missing_stages "$tier" "$sha" "$branch")"
    fix="Invoke each with the Skill tool (e.g. Skill sk:ship-review) while the session's working \
directory (a subagent: the directory its last Bash cd'd into) is the checkout at ${sha:0:7}; each run \
records a receipt for that head. Check with
  ~/.claude/hooks/intent-ledger.sh stages $tier ${sha:0:7} $branch"
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
  [ -n "$LIGHT_WAIVED" ] && reason="$reason; stood in for by the open PR: $LIGHT_WAIVED"
  if [ "$status" = PASS ]; then landing_check "$branch" "$sha" || exit 1; fi
  acquire "$LEDGER" || { echo "gate: could not acquire the ledger lock" >&2; exit 2; }
  header_if_new "$LEDGER"
  {
    printf '\n## %s · session %s · gate\n\n' "$(date -u +%Y-%m-%dT%H:%M:%SZ)" "$SID"
    printf 'gate: %s %s %s %s\n' "$branch" "$sha" "$status" "$reason"
  } >> "$LEDGER"
  echo "Recorded $status gate for $branch at ${sha:0:7} in $LEDGER"
  exit 0
  ;;

stop)
  # Loop safety, three independent guards. A Stop hook that re-blocks the finish it just caused is an
  # unbreakable session, which is the failure task-intake.sh documents for a different hook.
  #   1. stop_hook_active — the payload's own "you are already continuing because of a stop hook".
  #      The reconciliation block never fires on it; the runtime and learning gates may, each
  #      single-use per ledger snapshot, so one snapshot sees at most one block of each kind.
  #   2. markers for the exact ledger snapshot, so unchanged work cannot re-block.
  #   3. a reason that names the exact command satisfying it, so there is always a way out.
  active="$(jf '.stop_hook_active')"
  mkdir -p "$STATE" 2>/dev/null || exit 0
  resolve || exit 0
  [ -f "$LEDGER" ] || exit 0

  # The reconciliation, runtime and end-of-session learning checks. Run in a subshell so every exit 0 inside it
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
  # Unreconciled work comes first: the turn is mid-task, so only the reconciliation below can block.
  if [ "$pending" != 1 ]; then
    # Runtime asks (references/planning-and-tracking.md § Runtime asks): a
    # deployed system's clause is met only by a production run after its deploy. While the newest
    # reconcile still lists one as `runtime: open`, block once per ledger snapshot, also on a
    # stop_hook_active continuation (its own marker bounds it), so hand-back waits on the next run.
    ropen="$(runtime_open "$LEDGER")"
    if [ -n "$ropen" ]; then
      rsnap="$(cksum < "$LEDGER")"
      if [ "$(cat "$STATE/$SID.runtimegate" 2>/dev/null)" != "$rsnap" ]; then
        printf '%s\n' "$rsnap" > "$STATE/$SID.runtimegate" 2>/dev/null || exit 0
        jq -cn --arg l "$ropen" --arg r "The newest reconciliation in $LEDGER lists runtime clauses still open:" \
          --arg t "A deployed system's runtime clause is met only by a production run that started after its \
deploy (references/planning-and-tracking.md, Runtime asks). Before finishing: wait \
event-driven for the next deploy or scheduled run (gh run watch <id>, or a run_in_background wait with a \
timeout; never a cron or a tight poll), read its output against each open clause, fix and deploy what \
failed, then append a reconcile whose line for each clause reads runtime: observed <evidence link> or \
runtime: blocked <Simon-only reason>. Stop early only for the same failure in 2 consecutive runs, a \
Simon-only decision, or a flake, naming the clause, runs and next step; no archive line while one is open. \
This fires at most once per ledger snapshot." \
          '{decision:"block",reason:($r + "\n" + $l + "\n" + $t)}'
        exit 0
      fi
    fi
    # Ask coverage (KPIS.md): the archive line waits while the newest reconcile still lists an ask as
    # open, not met or partly met, so the session keeps working until each one is met, blocked on a
    # Simon-only reason, or dropped by his own words (the fix for asks found missing after hand-back).
    case "$(jf '.last_assistant_message')" in *"You can archive this session"*)
      unmet="$(unmet_asks "$LEDGER")"
      if [ -n "$unmet" ]; then
        usnap="$(cksum < "$LEDGER")"
        if [ "$(cat "$STATE/$SID.unmetgate" 2>/dev/null)" != "$usnap" ]; then
          printf '%s\n' "$usnap" > "$STATE/$SID.unmetgate" 2>/dev/null || exit 0
          jq -cn --arg l "$unmet" --arg r "The newest reconciliation in $LEDGER still lists asks that are not done:" \
            --arg t "Keep working until each is met with evidence (KPIS.md ask coverage), then append a reconcile whose \
line for it reads done; only a Simon-only blocker (blocked: <reason>) or his own drop decision may stay. No archive line \
before then. This fires at most once per ledger snapshot." '{decision:"block",reason:($r + "\n" + $l + "\n" + $t)}'
          exit 0
        fi
      fi ;;
    esac
    # End-of-session learning gate (rules/communication.md Close the session). The archive line waits
    # until a learning note covers every ask this session sent: Simon says go or skip, the session
    # learns (or records the skip), and only then archives. Work turns are never blocked for it, and
    # it fires once per ledger snapshot, so it cannot loop.
    last="$(jf '.last_assistant_message')"
    case "$last" in *"You can archive this session"*) ;; *) exit 0 ;; esac
    lstate="$(learning_state)"
    n="$(printf '%s' "$lstate" | cut -f2)"
    [ "${n:-0}" -gt 0 ] 2>/dev/null || exit 0
    lsnap="$(cksum < "$LEDGER")"
    [ "$(cat "$STATE/$SID.learngate" 2>/dev/null)" = "$lsnap" ] && exit 0
    printf '%s\n' "$lsnap" > "$STATE/$SID.learngate" 2>/dev/null || exit 0
    if [ "$(printf '%s' "$lstate" | cut -f4)" = 1 ]; then
      jq -cn --arg r "Simon's go for the end-of-session config learning stands for this session: run \
references/session-performance.md section End-of-session learning over his $n newer messages now, without \
asking him again, record ~/.claude/hooks/intent-ledger.sh note learning <scratch.md> holding \
\"session learning: done\", then give the archive line. This fires at most once per ledger snapshot." \
        '{decision:"block",reason:$r}'
      exit 0
    fi
    jq -cn --arg r "The archive line waits for the end-of-session config learning: $n of Simon's \
messages in this session have no learning note. Replace the archive line with line 1 \
\"Action needed: say go to run the end-of-session config learning over your $n messages in this session\" \
(or \"skip\"). On go, run references/session-performance.md section End-of-session learning, record \
~/.claude/hooks/intent-ledger.sh note learning <scratch.md> holding \"session learning: done\" (or \
\"session learning: skipped\" on skip), then give the archive line. This fires at most once per ledger snapshot." \
      '{decision:"block",reason:$r}'
    exit 0
  fi
  [ "$active" = "true" ] && exit 0
  # A turn that ends only to wait on background work is paused, not done (the Stop payload's
  # background_tasks, Claude Code hooks reference): reconcile at the real hand-back, never on every wait
  # (KPIS.md: Stop blocks per request; 61% of session time was such waits, 2026-11-27 audit).
  [ "$(printf '%s' "$INPUT" | jq -r '(.background_tasks // []) | length' 2>/dev/null)" -gt 0 ] 2>/dev/null && exit 0
  snapshot="$(cksum < "$LEDGER")"
  [ "$(cat "$STATE/$SID.stopblock" 2>/dev/null)" = "$snapshot" ] && exit 0
  printf '%s\n' "$snapshot" > "$STATE/$SID.stopblock" 2>/dev/null || exit 0
  # A stretch of pure status questions or thanks adds nothing to reconcile: the Haiku step says so and the
  # turn ends unblocked. Any new work, a plan or pivot entry, or no verdict keeps the block below.
  status_only && exit 0
  jq -cn --arg r "This worktree has recorded input newer than its last reconciliation. Before \
finishing: re-read $LEDGER and the living gauntlet plan, account for every request and remaining \
item, continue ready authorized work, and append the current outcomes with
  ~/.claude/hooks/intent-ledger.sh note reconcile <scratch.md>
Config learning waits for the session's end (rules/self-healing-config.md); fix now only a config defect blocking this task. \
Record evidence for completed work and the next action for every real blocker or pause (not hypothetical checks; see rules/communication.md Close the session). An unapproved \
proposal remains recorded, not permission to implement. Open the final message by answering each question \
and point of the prompt that started this work, in its order, before any status (rules/communication.md \
Answer first). When the session opened, pushed, reviewed or merged a PR, the final message's last block is \
the PR status block (references/tldr-report-formats.md § PR status block: each PR linked once under Merged, \
Approved, merging, Needs your ok, In progress or Deferred / blocked). When nothing is left, end the final message with \
the end-of-session learning ask from rules/communication.md Close the session (or run it when his go already stands), and the archive line only \
once a learning note covers this session's messages; with CI running, a session PR awaiting Simon's merge or a \
promised smoke or reply open, end with the PR status block and no archive line. When this turn began from a background \
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
    CARRY_DIR="$oroot"; carry="$(carriable_heads "$osha" "$obranch")"
    for t in hotfix light standard deep; do
      st="$(stage_status "$t" "$osha" "$obranch" "$carry")"
      m="$(printf '%s\n' "$st" | sed -n 1p)"; f="$(printf '%s\n' "$st" | sed -n 2p)"
      if [ -n "$m" ]; then printf '    %s: Not run: %s\n' "$t" "$m"
      elif [ -n "$f" ]; then printf '    %s: All stages ran (carried from %s: a Light-sized follow-up delta; run only its own checks)\n' "$t" "$f"
      else printf '    %s: All stages ran\n' "$t"; fi
    done
  done)"
  msg="This session pushed these branches and recorded no ship-gate result for the pushed head:
$list
Before finishing, run /sk:ship-full-detailed-workflow on each at its tier (references/testing-strategy.md, \
Size the checks to the change; rules/process.md, Prove every point of the ask was built): invoke each \
stage listed under that tier above with the Skill tool, from the checkout at that head (each run records \
its receipt; a receipt on an older head does not count). When that branch's checkout is not this \
session's cwd, record each stage you ran for it with \
\`~/.claude/hooks/intent-ledger.sh receipt <stage> <checkout dir>\` (it records that dir's HEAD). Then record the gate:
  ~/.claude/hooks/intent-ledger.sh gate <branch> <sha|HEAD> PASS|BLOCKED|N/A [hotfix|light|standard|deep] [reason]
BLOCKED, N/A and a hotfix, light or standard PASS need a reason: the exact blocker, why the harness does not \
apply to this push, or the tier's trigger and skipped stages. A standard or deep BLOCKED \
reason holds \"All stages ran\" or \"Not run: <stage>, <stage>\" naming each stage not invoked as its own \
skill on that head; a standard or deep PASS holds \"All stages ran\" and is refused with any \"Not run:\" list. \
A PASS names its tier and is refused while any stage that tier requires has no receipt on the head. \
Run every stage the tier requires first, on the newest head, unprompted, even when an external blocker makes it BLOCKED. A gate \
recorded for an older head does not count once a newer head is pushed; only each branch's latest head is listed. A light or standard tier reading \"carried from\" \
needs only the follow-up delta's own checks (its affected tests, one screenshot if it is visible, the PR body's head) before \
the gate (references/testing-strategy.md, Follow-up pushes). On a light head with an open PR, \`gate\` and \`stages light <sha> <branch>\` \
drop sk:ship-screenshot-changes (the landing gate checks the PR's Screenshots section) and, when the PR has no review or \
comment, sk:ship-resolve-pr-comments; a hotfix head drops the latter the same way. When Simon waived the checks for this PR, record \
gate <branch> <sha> N/A <tier> \"waived by Simon: <his words verbatim>\"; it covers the branch's later heads. \
This fires at most once per set of open pushes."
  jq -cn --arg r "$msg" '{decision:"block",reason:$r}'
  exit 0
  ;;

latest-ask)
  # This session's recorded asks, verbatim. Same resolution as `submit`, silent, read-only; no ledger
  # or no ask for this session prints nothing. `--since <ts>` returns every ask from that second on.
  QUIET=1
  since=""; stamped=0
  if [ "${2:-}" = "--stamped" ]; then stamped=1; shift; fi
  if [ "${2:-}" = "--since" ]; then
    since="${3:-}"
    case "$since" in
      [0-9][0-9][0-9][0-9]-[0-9][0-9]-[0-9][0-9]T[0-9][0-9]:[0-9][0-9]:[0-9][0-9]Z) ;;
      *) exit 0 ;;
    esac
  fi
  if ! resolve; then [ "$stamped" = 1 ] && exit 3; exit 0; fi
  # The stamped read serves the merge guard's final check: a prompt in the lock-contention fallback
  # file is a recorded message it cannot see, so it fails (exit 4), checked again after the read.
  fallback="${LEDGER%.md}.$SID.md"
  [ "$stamped" = 1 ] && [ -e "$fallback" ] && exit 4
  [ -f "$LEDGER" ] || exit 0
  # Every prompt record of every session and kind (ask, peer) is parsed with its fence, and only then
  # filtered to this session's asks, so text inside ANY prompt (a pasted heading included) is never
  # read as a record boundary. Any unfinished record (no fence before the next heading or the end, or
  # an unclosed fence) exits 5, so the merge guard treats the read as failed. --stamped prints each
  # record as "<time>\037<ask|peer>\037<text>", split by \036, so one read serves every window.
  awk -v sid="$SID" -v since="$since" -v stamped="$stamped" '
    function flush() { if (mine) { rec = (stamped ? ts "\037" kind "\037" : "") buf; last = rec
      if (since != "" && (ts "") >= (since "")) { out = out (n++ ? "\036" : "") rec } } }
    inrec && fence != "" && $0 == fence { flush(); inrec = 0; fence = ""; next }
    # A prompt holding the reserved \036 or \037 delimiter could split into forged records: fail the read.
    inrec && fence != "" { if (mine) { if (index($0, "\036") || index($0, "\037")) broken = 1; buf = buf $0 "\n" }
      next }
    $0 ~ /^## [0-9][0-9][0-9][0-9]-[0-9][0-9]-[0-9][0-9]T[0-9][0-9]:[0-9][0-9]:[0-9][0-9]Z · (ask|peer) · session [A-Za-z0-9._-]+$/ &&
      split($0, part, " · ") == 3 {
      if (inrec) broken = 1
      # --stamped also returns the peer records of this session, so the time-order check of the merge guard
      # sees every record; the guard then drops them: a peer envelope neither holds nor lifts.
      inrec = 1; fence = ""; buf = ""; ts = $2; kind = part[2]
      mine = ((part[2] == "ask" || (stamped && part[2] == "peer")) && part[3] == "session " sid); next }
    inrec && fence == "" && $0 ~ /^`{3,}$/ { fence = $0; next }
    inrec && index($0, "## ") == 1 { broken = 1; inrec = 0 }
    # --stamped also returns this session'"'"'s gate records, in append order with the asks, so the guard can
    # tell a message written after a gate even when the clock stepped back between them.
    # Compared as a string, never a regex: a "." in a session id must not match another id.
    !inrec && index($0, "## ") == 1 { gsuf = " · session " sid " · gate"
      ingate = (stamped && length($0) > length(gsuf) && substr($0, length($0) - length(gsuf) + 1) == gsuf)
      gts = $2; next }
    !inrec && ingate && /^gate: / && (index($0, "\036") || index($0, "\037")) { broken = 1; next }
    !inrec && ingate && /^gate: / && since != "" && (gts "") >= (since "") { out = out (n++ ? "\036" : "") gts "\037gate\037" $0 }
    END { if (inrec || broken) exit 5; if (since == "") printf "%s", last; else printf "%s", out }
  ' "$LEDGER"
  rc=$?
  [ "$stamped" = 1 ] && [ -e "$fallback" ] && exit 4
  exit $rc
  ;;

learning-count)
  # Read-only: N for the hand-back's "say go ... over your N messages" line. Silent with no ledger.
  QUIET=1
  resolve || exit 0
  learning_state | cut -f2
  exit 0
  ;;

gates)
  # Read-only: every recorded landing-gate line of this session's ledger, outside prompt fences, as
  # `gate: <branch> <sha> <STATUS> <tier> <reason>`. hooks/git-commit-guard.py reads it for the
  # monitoring-only merge path, which needs a PASS on the PR's exact head. Silent with no ledger.
  # Only this session's records count: the writer stamps its session id into the heading. Exit 3 when
  # the ledger cannot be resolved, so the guard tells a failed read from an empty one.
  QUIET=1
  resolve || exit 3
  # A prompt written to the lock-contention fallback file is not in the ledger yet: exit 4, so the
  # guard declines rather than miss a halt there.
  [ -e "${LEDGER%.md}.$SID.md" ] && exit 4
  [ -f "$LEDGER" ] || exit 0
  # A ledger that ends inside a fence exits 6: every record after the opening line is unreadable.
  awk -v sid="$SID" "$FENCE_AWK"'
    !fence && /^## [0-9][0-9][0-9][0-9]-/ { stamp = $2; suffix = " · session " sid " · gate"
      insec = (length($0) > length(suffix) && substr($0, length($0) - length(suffix) + 1) == suffix); next }
    !fence && insec && /^gate: [^ ]+ [0-9a-f]+ (PASS|BLOCKED|N\/A)( |$)/ { print stamp " " $0 }
    END { if (fence) exit 6 }
  ' "$LEDGER"
  exit $?
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
