# Parallelization & delegation

How to fan work out — across agents, tasks, and pipeline stages — without clashing or losing quality.

## Separate sessions beat in-session subagents, by a fixed ~33s (MEASURED 2026-08-06)

This section is measurement, not inference, and it supersedes the older subagent-first framing below
wherever the two disagree. Claude Code 2.1.220, Apple M2 8-core, Max plan, MCP disabled, arms
interleaved, correctness checked against known ground truth.

| | 1 session, 4 subagents | 1 session, 4 teammates | **4 parallel `claude -p`** |
|---|---:|---:|---:|
| trivial task, 1 round (5 reps) | 55s | 55s | **25s** |
| trivial task, 1 round (3 reps) | 52s | 59s | **22s** |
| real task, 1 round (3 reps) | 64s | 59s | **31s** |
| trivial, 3 rounds (3 reps) | 111s | 121s | **75s** |

**Separate sessions won all four configurations and all fourteen individual reps**, at identical
correctness (24/24 every arm). **Agent teams are refuted**: slower than plain subagents in every
config, same cost, nothing gained from teammates persisting across rounds.

**The gap is a fixed ~33s, not a multiplier.** 30s at one round, 36s at three (ratio 1.20x, where 3.0x
would mean per-round). It is a one-time orchestration toll. So it is 2.4x on a 22-second job and under
1% on an hour-long one. **Reach for parallel sessions when work genuinely splits, not to speed up one
long serial task.**

**Why it is faster at all:** every in-session primitive is capped. Subagents at 20 concurrent (10 in
`settings.json` here), dynamic workflows at 16 and lower on machines with few cores. Separately
launched sessions have no documented cap.

**The four rules that came out of it**, each with its reason:

1. **Same directory, disjoint files. Not worktrees**, unless slices genuinely collide. The prompt cache
   is scoped to the working DIRECTORY, so sessions in one directory share a prefix and sessions in
   separate worktrees never do. That is the entire measured 2x cost difference, and it is avoidable.
2. **Never `--bare`.** It looks like the obvious startup fix; it drops off the Max subscription onto
   per-token API billing and skips CLAUDE.md.
3. **Verify each slice on disk, never on its exit code.** `anthropics/claude-code#74761`: `claude -p`
   can exit 0 with well-formed result JSON while the agent is mid-task.
4. **Cap at 3-5**, and give every slice a self-contained spec with an explicit expected result. A slice
   that stops to ask a question dies silently, because nobody can answer it.
5. **A fresh worktree is a bare checkout. Read the repo's `CLAUDE.md` and `CLAUDE.local.md` for its
   setup ritual and follow it exactly** rather than inventing a shortcut. **If neither documents one,
   say so before starting**, not after a slice has already failed on it.

**The lever that beats all of the above is slice balance.** One measured run spent 451s of a 466s round
on a single slice while three workers idled. Sizing slices evenly is worth more than any change of
mechanism.

**The runnable form is `/sk:work-superspeed`** (engine: `~/.claude/bin/superspeed-dispatch.sh`, waste
analysis: `~/.claude/bin/superspeed-analyse.py`). Run `/sk:claude-config-self-optimize-analysis-after-run` on the run
directory afterwards.

**`/sk:work-hyperspeed` is a two-level layer ON TOP of this** — an OUTER human relay (you paste each
slice into its own session) where each session runs the INNER superspeed on its own slice where it makes
sense, assembling from pushed branches off a shared START commit. It goes wider than one run's caps at
the cost of a manual relay. `/sk:work-warpspeed` (TODO) is the third layer on top of that — the same relay spread across VMs/VPSs on
DIFFERENT accounts/orgs, the only tier that breaks the per-org rate ceiling.

**Honest limits:** measured at 22-120s per round on one machine, one account, one repo. The reconcile
stage was not in the benchmark, so its cost is not in those numbers.

## Self-improving a parallel run — shared by superspeed and hyperspeed

