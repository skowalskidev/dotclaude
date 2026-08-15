---
name: work-copilot-agile-build
description: Build a feature WITH Simon as an agile copilot loop, not waterfall. Each round builds the proposed interface in the real app with realistic SIMULATED data FIRST — no backend, it only has to look real — then walks him through it as a first-time user (previewable frontend) or shows the user-and-system journey in TLDR previewable form (backend), gets his feedback, and builds the backend for that slice ONLY after he confirms the UX and journey are right. Then it repeats, each loop showing what's built and what's next. Use for "build this with me", "copilot this with me", "let's do this in an agile loop", "preview it with fake data first", "show me the interface before you build the backend". Neighbours it must not duplicate: test-copilot verifies a WORKING feature with him; work-full-detailed-workflow is the full single-build harness; ship-mockup-before-after is one preview, and this is the repeating loop that drives it.
argument-hint: "[what to build, e.g. 'the review queue' or 'this ticket']"
---

# Build it with him, one previewable loop at a time

**Why this exists:** building the backend for a screen Simon has not seen is the expensive mistake.
He approves a plan he had to imagine, the backend gets built, the UX is wrong, and the correction now
costs a rebuild instead of a sentence. This skill inverts the order: the interface comes first, fake
but realistic, he reacts to something he can see, and no backend is written until the journey he
confirmed is the one being built. Agile, human in the loop every round, the opposite of waterfall.

**Don't duplicate the neighbours:**
- `/sk:ship-mockup-before-after` — builds ONE preview and, after approval, implements it. This skill
  is the repeating loop that drives it round after round.
- `/sk:test-copilot` — paces him through a WORKING feature while watching logs. Here the preview does
  not work by design; there is nothing to instrument yet.
- `/sk:work-full-detailed-workflow` — the full plan-first harness for a single build. This is the
  lighter, interface-first loop that grows a feature with him a slice at a time.

Read, don't restate: `~/.claude/references/tldr-report-formats.md` (the glance test — the shape every
check-in passes) and `~/.claude/references/user-journey-review.md` (what to look for as he walks a
flow). The preview mechanics and the journey report are owned by the two skills above; this skill
sequences them, it does not re-explain them.

## The loop — this is the whole skill

Each round builds ONE slice, then repeats until the feature is done.

1. **Preview first, and fake.** Build the slice's interface in the real app with the project's own
   components, via `/sk:ship-mockup-before-after`. It has to LOOK real and DO nothing — no backend, no
   persistence, no network.
   **DO populate it with realistic SIMULATED data.** This is the one place the mockup skill's "use the
   real data" rule is overridden on purpose: the backend that would produce real data does not exist
   yet, so plausible fabricated data is correct here — enough rows, real-looking values, the empty and
   overflow states, not three lorem-ipsum cards. TEST: the preview shows the states a first-time user
   would actually hit, with data indistinguishable at a glance from production.

2. **Show it, don't describe it.** The medium follows the subject.
   - **Previewable (frontend):** walk him through the slice as a first-time user would move through it
     — the screens, the controls, the order. He is looking, reacting, judging the UX.
   - **Non-previewable (backend):** there is no screen, so show the **user journey and system journey
     in TLDR previewable form** via `/sk:ship-report-and-ensure-correct-user-system-journey` — what the
     user goes through and what the system does under the hood, step by step, at a glance.
   Either way this doubles as the progress view: **what's built this round, and what's next.** Format
   is the glance test in `tldr-report-formats.md` — answer-first, one line per step, each ending in
   something he can act on. Not word vomit, not too sparse.

3. **Hold the backend until he confirms.** **DO NOT write a line of backend for a slice until Simon has
   confirmed its user journey and its UX/UI are right.** His feedback loops straight back into the
   preview (step 1) — change the interface, show him again — until he approves. TEST: every backend
   change traces to a preview or journey he signed off on; a backend commit with no prior approval is
   the failure this skill exists to prevent.

4. **Then implement, and prove it matches.** Once he approves the slice, build its backend and prove
   the shipped screen matches the approved preview — the second half of `/sk:ship-mockup-before-after`:
   inventory every difference, wire each call site (a component that grew a prop no caller passes is
   the default failure), verify each on the real screen, then delete the preview in the same change.

5. **Commit the slice and loop.** Commit this round as one logical unit (`process.md`), then start the
   next slice at step 1.

## When a round keeps failing

**DO rewind after about two failed correction rounds on the same slice**, rather than pushing a third
variation at it — re-preview from a cleaner start, or re-scope the slice with him. Grinding one slice
is how a loop that should self-correct turns into sunk cost. (The confirm-before-backend gate is the
drift guard; this is the escape hatch for when the preview itself will not converge.)

## The two ways this skill fails

1. **Building backend ahead of confirmation.** The whole point is that no backend exists for a UX he
   has not seen and approved. A backend commit that races the approval is the waterfall mistake wearing
   an agile label.
2. **Word vomit in the check-in.** Each round's show-and-tell is TLDR and actionable — what's built,
   what's next, one line per step, ending in a decision he can make. A check-in he has to re-read has
   already failed.
