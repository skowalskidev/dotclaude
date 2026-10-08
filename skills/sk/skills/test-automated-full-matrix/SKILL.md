---
name: test-automated-full-matrix
description: Exhaustively test a finished diff or PR AUTONOMOUSLY — no human in the loop, safe to leave running overnight. Enumerates every feature the diff added (git diff + the plan's acceptance criteria + the Linear tickets), then holds each to TWO stages: Stage 1 traditional deterministic tests (unit/integration/e2e, happy path AND all edge cases, writing the missing ones), and Stage 2 Claude-as-judge reasoning (reads the real inputs/outputs + trajectory, judges against the feature's intent + acceptance criteria and whether a user would find it sensible — even when Stage 1 is green). Produces a coverage+judgment MATRIX, saves it, and posts it to the PR's tests section. The SSOT home for automated full testing: /sk:test-copilot's machine pass, /sk:ship-full-detailed-workflow and /sk:work-full-detailed-workflow all run it rather than restating it. Fans out in parallel for scale. Use for "run the full automated test matrix", "test this diff/PR exhaustively", "test X overnight unattended", "automated coverage + judge posted to the PR".
argument-hint: "[PR number / branch / diff to test]"
---

# The full automated test matrix — autonomous, two-stage

Run this on a finished diff or PR to assess EVERY feature it added, with an evidence-backed verdict,
UNATTENDED. It runs autonomously: no AskUserQuestion, no pacing, no human step, so it is safe to leave
on a diff overnight. It is DISTINCT from `/sk:test-copilot` (the human-driven journey); co-pilot runs
THIS for its machine pass, then adds the human judgment on top.

**Read `~/.claude/references/testing-strategy.md` § The full automated test matrix, § Defects first
and § Native simulator suites.** Apply their batch timing, evidence reuse and native opt-in to this flow.
TEST: invoking this skill alone does not authorize native runtime/UI tests or screenshot capture.

## Run it

1. **Enumerate the work-list.** `git diff <base>...HEAD` cross-referenced with the plan's acceptance
   criteria (`/sk:plan-stable-persistent-dynamic-complete-full-plan`) and the Linear tickets — one
   matrix row per feature (feature · layer · Stage-1 test · Stage-2 judgment · verdict). A feature with
   no row is a hole.
2. **Fan preparation and judgments out per feature** (`~/.claude/references/parallelization.md`):
   `/sk:work-hyperspeed` at 3-5+ disjoint slices, else an in-session Workflow under the concurrency cap.
   Each slice prepares Stage-1 tests, writes missing regressions, and completes Stage-2 judgment against
   code, test design and available evidence. Land review fixes before execution; do not run a suite per row.
3. **Run the final batch gate once.** The coordinator deduplicates suites across all rows, reuses matching
   passing evidence and runs uncovered relevant checks. Attach results to the matrix; a later workflow
   stage consumes them without rerunning unchanged coverage. Fix failures and rerun affected checks.
4. **Assemble the matrix, save + post.** Save it under the run's `.context/`; POST it to the PR's tests
   section GitHub-native, on `/sk:ship-screenshot-changes` Step 5's posting rails.
5. **Autonomous to the end.** No human step. Mark unreachable rendered interactions NEEDS-DRIVING and
   hand them to `/sk:test-copilot`; mark unrequested native runtime/UI cases SKIPPED with the reason.
   Report COVERED, GAP, NEEDS-DRIVING and SKIPPED counts and evidence. Never call unrun coverage green.

Extra context for this run (if any): $ARGUMENTS
