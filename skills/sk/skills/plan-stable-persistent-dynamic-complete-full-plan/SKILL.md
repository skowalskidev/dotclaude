---
name: plan-stable-persistent-dynamic-complete-full-plan
description: Keep ONE living, source-of-truth plan file instead of re-writing or re-explaining the plan every time it changes. It updates only the SECTIONS a request touches (surgical edits, so the plan never drifts or needs re-reading whole), prepends a dated Changelog entry naming what changed, and shows you ONLY the changed section(s) in chat as the delta — so you read the change, not the whole document. It stays LOCKED in plan-mode: every new request, correction or idea folds back into the single plan, and it does NOT implement until you explicitly confirm ("implement" / "start building" / "go build" / "the plan is confirmed"). On confirmation it asks whether to break the plan into Linear tickets, then hands off to /sk:work-full-detailed-workflow automatically. The plan lives at .context/<slug>-plan.md (durable, survives a restart). Use for "keep a single plan", "stop making me re-read the plan", "just update the plan", "one source of truth plan", "living plan", "stay in plan mode until I say go", or /sk:plan-stable-persistent-dynamic-complete-full-plan. Reuses references/planning-and-tracking.md for what a complete plan contains.
argument-hint: "[the plan's subject, or the update to fold in]"
---

# Plan — one living source of truth, updated in place

Keep ONE plan that stays current without drift or re-reading. Every request updates the right SECTION,
the change is highlighted so Simon reads only the delta, and nothing is implemented until he confirms.
The name is the four properties: STABLE (a fixed section skeleton, surgical edits), PERSISTENT (one
durable file, survives a restart), DYNAMIC (updated on every request), COMPLETE (every section filled and
the completeness bar met before it can be confirmed).

## The single plan file

- Lives at `.context/<slug>-plan.md` — durable per `rules/process.md` (survives a restart, never
  `/tmp`), matching the `.context/<TICKET>-plan.md` convention. ONE file per plan, the source of truth.
  NEVER spawn a second plan doc; every request folds into this one.
- Its CONTENT — what a complete plan contains (user-journey TLDR first, questions consolidated, scope
  across every surface, re-check against sources, verify foundations) — is
  `references/planning-and-tracking.md`'s job. Read it there. This skill owns the FILE LIFECYCLE, not the
  plan's contents.

## The stable skeleton (so edits stay surgical)

Give the file fixed section anchors from the start. Adjust which sections exist per task, but keep them
STABLE within a plan so an update targets ONE section, not the whole doc:

- `## Changelog` — newest first, at the very top.
- `## Status` — `PLANNING (locked)` | `CONFIRMED`; one line.
- `## Goal & user-journey TLDR`
- `## Open questions` — Simon's decisions, each with a proposed default.
- `## Approach`
- `## Tasks` — the work breakdown (the unit tickets are cut from).
- `## Decisions & rationale`
- `## Risks & assumptions`
- `## Out of scope`
- `## Sources` — the tickets/links this plan is judged against (or `prompt-derived`).

## First invocation — create the plan, show it once

Create the file with the skeleton, fill it from the request and `references/planning-and-tracking.md`,
set `## Status` to `PLANNING (locked)`, and show the WHOLE plan in chat this once — the only time Simon
reads it whole. Then wait.

## Every later request — surgical, logged, delta-in-chat

A new requirement, a correction, an answer to a question, a new idea — each is a plan UPDATE, not a build:

1. **Find the section(s) it touches** — one or a few, never the whole doc. If it fits none, ADD a section
   (and log it).
2. **Edit ONLY those sections in place.** Never rewrite an untouched section — that is exactly what
   causes drift and forces a re-read.
3. **Prepend a Changelog entry:** `### rev N · <today, from `date +%F`> · <one line>` naming each changed
   section (its `## anchor`), what changed, and WHY.
4. **Show Simon ONLY the delta in chat** — the changed section(s) in full under a `What changed (rev N)`
   header, nothing else. He reads the change; the file stays the complete source of truth he can open
   any time.

TEST: after an update, Simon can act from the chat delta alone, and the repo still has exactly ONE plan
file with one new Changelog entry.

## Plan-mode lock — do NOT implement until confirmed

- **Stay in plan-mode.** Every request updates the plan. It does NOT trigger a code edit, a branch, a
  build, or `/sk:work-full-detailed-workflow`. "Add X" means "add X to the plan", never "build X". In
  plan-mode, starting to build is THE failure this skill prevents — it overrides the harness's default
  eagerness to start.
- **Exit ONLY on an explicit confirmation from Simon:** "implement" / "start building" / "go build" /
  "exit plan mode" / "the plan is confirmed" / "approved, go" (or an unmistakable equivalent). If unsure
  whether a message confirms or just updates, treat it as an update and ask.
- **The plan must be COMPLETE before it can be confirmed** (planning-and-tracking.md's bar): every open
  question has a proposed answer or is flagged for Simon, every source has a verdict, the user-journey
  TLDR is present. Refuse to mark `CONFIRMED` while a question is unanswered; surface what's missing.

## On confirmation — ask about tickets, then hand off automatically

1. Set `## Status` to `CONFIRMED` and log it.
2. **Ask Simon whether to break the plan into tickets** (AskUserQuestion): encode the `## Tasks`
   breakdown as Linear tickets, or keep the `.context/` plan as the single doc. If yes, cut the tickets
   from `## Tasks` per `references/planning-and-tracking.md` (one main ticket carrying the plan, subtasks
   ordered by priority, each with its testing steps and how it relates to the rest) and the project's own
   ticket conventions in its `CLAUDE.md`; link them, and keep the plan file as the connecting source of
   truth. Do NOT auto-post the plan as ticket comments unprompted.
3. **Hand off to `/sk:work-full-detailed-workflow` automatically** with the plan file (and the tickets,
   if created) as its input — no second command needed. The plan file stays the source of truth the
   build and the end report are judged against.
