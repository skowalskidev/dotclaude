---
name: work-hyperspeed
description: Two-level, hand-run parallelism that sits ON TOP OF /sk:work-superspeed, not in place of it. The OUTER layer is you: the orchestrator commits a clean START commit and writes ONE durable plan file split into fully self-contained paste-and-forget parts (each carries the whole shared context, its owned files, the git branch-off-START ritual, the repo setup steps, and a fixed report-back block), and you paste each part into its own separate Claude session. The INNER layer is superspeed: each session runs its slice through /sk:work-full-detailed-workflow and fans its OWN slice out with /sk:work-superspeed where it makes sense, then proves its goals with /sk:ship-report-and-ensure-correct-user-system-journey and writes its status + output location to a shared file in this run's own dir. The orchestrator POLLS that file, so you NEVER relay anything back — your only actions are pasting the starter block into each session and archiving the sessions at the end; the orchestrator knows when all are done, merges the branches, deletes them, and cleans up. Use for "hyperspeed", "I'll paste the parts into separate sessions myself", "split this into paste-and-forget parts", "hand-parallelise this", or when you want more parallelism than one superspeed run's caps. /sk:work-warpspeed is the third layer on top of this (many VMs/VPSs on different accounts/orgs), not built yet; the slice-cutting craft is shared and lives in references/parallelization.md.
argument-hint: "[the task to hand-parallelise]"
---

# Hyperspeed — two-level parallelism (hand-run on top of superspeed)

Hyperspeed is a LAYER ON TOP of `/sk:work-superspeed`, not a replacement for it. The OUTER layer is
you: the orchestrator cuts the work, writes a plan file, and you paste each part into its own session.
The INNER layer is superspeed: each of those sessions fans its OWN slice out with `/sk:work-superspeed`
where it makes sense. So the parallelism multiplies — N hand-run sessions, each fanning out again —
which is why it goes wider than superspeed alone.

## Tell Simon how it runs, before the first paste — a first-timer cannot infer it

Nothing MOVES to another session. THIS session is the orchestrator and STAYS PUT — it holds the whole
partition and does the assembly. Simon opens N NEW sessions himself, pastes ONE ready-made block into
each, and they run IN PARALLEL; each reports its own status to a shared file THIS session POLLS, so
Simon copies NOTHING back. State exactly that, in his words, as the FIRST thing you say — before the
plan, before any paste — because a first run reads "parts into separate sessions" as "this chat is about
to move elsewhere" and stalls on it: e.g. "this session stays here as the orchestrator and assembles
everything; you open N new sessions and paste one block I hand you into each, they run at once and
report to me automatically, and your only other job is to archive the sessions once I say they're done."
TEST: before the first handoff, Simon has been told three things plainly — the orchestrator stays, the
sessions run in parallel, and he never copies anything back (I poll the shared status; his only end
action is archiving).

## Why two levels, honestly

`references/parallelization.md` is the source for the win and its limits — read it, don't restate it.
The measured finding: separately launched sessions have no documented concurrency cap, while in-session
subagents cap at 10 and workflows at 16. The OUTER hand-run layer buys what an automated dispatcher
cannot: you SEE each session finish, each has full tools (it can Bash, and it can run superspeed
itself), and a stuck session is one you notice rather than a `claude -p` slice that exits 0 mid-task and
dies silently. The INNER superspeed layer buys throughput inside each session's slice.

**The honest caveat, from `references/parallelization.md`: Anthropic's limits key on the ORGANIZATION,
not the machine.** So all these sessions on ONE account share one rate pool — the win is the removed
concurrency cap, the removed outer-layer orchestration toll, and full-tool reliability per session, NOT
a raw throughput multiplier. Genuine multiplication needs different accounts/orgs, which is
`/sk:work-warpspeed`'s territory.

## Run it as a paced co-pilot session, not a memo

