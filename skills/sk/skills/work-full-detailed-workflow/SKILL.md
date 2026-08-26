---
name: work-full-detailed-workflow
description: Simon's full detailed working harness — plan-first with tickets, verify foundation assumptions empirically before building, tests-first as a tree, parallel sub-agents with tracked progress, observability, UX standards, scope discipline, PR/deploy hygiene. Apply to any substantive or multi-step task (feature, integration, refactor, or adopting someone else's work). Thin index — it points to the shared reference catalogs in ~/.claude/references/ that hold the detail.
argument-hint: "[optional task context]"
---

# Simon's Working Harness

For any substantial or multi-step task, apply the shared reference catalogs below. They are the SINGLE
SOURCE OF TRUTH — the same catalogs CLAUDE.md and the other skills point to, so nothing is duplicated.
Read each catalog when its stage is in play:

- **Research** → `~/.claude/references/research.md` — open the run with it: what already solves this,
  what changed since training, what the people who did it hit. Never from memory.
- **Contracts** → `~/.claude/references/contracts-and-outcomes.md` — find out whether the project
  declares what each unit produces, and keep those criteria true. A green suite does not prove it.
- **Plan & track** → `~/.claude/references/planning-and-tracking.md` — plan first (user-journey TLDR +
  tracker + questions consolidated, re-checked against the original tickets so nothing drops), verify
  foundation pillars before building (real code + online + an empirical spike), a DYNAMIC checklist
  that absorbs emergent work and tracks every ask to completion — committed stage by stage as a
  resumable checkpoint so a quota/usage cut-off costs one stage, not the run — and the worktree's
  `.context/intent-ledger.md` — the hook records every ask verbatim; you record the sources, the plan
  he ratified, each pivot, and the closing reconciliation of asked against built.
- **Parallelize & delegate** → `~/.claude/references/parallelization.md` — fan out across tasks AND
  stages, orchestrate-strong / implement-with-Sonnet-4.6 (`claude-sonnet-4-6`), explicit DO-NOT-TOUCH lists, verify on disk, review
  the delegated diff.
- **Test** → `~/.claude/references/testing-strategy.md` — tests first, structured as a tree
  (unit → integration → e2e), gated "needs-resources" suites; the exhaustive full-diff automated
  matrix (Stage-1 deterministic + Stage-2 Claude-judge, saved + posted to the PR) is
  `/sk:test-automated-full-matrix`, run at stage 4.
- **Dev server & lanes** → `~/.claude/references/dev-server-hygiene.md` — take a LANE before binding a
  port (`bin/port-slot.sh`, or `/sk:work-isolate-environment` to wire a project up), identity-handshake
  the server before trusting a log line, process-group teardown. Several sessions run at once, so
  "something answered on :3000" is not "my server is up".
- **Code quality** → `~/.claude/references/code-best-practices.md` — DRY/SRP, reuse before building,
  observability/failure handling, UX standards (skeletons, optimistic, no dead ends), scope discipline.
- **Git / PR / deploy** → `~/.claude/references/git-pr-deploy.md` — rebase the default branch first, fix
  all PR comments, build+verify, draft PR + teardown, deploy-step tracking.
- **Real-API iteration** → `~/.claude/references/api-empirical-iteration.md` — drive the project's own
  harness with real calls, project-scoped keys, ask-first for billable calls, freeze wins as gated tests.
- **Report at the end** → `~/.claude/references/tldr-report-formats.md` — the user journey, the system
  journey and what changed on this branch, cross-checked for mismatches. `/sk:ship-report-and-ensure-correct-user-system-journey` assembles it, then checks it against the plan's criteria and closes the gaps.

Always-on rules in your `~/.claude/rules/*.md` (auto-loaded) also apply and are NOT repeated here: copy
quality / anti-AI-copy, response & TLDR format, the security guard, versions, data-archive, UI conventions,
the living plan as the rail (`rules/living-plan.md`) — read `.context/<slug>-plan.md` first, keep it
current, reconcile against it.

**Top-view game plan for any run:**
1. **Research first** (`references/research.md`) — always, before planning. Simon should never have to
   ask for it separately.
2. **Open the plan with the user-journey TLDR** — the steps the user takes, what they see, and the
   assumptions it rests on — then the tracker and the detail. Get sign-off on big or risky work, and
   write the plan he ratified into `.context/intent-ledger.md` with its sources, plus every later
   pivot as it lands. The hook already records his asks; what it cannot record is which plan he said
   yes to. **With no ticket the prompt IS the plan**: derive it, record the source as
   `prompt-derived`, and his approval is the ratification. That is the common case, not the edge one.
3. Verify the foundation assumptions (read the real code, check online, run an empirical spike) — and
   read the project's contracts before changing any unit that has one.
4. Tests first, tree-structured — the exhaustive full-diff coverage runs via `/sk:test-automated-full-matrix` (Stage-1 deterministic + Stage-2 Claude-judge, saved + posted).
5. Implement — parallel where independent, delegate edits to Sonnet 4.6 (`claude-sonnet-4-6`), verify on disk after each batch.
6. Observability + failure handling; never fail silently, no dead-end states.
7. Build/verify with the project's commands, draft PR, tear down scratch, track deploy steps.
8. Watch the deploy through and loop on what it surfaces; shipping is not done when the merge lands.
9. **Close with the end report** (`/sk:ship-report-and-ensure-correct-user-system-journey`) — the user journey, the system
   journey, the mismatches between them, and what changed on this branch. It then judges those
   journeys against the criteria this plan validated, backs each verdict with a test it writes and
   commits, closes any gap in code, and reconciles the ledger's asks against what was built, so
   step 2's plan and the shipped result are the same thing. Simon should never have to ask for it.

Extra task context for this run (if any): $ARGUMENTS
