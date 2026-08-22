---
name: work-split-session-in-parallel-branch-offshoot
description: Spin ONE idea off into its own parallel Claude session as a throwaway branch, while THIS session keeps working — and DON'T merge it back on finish. For a spur-of-the-moment "what if" you want out of the way of the main work and may bin after a look: the orchestrator commits a clean START, hands you one paste-and-forget block for a new session, and polls a shared status file so you relay nothing. When the offshoot reports done it HOLDS — surfaces its branch and any screenshot/preview for you to eyeball — and waits for your call: merge it back, or discard it (branch + worktree binned). Reuses /sk:work-hyperspeed's START/paste/poll plumbing; the only difference is the finish is hold-don't-assemble, and it is always ONE session, not a 3-5+ fan-out. Use for "work this as a branch offshoot", "spin this off, I might discard it", "try this as an offshoot in parallel", "explore this on a side branch I'll eyeball later", "offshoot this", "don't merge it back yet". For a task that DIVIDES into 3-5+ slices, that is /sk:work-hyperspeed instead.
argument-hint: "[the idea to spin off as a throwaway branch]"
---

# Branch offshoot — one parallel spike you hold, then merge or bin

An offshoot is a single idea run in its OWN session, off to the side of the main work, that you look at
then keep or throw away. It is NOT hyperspeed: hyperspeed DIVIDES a task across 3-5+ sessions and
ASSEMBLES them the moment they finish. An offshoot is ONE session and DOES NOT auto-merge — the point
is that you decide, after eyeballing it, whether it lives.

## When to use it — and when not

DO reach for it when Simon says "spin this off / try it as an offshoot / branch off and I'll look later
/ I might discard it" — a self-contained "what if" he wants OUT of the main session's way and is willing
to bin.
DON'T use it for a task that divides into 3-5+ independent slices — that is `/sk:work-hyperspeed`.
DON'T use it for work that must land — an offshoot's default fate is the bin, so a change Simon needs
merged goes through `/sk:work-full-detailed-workflow` on this branch, not here.

## Reuse the plumbing — only the finish differs

The START-commit, the single paste-and-forget block, and the shared-status POLL are the shared handoff
unit — `references/parallelization.md` § "The hand-run session handoff", run with exactly ONE part and
`<harness>` = `offshoot`; do not restate them. Two deltas for an offshoot:

- **The part is ONE, and it does not assemble.** Cut no partition — the whole idea is the single part.
  Its paste block still branches off START, writes `working`→`done` to the run's STATUS_DIR, and reports
  its branch plus the absolute path of anything viewable it produced (a screenshot set, a preview
  build), the way hyperspeed's standalone-artifact variant does.
- **Build it to a LOOKABLE state, not a merged one.** The part builds/runs far enough that Simon can
  eyeball the idea (a before/after, a screenshot, a running route), then STOPS. It opens no PR and the
  orchestrator does not merge it.

## Finish — HOLD, then merge or bin on Simon's word

When the status file reads `done`, do NOT assemble. Instead, per `references/human-pacing.md`:

1. **Surface it for the eyeball.** Fetch the branch, gather the reported artifact into this session's
   scratch, and SEND it to Simon (screenshots via SendUserFile, or the diff summary). One line: what it
   is, its branch name, that nothing is merged.
2. **WAIT for his verdict — never merge on your own.**
   TEST: after `done`, the offshoot branch is neither merged nor deleted until Simon gives an explicit
   merge-or-discard call.
3. **On "merge it":** `git fetch`, merge the offshoot branch into the working branch, run the project
   gate (build + tests), then offer cleanup as in hyperspeed's Step 6 (delete the branch local+remote
   after proving it merged; the part's worktree goes when Simon archives that session).
4. **On "bin it":** delete the offshoot branch (local + remote) and its worktree WITHOUT merging —
   confirm the exact list first (`references/git-pr-deploy.md` § deleting a branch), then remove. A
   discarded offshoot leaves no branch, no worktree, no status dir behind.

Hold indefinitely if he says neither — an offshoot has no deadline; it waits until he returns to it.