A parallel harness is mediocre on its first runs and gets good only if each run records what it cost and
the next one is cut better. Both `/sk:work-superspeed` (automated) and `/sk:work-hyperspeed` (hand-run)
use this loop; it is defined ONCE here and neither restates it.

**Record every fixed file with a `cause`** in the run's `reconcile.json`:
- `slice` — the slice got it wrong. The ONLY cause that means the PARTITION needs changing.
- `late_scope` — the ask changed after dispatch. The partition was fine for what it was told.
- `reconciler` — you broke it while assembling. Not the slice's fault, not the partition's.

Recording all three as one number gets two of them the wrong prescription — measured across two
consecutive runs whose identical rework counts came from opposite causes.

**Analyse every run, then heal only what RECURS.** Run
`/sk:claude-config-self-optimize-analysis-after-run <run-dir>` on completion — an event, not a cron, so
it stays inside `rules/self-healing-config.md`'s no-periodic-scan line. It reads what the run left and
proposes durable fixes, including to the skill itself. But **auto-analyse, never auto-optimize:** the
run analyses itself, it does not change the config on its own — an edit still goes through the
self-healing propose-and-confirm gate, and most runs propose NOTHING. Weigh every candidate against the
fixed ~33s fan-out toll: splitting a fast slice finer, freezing one more contract, or adding a log field
for a one-off spends more than it saves and DEGRADES the next run. Only a finding that RECURS across
runs (check the prior run's log) is durable enough to become a rule; a single run's symptom is a
re-partition note, not a config change. Silence is the default.

**Harvest each worker's friction + timings, self-diagnose the bottleneck after EVERY run, and route the
fix to its right home.** Beyond the `reconcile.json` causes, read every worker's `<name>.friction.md` and
timestamped `<name>.log` (§ "The hand-run session handoff") alongside its result. Diagnose the BOTTLENECK
from the timestamps — which phase (install / build / the work) ate the wall-clock — and the frictions
that RECUR. Then improve in two tiers:
- **Within the run (AUTOMATIC, no config edit):** fold each round's friction fixes and the right setup
  into the NEXT round's worker blocks — bake the correct instruction in, or point the workers at the
  project's `CLAUDE.md`/`CLAUDE.local.md` (and `~/.claude`) to read BEFORE they start — so round N+1 is
  not tripped by what tripped round N.
- **Across runs, ROUTED to the home that OWNS the fact (ASK-FIRST, per `rules/self-healing-config.md`):**
  a friction or bottleneck that RECURS is durable enough to fix at source, and it goes to the ONE home
  that owns that fact so it stays DRY and reproducible — a PROJECT setup/build fact (how THIS repo builds,
  warms, what is heavy) to the project's COMMITTED `CLAUDE.md` so every worker and teammate gets it; a
  machine-local fact to that project's `CLAUDE.local.md`; a GENERIC-methodology fact (the pattern itself)
  to this reference. Each lands through `/sk:claude-config-update`'s gate; a run never edits any of them
  silently. The system handles ANY future setup step without changing the methodology — the worker reads
  the project's own setup section verbatim (whatever steps it lists), the friction surfaces when that
  section is wrong or stale, and the fix is routed to whichever home — dotclaude or the project's own docs
  — keeps it correct. This is the same auto-analyse-never-auto-optimize rule, now fed by worker friction.

## The hand-run session handoff — START, paste-block, poll (shared)

`/sk:work-hyperspeed` and `/sk:work-split-session-in-parallel-branch-offshoot` both build on ONE unit:
a clean START commit, a self-contained paste-and-forget block per spun-off session, and a shared status
file the orchestrator polls. Hyperspeed runs the unit N times and ASSEMBLES; the offshoot runs it ONCE
and HOLDS. This section OWNS the unit; each skill composes it and adds only its own finish. Put
`<harness>` = `hyperspeed` or `offshoot` in the paths so two runs never share a dir, and give each run a
UNIQUE `<run-id>`.

### 1. Commit + push a clean START
Every spun-off session branches from ONE commit so it starts identical (and, for hyperspeed, assembles
cleanly). If the tree is dirty, commit it (one logical unit; `references/git-pr-deploy.md` owns the
message). If on the default branch, branch first — never branch off `master`/`main`. Push, and record the
START SHA; it goes VERBATIM into every paste block.
```bash
git switch -c <harness>/<run-id>          # if not already on a feature branch
git add -A && git commit -F <msg-file>    # only if dirty; -F, never -m (git-pr-deploy.md)
git push -u origin HEAD
git rev-parse HEAD                        # ← the START SHA each session fetches and branches from
```

### 2. Create the shared STATUS dir
Put it INSIDE this run's own dir, `.context/<harness>/<run-id>/status/`, beside the plan file, and hand
each session its ABSOLUTE path. Co-locating keeps a run's state in ONE place and means two runs from
different orchestrator sessions never clash.
```bash
mkdir -p .context/<harness>/<run-id>/status
STATUS_DIR="$(git rev-parse --show-toplevel)/.context/<harness>/<run-id>/status"   # absolute; into each block
```

### 3. The self-contained paste-block skeleton
Each spun-off session gets ONE block, pasteable into a COLD session with zero other context. It carries,
in order: a first-line title `Session <n> (<name>):`; the front-door invoke
`/sk:meta-dotclaude-copilot-start-here-for-any-task` so the slice runs the right harness autonomously and
asks nothing; the git branch-off-START ritual below; the repo's fresh-worktree setup ritual reproduced
VERBATIM from its `CLAUDE.md`/`CLAUDE.local.md` (EVERY step, not just install); a FIRST action writing
`{"status":"working","part":"<name>","branch":"<branch>"}` to `<STATUS_DIR>/<name>.json` (branch recorded
NOW so a mid-work death still leaves it); a LAST action that tears down everything it started then
OVERWRITES the file with `{"status":"done","part":"<name>","branch":"<branch>","paths":[<absolute
outputs>],"goals":"met|not-met"}` (or `{"status":"blocked","part":"<name>","reason":"<why>"}`); and, after
that, the fallback report block (§ below) printed in case the status write failed. Throughout, it also
keeps a TIMESTAMPED phase log and a FRICTION report beside its status file: `<STATUS_DIR>/<name>.log` gets
a UTC timestamp at each phase boundary (install start/end, build start/end, work start/end) so the
orchestrator sees WHERE the wall-clock went; `<STATUS_DIR>/<name>.friction.md` lists everything that
slowed it or it had to fix (a node_modules symlink, a missing setup step, a cold rebuild that should have
been a cache hit), each with the fix and the instruction that would have avoided it — this is what the
self-improve loop harvests. Every `/sk:` name a
block loads must be VERIFIED installed first (`find -L ~/.claude/skills -name SKILL.md`) — one wrong name
derails every session at once.
```bash
git fetch origin
git switch -c <harness>/<run-id>/<name> <START-SHA>   # a Conductor workspace is already on its own branch
# off START — keep that one instead; either way it must sit on <START-SHA>. REPORT the exact branch name
# (Conductor names its own), so the orchestrator cleans up by the reported name, never by a pattern.
# …do the work…
git add -A && git commit -F <msg-file>     # -F, never -m
git push -u origin HEAD
```

### 4. Poll the shared status, with a progress bar
The orchestrator watches `$STATUS_DIR` — Simon only watches progress. Mirror the sessions to the harness
Task list (one task each, `completed` as its status flips to `done`) and print the compact bar per tick
(`references/progress-bar.md`). Run the loop BACKGROUNDED (`run_in_background`) so the session stays free.
```bash
S="$STATUS_DIR"; N=<count>; DEADLINE=$((SECONDS+3600))   # 60-min ceiling; raise for long slices
bar(){ local d=$1 t=$2 f=$(( d*8/(t>0?t:1) )) i o=""; for ((i=0;i<8;i++)); do [ $i -lt $f ] && o+="▓" || o+="░"; done; echo "$o $d/$t reported · $(date +%H:%M:%S)"; }
while :; do
  d=$(grep -lE '"status" *: *"(done|blocked)"' "$S"/*.json 2>/dev/null | wc -l | tr -d ' ')
  bar "$d" "$N"
  { [ "$d" -ge "$N" ] || [ $SECONDS -ge $DEADLINE ]; } && break
  sleep 15
done
echo "REPORTED:"; for f in "$S"/*.json; do echo "  $(basename "$f"): $(grep -o '"status" *: *"[a-z]*"' "$f")"; done
```
Any session still `working` or absent at the deadline is STUCK — name it for Simon; a `blocked` one is a
real stop with a reason.

### The fallback report block
The PRIMARY report is the JSON in `<STATUS_DIR>/<name>.json`; each session ALSO prints this same-field
plaintext, which Simon pastes ONLY if the orchestrator says the status file never arrived:
```
PART DONE
run: <run-id>
part: <name>
branch: <branch-name> (pushed: yes|no)
paths: <comma-separated ABSOLUTE output paths created or changed>
goals: met | not-met
status: done | blocked
```
A `blocked` session sets `status: blocked` + reason in BOTH places and leaves `BLOCKED.md` in the repo root.

## Parallelize across tasks AND stages
- Default to fanning work out across parallel agents whenever it's safe and speeds things up — wherever the pieces are genuinely independent (disjoint files, no shared state, no same-account/CLI clashes).
- Parallelize across BOTH tasks and stages, not just many agents on one stage — run independent tasks and independent pipeline stages concurrently wherever they don't clash on shared state.
- Don't go overboard and cause clashes, and don't parallelize for its own sake.
- When a new request lands mid-task, don't stop what you're already doing — spin the new work onto a separate parallel agent and keep both running.
- Orchestrate agents so they don't clash on shared state — e.g. not all mutating the same account/CLI/shared file at once.
- **Cap an in-session fan-out at 10 concurrent.** `CLAUDE_CODE_MAX_CONCURRENT_SUBAGENTS` is 10 here (60 per session total); at most 10 background agents run at once and the rest queue. Launching many more than 10 in ONE batch gets the excess REJECTED, not queued (observed: 20 launched → 19 accepted, the 20th errored `You can run 10 subagents at once`). DO cut the work into ≤10 slices, or dispatch in waves of ≤10 and expect ~N/10 waves of wall-clock. TEST: no single launch batch exceeds 10 agents unless the waves are deliberate.

## Parallelize verification, not just agents
The section above is about fanning out AGENTS. The same rule applies to the VERIFY step, and that is the
one that gets missed: typecheck, test and lint for independent units are independent COMMANDS, so issue
them as parallel tool calls rather than chaining them into one sequential shell invocation.

- **Build shared dependencies first, THEN fan out every consumer.** That first step is the only genuinely
  serial one — a consumer checked against a stale or missing shared build reports errors that aren't real.
  Everything downstream of it runs concurrently.
- **Only rebuild a shared dependency when that dependency actually changed.** Track what you touched. A
  needless rebuild of one shared package measured ~54s per cycle on one repo.
- **A fresh-worktree worker REUSES the orchestrator's build — it does not rebuild cold.** A worktree
  worker (hyperspeed/offshoot, or a teammate/cloud session in a fresh checkout) starts bare, so the reflex
  is a full cold rebuild — the wall. Instead: the orchestrator WARMS the build once at START; each worker
  runs the IDENTICAL build command so unchanged packages restore from the build tool's cross-worktree
  cache (a HIT), rebuilding ONLY the packages its own diff touched. Classify the slice by DELIVERABLE
  first — a typecheck+unit-test slice needs no app build and no native/`go` build at all, only
  cache-restored libs; reserve a full app build for a bundle/e2e/dev-boot slice. VERIFY the hits (dry-run
  the build), never assume. NEVER share one `node_modules` across worktrees: a monorepo's internal-package
  symlinks are relative, so worktree B silently runs worktree A's source — a correctness bug, not a
  slowdown; each worktree installs its own (sped by the package manager's global cache / hardlinks). The
  CONCRETE per-project recipe — the build command, the env that must match, which cache, which packages
  are heavy — belongs in the PROJECT's COMMITTED `CLAUDE.md`, so ANY worker on the repo (teammate, cloud,
  worktree) gets it and it stays reproducible; read it BEFORE building, and if it is missing or stale that
  gap is what the self-improve loop routes back into it.
- **Background the long pole and keep working.** A dependency install or a first cold build blocks nothing
  you are currently editing — start it detached and carry on with files that don't need it.
- **Expect sublinear speedup.** Parallel jobs contend for CPU: three checks measured 104s serial vs 56s
  parallel (1.9x, not 3x), and each individual job got slower. Fan out because the wall-clock is free, not
  because it scales linearly — and don't fan out so wide that everything thrashes.
- **Verify at TASK boundaries — not after every edit, and not only at the end.** Both extremes cost more
  than they save, and the end-loaded one is worse: errors CASCADE across unit boundaries, so a single
  broken file in a shared package emits a wall of unrelated "cannot find module" failures downstream and
  you debug the noise instead of the defect. Worse still, some defects never surface as a compile error at
  all — e.g. an incomplete runtime list that compiled clean and would have silently dropped records — and
  those are only caught by looking at what a change touched while it is still one change.
- **Batch edits that share a verification surface, then verify once.** Doing all the work behind one
  surface, verifying, then the next, beats interleaving them and paying a full fan-out each time.
- **Triage before reacting to a failure.** Separate YOUR errors from pre-existing and environmental ones
  FIRST — an unbuilt shared dependency can emit hundreds of spurious errors with nothing to do with your
  change. Filter by path, or take a baseline on a clean tree, before reading a single line.
- **Read the failure before rerunning.** A cascade almost always has one root cause at the top and N
  consequences below it. Fix the top one and re-run once, rather than reacting to the tail.

## Orchestrate with strong models, implement with smaller ones
- Act as the orchestrator: do the planning, decomposition, writing the spec sub-agents follow, reviewing, and verifying yourself, on the strong/expensive model. Delegate the actual implementation (file edits) to smaller models.
- Default implementation tier: **Sonnet 4.6** (`claude-sonnet-4-6`) for substantive code edits. **haiku** ONLY for genuinely mechanical edits — one unambiguous rule, no taste required (a rename, a find/replace with a single correct answer).
- A "string/label swap" is NOT mechanical if choosing the replacement needs judgement. When in doubt, use Sonnet 4.6 — the token saving is never worth the silent damage.
- **Haiku also fits simple, high-volume PARALLEL fan-out**, not just single mechanical edits: a fleet each doing a well-specified, low-judgement pass over its own slice — a leak/pattern scan, a classification, a mechanical audit, a "read these files and report X". It is cheap and fast, and reads semantically not just by pattern (one run: 19 Haiku agents scanned a ~135-file tree in ~2 min for ~1.1M tokens, and surfaced two leaks a plain `grep` missed). DO keep the three tiers distinct: Opus 4.8 orchestrates, Sonnet 4.6 implements where correctness or nuance matters (logic edits, reviews), Haiku does the parallel grunt-work. DON'T give Haiku a logic edit, a nuanced review, or any pass where a wrong answer is costly. TEST: every Haiku slice is one where a wrong answer is cheap and the spec leaves no judgement call.
- Match the model to the judgement required. Escalate to Sonnet 4.6 the moment a call needs taste — haiku will otherwise silently reword things it shouldn't, drop information, and mis-scope.
- **Pin the version — today's-landscape exception.** The bare `sonnet`/`opus` aliases now resolve to Sonnet 5 / Opus 5, which are a downgrade for this work, so pin delegated models to **Sonnet 4.6** (`claude-sonnet-4-6`) for implementation and **Opus 4.8** (`claude-opus-4-8`) when a delegated step needs the strong tier — until that reverses. Caveat: the Agent/Task `model` param is a strict enum (`sonnet`/`opus`/`haiku`/`fable`) and cannot carry a full ID, so a delegated Agent call still resolves the alias to 5. The pin only holds where the mechanism takes a full ID: `claude -p --model claude-sonnet-4-6` (superspeed), or a session `--model` / `/model` override. Where you must go through the Agent enum, keep orchestration on the pinned-4.8 session and delegate as little judgement as possible until the alias points back at a non-downgrade.
- Reserve the strong model for: planning, decomposition, the spec, build/test/verify loops, and reviewing + integrating sub-agent output. Run build/tests yourself after each batch and fix the integration seams.

## Give every agent a precise, self-contained spec
The spawn prompt is the ONLY channel — a subagent inherits none of the parent conversation — so
anything it isn't told, it doesn't have.

`rules/communication.md`'s five rules apply to the spawn prompt, not just to what you write Simon;
they are always-on and not restated here. The two that bite hardest on a delegation: state the
expected result (an agent told only what to do cannot tell you it failed), and name the real thing
(a path it has to guess at is a path it will guess wrong).
- Exact file paths, API-preservation rules, and conventions — so a smaller model can succeed.
- **Always give an explicit DO-NOT-TOUCH list, not just the task.** Name the look-alikes to leave alone and how to tell them apart (e.g. "en dashes – are NOT em dashes —"; "this string is a model prompt, not UI"). Collateral damage lands exactly where two things look similar.
- **State the OUTPUT FORMAT, not just the task.** This is the one field Anthropic requires that the
  rest of this list doesn't already cover (their four: objective, output format, tool/source
  guidance, task boundaries). In a Workflow script, make it a real JSON schema via `agent(prompt,
  {schema})` rather than prose, so a wrong shape can't come back at all.
