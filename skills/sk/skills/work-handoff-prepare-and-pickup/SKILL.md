---
name: work-handoff-prepare-and-pickup
description: Hand a running gauntlet (or any dashboard-backed session) to another agent, or pick one up, through the dashboard link — so hitting a quota wall never loses context. One skill, two sides. PREPARE (the agent running low): flush the live state, commit the plan+dashboard so the record is durable, and hand back the copy-paste dashboard link. PICK UP (the fresh agent): from a pasted dashboard link, dashboard .html, or plan .md, locate and verify the plan on this machine, re-attach, regenerate the dashboard, and resume the recorded engine where it left off with full context and up-to-date progress — no re-briefing, no second options interview. Idempotent and repeatable, so handoffs chain A→B→C without bound and nothing degrades. Same machine only (loopback URL + worktree path). Use for "prepare a handoff", "hand this off", "I'm running out of quota", "pick up this handoff", "resume from this dashboard link", "take over this gauntlet", "keep handing this off", or /sk:work-handoff-prepare-and-pickup.
argument-hint: "[prepare | <pasted dashboard link | dashboard.html | plan.md>] [--by name] [--note text]"
---

# Gauntlet handoff — prepare and pick up

DO read `~/.claude/references/workflow-loops.md` § "Handoff and resume" and run its steps; that is the
SSOT for the mechanic, this skill just drives the two sides. The living plan IS the handoff artifact;
the dashboard is a self-contained render of it. Same machine only by design.

DO pick the side from the input. No pasted link/path, or "prepare"/"hand off"/"running out of quota"
→ PREPARE. A pasted dashboard link, dashboard `.html` or plan `.md` → PICK UP.

DO run PREPARE for the agent running low:
- Flush the live state to the plan (`update`), then `workflow-dashboard.py handoff <plan> --by <who>
  --note <why>` to stamp the resume manifest, bump the hop and re-render the "Handed off" banner.
- Commit the plan and dashboard when the worktree is tracked, so the record survives (never disturb
  unrelated WIP; per `rules/process.md`).
- Hand back the printed `HANDOFF_LINK` in one line: "Paste this to a fresh agent and run
  /sk:work-handoff-prepare-and-pickup <link>." Then stop.
TEST: prepare returns one copy-paste link and the dashboard shows the banner; a second prepare on the
same plan reports the next hop, proving the chain never degrades.

DO run PICK UP for the fresh agent:
- `workflow-dashboard.py resolve --target "<pasted>"` to get `PLAN_PATH`, `WORKTREE`, the recorded
  `ENGINE`/`GAUNTLET`/`ITERATION`/`PHASE` and `HANDOFF_HOP`. It accepts a loopback dashboard URL, a
  `file://`/filesystem dashboard `.html`, or a plan `.md`.
- Regenerate the dashboard (`link`) and, if the user wants it open, `serve` it.
- Resume the recorded engine from `PLAN_PATH` with NO fresh options interview — a gauntlet resumes
  via `/sk:work-gauntlet-loop --resume <PLAN_PATH>`, ordinary work via
  `/sk:work-full-detailed-workflow`. Continue where the sections left off with the full plan context.
TEST: pick-up resumes the exact recorded engine and progress from any of the three target forms,
without re-asking the run options.

DO keep the chain unbounded: pick-up leaves the manifest in place, and the next agent runs PREPARE
again to hand off further. Nothing accumulates; every hop regenerates from the one plan.

DO surface the same-machine limit plainly: a pasted loopback URL or worktree path only resolves on the
machine that produced it. If a target does not resolve here, say so and ask for the plan `.md` path in
this checkout, rather than guessing.
