---
name: work-hyperspeed
description: Hand-run parallelism — instead of dispatching `claude -p` subprocesses like superspeed, YOU paste each slice into a separate Claude session yourself. The orchestrator commits a clean START commit, writes ONE durable plan file split into fully self-contained paste-and-forget parts (each carries the whole shared context, its owned files, the exact git branch-off-START ritual, the repo setup steps, and a fixed report-back block), and hands you the file location. You open a session per part and paste it; each works on its own branch off START in its own Conductor workspace and, when done, prints its branch + output paths; you relay those back; the orchestrator merges the branches, deletes them, tells you to archive the sessions, and loops until the whole task is done. Use for "hyperspeed", "I'll paste the parts into separate sessions myself", "split this into paste-and-forget parts", "hand-parallelise this", or when superspeed's automation is slower or less reliable than you pasting into fresh sessions by hand. Sibling of /sk:work-superspeed (automated) and /sk:work-warpspeed (the VM/VPS evolution, not built yet); the slice-cutting craft is shared and lives in references/parallelization.md.
argument-hint: "[the task to hand-parallelise]"
---

# Hyperspeed — hand-run parallelism

You paste the parts into separate sessions yourself; the orchestrator only cuts the work, writes the
plan file, and assembles the branches. It is `/sk:work-superspeed` with the automated `claude -p`
dispatch replaced by a human relay, because on your setup the manual separate sessions beat the
automated ones.

## Why this exists, honestly

`references/parallelization.md` is the source for BOTH the win and its limits — read it, don't restate
it here. The measured finding: separately launched sessions have no documented concurrency cap, while
in-session subagents cap at 10 and workflows at 16. Superspeed already rides that finding with
`claude -p`. This skill exists because that automation carries failure modes a hand-run session does
not: a `claude -p` slice can exit 0 mid-task, it runs under `acceptEdits` so it cannot Bash, and a
blocked slice dies silently. A full interactive session you drive has all its tools, asks nothing it
cannot resolve, and you SEE it finish.

**The honest caveat, from `references/parallelization.md`: Anthropic's limits key on the ORGANIZATION,
not the machine.** So many hand-run sessions on ONE account share one rate pool — the win here is the
removed concurrency cap, the removed orchestration toll, and full-tool reliability per session, NOT a
raw throughput multiplier. Genuine multiplication needs different accounts/orgs, which is
`/sk:work-warpspeed`'s territory.

## Run it as a paced co-pilot session, not a memo

Simon drives the pasting; you drive the cutting and assembly. GUIDE him through it the way
`/sk:test-copilot` runs a journey — the shared contract is `references/human-pacing.md`: keep the plan
in the file, give him ONE handoff at a time with a progress marker ("round 1 · 3 parts to paste, then
relay back"), signal the hand-off, and WAIT for his relay before the next move. The Steps below are the
CONTENT of those handoffs, not a wall to paste at him. Each round is one overview line, then: paste
handoff → wait → assemble → cleanup handoff → next round.

## Step 0 — decide whether to fan out at all

Same test as superspeed (`references/parallelization.md` § "decide whether to fan out"): only fan out
work that splits into slices touching DISJOINT files, at 3-5+ slices. If it does not divide, work in
one session — every part hitting the same file is the indivisible-task failure. If a slice is under a
minute, don't make it a part; the relay overhead is a paste and a copy-back per part.

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

## Step 2 — cut the task (shared craft, not restated)

The partition rules are IDENTICAL to superspeed and live in `references/parallelization.md` and
`/sk:work-superspeed` Step 1: freeze any shared contract into START first, give every slice exclusive
`owns`/`reads`/`forbid`, name what each file ASSERTS not only what it writes, split any slice owning
more than 4 files or creating files from scratch, and balance by deliverable count. Read them there.
Only the dispatch differs; the cut does not.

## Step 3 — write ONE plan file, split into self-contained parts

Write it to `.context/hyperspeed/<run-id>/plan.md` — durable per `rules/process.md` (survives a
restart, never `/tmp`). **Hand Simon the file's ABSOLUTE path.** The file opens with the shared goal
and the START SHA, then one `## PART <n> — <name>` section per slice.

**Every part is pasteable into a COLD session with zero other context.** Each part section carries, in
this order:

1. **The whole goal**, in enough detail to act on alone — the session inherits none of this conversation.
2. **This part's task**, written as a rule not an example (`rules/process.md` § "Fix the CLASS"), with
   its `owns` (may edit), `reads` (read-only), `forbid` (the look-alikes another part owns), an
   `accept` line, and a runnable `verify` command scoped to its owned files.
3. **The git ritual, verbatim and copy-pasteable:**
   ```bash
   git fetch origin
   git switch -c hs/<run-id>/<part-name> <START-SHA>
   # …do the work…
   git add -A && git commit -F <msg-file>     # -F, never -m
   git push -u origin HEAD
   ```
4. **The repo setup ritual**, lifted from the project's `CLAUDE.md` and `CLAUDE.local.md` (e.g. Node
   version, `yarn install`, any build a fresh worktree needs) — the part must not have to go find it.