Simon drives the pasting; you drive the cutting and assembly. GUIDE him through it the way
`/sk:test-copilot` runs a journey — the shared contract is `references/human-pacing.md`: keep the plan
in the file, give him ONE handoff at a time with a progress marker ("round 1 · 3 parts to paste, then I
poll till done"), signal the hand-off, and WAIT while the poll runs before the next move. The Steps
below are the CONTENT of those handoffs, not a wall to paste at him. Each round is one overview line,
then: paste handoff → poll → assemble → cleanup handoff → next round.

## Step 0 — decide whether to fan out at all

Same test as superspeed (`references/parallelization.md` § "decide whether to fan out"): only fan out
work that splits into slices touching DISJOINT files, at 3-5+ slices. If it does not divide, work in
one session — every part hitting the same file is the indivisible-task failure. If a slice is under a
minute, don't make it a part; the overhead is a paste per part (the orchestrator polls the rest).

## Step 1 — commit and push a clean START, before anything else

Every part branches from ONE commit so they all start identical and assemble cleanly.

1. If the tree is dirty, commit it (one logical unit; `references/git-pr-deploy.md` owns the message).
2. If you are on the default branch, branch first — never make parts branch off `master`/`main`.
3. Push it, and record the START: its SHA and its remote branch. This SHA goes VERBATIM into every part.

```bash
git switch -c hs/<run-id>        # if not already on a feature branch
git add -A && git commit -F <msg-file>   # only if dirty; -F, never -m (git-pr-deploy.md)
git push -u origin HEAD
git rev-parse HEAD               # ← the START SHA every part fetches and branches from
```

**Also create the SHARED STATUS dir the parts report to and you POLL — put it INSIDE this run's own
dir, `.context/hyperspeed/<run-id>/status/`, right beside the plan file, and hand each part its ABSOLUTE
path.** Co-locating it there keeps all of a run's state in ONE place (DRY/SRP) and means two hyperspeed
runs from DIFFERENT orchestrator sessions NEVER clash — each writes under its own worktree's own
`<run-id>`, never a shared global path. Give each run a UNIQUE `<run-id>`.

```bash
mkdir -p .context/hyperspeed/<run-id>/status
STATUS_DIR="$(git rev-parse --show-toplevel)/.context/hyperspeed/<run-id>/status"   # absolute; into every part
```

The parts (in OTHER worktrees, same machine) write their status file there by that absolute path; you
paste the parts and forget them, and THIS session watches `$STATUS_DIR`. That watch is what removes the
manual relay (§ Step 4.5).

## Step 2 — cut the task (shared craft, not restated)

The partition rules are IDENTICAL to superspeed and live in `references/parallelization.md` and
`/sk:work-superspeed` Step 1: freeze any shared contract into START first, give every slice exclusive
`owns`/`reads`/`forbid`, name what each file ASSERTS not only what it writes, split any slice owning
more than 4 files or creating files from scratch, and balance by deliverable count. Read them there.
Only the dispatch differs; the cut does not. Size a slice so it is worth a whole session — a slice that
itself sub-divides is fine, because its session will superspeed it (Step 3, item 3).

## Step 3 — write ONE plan file, split into self-contained parts

Write it to `.context/hyperspeed/<run-id>/plan.md` — durable per `rules/process.md` (survives a
restart, never `/tmp`). The file opens with the shared goal and the START SHA, then one
`## PART <n> — <name>` section per slice.

**The plan file is the DURABLE RECORD, not the handoff.** Hand Simon its ABSOLUTE path AND present each
part as a ready-to-paste block in chat (Step 4) — never just give the path and tell him to open it and
pull the parts out. He should be able to copy a block straight into a new session without touching the
file at all.

**Every part is pasteable into a COLD session with zero other context.** Each part section carries, in
this order:

1. **The whole goal**, in enough detail to act on alone — the session inherits none of this conversation.
2. **This part's task**, written as a rule not an example (`rules/process.md` § "Fix the CLASS"), with
   its `owns` (may edit), `reads` (read-only), `forbid` (the look-alikes another part owns), an
   `accept` line, and a runnable `verify` command scoped to its owned files.
3. **Run the slice through the full harness — autonomously, and superspeed WITHIN it.** The session
   drives its slice with the spine skill that fits the part's TASK SHAPE (per `references/skill-stack.md`)
   — `/sk:work-full-detailed-workflow` for a code/build slice (it takes a port lane via
   `/sk:work-isolate-environment` and closes with `/sk:ship-report-and-ensure-correct-user-system-journey`),
   `/sk:ship-mockup-before-after` for a design mockup, the matching design/review skill for those —
   and **fans its OWN slice out with
   `/sk:work-superspeed` where that slice sub-divides into 3-5+ independent pieces** — this is the inner
   layer, hyperspeed on top of superspeed. It runs UNATTENDED: this spec IS the ratified plan (no
   sign-off to wait for), the `accept` line is the criteria ship-report judges against, and it asks
   NOTHING. It prints its report block only AFTER ship-report confirms the slice's goals are met, so the
   orchestrator assembles verified work.
4. **The git ritual, verbatim and copy-pasteable:**
   ```bash
   git fetch origin
   git switch -c hs/<run-id>/<part-name> <START-SHA>   # a Conductor workspace is already on its own
   # branch off START — keep that one instead of switching; either way it must sit on <START-SHA>
   # …do the work…
   git add -A && git commit -F <msg-file>     # -F, never -m
   git push -u origin HEAD
   ```
   Whichever branch you land on, REPORT its EXACT name (item 6) — the orchestrator cleans up by the
   reported name, never by an `hs/` pattern, because Conductor names its workspace branch itself.
5. **The repo setup ritual**, lifted from the project's `CLAUDE.md` and `CLAUDE.local.md` (e.g. Node
   version, `yarn install`, any build a fresh worktree needs) — the part must not have to go find it.
