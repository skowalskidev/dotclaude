---
name: ship-full-detailed-workflow
description: Simon's full SHIP harness — drive a FINISHED PR or branch through the whole verify-and-ship sweep: assemble onto master, verify every ticket's acceptance criteria and the user + system journeys across the whole diff with a test per verdict, multi-model + security review, resolve every review thread, screenshot the UI, meet the Deploy-TLDR standard, then reconcile and hand back. The counterpart to /sk:work-full-detailed-workflow, which builds; this proves and lands what is already built. Apply when a PR or branch is finished and the job is to cover the whole diff, all its tickets, and ship it. Thin index — points to the owning skills.
argument-hint: "[PR number / branch / what to ship]"
---

# Simon's Ship Harness

Run this on a FINISHED PR or branch to prove it covers every ticket and the whole diff, then land it.
The counterpart to `/sk:work-full-detailed-workflow`: that one builds; this one ships what is built. Each
stage's owning skill is the single source of truth — invoke it at its stage, do not restate it here.

The always-on `~/.claude/rules/*.md` apply throughout: `process.md` (run-to-completion,
commit-when-done, track-every-task, ask before booting a browser), `living-plan.md`,
`engineering-standards.md`, `security.md`.

**Safe to run on several branches at once.** Each run writes ONLY its own branch and its own PR +
tickets; a fix that belongs to another PR is handed to that owner via
`/sk:ship-check-merge-readiness`'s cross-owner discipline, never applied across branches.

**The stages, in order:**

0. **Establish state, then sync the branch.** The PR number, branch, worktree, base, draft flag,
   behind/ahead master; the authoritative ticket list from the PR body; the full diff surface
   (`git diff <base>...HEAD`). PUSH the PR's own branch to origin so it is current — CI, the review,
   and merge-readiness all read the pushed state. NEVER push, merge into, or otherwise write master.
1. **`/sk:plan-stable-persistent-dynamic-complete-full-plan`** — fold every ticket and criterion into
   the living plan; reconcile against it at stage 9.
2. **`/sk:ship-check-merge-readiness`** — assemble onto CURRENT master; own this PR's scope, track the
   rest. Defer automated verification to stage 6 after the whole authorized batch and review fixes converge.
3. **`/sk:ship-review`** — over the whole diff, with stage 6's criterion judges in the same fan-out; fix the confirmed findings.
4. **`/security-review`** (Claude Code built-in) — when the diff touches auth, tenant isolation, money, a
   dial or allowlist relaxation, or an injection surface.
5. **`/sk:ship-resolve-pr-comments`** — drive EVERY open review thread to a verdict; never hand back a
   list to chase.
6. **`/sk:ship-report-and-ensure-correct-user-system-journey`** — the spine, run ONCE on the reviewed and fixed code (stages 3-5 find and fix defects first, per `rules/process.md` § Fan out verification); re-judge criteria whose evidence or inputs those fixes changed, including dependent readers and configuration. Verify the user + system
   journeys AND every ticket's acceptance criteria against the merged diff, one committed test per
   verdict, close gaps in fix→verify loops.
   When it splits into 3-5+ independent tickets, fan the per-ticket verification out — one adversarial verifier per ticket reading the real code against its
   criteria — via a Workflow or `/sk:work-superspeed` / `/sk:work-hyperspeed`
   (`references/parallelization.md`).
   **DO invoke `/sk:test-automated-full-matrix` AND `/sk:ship-verify-with-prod-data` on EVERY PR in the
   run, multi-PR and multi-repo included, as real skill invocations dispatched per PR as parallel
   background agents on that same fan-out.** They never block: every stage that reads neither result
   proceeds, ship-report reads the matrix for its per-ticket verdicts (including each feature's
   simulation applicability and evidence), data-surface screenshots wait on the prod-data data mode,
   and the landing gate waits on both. Prod-data's own Phase 1 rules out a diff with no data-shaped
   output; its doesn't-apply verdict with the named reason is the recorded result.
   **DON'T substitute ad-hoc suites or one-off queries for either skill, or skip prod-data because the
   diff looks data-free.** TEST: every PR in the run shows both skills' verdicts at the landing gate.
   (the fix for a run that substituted ad-hoc suites and one-off read-only queries for both skills
   across three PRs; run properly, the matrix found four real gaps and the data check found a
   per-person cross-repo reconciliation.)
   **DO run `references/git-pr-deploy.md` § Deploy safety on EVERY PR in the run, unprompted, as a
   parallel background agent on that same fan-out.** It never blocks; stage 8's Deploy TLDR and the
   landing gate wait on it. A merge-train conflict, red suite or unsafe migration is a finding fixed
   before hand-back.
   **DON'T treat each PR's green CI as proof the set merges and deploys safely.** TEST: every PR in
   the run shows the merge-train result, migration verdict and cutover table at the landing gate
   without Simon asking.
