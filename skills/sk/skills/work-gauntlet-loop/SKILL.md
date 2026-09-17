---
name: work-gauntlet-loop
description: Maintain every session's gauntlet record and continue all requested work to verified completion, including requirements added mid-conversation. Use for "gauntlet loop", "don't forget any requests", "keep going after tangents", "independent judge", or "live progress dashboard". Reuse the one living plan and its unfinished queue. Configure Ralph or independent judgement when requested; otherwise use current-session execution without an options interview. Resume a handed-off gauntlet from a pasted dashboard link with its recorded options.
argument-hint: "[goal | --resume plan-path | --resume <dashboard link>] [--engine current|ralph] [--judge on|off] [--max-iterations N] [--references images|names|none] [--inspiration platform names]"
---

# Gauntlet loop

DO read `~/.claude/references/workflow-loops.md` and run its shared lifecycle, including Handoff and resume.
DO detect a handoff FIRST: when `--resume` gets a dashboard link/HTML/plan (or a bare pasted link),
run `workflow-dashboard.py resolve --target`, resume the recorded engine from its `PLAN_PATH`, and
retain its recorded options without a second interview. Hand off with
`/sk:work-handoff-prepare-and-pickup` when this session runs low.
DO apply Continuous request reconciliation on every turn, including mid-run additions and handoff.
Default to current-session execution with the independent judge off. Ask for run options only when
Ralph, independent judgement or custom loop options are requested; reuse already recorded answers.
DO reuse the living plan; compose `/sk:plan-stable-persistent-dynamic-complete-full-plan` only when
one is needed, and `/sk:ship-mockup-before-after` for visual targets. Preserve existing authorization.
DO dispatch the selected engine within existing authorization and any required target approval:
- `current` → `/sk:work-full-detailed-workflow`.
- `ralph` → `/sk:work-ralph-loop`, passing the same plan and already confirmed options.
DO retain supervisor ownership of the shared plan, dashboard and any enabled independent judge.
Run the shared judge stage after each build result and route its gaps back to the selected engine.
TEST: both engines keep the same plan and viewer; selecting Ralph starts no second options interview.