6. **Report status to the SHARED file (primary), tear down, THEN print the block (fallback).** The
   part's block carries its `<STATUS_DIR>` absolute path (from Step 1). As its FIRST action AFTER the
   branch-off-START ritual (item 4) it writes `<STATUS_DIR>/<part-name>.json` =
   `{"status":"working","part":"<name>","branch":"<the branch it just landed on>"}` — recording the
   branch NOW, not only at done, so that even a mid-work death leaves the branch name for the orchestrator
   to find and clean, since a Conductor branch name cannot be reconstructed by pattern. As its LAST actions it
   (a) tears down everything it started — its harness dev servers, its port lane, and any inner
   `/sk:work-superspeed` `claude -p` slices — per `rules/process.md` § "Clean up after yourself" and
   `references/dev-server-hygiene.md`, so the finished session holds no live processes and archiving only
   reaps its idle `claude`; (b) OVERWRITES its status file with
   `{"status":"done","part":"<name>","branch":"<branch>","paths":[<absolute outputs>],"goals":"met|not-met"}`
   — or `{"status":"blocked","part":"<name>","reason":"<why>"}` if it stops — which is what the
   orchestrator POLLS, so Simon never relays; then (c) PRINTS the report-back block (§ below) as a
   FALLBACK for the rare case the shared write failed. TEST: after DONE, `<STATUS_DIR>/<part-name>.json`
   reads `done`, and `pgrep` for the part's servers and its `claude -p` slices returns nothing.
7. **The leaf-worker boundary:** you own only your `owns` files — never edit a `forbid` file to make
   your slice pass. If the work genuinely needs one, or you get stuck, that is a `BLOCKED.md` in the
   repo root (what and why) and a stop, not an edit.

**Every skill name a part tells its session to load must be VERIFIED installed FIRST.** Glob it —
`find -L ~/.claude/skills -name SKILL.md` — or confirm it in the runtime skill listing before you write
it into a part; never write a skill name from memory. One wrong or non-existent name in the shared
template derails ALL parallel sessions at once, and you only find out after paying for N sessions (e.g.
the mockup run told every session to load a non-existent `artifact-design`; the installed mockup flow was
`/sk:ship-mockup-before-after`). TEST: every `/sk:` name across all parts resolves to an installed
SKILL.md before the plan is handed over.

TEST: a part pasted into a brand-new session, with nothing else, can reach `accept`, push its branch,
and print its report block.

## Step 4 — hand over ready-to-paste blocks; parts report their location

