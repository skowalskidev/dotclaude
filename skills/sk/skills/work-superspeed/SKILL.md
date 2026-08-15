---
name: work-superspeed
description: Run a task across real parallel Claude sessions instead of in-session subagents, then reconcile in one warm session and log the run so it can be made faster next time. Cuts the work into slices with exclusive file ownership so no two slices do the same job, dispatches each as its own `claude -p` process, verifies every slice on disk, assembles and gates the result, and writes a waste analysis. Use for "run this in parallel", "fan this out", "split this across sessions", "superspeed", or any task that genuinely divides into 3-5 independent pieces. Not for work that does not divide.
argument-hint: "[the task to parallelise]"
---

# Superspeed

Fan a task out across real parallel sessions, reconcile it warm, and leave a log that says how to do
it better next time.

## Read this before using it

The advantage is real but narrow, and it was measured rather than assumed. On 2026-08-06, Claude Code
2.1.220, Apple M2 8-core, Max plan, four configurations and fourteen reps:

| | one session, 4 subagents | one session, 4 teammates | **4 parallel `claude -p`** |
|---|---:|---:|---:|
| trivial task, 1 round | 52s | 59s | **22s** |
| real task, 1 round | 64s | 59s | **31s** |
| trivial, 3 rounds | 111s | 121s | **75s** |

Separate sessions won every configuration and every individual rep, at identical correctness (24/24).

**The mechanism is a fixed ~33s, not a multiplier.** The gap was 30s at one round and 36s at three, so
it is a one-time orchestration toll, not something that compounds. That makes it 2.4x on a 22-second
job and under 1% on an hour-long one.

**So the honest rule: use this when a task splits into pieces that can run at once. Do not use it
hoping to make one long serial task faster.** If the work does not divide, nothing here helps, and
Anthropic's own 16-agent C-compiler run is the cautionary case: on an indivisible task every agent hit
the same bug and overwrote the others.

**Why separate sessions and not subagents.** Every in-session primitive is capped: subagents at 20
concurrent (10 in these settings), dynamic workflows at 16 and lower on machines with few cores.
Separately launched sessions have no documented cap. The limit you feel in one session is real.

## Step 0 — decide whether to fan out at all

One question: **can this split into slices that touch disjoint files?**

If no, stop and work in one session. If the slices would each take under about 30 seconds, also stop:
the toll you avoid is 33s, so fanning out costs more than it saves. The analyser flags this after the
fact as `fanout_not_worth_it`, but it is cheaper to notice now.

## Step 1 — cut the task so no two slices do the same work

This is the whole game, and it is where the time is actually won or lost. In one measured run the
slowest slice took 451s of a 466s round while three workers sat idle.

1. **Freeze the shared contract first.** Anything several slices depend on (shared types, an interface,
   a schema) gets written and committed in the base commit BEFORE dispatch. A slice that has to invent
   a shared type will conflict with the slice that invented it differently.
2. **Give every slice exclusive ownership.** Each slice declares `owns` (may edit), `reads` (read-only
   context), and `forbid` (the look-alikes another slice owns). Lay the `owns` lists side by side and
   check them against each other; individually-correct specs still overlap, and the overlap is
   invisible read one at a time. **Grep the finished prompt for paths, and put every one in that
   slice's `owns`.** `owns` gets written from the deliverable while the prompt quietly instructs side
   artifacts — a summary, a log, a scratch note — so the two drift apart. TEST: zero paths in the
   prompt that are absent from `owns`. (The fix for three slices each writing a per-slice summary no
   partition declared; distinct filenames were the only thing that stopped it racing.)
