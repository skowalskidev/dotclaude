---
name: meta-dotclaude-copilot-start-here-for-any-task
description: The single skill to call for ANY task with this dotclaude config, so Simon never has to remember which skill fits. It reads the task, routes it to the right skills via references/skill-stack.md (verifying each is installed), presents the plan, and drives the whole job to a verified finish — keeping an always-visible progress bar (overall + nested sub-progress), applying each skill at its stage, and gracefully RESUMING the main thread after a tangent (a mid-task fix, a discovered todo). Callable at any stage; it re-reads the tracker and continues where the plan left off. Reuses references/skill-stack.md (the map), the task-intake gate, and rules/process.md (a tangent is a queued task; track every task to completion); it owns the single entry point, the progress bar, verifying skill names, and the resume. Use for "start here", "what should I use for this", "run this the right way", "just handle this", "which skills for this task", "copilot this whole thing", or /sk:meta-dotclaude-copilot-start-here-for-any-task.
argument-hint: "[the task, or the stage you're resuming]"
---

# Start here — the one skill to route and run any task

You do not want to remember which of 25+ skills fits a task, and you should not have to. Call this for
anything. It routes the task to the right skills, shows a live progress bar, and keeps every skill
applied through to a verified finish — resuming the main thread after any tangent.

## What it reuses, and what it owns

- **The MAP is `references/skill-stack.md`** — task-shape → the right spine skill + what genuinely stacks
  on it. Read it; never guess a skill from its name, and never restate the map here.
- **The intake survey already runs** (`hooks/task-intake.sh` fires on every task); this skill is the
  user-invocable FRONT DOOR that makes routing deliberate and drives it to the end.
- **`rules/process.md` owns** run-to-completion, "a mid-run message is a QUEUED task not an interrupt,"
  track-every-task-to-completion, and commit-when-done. Point to it; do not restate it.
- **This skill OWNS**: the single entry point, the always-on progress bar, verifying each routed skill is
  installed, and resuming skills after a tangent.

## Step 1 — read the task and ROUTE it (via the map, verified)

- Match the task to a row in `references/skill-stack.md`; pick the spine skill plus any that genuinely
  stack. If nothing fits, say so and just do the work — one skill that fits beats three that half-fit.
- **VERIFY every skill you name is INSTALLED before you plan on it** — glob
  `find -L ~/.claude/skills -name SKILL.md`, or check the runtime skill listing; never write a `/sk:`
  name from memory. A missing or mistyped name derails the run (one non-existent `artifact-design`
  reference broke a whole parallel round). TEST: every skill in the plan resolves to an installed SKILL.md.
- Decide HOW too (`references/parallelization.md`): serial, a small in-session fan-out, or
  `/sk:work-superspeed` / `/sk:work-hyperspeed` when it splits into 3-5+ genuinely independent slices.

## Step 2 — present the PLAN, get the go

- Open with the user-journey TLDR, then the ordered skill-plan (which skill at which stage), then the
  questions in one block (`references/planning-and-tracking.md`). Get sign-off for big or risky work.
  With no ticket, the prompt IS the plan.
- Write the plan + progress to a DURABLE tracker — the harness Task list AND `.context/`
  (`rules/process.md`) — so a restart or a hand-off resumes it, not memory.

## Step 3 — the ALWAYS-ON progress bar

Simon must always see how far along he is, at every level. The format, the Task-list-as-canonical-tracker
and the nested sub-progress convention are `references/progress-bar.md`'s — read it there, don't restate
it. Here the steps ARE the plan's stages, and a sub-skill (`/sk:work-full-detailed-workflow`,
`/sk:work-superspeed`) shows its own nested bar under the main one.

## Step 4 — RUN it, applying each skill at its stage

- Invoke each routed skill at its stage and FOLLOW it — the skill stays applied through the whole stage,
  not merely named at the start.
- The always-on `rules/*.md` stay in force throughout; they are auto-loaded, so this skill does not
  restate them.

## Step 5 — tangents: handle, then RESUME the main thread

A tangent WILL arise — a bug surfaces, a todo-fix is discovered, Simon asks for something mid-run.

- **A tangent is a QUEUED task** (`rules/process.md`), never a reason to drop the main thread. Add it to
  the tracker, do it (route IT through this same skill if it is non-trivial), then RETURN to the exact
  step the main plan was on — the progress bar makes the return point obvious.
- **Never let a tangent silently end the main job.** The response after a tangent continues the main
  plan, the bar showing the tangent done and the main thread resuming.
  TEST: after any tangent, every remaining step of the main plan still gets done; nothing is dropped.

## Step 6 — finish and hand back

- Drive to a VERIFIED finish: `/sk:ship-report-and-ensure-correct-user-system-journey` closes substantive
  work (the build spine already calls it), and commit-when-done applies (`rules/process.md`).
- The bar reads 100% only when every plan step AND every tangent is done and verified.

## Callable at any stage

Re-invoke this at any point — hand it the stage you are resuming, or nothing. It reads the tracker (the
Task list + `.context/`), works out where the plan left off, and continues from there without restarting
done work.
