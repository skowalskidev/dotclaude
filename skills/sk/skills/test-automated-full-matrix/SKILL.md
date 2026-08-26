---
name: test-automated-full-matrix
description: Exhaustively test a finished diff or PR AUTONOMOUSLY — no human in the loop, safe to leave running overnight. Enumerates every feature the diff added (git diff + the plan's acceptance criteria + the Linear tickets), then holds each to TWO stages: Stage 1 traditional deterministic tests (unit/integration/e2e, happy path AND all edge cases, writing the missing ones), and Stage 2 Claude-as-judge reasoning (reads the real inputs/outputs + trajectory, judges against the feature's intent + acceptance criteria and whether a user would find it sensible — even when Stage 1 is green). Produces a coverage+judgment MATRIX, saves it, and posts it to the PR's tests section. The SSOT home for automated full testing: /sk:test-copilot's machine pass, /sk:ship-full-detailed-workflow and /sk:work-full-detailed-workflow all run it rather than restating it. Fans out in parallel for scale. Use for "run the full automated test matrix", "test this diff/PR exhaustively", "test X overnight unattended", "automated coverage + judge posted to the PR".
argument-hint: "[PR number / branch / diff to test]"
---

# The full automated test matrix — autonomous, two-stage

Run this on a finished diff or PR to prove EVERY feature it added is covered — exhaustively and
UNATTENDED. It runs autonomously: no AskUserQuestion, no pacing, no human step, so it is safe to leave
on a diff overnight. It is DISTINCT from `/sk:test-copilot` (the human-driven journey); co-pilot runs
THIS for its machine pass, then adds the human judgment on top.

**The method is `~/.claude/references/testing-strategy.md` § "The full automated test matrix" — read it,
do not restate it here.** It owns the feature enumeration, the two stages (deterministic +
Claude-as-judge), the exhaustiveness, the hyperspeed fan-out, and the save+post-to-PR format. This SKILL
is the flow that runs it, and the SSOT other skills point at.

## Run it

1. **Enumerate the work-list.** `git diff <base>...HEAD` cross-referenced with the plan's acceptance
   criteria (`/sk:plan-stable-persistent-dynamic-complete-full-plan`) and the Linear tickets — one
   matrix row per feature (feature · layer · Stage-1 test · Stage-2 judgment · verdict). A feature with
   no row is a hole.
2. **Fan the two stages out per feature** (`~/.claude/references/parallelization.md`): `/sk:work-hyperspeed`
   at 3-5+ disjoint slices, else an in-session Workflow under the concurrency cap. Each slice runs Stage
   1 (deterministic — WRITE the missing test where a feature has none) then Stage 2 (Claude-as-judge,
   several independent lenses, defaulting a lens to "fails" when unsure).
3. **Assemble the matrix, save + post.** Save it under the run's `.context/`; POST it to the PR's tests
   section GitHub-native, on `/sk:ship-screenshot-changes` Step 5's posting rails.
4. **Autonomous to the end.** No human step. A rendered frontend interaction a unit test structurally
   cannot reach is marked NEEDS-DRIVING and handed to `/sk:test-copilot`, never faked green. Report the
   matrix and the verdict: every feature COVERED, or the list of GAPs (missing tests) and NEEDS-DRIVING.

Extra context for this run (if any): $ARGUMENTS