3. **Name what each file ASSERTS, not only what it writes.** `owns` and `forbid` model writes, so they
   catch two slices editing one file and miss the coupling that actually bites: a file that encodes
   another slice's output. Tests, snapshots, fixtures, golden files and docs that quote code all do
   this. Every slice is individually correct and the seam still breaks, because nothing in the
   partition says the two are joined. For each file a slice owns, ask whose output it asserts, then
   either state that slice's contract in the prompt or hand the file to the reconciler from the start.
   **Ask it of UNOWNED files too**, which is the half that is easy to miss: a file nobody is editing
   still breaks when the thing it asserts changes underneath it, and because no slice owns it, no
   slice is watching it. Sweep the test and fixture files around every file being changed, not only
   the ones already in an `owns` list.
4. **Give a slice the file a symbol is DECLARED in, never only the file that reads it.** A slice
   asked to widen a type, enum, interface or constant needs the declaration. TEST: grep
   `export type X` / `export const X` before writing the `owns` list, and put THAT file in it.
   (The fix for a slice that added a stage to the array and could not add it to the type.)
5. **Split any slice owning more than 4 files, or creating any file from scratch.** Measured across
   three runs: the critical path was the slice owning the MOST FILES every time — 705s for 7 files
   including one new, against 231-360s for slices owning 2-4 existing ones. A new file has no
   surrounding structure to follow, so it costs more than an edit of the same size.
6. **Summarise a frozen shared contract IN each prompt and leave it OUT of `reads`.** Freezing it
   before dispatch stops the slices disagreeing; listing it in `reads` still makes all N pay to read
   it. Do both halves.
7. **Size by expected work, not by file count.** One slice touching a large module is not equivalent to
   one touching three small files. Imbalance is the dominant waste in every run measured so far.
   **Use FILE COUNT as the proxy (line count was the old one and predicted the critical path less well than file count did across three runs).** Across
   three measured runs the critical path was the slice owning the largest TEST file every time, at
   roughly 0.2 seconds per line of that file (2,003 lines took 437s then 476s; 1,083 lines took 200s).
   So a test file over about 1,200 lines is a slice on its own, or is split by `describe` block. This
   is the one imbalance you can see before dispatching rather than in the analysis afterwards.

   **Line count only works when the files already exist.** A slice that CREATES files has no line
   count to read, so the proxy silently returns zero and every greenfield slice looks equally cheap.
   Count deliverables instead, weighting a tested pure module and a UI surface as one unit each: a
   slice building a module, its test file, a server page, a client component and an API route is five,
   and it is two slices. Measured 2026-08-08: a five-deliverable slice took 425s against 182s for a
   two-deliverable one in the same run, 2.3x imbalance and 243s of a worker sitting idle. The split
   that was available and not taken was the obvious one, pure logic plus tests in one slice and the
   surfaces that consume it in another.
8. **Give every slice an `accept` line AND a runnable `verify` command.** A slice told only what to
   do cannot tell you it failed, and a slice told only what to *check* still cannot, unless it can
   execute the check. Headless slices run under `--permission-mode acceptEdits`, which permits edits
   and NOT Bash, so the only commands they can run are ones the repo has already allowlisted: pick
   `verify` from that list and scope it to the files the slice owns. The dispatcher refuses to
   dispatch a `verify` no rule allows, for the same reason it refuses a missing `setup`.
   **`verify: "none"` is only for a slice that writes nothing runnable, never a shortcut.** A
   migration or refactor slice gets a scoped `verify` even when the whole-tree gate runs centrally in
   reconcile: a per-slice `tsc --noEmit` (or a targeted test) on the owned files catches the slice's
   own errors — a stale test mock, a syntax slip, a wrong assertion — where they are cheap, not in
   reconcile where they are not. TEST: every slice that edits code carries a `verify` that compiles
   or tests what it owns; `none` appears only on a docs-or-data-only slice. (The fix for a coupled
   refactor dispatched with `verify: "none"` throughout, whose reconcile then paid for four
   slice-fault fixes a per-slice typecheck would have surfaced first.)
   **A banned pattern goes in `verify` as a grep that EXITS ZERO when the pattern is ABSENT.** A
   structural check cannot see a lexical constraint — a banned word, a required token format, a
   forbidden import, a naming convention — so the slice exits 0, writes a confident DONE, and the
   reconciler pays. Write it INVERTED — `! grep -qE 'PATTERN' <files>` — because a bare `grep PATTERN`
   exits 1 on no matches and the dispatcher records any non-zero `verify` exit as a slice FAILURE, so
   a bare `tsc --noEmit | grep 'error'` flags the slice as failed exactly when it is CLEAN. The same
   trap catches any `verify` whose success is "no output": end it so the clean case exits 0. TEST:
   every "do not use X" in the prompt has a matching inverted grep in `verify`, and that `verify` run
   on the fixed tree exits 0.
   **Never declare auto-loaded files in `reads`.** A project's `CLAUDE.md` and its `.claude/rules/*.md`
   already reach every slice through the nested-import chain. Listing them buys nothing, and it makes
   the duplicated-reads metric propose freezing a file that was never the cost.
