---
name: work-gauntlet-loop
description: Run a gauntlet loop with an independent judge and a live progress dashboard. Use for "gauntlet loop", "independent judge", or "live progress dashboard". Ask upfront whether to use the existing workflow or the Ralph execution skill, then record the run options and display them read-only. Judge implementation against supplied references or an AI-drafted target approved by the user, with no loose ends.
argument-hint: "[goal | --resume plan-path] [--engine current|ralph] [--judge on|off] [--max-iterations N] [--references images|names|none] [--inspiration platform names]"
---

# Gauntlet loop

DO read `~/.claude/references/workflow-loops.md` and run its shared lifecycle.
DO ask for the run options before dispatch. Recommend existing workflow with Gauntlet on; treat
fully specified invocation options as the answer. Show the recorded choices read-only in This run.
DO reuse the living plan; compose `/sk:plan-stable-persistent-dynamic-complete-full-plan` only when
one is needed, and `/sk:ship-mockup-before-after` for visual targets. Preserve existing authorization.
DO dispatch the selected engine after options and any required target approval are recorded:
- `current` → `/sk:work-full-detailed-workflow`.
- `ralph` → `/sk:work-ralph-loop`, passing the same plan and already confirmed options.
DO retain supervisor ownership of the shared plan, dashboard and any enabled independent judge.
Run the shared judge stage after each build result and route its gaps back to the selected engine.
TEST: both engines keep the same plan and viewer; selecting Ralph starts no second options interview.
