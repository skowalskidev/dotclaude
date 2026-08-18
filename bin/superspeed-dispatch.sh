#!/usr/bin/env bash
# superspeed-dispatch — fan a task out across real parallel Claude sessions and log everything.
#
# WHY THIS EXISTS (measured 2026-08-06, Claude Code 2.1.220, Apple M2 8-core, Max plan)
# Every IN-SESSION parallelism primitive is capped: subagents at 20 concurrent (10 in your
# settings), dynamic workflows at 16 and reduced further on machines with few cores. Separately
# launched sessions have no documented cap. Across 4 configurations and 14 reps, four parallel
# `claude -p` processes beat one session fanning out to four subagents EVERY time: 2.36x at one
# round, 1.48x at three rounds, with identical correctness (24/24 both).
#
# WHAT IT IS NOT. The advantage is a roughly constant ~33s of orchestrator turn-taking, not a
# multiplier. On an hour-long job that is under 1%. Do not reach for this to make long work faster;
# reach for it when a task genuinely splits and you want the splits running at once.
#
# Usage:
#   superspeed-dispatch.sh <slices.json> [outdir]
#
# slices.json:
#   {
#     "task": "one line describing the whole job",
#     "repo": "/abs/path/to/repo",
#     "gate": "yarn lint && yarn test",          # optional, run by the RECONCILER not by slices
#     "setup": "yarn install",                    # optional, run ONCE here before any slice starts;
#                                                 # take it from the repo's CLAUDE.md / CLAUDE.local.md
#     "model": "claude-sonnet-4-6",               # optional, default claude-sonnet-4-6
#     "slices": [
#       { "name": "api",
#         "owns":    ["apps/api/src/routes/foo.ts"],
#         "reads":   ["packages/types/src/foo.ts"],
#         "forbid":  ["apps/api/src/routes/bar.ts"],
#         "accept":  "apps/api/src/routes/foo.ts contains a handler named createFoo",
#         "verify":  "npm run test:run -- apps/api/src/routes/__tests__/foo.test.ts",
#                    # the ONE command this slice runs to check itself. Must be covered by the
#                    # repo's permissions.allow, or dispatch stops before spending. "none" only
#                    # when nothing the slice writes is runnable.
#         "prompt":  "what this slice must do" }
#     ]
#   }
#
# Every slice runs with CLAUDE_INTAKE_GATE=off, because the intake gate cannot be satisfied by a
# headless session and would otherwise deny the run after the reading is already paid for.
# It also runs with CLAUDE_INTENT_LEDGER=off: slices share the orchestrator's directory, so N of them
# would race on one ledger, and a dispatched machine-written prompt does not belong in a record whose
# whole value is that it is your words verbatim.

set -uo pipefail

SPEC="${1:?usage: superspeed-dispatch.sh <slices.json> [outdir]}"
OUT="${2:-.superspeed/$(date +%Y%m%d-%H%M%S)}"

command -v jq >/dev/null 2>&1 || { echo "superspeed: jq is required" >&2; exit 2; }
[ -f "$SPEC" ] || { echo "superspeed: no such spec: $SPEC" >&2; exit 2; }

REPO="$(jq -r '.repo // "."' "$SPEC")"
MODEL="$(jq -r '.model // "claude-sonnet-4-6"' "$SPEC")"
TASK="$(jq -r '.task // ""' "$SPEC")"
N="$(jq '.slices | length' "$SPEC")"

REPO="$(cd "$REPO" 2>/dev/null && pwd)" || { echo "superspeed: repo not found" >&2; exit 2; }