9. **Write each prompt as a rule, not as the example that prompted it.** `rules/process.md` § "Fix the
   CLASS of failure, not the one instance I reported" governs, and it costs more here than elsewhere:
   a prompt is authored once and copied to N slices, so an instruction fitted to one example is
   replicated N times and every slice inherits the same blind spot at once.

Write it as a spec file:

```json
{
  "task": "one line describing the whole job",
  "repo": "/abs/path/to/repo",
  "gate": "yarn lint && yarn test",
  "setup": "yarn install",
  "model": "claude-sonnet-4-6",
  "slices": [
    { "name": "api",
      "owns":   ["apps/api/src/routes/foo.ts"],
      "reads":  ["packages/types/src/foo.ts"],
      "forbid": ["apps/api/src/routes/bar.ts"],
      "accept": "foo.ts exports a handler named createFoo that validates input",
      "verify": "yarn test apps/api/src/routes/__tests__/foo.test.ts",
      "prompt": "what this slice must do, in full; it inherits none of this conversation" }
  ]
}
```

## Step 2 — dispatch

```bash
~/.claude/bin/superspeed-dispatch.sh slices.json .superspeed/run-1
```

It launches one `claude -p` per slice in parallel, each with `--model claude-sonnet-4-6`,
`--permission-mode acceptEdits`, `--output-format json`, and `CLAUDE_INTAKE_GATE=off`.

**The orchestrator sets the tree up once, before any slice starts, and `setup` is mandatory.**

1. Read the repo's `CLAUDE.md` and `CLAUDE.local.md` for its ritual and put it in the spec's `setup`.
2. The dispatcher runs it once, in the shared checkout, and **verifies it before dispatching**.
3. Only then does it fan out, telling every slice the tree is already built so none of them installs
   anything.

**If `setup` is missing, the dispatcher STOPS and asks.** It does not guess. It prints which of the two
files exist, greps the candidate commands out of them, and exits 3 without spending on a single slice.
If neither file exists it says so and asks for the instructions outright.

A setup failure aborts the run for the same reason: every slice would have failed the same way,
separately and in parallel, producing N errors that look nothing like their cause.

The one escape is explicit: `"setup": "none"`, meaning this checkout is already built and working. That
is common and fine, but it has to be stated rather than assumed. You need a working tree for the
reconcile gate anyway, so setting it up here costs nothing extra.

Five rules it enforces, each with a reason:

- **Same directory, disjoint files. Not worktrees**, unless slices genuinely collide. The prompt cache
  is scoped to the working directory, so sessions in one directory share a prefix and sessions in
  separate worktrees never do. That is where the measured 2x cost came from, and it is avoidable.
- **Never `--bare`.** It looks like the obvious startup fix. It drops off the Max subscription onto
  per-token API billing and skips CLAUDE.md, so a slice would lose the project's rules.