- **Precise, not long.** Anthropic's own worked spec is four sentences. An orchestrator that hasn't
  read the code is the node LEAST able to prescribe implementation, so specify the boundary and the
  acceptance test, then stop.
- **Check the owned file sets against EACH OTHER before dispatching.** N individually-correct specs
  can each name exact paths and a DO-NOT-TOUCH list and still overlap, and the overlap is invisible
  when you read them one at a time. Lay them side by side. Trigger on coupling, not agent count: do
  it whenever there are 4+ writers, two agents in one package, or a shared interface between units.
  When two writers genuinely must share a directory, stop partitioning and isolate instead —
  `isolation: worktree` in the subagent's frontmatter is a harness-enforced boundary, a written
  partition is advisory. (In this monorepo a fresh worktree branches from the DEFAULT branch unless
  `worktree.baseRef` is `"head"`, and has no `node_modules`, so an isolated agent can edit but
  cannot build or test until someone pays `yarn install`.)

## There is no middle tier — one planner, flat leaf workers (settled 2026-08-04)
The recurring idea is a tree: a main orchestrator, group orchestrators under it, workers under
those. It was researched properly and rejected. Do not re-propose it without new evidence.

**It is buildable** (subagents nest three layers deep by default), so feasibility is not the
argument. The arguments are:
- **The tier is defanged.** `Workflow` and `AskUserQuestion` are stripped from EVERY subagent, so a
  mid-tier orchestrator cannot invoke the scale mechanism nor ask a question. It also cannot
  type-scope its own children (`Agent(type)` is main-thread only) and cannot approve their
  permission prompts, so a deep tree cannot run unattended. It burns a concurrency slot and a full
  context window while writing no code.
