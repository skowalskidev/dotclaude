---
name: work-consolidate-supersede-branches-prs
description: Consolidate several branches (and their PRs, if any) plus the latest base into ONE new branch that supersedes them all — merge each onto the others so every branch's changes propagate BOTH ways, reverse-merge the current base the same way, resolve every conflict for behaviour, build any additional asks on top, and hand it back as a superseding draft PR (or a bare branch) that closes the originals. Never touches master/the base; leaves the new PR draft. Use for "consolidate these branches/PRs into one", "supersede #A and #B with one branch", "merge these branches onto each other and master", "combine these PRs and build X on top", "make one draft PR that replaces these", or "propagate these branches' changes onto each other then reverse-merge master".
---

# Consolidate + supersede several branches/PRs into one

The task shape: N branches (each maybe carrying an open PR) overlap, plus extra feature asks, and become
ONE new branch that supersedes them all. Every branch's changes must survive onto every other (both ways),
the base is brought current (reverse-merge master/the base), the extra asks are built on top, and it ships
back as a draft PR — or a bare branch when no PR is wanted — that closes the originals. The base is never
touched.

This is a SPINE. It composes the parts below at each stage — invoke each, never restate it:
`/sk:plan-stable-persistent-dynamic-complete-full-plan`, `/sk:ship-check-merge-readiness`,
`/sk:work-full-detailed-workflow`, `/sk:ship-full-detailed-workflow`,
`/sk:meta-dotclaude-copilot-start-here-for-any-task`. Read `references/parallelization.md` for the fan-out
craft and `references/git-pr-deploy.md` for the branch/PR/deploy rules.

## Step 0 — Establish the inputs, confirm the two forks, never touch the base

- **List every input** — each branch's head ref, its PR if one exists (`gh pr view` for the ticket list +
  body), the additional feature asks, and the base (`git rev-parse origin/master`).
- **Confirm the two forks that waste the most work if guessed, in ONE AskUserQuestion up front:** the merge
  TOPOLOGY (a NEW branch off one head with the rest merged in), and whether to CLOSE the superseded PRs.
- **NEVER merge, push, or write the base.** The new branch is the only ref you push, and only when a
  PR/push is actually asked for. Any new PR stays DRAFT until the human flips it.

## Step 1 — Research before the merge (the run is won or lost here)

Before touching a file, fan out a READ-ONLY research pass (parallel agents, `references/parallelization.md`)
and fold it into the living plan:

- **Find each ask's real SPEC.** For one phrased "as per the tickets/comments", search the tracker's
  DESCRIPTIONS AND COMMENTS plus the PR review comments — a feature's real definition often lives in a
  comment, not the ticket body (the fix for a "make X continuous" ask whose meaning was only in the PR
  discussion). Cite every load-bearing claim to a source.
- **Map the conflicts** (which files overlap, what each side changed per critical/money file) and the
  implementation + inventory map for each ask (the components/functions/tests it touches, what moves).

TEST: the plan states each ask's spec with a cited source, and the per-file conflict resolution, before any
edit.

## Step 2 — Merge on GIT GROUND TRUTH, then verify the auto-merges SEMANTICALLY

- **Branch off one head, then TRIAL-merge each other branch** (`git merge --no-commit --no-ff <ref>`) to
  read the ACTUAL conflict set, and `--abort`. Trust git's set over any predicted overlap (a predicted
  21-file overlap was 3 real conflicts).
- **Resolve each conflict by TYPE:** an import block → union and dedup; two disjoint additive test suites
  that share a trailing brace → keep BOTH and reconcile the braces; a semantic clash (two features editing
  one function) → keep BOTH intents, or when they genuinely conflict take the NEWER/canonical side and FLAG
  the decision.
- **Find the ONE dangerous conflict.** Most are mechanical; the run-ender is the side-pick that silently
  reverts a fix the other side shipped (e.g. a delete-based teardown vs a write-based one — the stale side
  re-leaks what the other fixed). Get that one right and flag it.