- **Slices never run the gate, but every slice DOES run its own `verify`.** The reconciler runs the
  gate once; N slices running the whole suite is N times the work and can race. A `verify` is scoped
  to what one slice owns, and it is the only thing standing between a wrong slice and the reconciler.
  The dispatcher re-runs it after the slice exits and records `verify.txt`, so the record does not
  depend on the slice having bothered.
- **Slices never ask questions.** Nobody can answer, and a slice that stops to ask dies silently. A
  blocked slice writes `BLOCKED.md` and stops.
- **Slices never touch the intent ledger.** They run in the orchestrator's directory, so
  `.context/intent-ledger.md` is one shared file: N appends race, and a dispatched machine-written
  prompt landing in a log whose whole value is that it is Simon's words verbatim is a forgery the
  reconciliation would later judge against. The dispatcher sets `CLAUDE_INTENT_LEDGER=off` beside
  `CLAUDE_INTAKE_GATE=off`. The slice prompt stays the only channel, and a slice handed the whole ask
  instead of its slice is the indivisible-task failure at the top of this file.

## Step 3 — reconcile, in this session, warm

Do not spawn a fresh session for this. The orchestrator has the partition, the specs and the reasoning
already in context.

1. **Read `slices/*/verify.txt` first.** A slice whose own check failed is where your time is going,
   and knowing that costs one file rather than a whole diff.
2. **Check every slice on disk, never on its exit code.** `anthropics/claude-code#74761`: `claude -p`
   can exit 0 with well-formed result JSON while the agent is mid-task. The `DONE.md` artifact is the
   evidence; the dispatcher already writes a `status` per slice.
3. Read any `BLOCKED.md` and finish that work yourself. A blocked slice is the design working, not
   failing: it stopped rather than editing a file another slice owned.
4. **Check the instructions the slices were least likely to obey: the ones that contradict the file
   they were editing.** A slice matches the surrounding file's existing convention over an explicit
   instruction, however emphatic that instruction was, because the file is the stronger signal. So an
   instruction that runs against local convention needs a mechanical check here rather than more words
   in the prompt — grep the changed files for the thing you banned. Applies to any convention a file
   carries: naming, import order, comment density, error handling, prose style. The tell is that the
   rule was stated in the prompt and the diff still breaks it.
5. Assemble, fix the seams, then **run the gate once** over the whole tree.
6. **Give every fixed file a `cause`: `slice` (it got it wrong), `late_scope` (the ask changed
   after dispatch), or `reconciler` (you broke it). Only `slice` means the partition needs
   changing.** Recording all three as one number gets two of them the wrong prescription — measured
   across two consecutive runs whose identical rework counts came from opposite causes.
7. Record what you had to fix, so the next partition is better:

```bash
cat > .superspeed/run-1/reconcile.json <<'EOF'
{ "files_fixed": [
    { "file": "apps/api/src/routes/foo.ts", "cause": "slice" },
    { "file": "apps/web/src/Panel.tsx",     "cause": "late_scope" },
    { "file": "apps/api/src/routes/bar.ts", "cause": "reconciler" }
  ], "conflicts": 0, "gate": "pass", "seconds": 120 }
EOF
```

## Step 4 — analyse the run, always

```bash
python3 ~/.claude/bin/superspeed-analyse.py .superspeed/run-1
```

It reports idle capacity, imbalance ratio, cache read/write ratio, achieved concurrency, ownership
leaks, duplicated reads, reconcile rework, failed slices, and whether fanning out was worth it at all.
Every finding carries the specific change to make next time.

## Step 5 — `/sk:claude-config-self-optimize-analysis-after-run <run-dir>`, automatically after every run

**Run this automatically after every run — don't wait to offer it.** It fires on run completion (an
event, not a cron, so it stays inside `rules/self-healing-config.md`'s no-periodic-scan line). Step 4
is mechanical and finds what the numbers show; this reads the prompts, the `BLOCKED.md` files and the
thrashing slices to find why, and proposes the durable fixes, including changes to this skill and to
what the logs capture. Both `superspeed-dispatch.sh` and `superspeed-analyse.py` print it as their
last line so it survives being forgotten.