- **The fan-out never gets wide enough to need one.** Anthropic: *"Start with 3-5 teammates"*,
  *"three focused teammates often outperform five scattered ones."*
- **Collision avoidance is a filesystem property, not a supervisory one.** Where Anthropic wanted a
  hard guarantee they built a command-level check, not an instruction. An orchestrator is a model.
- **Nobody ships it.** Anthropic forbids nested teams outright; LangChain DELETED its
  supervisor-of-supervisors tutorial; CrewAI, the OpenAI Agents SDK, Semantic Kernel and Microsoft's
  clean-slate Agent Framework document zero hierarchical patterns. Google ADK is the sole exception.
- **It misbehaves in the wild.** `#73958` (three-level recursive re-delegation, 65-125k tokens for
  zero delivered work), `#74035` (1.7GB → 26GB RSS, OOM-killed).

`settings.json` now sets `CLAUDE_CODE_MAX_SUBAGENT_SPAWN_DEPTH: "1"`, which enforces this: workers
are leaves and cannot re-delegate. Raise it deliberately if a task genuinely needs nesting (the one
documented case is a reviewer dispatching a verifier per finding, for context hygiene).

**Honest limit of this decision:** nobody anywhere has measured a tree against a flat pool. The case
is circumstantial — vendor design decisions, a deleted tutorial, bug reports, missing capabilities —
not experimental. What IS well-supported is the other half: spec quality and disjoint ownership.