# The run directory MUST live inside the repo. A slice runs with the repo as its working directory and
# is sandboxed to it, so a run dir anywhere else means every slice fails to write its DONE.md and the
# whole fan-out reports "no-done-marker" for reasons that look nothing like the real cause. Found the
# hard way on the first end-to-end run, 2026-08-06.
case "$OUT" in
  /*) : ;;
  *) OUT="$REPO/$OUT" ;;
esac
mkdir -p "$OUT" 2>/dev/null
OUT="$(cd "$OUT" 2>/dev/null && pwd)" || { echo "superspeed: cannot create $OUT" >&2; exit 2; }
case "$OUT/" in
  "$REPO"/*) : ;;
  *) echo "superspeed: run dir must be inside the repo ($REPO), got $OUT.
Slices are sandboxed to the repo working directory and cannot write outside it." >&2; exit 2 ;;
esac

mkdir -p "$OUT/slices" || exit 2
cp "$SPEC" "$OUT/spec.json"

log() { printf '%s %s\n' "$(date +%H:%M:%S)" "$*" | tee -a "$OUT/run.log"; }
loadnow() { sysctl -n vm.loadavg 2>/dev/null | tr -d '{}' | awk '{print $1}' || echo 0; }

log "superspeed start: $N slices, model=$MODEL, repo=$REPO"
log "task: $TASK"
[ "$N" -gt 5 ] && log "WARNING: $N slices. Anthropic's guidance and the measured curve both say 3-5; \
beyond that coordination overhead and machine contention grow faster than the gain."

# ---- refuse to fan out onto the config directory itself ------------------------------------------
# A headless `claude -p` session CANNOT write anywhere under ~/.claude: the harness treats it as a
# sensitive path and denies Write, Edit and a Bash redirect alike, with no prompt a human can answer.
# Measured 2026-08-08: five slices ran to completion, reported the block in their result text, wrote
# no DONE.md, and cost $10.57 for zero output. Every one failed the same way, which is the same class
# as a missing `setup` — so it stops here, loudly, before spending anything.
# DO the config work in the interactive session instead; writes land there.
case "$REPO" in
  "$HOME/.claude"|"$HOME/.claude/"*)
    {
      echo
      echo "superspeed: STOPPED before dispatch. repo is $REPO, inside ~/.claude."
      echo "A headless claude -p cannot write under ~/.claude — the harness denies Write, Edit and"
      echo "Bash redirects there, with no prompt a headless session can answer. Five slices once"
      echo "spent \$10.57 discovering this and produced nothing."
      echo "Do config edits in the interactive session, through /sk:claude-config-update."
    } | tee -a "$OUT/run.log" >&2
    exit 5
    ;;
esac

# ---- setup, ONCE, by the orchestrator ------------------------------------------------------------
# The orchestrator needs a working tree anyway, to run the gate at reconcile. And in the recommended
# same-directory model there is exactly one tree, so setting it up once here serves every slice. Doing
# it per slice would run the same install N times in parallel, in one directory, racing each other.
#
# So: run the repo's documented ritual here, verify it, and tell the slices it is already done. If it
# fails, abort BEFORE spending on any slice, because every slice would fail the same way separately.
SETUP="$(jq -r '.setup // empty' "$SPEC")"

if [ -z "$SETUP" ]; then
  # STOP. Do not guess. A wrong assumption here fails N times in parallel, and the errors it produces
  # look nothing like their cause, so the cheapest place to resolve it is before anything is spent.
  SETUP_DOC=""
  for f in "$REPO/CLAUDE.md" "$REPO/CLAUDE.local.md"; do
    [ -f "$f" ] && SETUP_DOC="$SETUP_DOC $f"
  done
  {
    echo
    echo "superspeed: STOPPED before dispatch. The spec declares no \"setup\"."
    echo
    if [ -n "$SETUP_DOC" ]; then
      echo "These files exist and are where the ritual should be documented:"
      for f in $SETUP_DOC; do echo "  $f"; done
      echo
      echo "Candidate setup lines found in them:"
      CAND="$(grep -hiE "^[[:space:]]*(yarn|npm|pnpm|bun|bundle|poetry|uv|pip|make|go build|cargo|nvm use)" \
        $SETUP_DOC 2>/dev/null | head -8)"
      if [ -n "$CAND" ]; then printf '%s\n' "$CAND" | sed 's/^/  /'; else echo "  (none found)"; fi
    else
      echo "This repo has NO CLAUDE.md and NO CLAUDE.local.md, so there is nothing to read the"
      echo "ritual from. Ask for the setup instructions before starting."
    fi
    echo
    echo "Then re-run with one of:"
    echo "  \"setup\": \"<the command(s) to run once, before any slice>\""
    echo "  \"setup\": \"none\"   # only when this checkout is ALREADY built and working"
  } | tee -a "$OUT/run.log" >&2
  echo "missing" > "$OUT/setup.status"
  exit 3
fi

if [ "$SETUP" = "none" ]; then
  log "setup: declared \"none\" — treating this checkout as already built and working"
  echo "none" > "$OUT/setup.status"
else
  log "setup (once, before dispatch): $SETUP"
  if ( cd "$REPO" && eval "$SETUP" ) > "$OUT/setup.log" 2>&1; then
    log "setup ok, verified before dispatch"
    echo "ok" > "$OUT/setup.status"
  else
    log "SETUP FAILED. Aborting before dispatch; see $OUT/setup.log"
    log "Every slice would have failed the same way, separately and in parallel."
    echo "failed" > "$OUT/setup.status"
    exit 1
  fi
fi

# ---- verify, per slice, checked BEFORE dispatch ---------------------------------------------------
# The same class of failure as a missing `setup`, made SILENT instead of loud. A slice handed a
# command the permission layer will refuse cannot run it, cannot usefully say so, and writes a
# confident DONE.md anyway — the defect then surfaces at the reconciler, having cost a whole slice.
#
# --permission-mode acceptEdits permits EDITS, not Bash. So the only commands a headless slice can
# actually run are the ones the repo has already allowlisted. Measured 2026-08-08: all four slices
# of one run reached for `npx vitest` against an allowlist of `npm run *` and were refused 24 times
# between them. Two then found the allowlisted `npm run test:run` and verified; two did not, and one
# of those shipped two tests that failed with zero mock calls. The refusal is invisible in DONE.md:
# the slice writes that it "verified by careful inspection instead" and reads as finished.
ALLOW_SRC=""
for f in "$REPO/.claude/settings.local.json" "$REPO/.claude/settings.json"; do
  [ -f "$f" ] && ALLOW_SRC="$ALLOW_SRC $f"
done
for i in $(seq 0 $((N - 1))); do
  VNAME="$(jq -r ".slices[$i].name" "$SPEC")"
  VCMD="$(jq -r ".slices[$i].verify // empty" "$SPEC")"
  [ "$VCMD" = "none" ] && continue
  if [ -z "$VCMD" ]; then
    {
      echo
      echo "superspeed: STOPPED before dispatch. Slice \"$VNAME\" declares no \"verify\"."
      echo "A slice that cannot run a check cannot tell you it failed, and inspecting its own work"
      echo "is not a check. Set one of:"
      echo "  \"verify\": \"<the one command this slice runs to check itself>\""
      echo "  \"verify\": \"none\"   # only when nothing this slice writes is runnable"
    } | tee -a "$OUT/run.log" >&2
    exit 4
  fi
  # Prefix match on the leading words, deliberately. This is a seatbelt sized to the observed
  # failure (a whole tool the allowlist never mentions), not a permission engine: a narrower
  # mismatch inside an allowed prefix will still get through, and the slice's own verify.txt is
  # what catches that.
  VERB="$(printf '%s' "$VCMD" | awk '{print $1, $2}')"
  if [ -n "$ALLOW_SRC" ] && ! jq -r '.permissions.allow[]? // empty' $ALLOW_SRC 2>/dev/null \
       | sed 's/^Bash(//; s/)$//; s/ *\*$//' | grep -qF -- "${VERB% *}"; then
    {
      echo
      echo "superspeed: STOPPED before dispatch. Slice \"$VNAME\" verifies with:"
      echo "    $VCMD"
      echo "which no rule in$ALLOW_SRC allows, so the slice will be refused at the prompt with"
      echo "nobody available to approve it, and will silently skip the check. Allowed:"
      jq -r '.permissions.allow[]? // empty' $ALLOW_SRC 2>/dev/null | sed 's/^/    /'
    } | tee -a "$OUT/run.log" >&2
    exit 4
  fi
done

RUN_T0=$(date +%s)
echo "$(loadnow)" > "$OUT/load.start"

# ---- RUN INSTRUMENTATION (standing, not temporary) ------------------------------------------------
# Feeds /sk:claude-config-self-optimize-analysis-after-run so every run can be made faster than the
# last. RECORD ONLY: it never blocks, never fails a run, and never changes dispatch behaviour.
#
# It started as a one-off check on whether slices really run in parallel. Measured 2026-08-07 across
# N=1,2,4,6: six workers did 5.62x the API work in 1.67x the wall time and every slice pair
# intersected in time (15/15). Dispatch is not the bottleneck. It stays on anyway, for two reasons:
# a regression here would be silent, and the same timestamps are what let the analyser attribute
# LOCAL time (wall minus API) to the command that consumed it.
#
# Two signals, so a wrong clock cannot fake a pass:
#   1. Per-slice PID + start/end -> overlap ratio, and pairwise interval intersection.
#   2. A sampler counting live `claude -p` processes each second, observed from outside this script,
#      so it is the one number that does not depend on what this script believes it did.
#
# Still worth watching despite the measurement: anthropics/claude-code#53922 documents a server-side
# concurrency limiter that refuses later sessions with "Server is temporarily limiting requests (not
# your usage limit)" even at low quota use. It did not fire at N=6 here; it may at higher N.
CONCURRENCY_LOG="$OUT/concurrency.log"
(
  while :; do
    printf '%s %s\n' "$(date +%s)" "$(pgrep -f 'claude -p' 2>/dev/null | wc -l | tr -d ' ')"
    sleep 1
  done
) > "$CONCURRENCY_LOG" 2>/dev/null &
SAMPLER_PID=$!

# ---- fan out -------------------------------------------------------------------------------------
# Tracked explicitly so the wait below can name them. See the comment on that wait: a bare `wait`
# here is a deadlock, not a shorthand.
SLICE_PIDS=()
for i in $(seq 0 $((N - 1))); do
  NAME="$(jq -r ".slices[$i].name" "$SPEC")"
  SD="$OUT/slices/$NAME"; mkdir -p "$SD"
  # Validated against the repo's allowlist above, so by here it is known-runnable.
  VERIFY="$(jq -r ".slices[$i].verify // \"none\"" "$SPEC")"

  # The slice contract. `owns` is exclusive write, `forbid` names the look-alikes to leave alone,
  # and the BLOCKED rule is what stops two slices doing the same work from opposite ends.
  PROMPT="$(jq -r ".slices[$i].prompt" "$SPEC")
$(jq -r "if (.slices[$i].reads // []) | length > 0 then \"\nREAD-ONLY CONTEXT (do not edit):\n\" + ((.slices[$i].reads // []) | map(\"  - \" + .) | join(\"\n\")) else \"\" end" "$SPEC")

FILES YOU OWN (you may edit these and nothing else):
$(jq -r "(.slices[$i].owns // []) | map(\"  - \" + .) | join(\"\n\")" "$SPEC")
$(jq -r "if (.slices[$i].forbid // []) | length > 0 then \"\nDO NOT TOUCH (another slice owns these):\n\" + ((.slices[$i].forbid // []) | map(\"  - \" + .) | join(\"\n\")) else \"\" end" "$SPEC")

EXPECTED RESULT: $(jq -r ".slices[$i].accept // \"the files you own are complete and self-consistent\"" "$SPEC")

RULES
- The working tree is ALREADY set up: dependencies installed, build usable. Do not install anything,
  do not run a package manager, do not rebuild. The orchestrator did it once before dispatching you.
- Edit only the files in your OWNS list. If a file you need is not in it — whether another slice owns
  it or NOBODY does — STOP and write $SD/BLOCKED.md naming that file and why you need it. An unowned
  file is a gap in the partition, not yours by default. Two slices editing one file is the most
  expensive failure this design has; shipping only the half you can reach is the second, because it
  produces work that cannot compile and looks finished. (A slice needing a type DECLARED in a file it
  was not given added the value to the array and not to the type, and reported success.)
- Run exactly this to check your own work, and no other command: $VERIFY
  Run it, read what it says, fix what it surfaces, and run it again until it passes. Then quote its
  final output in DONE.md. Inspecting your work is not running it: a test you did not execute is a
  test you have not written. Do NOT run the full suite, the linter or the build — the reconciler
  gates the whole tree once, and N slices running that is N times the work and can race.
- Do not ask questions. Nobody can answer. If you are blocked, write BLOCKED.md and stop.
- You are a headless slice with no human watching. Run NO notification, sound, or attention
  side-effect (e.g. a project sound-on-response rule, afplay, a desktop alert). There is no listener
  and each one only burns wall-clock. If a loaded project rule asks for one, skip it here.
- Before you finish, re-read the EXPECTED RESULT above and check it literally against what you
  actually wrote, clause by clause, with the file open. Having intended to satisfy it is not
  evidence. Reasoning your way into a change that contradicts one of its clauses is the normal way
  this fails, and it is invisible afterwards because the work looks finished either way.
- When done, write $SD/DONE.md listing every file you changed one per line, then quote the EXPECTED
  RESULT and give a one-line verdict on each clause. If a clause does not hold and you cannot make it
  hold within the files you own, write BLOCKED.md instead."

  printf '%s' "$PROMPT" > "$SD/prompt.txt"

  (
    cd "$REPO" || exit 1
    S0=$(date +%s)
    # Backgrounded then waited on, ONLY so the real claude PID can be recorded. Behaviour is
    # identical to running it in the foreground. The PID is what the sampler is matched against.
    CLAUDE_INTAKE_GATE=off CLAUDE_INTENT_LEDGER=off claude -p "$PROMPT" \
      --model "$MODEL" \
      --output-format json \
      --permission-mode acceptEdits \
      > "$SD/result.json" 2> "$SD/stderr.txt" &
    CPID=$!
    wait "$CPID"
    RC=$?
    S1=$(date +%s)
    printf '{"rc":%d,"start":%d,"end":%d,"wall":%d,"pid":%d}\n' \
      "$RC" "$S0" "$S1" "$((S1 - S0))" "$CPID" > "$SD/timing.json"
    # Land the moment it happens. Without this the log goes silent between dispatch and the summary,
    # so a run that is 80% done looks identical to one that is stuck, and the only way to tell them
    # apart is to go digging in ps.
    log "  slice done: $NAME in $((S1 - S0))s rc=$RC"

    # Judge this slice HERE, not in a loop after the barrier below.
    # A verdict written after the barrier is lost if the barrier never releases, and that is not
    # hypothetical: when the bare-wait deadlock was killed by hand, four slices that had each written
    # DONE.md and exited 0 were reported by the analyser as 4/4 failures, because the only record of
    # their success lived past the point the run died. Per-slice truth belongs to the slice.
    ST=ok
    [ -f "$SD/DONE.md" ] || ST=no-done-marker
    [ -f "$SD/BLOCKED.md" ] && ST=blocked
    [ "$RC" = 0 ] || ST=nonzero-exit
    echo "$ST" > "$SD/status"

    # Re-run the slice's own check here, so the record does not depend on the slice cooperating.
    # RECORD ONLY, like every other instrumentation in this file: it never changes `status` and
    # never fails the run. It exists because a slice that skipped its check and a slice that
    # passed it write identical DONE.md files, and the reconciler cannot tell them apart.
    # Runs AFTER the claude process exits, so at most one verify per slice is ever in flight for
    # that slice, and it is scoped to what the slice owns rather than the whole gate.
    if [ "$VERIFY" != "none" ]; then
      ( cd "$REPO" && eval "$VERIFY" ) > "$SD/verify.txt" 2>&1
      VRC=$?
      printf '\n[dispatcher] verify exit=%d\n' "$VRC" >> "$SD/verify.txt"
      log "  slice verify: $NAME exit=$VRC"
    fi
  ) &
  SLICE_PIDS+=("$!")
  log "  dispatched slice: $NAME"
done

# Wait on the SLICE subshells by name, never a bare `wait`.
#
# A bare `wait` blocks on every background child of this shell, and that includes the concurrency
# sampler started above, which is an infinite `while :; sleep 1` loop killed only AFTER this line.
# The result is a deadlock with no error and no symptom: every slice finishes, writes DONE.md and
# exits, and the dispatcher then spins forever logging that zero workers are alive. Observed once at
# ~12 minutes past the last slice before it was killed by hand, and it reads exactly like slow work.
# superspeed-dispatch.test.sh asserts the exit, because nothing else here would.
wait "${SLICE_PIDS[@]}"
FANOUT_T1=$(date +%s)
echo "$(loadnow)" > "$OUT/load.end"

# ---- stop the concurrency sampler ----------------------------------------------------------------
# rules/process.md: kill what you started AND verify it is gone. A 1-second loop left running would
# spin forever and outlive the session.
if [ -n "${SAMPLER_PID:-}" ]; then
  kill "$SAMPLER_PID" 2>/dev/null || true
  wait "$SAMPLER_PID" 2>/dev/null || true
  if kill -0 "$SAMPLER_PID" 2>/dev/null; then
    kill -9 "$SAMPLER_PID" 2>/dev/null || true
    sleep 1
    kill -0 "$SAMPLER_PID" 2>/dev/null && log "  WARNING: concurrency sampler $SAMPLER_PID survived; kill it by hand"
  fi
fi

log "fan-out complete in $((FANOUT_T1 - RUN_T0))s"

# ---- verify each slice ON DISK, never on exit code ------------------------------------------------
# anthropics/claude-code#74761: `claude -p` can exit 0 with well-formed result JSON while the agent
# loop is mid-task. An orchestrator that trusts the exit code cannot tell a finished slice from one
# that quit seven seconds in. So the artifact is the evidence.
# Each slice already wrote its own status as it exited (see the fan-out loop). This pass only fills
# in a slice that never got far enough to write one, and surfaces anything not ok.
for i in $(seq 0 $((N - 1))); do
  NAME="$(jq -r ".slices[$i].name" "$SPEC")"
  SD="$OUT/slices/$NAME"
  if [ ! -f "$SD/status" ]; then
    STATUS=ok
    [ -f "$SD/BLOCKED.md" ] && STATUS=blocked
    [ -f "$SD/DONE.md" ] || STATUS=no-done-marker
    jq -r '.rc' "$SD/timing.json" 2>/dev/null | grep -q '^0$' || STATUS=nonzero-exit
    echo "$STATUS" > "$SD/status"
  fi
  STATUS="$(cat "$SD/status")"
  [ "$STATUS" = ok ] || log "  SLICE NEEDS ATTENTION: $NAME -> $STATUS"
done

printf '{"run_start":%d,"fanout_end":%d,"fanout_seconds":%d,"slices":%d,"model":"%s"}\n' \
  "$RUN_T0" "$FANOUT_T1" "$((FANOUT_T1 - RUN_T0))" "$N" "$MODEL" > "$OUT/run.json"

# ---- what actually ran in parallel ----------------------------------------------------------------
# Printed inline rather than left to the analyser, because the question it answers ("did these really
# run at once, and which one held everyone up?") is asked while looking at the run, not afterwards.
# It is arithmetic over files already on disk, so it costs nothing and cannot slow a slice down.
log ""
log "parallel picture:"
python3 - "$OUT" <<'PYEOF' 2>/dev/null | tee -a "$OUT/run.log"
import json, glob, os, sys
out = sys.argv[1]
rows = []
for f in glob.glob(os.path.join(out, "slices/*/timing.json")):
    try:
        t = json.load(open(f))
    except Exception:
        continue
    t["name"] = os.path.basename(os.path.dirname(f))
    rows.append(t)