**Present each part directly in chat as its own clearly-labelled, fenced copy-paste block** — one per
parallel session, headed with which session it goes in (e.g. "► Paste into session 1 (Command Center)")
— so Simon copies a block straight into a new session. Each block is self-contained: pointing to the
durable plan file and the shared inputs by ABSOLUTE path is fine, but the block itself carries the whole
instruction. Do NOT hand only the plan-file path and make him extract the parts himself — that is the
first-run confusion this skill exists to remove. TEST: Simon can run the round by copying blocks out of
the chat, never opening the plan file.

**Start each block with a cross-verifiable session line — the FIRST line INSIDE the fence is a clean
title `Session <n> (<part-name>):` on its own line (the instruction follows below it)**, matching the
block's header label and the report block's `part:`. A new
session auto-names itself from its first prompt line, so this makes the name land logically ("Session 1
(Command Center)") and lets Simon cross-reference a report block to its session by number at a glance.
**Keep the blocks as plain fenced code-blocks** — the terminal's own copy button flashes "Copied"
natively, so the copy-state affordance needs nothing built; don't spin up a separate HTML card just for
that. TEST: for every part, the session's auto-name, its header label, and its report block's `part:`
all name the same direction.

Open one session per part — a separate Conductor workspace is the intended home, so each part gets its
own worktree and branch off START without fighting the others over the checkout (and its own port lane
when its harness boots a server). Paste the part, forget it — that is Simon's ONLY action per part. Each
session runs the full harness on its slice (Step 3, item 3) and writes its status to `$STATUS_DIR`; the
orchestrator POLLS that dir (Step 4.5), so Simon copies NOTHING back. The printed report block is only a
fallback he pastes if the orchestrator reports a part's status file never arrived.

## Step 4.5 — POLL the shared status, with a PROGRESS BAR, until every part reports

The orchestrator watches `$STATUS_DIR` — Simon does nothing here but watch progress. SHOW it per
`references/progress-bar.md`: mirror the parts to the harness Task list (one task per part, marked
`completed` as its status flips to `done`) as the canonical tracker, and print the compact bar each poll
tick. Run the wait-loop BACKGROUNDED (`run_in_background`) so this session is free; its ticking output IS
the live bar, and the harness wakes the orchestrator when every part is `done`/`blocked` or the timeout
fires.

```bash
S="$STATUS_DIR"; N=<part-count>; DEADLINE=$((SECONDS+3600))   # 60-min ceiling; raise for long slices
bar(){ local d=$1 t=$2 f=$(( d*8/(t>0?t:1) )) i o=""; for ((i=0;i<8;i++)); do [ $i -lt $f ] && o+="▓" || o+="░"; done; echo "$o $d/$t parts reported · $(date +%H:%M:%S)"; }
while :; do
  d=$(grep -lE '"status" *: *"(done|blocked)"' "$S"/*.json 2>/dev/null | wc -l | tr -d ' ')
  bar "$d" "$N"
  { [ "$d" -ge "$N" ] || [ $SECONDS -ge $DEADLINE ]; } && break
  sleep 15
done
echo "REPORTED:"; for f in "$S"/*.json; do echo "  $(basename "$f"): $(grep -o '"status" *: *"[a-z]*"' "$f")"; done
```

On the wake, read every `$STATUS_DIR/*.json`: any part still `working` or absent at the deadline is a
STUCK part — name it for Simon (its session may need a look) and assemble what did report; a `blocked`
part is the design working, handled in Step 5.

## Step 5 — assemble, warm, in the orchestrator session

Do NOT spawn a fresh session; the orchestrator holds the partition and the reasoning already. Read each
part's `branch` and `paths` from `$STATUS_DIR/*.json` (the poll already confirmed them done):

1. `git fetch origin` all reported branches.
2. Create an assembly branch off START and merge each part branch into it, in a stable order.
3. Fix the seams, then run the project gate ONCE over the whole tree — the reconcile craft is
   superspeed Step 3 (`/sk:work-superspeed`); read it there, don't restate it.
4. Read any `BLOCKED.md` a part pushed and finish that work yourself.

## Step 6 — clean up, then loop

Cleanup runs in the SAME turn as the assembly (Step 5) — a merged assembly branch is a checkpoint, not
the finish (`rules/process.md` § "run to completion"), so do NOT report "assembled" and end the turn with
the branches and worktrees still lying around. The run is DONE only when this reconcile's TEST passes. A
run leaves BRANCHES, WORKTREES and PROCESSES across N sessions, and all three are torn down here every
round, per `rules/process.md` § "Clean up after yourself" and `references/dev-server-hygiene.md`.

- **Confirm before deleting — present the list, wait for a yes.** Before removing ANYTHING, show Simon
  the exact set you propose to delete — every reported part branch, the run's START branch, and each part
  worktree — and get his explicit yes; never delete unprompted, even though the gate proves each is merged
  (`references/git-pr-deploy.md` § "Deleting a merged branch safely"). This is one paced handoff
  (`references/human-pacing.md`): show the list, WAIT, then delete only the batch he approved. He can veto
  any item — keep it and move on. (Remote-branch deletion is part of what he approves; it is a shared-remote
  write.)
- **Branches — delete each part branch BY ITS REPORTED NAME, local and remote.** Read the `branch` field
  from every `$STATUS_DIR/*.json` (Step 5 already has them). Do NOT glob `hs/<run>/*`: the parts run in
  Conductor workspaces, which NAME the branch themselves (`skowalskidev/<workspace>`, not `hs/...`), so a
  name pattern matches nothing and the branches pile up unseen — and a shell glob cannot expand branch
  names anyway. For each reported branch, prove it merged into the assembly branch
  (`git merge-base --is-ancestor <part-branch> <assembly-branch>`), then `git branch -D <part-branch>`
  and, if it was pushed, `git push origin --delete <part-branch>`. Use `-D` after that gate, never `-d`
  (its merge check is HEAD-relative and refuses a genuinely-merged branch in a stale worktree) — the rule
  is `references/git-pr-deploy.md` § "Deleting a merged branch safely". The orchestrator owns this. **Also
  delete the run's own START branch** when Step 1 created a fresh `hs/<run-id>` (NOT a pre-existing feature
  branch you were already on): once the final assembly supersedes it, `git merge-base --is-ancestor <start>
  <assembly>` then `git branch -D` local and remote — same for any superseded prior-round assembly branch,
  or `hs/<run-id>` accumulates one dead branch per run.