**But bound it — auto-analyse, never auto-optimize.** The run analyses itself; it does not CHANGE the
config on its own. An actual config or skill edit still goes through the self-healing propose-and-confirm
gate, and most runs should propose NOTHING — silence is the default, and a well-partitioned run has
nothing to say. Weigh every candidate change against its own cost: the fan-out toll is a fixed ~33s, so
splitting a fast slice finer, freezing one more contract, or adding a log field for a one-off spends
more than it saves and DEGRADES the next run. Only a finding that RECURS across runs (check the prior
`analysis.json`) is durable enough to become a rule; a single run's symptom is a re-partition note, not
a config change.

## Teardown

Slices leave nothing running, but the logs are yours to keep. Put `.superspeed/` in the project's
ignore layer (`.git/info/exclude`, not the committed `.gitignore`, since it is personal). Keep the
analyses: comparing them across runs is what makes the next partition better.

## Self-optimisation — standing, every run

**Nothing here changes how a run behaves.** It records, never blocks. Every run feeds
`/sk:claude-config-self-optimize-analysis-after-run` so the next partition is better than this one.

### What was measured, so this is not re-litigated

**Dispatch is not the bottleneck.** 2026-08-07, N=1/2/4/6 on the Max plan:

| N | Fan-out wall | API work done | Slice pairs overlapping |
|--:|--:|--:|:--|
| 1 | 6.7s | 1.00x | - |
| 2 | 7.3s | 1.63x | 1/1 |
| 4 | 11.7s | 3.50x | 6/6 |
| 6 | 11.1s | **5.62x** | **15/15** |

Six workers did 5.62x the API work in 1.67x the wall. Every pair overlapped in time. `claude -p`
workers are real, separate, concurrent processes and the API parallelises them.

Two things that follow, both worth not re-testing:

- **Containers and VMs cannot help throughput.** Anthropic's limits key on the ORGANIZATION, not the
  machine or IP, so requests from a container, a VM or another laptop share one pool. A container's
  only real benefit here is filesystem isolation, which is a collision fix, not a speed fix.
- **Startup is ~4-7s per slice.** Real, but noise against an hour-long ticket. It was measured, and
  over-weighted before that measurement existed.

### So the remaining cost is LOCAL work

`local = wall - api` is time a worker is alive and burning zero tokens. That is where a slow run now
comes from, and the analyser attributes it to the command responsible by reading each slice's
transcript (`~/.claude/projects/<project>/<session_id>.jsonl`, found via the `session_id` in
`result.json`).

Per slice it reports:

| Signal | Catches |
|---|---|
| Slowest Bash commands with duration and % of slice wall | A slice running the WHOLE test suite when it owns three files |
| Tool time split (Bash / Read / Edit) | A slice that reads far more than it writes, meaning the prompt lacked context |
| Files touched vs declared `owns`/`reads` | A partition bug, before it becomes two slices editing one file |
| Turn count | Thrash |

Any single command taking 30%+ of a slice's wall raises a high finding naming that command. That is
the check for the failure this section exists to catch: **workers running platform-wide commands that
are irrelevant to their slice.** Scope it in the slice prompt, or give the slice its own narrower
command in `accept`.

### Also standing

Overlap ratio, pairwise intersection, and a sampler counting live `claude -p` processes each second.
Kept even though the answer came back healthy, because a regression would otherwise be silent, and
the same timestamps are what make the local-time attribution possible.

## Honest limits

- Measured at 22-120s per round. The 2.0-2.4x does not transfer to hour-long rounds, where the 33s
  toll is under 1%.
- One machine, one account, one repo, one task family.
- The reconcile stage was not in the benchmark. Its cost is real and is not in those numbers.
- A warm orchestrator judging work it dispatched has a documented bias risk. The mitigation used here
  is that the gate is objective: it runs the tests rather than asking the orchestrator's opinion.