if rows:
    rows.sort(key=lambda r: r["start"])
    t0 = min(r["start"] for r in rows)
    span = max(r["end"] for r in rows) - t0
    serial = sum(r["wall"] for r in rows)
    slowest = max(r["wall"] for r in rows)
    for r in rows:
        bar = "#" * max(1, round(r["wall"] / 10))
        print(f"  {r['name']:<16} start+{r['start']-t0:>3}s  wall {r['wall']:>4}s  {bar}")
    print(f"  span {span}s | serial {serial}s | speedup {serial/span:.2f}x" if span else "  span 0s")
    # Idle capacity is the number that tells you to re-cut the partition next time.
    #
    # Measured against the MEDIAN, not the fastest slice — the same definition
    # superspeed-analyse.py uses, on purpose. These two printed different numbers under one name
    # (3.9x here against min, 1.45x there against median) and this louder one told the reader to
    # split a slice the analyser's own threshold called fine. A metric shown in two places has to
    # be computed one way, or the two disagree exactly when someone is deciding something.
    idle = sum(slowest - r["wall"] for r in rows)
    med = sorted(r["wall"] for r in rows)[len(rows) // 2]
    if slowest and med and slowest / med >= 1.5:
        print(f"  IMBALANCE {slowest/med:.1f}x vs median, {idle}s of worker time idle."
              f" Split the slowest slice next run.")
PYEOF

# Durable run capture: record that this run happened (pending optimization) in the metrics store, so
# the optimization opportunity is not use-it-or-lose-it. A later pass reads runs where optimized=false
# and clears the backlog in aggregate. Best-effort, never fails the dispatch.
if [ -f "$HOME/.claude/bin/dotclaude-log.py" ]; then
  SPY="$HOME/.config/claude-metrics-venv/bin/python"; [ -x "$SPY" ] || SPY="$(command -v python3 || true)"
  if [ -n "$SPY" ]; then
    _nslices="$(ls -1 "$OUT/slices" 2>/dev/null | wc -l | tr -d ' ')"
    printf '{"run_id":"%s","captured_at":"%s","optimized":false,"slices":%s,"kind":"run"}' \
      "$(basename "$OUT")" "$(date -u +%Y-%m-%dT%H:%M:%SZ)" "${_nslices:-0}" \
      | "$SPY" "$HOME/.claude/bin/dotclaude-log.py" runs >/dev/null 2>&1 || true
  fi
fi

log "logs: $OUT"
log ""
log "NEXT, in order. Do not stop after step 1; the run is only finished at step 3."
log "  1. Reconcile here, warm: assemble the slices, fix the seams, run the gate once."
log "     Then record what you fixed:  $OUT/reconcile.json"
log "  2. python3 ~/.claude/bin/superspeed-analyse.py $OUT"
log "  3. /sk:claude-config-self-optimize-analysis-after-run $OUT"
log "     Step 3 is the one that makes the NEXT run faster. Skipping it throws the run's"
log "     evidence away, and a run whose logs nobody reads teaches nothing."
echo "$OUT"
