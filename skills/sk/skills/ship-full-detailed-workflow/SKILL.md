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
   rest.
3. **`/sk:ship-report-and-ensure-correct-user-system-journey`** — the spine. Verify the user + system
   journeys AND every ticket's acceptance criteria against the merged diff, one committed test per
   verdict, close gaps in fix→verify loops. The exhaustive automated coverage + Claude-judge over the
   WHOLE diff is `/sk:test-automated-full-matrix` (run it here — it enumerates every feature, writes the
   missing tests over happy path + edges, judges intent + UX, and saves + posts the matrix to the PR);
   ship-report's per-ticket verdicts read that matrix rather than re-deriving coverage. When it splits
   into 3-5+ independent tickets, fan the
   per-ticket verification out — one adversarial verifier per ticket reading the real code against its
   criteria — via a Workflow or `/sk:work-superspeed` / `/sk:work-hyperspeed`
   (`references/parallelization.md`).
4. **`/sk:ship-review`** — over the whole diff; fix the confirmed findings.
5. **`/security-review`** (Claude Code built-in) — when the diff touches auth, tenant isolation, money, a
   dial or allowlist relaxation, or an injection surface.
6. **`/sk:ship-resolve-pr-comments`** — drive EVERY open review thread to a verdict; never hand back a
   list to chase.
7. **`/sk:ship-screenshot-changes`** — when the diff changes a frontend surface: capture each changed
   surface AND post them onto the PR (opt-in, GitHub-native). Plan the post from the start of the
   sweep, not as an end-of-run afterthought.
8. **`/sk:ship-pr`** — the PR body carries the Deploy-TLDR.
9. **Finish.** Reconcile the plan (every ticket → a verdict + a test), DRY/SSOT-sweep the diff (one
   owner per shared value or behaviour), tear down with `/sk:meta-cleanup-worktrees`, commit-when-done,
   hand back a per-ticket verdict report.

**Conditional legs — fire when the PR calls for them, not by default:**
- `/sk:test-eyeball` — hammer the changed UI in a real browser (stage 3's journey leg, autonomous).
- `/sk:test-copilot` — a human-driven UI test; opt-in, because `process.md` says ask before a browser.
- `/sk:work-isolate-environment` — a port lane when a stage boots a server.

**Kept out, so the sweep stays PR-shaped:** building (`/sk:work-full-detailed-workflow` and the
design/POC skills) and whole-repo passes (`/sk:maintenance-code-cleanup-repo`) — stage 9's DRY sweep is
diff-scoped.

Extra ship context for this run (if any): $ARGUMENTS