- **Worktrees — remove each part's worktree, then prune.** `git worktree remove` any worktree the
  orchestrator itself created; NAME each Conductor workspace (the default, Conductor-managed home) for
  Simon to archive — archiving removes the worktree AND reaps that session's idle process. Then
  `git worktree prune` and reconcile `git worktree list` against what should remain.
- **Processes — sweep the machine for what the run left.** Each part self-cleans its servers, port lane
  and inner `claude -p` slices at finish (Step 3, item 6); at reconciliation run
  `bin/kill-orphan-workers.sh` for any BURNING dev-server orphan a killed session left, release held
  port lanes (`bin/port-registry.sh`), and check `pgrep -fl 'claude -p'` for stray inner slices. The
  orchestrator cannot close an interactive session, so it NAMES each idle session for Simon to archive —
  the one action that reaps the session's own `claude` process.
- **Backstop — sweep anything a run leaks with `/sk:meta-cleanup-worktrees`.** A Conductor workspace that
  Simon archives leaves its branch behind, and a session that dies before self-cleaning leaves a worktree;
  that skill discovers merged branch-only orphans and idle worktrees for this repo and clears them safely.
  Run it if the TEST below still shows residue after the per-part cleanup. **If the ORCHESTRATOR itself
  died mid-run**, the run's `.context/hyperspeed/<run-id>/status/*.json` still names every part's branch
  (recorded at working-state, Step 3 item 6), so recovery reads those names and cleans by them — the
  branches are not lost just because assembly never ran.
- TEST: at hand-back, NONE of the reported part branches survive — for every `$STATUS_DIR/*.json`
  `branch`, `git show-ref --verify --quiet refs/heads/<branch>` fails and it is gone from
  `origin` — `git worktree list` shows no part worktree, and `pgrep -fl 'next-router-worker|vitest|jest'`
  lists only what the orchestrator started.
