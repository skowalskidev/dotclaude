---
name: work-ralph-loop
description: Run a Ralph loop to complete unfinished plan items with one fresh worker per item and no loose ends. Use for "ralph loop", "fresh worker per task", or "finish every plan item". Works alone or as the execution engine selected by Gauntlet. Reuse the permanent plan and live dashboard, verify each outcome, persist learnings, and resume from a checkpoint without losing evidence.
argument-hint: "[goal | --resume plan-path] [--judge on|off] [--max-iterations N] [--references images|names|none] [--inspiration platform names]"
---

# Ralph loop

DO read `~/.claude/references/workflow-loops.md` and run its Ralph execution stage.
DO use `engine=ralph`. On direct invocation, run the shared upfront options interview with that
engine fixed; recommend the judge off, and record the user's answer before dispatch.
When composed by a supervisor with confirmed options, reuse its plan and answer; do not ask again,
reset the iteration budget, create a second supervisor, or start another viewer.
DO reuse the living plan; compose `/sk:plan-stable-persistent-dynamic-complete-full-plan` only when
one is needed, and `/sk:ship-mockup-before-after` only when a visual target is required.
DO give one ready unfinished section to each fresh worker, verify its result, persist learnings and
continue under the shared checkpoint/completion rules. Return each result to the composing supervisor
for its enabled judge; on direct invocation own that shared judge stage when the user enables it.
TEST: direct and composed runs use identical worker mechanics and one plan, with one options answer
and one budget per invocation. A checkpoint or missing fresh-agent capability never counts as done.
