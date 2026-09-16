# Living plan and dashboard — the rail for every task

`.context/<slug>-plan.md` is the ONE task record; derive its dashboard.

**DO run `python3 "$HOME/.claude/bin/workflow-dashboard.py" init --root .` on the first task-bearing
prompt, then replace its skeleton via `/sk:plan-stable-persistent-dynamic-complete-full-plan`.**
Keep asks, sources, decisions, artifacts and pivots there; reconcile at hand-back.
Regenerate after every transition (a ticket, PR, mediation round or preview each counts) so the ONE
dashboard tracks EVERY open workstream. One active plan; a gauntlet/per-task plan absorbs into it, not
a second island.

Details: `references/planning-and-tracking.md`, `rules/process.md`, `references/workflow-loops.md`.

TEST: at any check-in, one active plan and the dashboard `updatedAt` ≥ the latest transition; a stale
`file://` snapshot or a second plan is reconciled first.