- **If work remains, loop:** the assembled branch is the new START. Commit + push it, write the next
  round's plan file, and repeat Steps 3-6 until the whole task is done. Say plainly, each round, what is
  done and what parts remain.

## Variant — standalone / gitignored artifacts (no branches to merge)

When the parts produce UNTRACKED artifacts (gitignored mockups, reports, build outputs) rather than
tracked code, there are no branches to assemble — so the git ritual is REPLACED, not skipped:

- **Steps 1 & 4 (START commit, branch off START):** the git bits are dropped — no START, no per-part
  branch, no diff to review. The SHARED STATUS dir + polling (Step 1's status setup and Step 4.5) STAY:
  each part still writes `working` → `done`/`blocked` + its `paths` to `$STATUS_DIR`, and the orchestrator
  still polls, so Simon still copies nothing back.
- **Output path — write to your OWN worktree, NEVER a hardcoded sibling.** Each part writes its artifact
  to `<its-own-repo-root>/.context/<run-id>/<file>` — the worktree the session is actually in. Do NOT
  pin one participant worktree's absolute path into every part: the sessions run in DIFFERENT worktrees,
  so a fixed sibling path scatters the output (rr-mockups-r1 put 3 artifacts in one worktree and 1 in
  another because the path was pinned to a single worktree).
- **Report the ABSOLUTE path** in the report block's `paths:` — this is what makes the gather deterministic.
- **Step 5 (assemble) becomes GATHER:** read each part's `paths` from `$STATUS_DIR/*.json` and copy
  every one into ONE collection dir in the orchestrator's own worktree (`.context/<run-id>/collected/`),
  then compare/review there. No merge, no seams.
- **Keep them gitignored — do NOT commit exploratory artifacts.** They live in `.context` and are
  disposable; forcing them into git history is noise. The branch-assembly default (Steps 1/4/5/6) is for
  tracked CODE; this variant is for everything else.

TEST: after the round, every reported artifact path resolves to a real file AND a copy of it sits in the
one collection dir, whichever worktree produced it.

## The report-back block (the FALLBACK mirror of the status file)

The part's PRIMARY report is the JSON it writes to `<STATUS_DIR>/<part-name>.json` (Step 3, item 6),
which the orchestrator polls. It ALSO prints this block — the same fields in plain text — as a FALLBACK
Simon pastes only if the orchestrator says a part's status file never arrived:

```
HYPERSPEED PART DONE
run: <run-id>
part: <part-name>
branch: <branch-name> (pushed: yes|no)
paths: <comma-separated ABSOLUTE output paths this part created or changed>
goals: met | not-met (ship-report verdict)
status: done | blocked
```

A `blocked` part sets `status: blocked` + the reason in BOTH the status file and this block, and leaves
`BLOCKED.md` in the repo root.

## Self-improvement — every round, like superspeed

Mediocre at first, good over rounds, the way `/sk:work-superspeed` got there. The loop — record each
fixed file's cause, analyse every run, heal only what RECURS — is shared and defined in
`references/parallelization.md` § "Self-improving a parallel run". Reuse it. Two hyperspeed-specifics:

- **Write the round's log to `.context/hyperspeed/<run-id>/reconcile.json`** (durable per
  `rules/process.md`), in that section's schema, plus `parts`, `rounds` and each part's status file (the
  run's `status/` dir sits right beside this log) so the analysis sees the partition, not only the fixes. Run
  `/sk:claude-config-self-optimize-analysis-after-run <run-dir>` after each round.
- **A hand-run round leaves reconcile + partition data, not `claude -p` token/timing telemetry**, so the
  analyser judges partition quality and rework, not idle-capacity. That is the honest limit, and it is
  enough to cut the next partition better.

## Teardown

Put `.context/hyperspeed/` in the project's personal ignore layer (`.git/info/exclude`, not the
committed `.gitignore`). Keep the plan files and the `reconcile.json`s; comparing them across rounds is
what makes the next partition better.