## Never trust a sub-agent's self-report — verify on disk
- Agents will confidently tell you a file is clean when they never touched it. After every delegated batch, prove it yourself with `grep`/`git diff`/tests. Treat the report as a claim to check, not evidence.
- Ask agents to paste real command output rather than summarise it — and still check.

## An agent you called "read-only" is not read-only unless you took its tools away
Calling a fan-out an "audit" does not restrict it. Agents inherit write tools, and one of them will
use them. On 2026-08-03 an audit agent — spawned purely to REPORT on `~/.claude` — committed a
pending change to the config repo AND pushed it to GitHub, mid-audit, unasked. (The work happened to
be correct, which is the part that makes this easy to miss: nothing looked wrong afterwards.)

So, whenever a fan-out is meant to be read-only:
- **Say it in the prompt, in those words:** "Do not edit, do not write, do not commit, do not push.
  Report findings only." A schema that only accepts findings is not a constraint on behaviour.
- **Check `git log` and `git status` in every repo the agents could reach, after the fan-out returns.**
  A push is not visible in the agents' reports, and `git status` looks clean precisely because the
  work was committed.
- **`Explore` is NOT read-only. Do not reach for it as the safe option.** Verified against the
  2.1.220 binary: its grant is a denylist of exactly six tools — `Agent`, `Artifact`,
  `ExitPlanMode`, `Edit`, `Write`, `NotebookEdit`. **Bash is not among them**, so an Explore agent
  can still `git commit`, `git push` and `rm -rf`; `anthropics/claude-code#75861` is one deleting
  `.claude/worktrees` unprompted. It would not have prevented the incident above. What Explore IS,
  is CHEAP: it is the only built-in type with `omitClaudeMd: true`, so it skips the whole CLAUDE.md
  hierarchy (~67KB here) that every other agent loads on every spawn. Reach for it to save tokens
  on a survey, never for safety.
- **The only real tool boundary is an allowlist.** A subagent defined with `tools: Read, Grep, Glob`
  cannot write by any route, because an unlisted tool is absent from its session. Use the allowlist
  form, never `disallowedTools` — `#78063` reports denylists are not inherited by subagents spawned
  through the Agent tool, and a denylist leaves `Agent` in place so a child can perform the write.
  Note this binds only when that `subagent_type` is actually chosen, so it supplements the prompt
  wording and the `git log` check above; it does not replace them.

## Verify the fan-out actually finished before acting on its output
A workflow reports "completed" whether its agents succeeded or died. On the same run, 53 of 68
verifier agents failed on a session limit, and the summary still arrived looking like a finished
result — with the dead agents' findings silently counted as unconfirmed rather than unverified.
Read the failure list and the done/error counts before treating the output as an answer, and re-run
the verification half if it was the part that died.

## Review the delegated diff before committing
- Watch specifically for: scope creep (rewording beyond the ask), dropped information, and edits to things you explicitly excluded.

## Keep durable, tracked progress
- Keep track of everything across parallel work — progress files, tickets, extra branches — tick off stages so you always know where you're at and can return to any part.
- Trivial one-line fixes during a conversation are fine to do inline; anything multi-file should fan out to smaller-model agents.