7. **`/sk:ship-screenshot-changes`** — capture changed web surfaces and explicitly requested native
   surfaces under `references/testing-strategy.md` § Native simulator suites. Post captured images and
   journey videos onto the open PR (GitHub-native); plan the post from the start of the sweep.
8. **`/sk:ship-pr`** — the PR body carries the Deploy-TLDR.
9. **Finish.** Reconcile the plan (every ticket → a verdict + a test), DRY/SSOT-sweep the diff (one
   owner per shared value or behaviour), tear down with `/sk:meta-cleanup-worktrees`, commit-when-done,
   hand back a per-ticket verdict report. A gap any stage found inside this PR's own scope is BUILT
   here, not ticketed: `/sk:ship-check-merge-readiness` Step 6 owns the three cases a ticket is for.

**Running the stages on a multi-layer PR:** fix rounds follow `references/parallelization.md` §
"Parallelize verification, not just agents": the contract page first, every layer in one batch, the
final gate by the orchestrator under the verification policy above, native work through `bin/native-slot.sh`.

**Landing gate — a stage that RAN but didn't LAND its artifact is not done.** Before stage 9 reconciles,
fetch EVERY pushed PR in the run (`gh pr view <n> --json body,comments` plus the `reviewThreads` GraphQL query) and
confirm each stage's OUTPUT is ON it, not just produced in-session. An artifact that lives only in chat, a
scratch file, or a green local run is INCOMPLETE — return to its stage and post it. TEST: every row below
reads ✓ against the FETCHED PR, never against memory of having run the stage. (the fix for a run that
verified the user + system journey, then handed back with it never posted to the PR body.)
- Journey (stage 6): `## User journey` and `## System journey` are in the PR body.
- Matrix (stage 6), on every PR: the results table with its COVERED, GAP, NEEDS-DRIVING and SKIPPED
  counts, each feature's simulation evidence or concrete N/A reason, and explicit verdicts for required
  cases that did not run.
- Prod data (stage 6), on every PR: the per-account reconciliation result, or the prod-data skill's
  doesn't-apply verdict with its named reason.
- Deploy safety (stage 6), on every PR: the merge-train result (PR order, default-branch sha, suites,
  pass), the migration-safety verdict and the cutover/rollback table, or a named doesn't-apply reason
  per part.
- Screenshots (stage 7): every surface eligible under stage 7 has its image and journey video on the PR; record native
  surfaces without explicit opt-in as not run, and identify a diff with no eligible frontend surface.
- Threads (stage 5): 0 unresolved review threads.
- Deploy-TLDR (stage 8): the PR body opens with it, each production step carrying its check, smoke
  and rollback.
Post to the body with a targeted fetch-edit-verify replace, never a reconstructed body; a fetch returning
empty or suspiciously short → STOP.

**Conditional legs — fire when the PR calls for them, not by default:**
- `/sk:test-eyeball` — hammer the changed UI in a real browser (stage 6's journey leg, autonomous).
- `/sk:test-copilot` — a human-driven UI test; opt-in, because `process.md` says ask before a browser.
- `/sk:work-isolate-environment` — a port lane when a stage boots a server.

**Kept out, so the sweep stays PR-shaped:** building (`/sk:work-full-detailed-workflow` and the
design/POC skills) and whole-repo passes (`/sk:maintenance-code-cleanup-repo`) — stage 9's DRY sweep is
diff-scoped.

Extra ship context for this run (if any): $ARGUMENTS
