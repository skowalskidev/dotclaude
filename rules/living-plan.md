# Living plan and dashboard — the rail for every task

`.context/<slug>-plan.md` is the ONE task record; derive its dashboard.

**DO run `python3 "$HOME/.claude/bin/workflow-dashboard.py" init --root .` on the first task-bearing
prompt, then replace its skeleton via `/sk:plan-stable-persistent-dynamic-complete-full-plan`.**
Keep asks, sources, decisions, artifacts and pivots there; reconcile at hand-back.
Regenerate after every substantive transition. When asked, run
`python3 "$HOME/.claude/bin/workflow-dashboard.py" link` and return its clickable `DASHBOARD_PATH`.
Stop when more than one active plan exists.

Details belong in `references/planning-and-tracking.md`, `rules/process.md` and
`references/workflow-loops.md`. DON'T duplicate them here.

TEST: repeated intake leaves one active plan and dashboard; neither is stale at hand-back.