- **Auto-merge ≠ verified.** Git cleanly combines two individually-fine changes that together break — one
  branch's copy plus the other's "does the copy state the deadline" flag left a reminder claiming a deadline
  the copy never gave. After merging: build the shared packages, typecheck, run the AFFECTED package's
  suites, and grep for the files both branches edited in the SAME function and read those. A marker-free
  merge that compiles is not a verified merge.
- **Reverse-merge the current base the SAME way** (trial → resolve → verify). Gate each merge in order:
  shared-package build → app typechecks → all unit suites green → commit. Watch a cross-cutting rename for
  stragglers a clean auto-merge left behind.

## Step 3 — Build the extra asks (central-file surgery serial, the rest fanned out)

- **Run `/sk:work-full-detailed-workflow` per ask.** Fan the INDEPENDENT pieces (a backend payload, a new
  component, a deletion, a dead-code sweep) out to in-session agents; do the surgery on any CENTRAL file
  every ask touches SERIALLY yourself — never two agents editing one central file at once.
- **Verify ON DISK after every agent batch** (typecheck + the affected suite); never trust a self-report.
  Commit each ask as its own logical unit once green.
- **When MOVING components** (e.g. old sections behind a new admin tab), preserve every fallback the old
  placement served — a component that double-duties as the ONLY surface for one user class must not leave
  that class with an empty screen. Flag the fallback call.

## Step 4 — Clear the inherited dead code to 0

A consolidation inherits whatever dead code each merged branch introduced, and a mergeable-to-base PR needs
the full-repo dead-code scan at 0. Run it and resolve each finding: delete-if-truly-dead,
export-the-leaked-type, suppress-with-justification for a namespace-reached export the scanner can't
resolve, or FLAG (don't delete) a real-but-unwired feature. A suppression carries its reason on a plain
`//` line directly ABOVE a BARE directive, never trailing text on the directive line.

## Step 5 — Ship it as a superseding draft PR (or a bare branch)

- **Run `/sk:ship-full-detailed-workflow`** (it runs `/sk:ship-report-and-ensure-correct-user-system-journey`
  — reconcile every ask to a verdict + committed-test evidence). Run the FINAL full gate ONCE (all suites +
  typechecks + the static gate + the baseline-ratchet guard); verify per-phase as you go, but BATCH the
  final gate rather than re-running everything each turn.
- **Push the new branch only when a PR/push is asked for** — "create a PR" IS that authorization, otherwise
  stay commit-only.
- **Create the DRAFT PR with a Deploy-TLDR-first body** (`/sk:ship-pr`): the cross-repo order, build
  prerequisites, deploy commands INCLUDING what the deploy REMOVES (a dropped scheduled job/function),
  index-before-functions, and the post-deploy smoke. Link only the tickets this PR actually delivers.
- **CLOSE each superseded PR with a comment linking the new one**; a bare superseded branch with no PR is
  noted in the plan and deleted only once merged (`references/git-pr-deploy.md`). Leave the new PR draft —
  the human flips ready, requests review, and deploys.

## Rules

- **Run to completion; keep the living plan current at every phase; at hand-back reconcile every ask → a
  verdict + test evidence.** A phase boundary is a commit, not a stopping point.
- **Flag every decision you made, don't bury it.** A conflict side taken, a copy chosen, a component
  deleted, a fallback preserved — each lands in the PR body AND the plan as an explicit line the human can
  override, never a silent pick.
- **Batch verification; don't stall on it.** Verify at phase boundaries and once at the end; a turn that
  only awaits a background suite it already launched, adding nothing, is wasted — kick off the gate, keep
  building or drafting the PR while it runs.
- **A run triggers self-healing** (`rules/self-healing-config.md`): fold any new pitfall this run surfaced
  back into this skill via `/sk:claude-config-update` before handing back.
