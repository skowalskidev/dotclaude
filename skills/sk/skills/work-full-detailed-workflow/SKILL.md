---
name: work-full-detailed-workflow
description: Simon's one work harness for any task done with any skill — "do this", "build this feature", "gauntlet this" — merging the full detailed workflow and the gauntlet loop, then shipping. Plan-first with tickets, research, verify foundation assumptions empirically before building, tests-first as a tree, parallel sub-agents with tracked progress, observability, UX standards, scope discipline, PR/deploy hygiene; one living plan and live progress dashboard so you don't forget any requests and keep going after tangents, including requirements added mid-conversation; optional Ralph engine or independent judge; resume a handed-off run from a pasted dashboard link with its recorded options. Its final stage runs /sk:ship-full-detailed-workflow on every PR the work opened or pushed to, without being asked. Apply to any substantive or multi-step task (feature, integration, refactor, adopting someone else's work, "implement these designs", "build this design pixel-perfect"). Use for "gauntlet loop" or any work request. Thin index — it points to the shared reference catalogs in ~/.claude/references/ that hold the detail.
argument-hint: "[goal | --resume plan-path | --resume <dashboard link>] [--engine current|ralph] [--judge on|off] [--max-iterations N] [--references images|names|none] [--inspiration platform names]"
---

# Simon's work harness

One harness for every task that produces a change: the full detailed workflow's stages, the gauntlet's
session record, reconciliation, engines and judge, and the ship harness as the final stage.

DO run this as the spine of every task-bearing request, including one that names another skill or
arrives through `/sk:meta-dotclaude-copilot-start-here-for-any-task`: the named or routed skill runs as
a stage inside it. Scale each stage to the task; a stage with nothing to do gets an N/A and its reason
in the plan.
DON'T skip the session record, request reconciliation or stage 10 because the task looks small.
TEST: every task-bearing plan shows each stage with evidence or an N/A reason.

## Catalogs

The catalogs below are the SINGLE SOURCE OF TRUTH, the same ones CLAUDE.md and the other skills point
to. Read each when its stage is in play:

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
- **Session record, engines & judge** → `~/.claude/references/workflow-loops.md` — the one living plan
  and dashboard, continuous request reconciliation, run options, Ralph execution, the shared judge
  stage, handoff and resume, and the supplied-design-source intake.
- **Parallelize & delegate** → `~/.claude/references/parallelization.md` — fan out across tasks AND
  stages using the saved setup for every worker and reviewer. Verify on disk and review the delegated diff.
- **Test** → `~/.claude/references/testing-strategy.md` — plan coverage as a tree
  (unit → integration → e2e), gated "needs-resources" suites; the exhaustive full-diff automated
  matrix (Stage-1 deterministic + Stage-2 judge on the saved setup, saved + posted to the PR) is
  `/sk:test-automated-full-matrix`, run at stage 9 after implementation and review fixes converge.
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

## Session record, engines and judge

- DO detect a handoff FIRST: when `--resume` gets a dashboard link/HTML/plan (or a bare pasted link),
  run `workflow-dashboard.py resolve --target`, resume the recorded engine from its `PLAN_PATH`, and
  retain its recorded options without a second interview. Hand off with
  `/sk:work-handoff-prepare-and-pickup` when this session runs low.
- DO apply Continuous request reconciliation on every turn, including mid-run additions and handoff.
- DO default to current-session execution with the independent judge off. Ask for run options only
  when Ralph, independent judgement or custom loop options are requested; reuse recorded answers.
- DO reuse the living plan; compose `/sk:plan-stable-persistent-dynamic-complete-full-plan` only when
  one is needed, and `/sk:ship-mockup-before-after` for visual targets. Preserve existing authorization.
- DO dispatch the selected engine within existing authorization and any required target approval:
  `current` runs the stages below in this session; `ralph` runs `/sk:work-ralph-loop` with the same
  plan and confirmed options, and its results return here for stages 7-10.
- DO retain supervisor ownership of the plan, dashboard and any enabled independent judge. Run the
  shared judge stage after each build result and route its gaps back to the selected engine.
- DO run § Build from a supplied design source from intake whenever a design source is supplied, by
  anyone and in any format, or a pixel-perfect match is asked for. Hold each such section at `review`
  until its measurement report is PASS with its difference images and every exception named; a
  side-by-side read by eye never passes it, on either engine and with the judge off.
- DO run a design build's deliverables per `references/parallelization.md` § One isolated worker per
  deliverable: parallel isolated workers, on-disk checks, resumed fix rounds, recommended-option
  answers and a fresh code reviewer per PR. Take from the design-source section its committed capture
  harness, `bin/design-diff.py` panels and the PR evidence verified by `naturalWidth`. Run
  `local-capacity.py prioritize` only per `references/dev-server-hygiene.md`, and clear it after.
- TEST: both engines keep the same plan and viewer; selecting Ralph starts no second options interview.

## Top-view game plan for any run

1. **Research first** (`references/research.md`) — always, before planning. Simon should never have to
   ask for it separately.
2. **Open the plan with the user-journey TLDR** — the steps the user takes, what they see, and the
   assumptions it rests on — then the tracker and the detail. Get sign-off on big or risky work, and
   write the plan he ratified into `.context/intent-ledger.md` with its sources, plus every later
   pivot as it lands. The hook already records his asks; what it cannot record is which plan he said
   yes to. **With no ticket the prompt IS the plan**: derive it, record the source as
   `prompt-derived`, and his approval is the ratification. That is the common case, not the edge one.
3. Verify the foundation assumptions (read the real code, check online, run an empirical spike) — and
   read the project's contracts before changing any unit that has one. When the task supplies a design
   source, finish its intake here, before step 5 briefs a builder.
4. Plan tree-structured coverage and write needed tests; defer execution to step 9.
5. Implement the whole authorized task batch, including every feature, on the selected engine; delegate independent edits using the saved setup and inspect the returned diffs on disk.
6. Observability + failure handling; never fail silently, no dead-end states.
7. Review before the heavy gate: `/sk:ship-review` over the whole diff, with step 8's criterion judges in
   the same fan-out, and fix its confirmed findings.
8. **Prove the ask with the end report** (`/sk:ship-report-and-ensure-correct-user-system-journey`) — the user journey, the system
   journey, the mismatches between them, and what changed on this branch. It then judges those
   journeys against the criteria this plan validated, backs each verdict with a test it writes and
   commits, closes any gap in code, and reconciles the ledger's asks against what was built, so
   step 2's plan and the shipped result are the same thing. Simon should never have to ask for it.
   Its gap fixes land here; its hand-back follows step 9's pass.
9. Run the relevant suites, and the automated matrix on a Deep-tier change (`references/testing-strategy.md`
   § Size the checks to the change), on the converged code, using the timing, retry
   and evidence-reuse policy in `rules/process.md` § Fan out verification. Apply the testing reference
   sections Defects first and Native simulator suites. When the diff changes a stored-data figure or a
   gate that depends on stored data, run `/sk:ship-verify-with-prod-data` here, unprompted. TEST: such a
   hand-back cites its population and reconciled figures. Draft PR, tear down scratch, track deploy steps.
10. **Ship, unprompted — the final stage.** DO run `/sk:ship-full-detailed-workflow` on every PR this
    run opened or pushed to, before hand-back, without Simon asking. Hand it steps 7-9's evidence for
    the same head; it reruns only what later fixes changed. Record each PR's landing-gate result with
    `hooks/intent-ledger.sh gate`. With no PR opened or pushed, record this stage N/A with that reason.
    When another supervisor composes this skill per ask or slice, return the result and leave this
    stage to that supervisor, recorded as N/A naming it. Once Simon merges, watch the deploy through
    and loop on what it surfaces; shipping is not done when the merge lands.
    TEST: a hand-back naming a PR from this run cites its ship landing-gate result.

Extra task context for this run (if any): $ARGUMENTS