5. **The report-back block** (§ below): the part PRINTS it as its last action so Simon can copy it.
6. **The leaf-worker rules:** you are one worker; do not ask questions (nobody can answer); if blocked,
   write `BLOCKED.md` in the repo root saying what and why, then stop rather than editing a `forbid` file.

TEST: a part pasted into a brand-new session, with nothing else, can reach `accept`, push its branch,
and print its report block.

## Step 4 — Simon pastes each part; parts report their location

Open one session per part — a separate Conductor workspace is the intended home, so each part gets its
own worktree and branch off START without fighting the others over the checkout. Paste the part, forget
it. When it finishes it prints its report block; copy every block back to the orchestrator in one
message.

## Step 5 — assemble, warm, in the orchestrator session

Do NOT spawn a fresh session; the orchestrator holds the partition and the reasoning already. When
Simon relays the branches:

1. `git fetch origin` all reported branches.
2. Create an assembly branch off START and merge each part branch into it, in a stable order.
3. Fix the seams, then run the project gate ONCE over the whole tree — the reconcile craft is
   superspeed Step 3 (`/sk:work-superspeed`); read it there, don't restate it.
4. Read any `BLOCKED.md` a part pushed and finish that work yourself.

## Step 6 — clean up, then loop

- **Delete every merged part branch, local and remote** (`git branch -D hs/<run>/*`,
  `git push origin --delete <branch>`). The orchestrator owns branch cleanup.
- **Tell Simon to archive the Claude sessions.** The orchestrator cannot touch the Claude UI, so it
  names the sessions/workspaces to archive; Simon archives them.
- **If work remains, loop:** the assembled branch is the new START. Commit + push it, write the next
  round's plan file, and repeat Steps 3-6 until the whole task is done. Say plainly, each round, what is
  done and what parts remain.

## The report-back block (fixed format each part prints)

Each part ENDS by printing exactly this, so Simon can copy it verbatim and the orchestrator can parse it:

```
HYPERSPEED PART DONE
run: <run-id>
part: <part-name>
branch: <branch-name> (pushed: yes|no)
paths: <comma-separated output files this part created or changed>
status: done | blocked
```

A `blocked` part prints `status: blocked` and the reason, and leaves `BLOCKED.md` in the repo root.

## Self-improvement — every round, like superspeed

Mediocre at first, good over rounds, the way `/sk:work-superspeed` got there. The loop — record each
fixed file's cause, analyse every run, heal only what RECURS — is shared and defined in
`references/parallelization.md` § "Self-improving a parallel run". Reuse it. Two hyperspeed-specifics:

- **Write the round's log to `.context/hyperspeed/<run-id>/reconcile.json`** (durable per
  `rules/process.md`), in that section's schema, plus `parts`, `rounds` and each part's report block so
  the analysis sees the partition, not only the fixes. Run
  `/sk:claude-config-self-optimize-analysis-after-run <run-dir>` after each round.
- **A hand-run round leaves reconcile + partition data, not `claude -p` token/timing telemetry**, so the
  analyser judges partition quality and rework, not idle-capacity. That is the honest limit, and it is
  enough to cut the next partition better.

## Teardown

Put `.context/hyperspeed/` in the project's personal ignore layer (`.git/info/exclude`, not the
committed `.gitignore`). Keep the plan files and the `reconcile.json`s; comparing them across rounds is
what makes the next partition better.
