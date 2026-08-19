# Show progress — a bar the human can always read

Reference catalog entry — load on demand. Used by `/sk:meta-dotclaude-copilot-start-here-for-any-task`
and `/sk:work-hyperspeed`.

When a task runs across many steps, or waits on something, Simon must always see how far along he is
without asking. Show it; don't make him infer it.

**DO keep the harness Task list as the CANONICAL tracker** — one task per step via TaskCreate, marked
`in_progress` / `completed` as they change, so the native live checklist carries the state across turns
and a restart.

**DO echo a COMPACT text bar alongside it — each response, and each poll tick:** `▓▓▓▓░░░░ N/M · now: X`.
Fill one block per done step out of 8 total, then the count, then what is happening now.

**DO nest a sub-process's OWN bar under the main one** when a step runs its own multi-step work (a
sub-skill, a poll over N parts): `└ <sub> ▓▓░░ 2/4 · <sub-step>`. Then the human reads the overall
position AND the current sub-process's position in one glance.

**DO update the bar the MOMENT a step or sub-step changes state — not at the end.** A bar that only moves
at the finish told him nothing while it mattered.

TEST: at any moment Simon can read one line and know the overall position (N/M) and, when a sub-process
is running, its position too.
