# Every session is a gauntlet session

`.context/<slug>-plan.md` is the ONE gauntlet file and task record; derive its dashboard. A delegated
worker (`AGENT_DELEGATED_WORKER=1`) writes none of it and returns results.

**DO run `python3 ~/.claude/bin/workflow-dashboard.py init --root .` on the first task-bearing
prompt, then fill its skeleton from the actual request and existing authorization.**
On EVERY user message, hook or skill or neither, read the plan and record new asks and decisions
first. Preserve unfinished work. Apply `references/workflow-loops.md` § Continuous request reconciliation.
Default to current execution, judge off, without re-locking authorized work.
Refresh the dashboard after every transition across ALL workstreams. Absorb per-task plans into it.

Details: `references/planning-and-tracking.md`, `rules/process.md`.

TEST: every actionable ask maps to a persistent item and outcome; zero asks disappear after a tangent,
restart or compaction. At any check-in, one active plan and dashboard `updatedAt` ≥ the latest transition.
