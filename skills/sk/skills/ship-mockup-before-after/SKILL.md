---
name: ship-mockup-before-after
description: Show Simon what a planned change will LOOK like, before it is built, as a shareable before/after artifact on Claude instead of a plan he has to read and imagine. Builds a standalone artifact that is pixel-identical to the real app — a real screenshot of the target screen as the BEFORE, an HTML/CSS overlay sized from the real components' MEASURED styles as the AFTER — one per ticket or plan part, each citing the validated plan it came from and flagging anything that changed after validation. Independent of the app: it ships to a Claude URL and needs nothing running to view or share. Use for "mock this up", "show me before and after", "what will this look like", "preview the plan", "I want to see it before you build it", or whenever a plan proposes a visible change. Then, once he approves it, this same skill owns the implementation: it inventories every difference from the artifact, wires each one's call site, proves each on the real screen. Use it again for "implement the mockup", "build what I approved", or "the screen doesn't match the mockup".
argument-hint: "[optional: ticket id, plan path, or which part to mock]"
---

# Show him the change, don't describe it

**Why this exists:** a plan describes a screen and Simon has to hold it in his head to judge it.
He cannot, so he approves something he has not seen and corrects it after it is built, which is the
expensive end. A preview moves every correction to before the work.

**DO ship the preview as a standalone, shareable Claude artifact, built from real app pixels.**
**DON'T hand-write the screen from scratch, and DON'T build a dev route just to view it.** A rebuilt
screen is always nearly right, and nearly right is what wastes the round — the artifact and the
hand-rebuild were both rejected on 2026-08-10, in his words: *"it's not looking like the real app"*,
then *"still not reusing existing components... I want you to use the exact components not remake
them"*. The rule that survives both rejections: **the mockup's fidelity comes from the real app, never
from eyeballing.** An artifact that starts from a real screenshot and measured real-component styles
IS exact, and it wins the medium — one Claude URL, shareable, needing nothing running to open.

A change with NO screen — a schema, a prompt harness, a pipeline ordering — has nothing to screenshot;
diagram the before and after in the artifact instead. The rule is the medium follows the subject.

## Capture the BEFORE from the real app

**DO screenshot the target screen at a FIXED viewport, in one theme, populated with realistic data.** A
seeded demo is fine and preferred — seed the screen and everything it references with realistic values
(plausible names, lengths, counts) so it looks like the app in real use. Record the route, viewport
size and theme in the artifact's own comments. That raster is the substrate the AFTER sits on, so every
pixel around the change stays true to the app.
**DON'T screenshot placeholder, lorem or empty-stub content.** The wrapping, truncation and populated
states are the whole reason to look, and only realistic content shows them.

## Measure the real components — never eyeball the AFTER

**DO measure the real rendered components before drawing anything** — `getComputedStyle` and
`getBoundingClientRect` for box size, font, colour, spacing, border-radius, shadow — and size the
AFTER from those exact values. The app itself is the render rig; stand up a scratch route ONLY when a
component the AFTER needs is not reachable on any real screen.
**DON'T set a dimension, colour or font in the overlay by eye.** Eyeballing is the nearly-right failure
that got the rebuild rejected; a measured value cannot be nearly right.
TEST: every dimension and colour in the overlay traces to a value you measured this run.

## Render the AFTER: overlay a screen, storyboard a flow

**DO overlay the change on the BEFORE screenshot when it is a single screen** — HTML/CSS positioned and
sized from the measured values, changing ONLY the region the plan touches. Everything outside the change
stays the untouched screenshot, so it is real pixels by construction.
**DON'T re-render the parts that did not change.** Re-drawing them re-introduces the exact nearly-right
rebuild this skill exists to avoid.

**DO make it a WALKABLE storyboard when the change is a flow** — every step the user passes through,
each new state built from the measured component styles, each state the app already renders reused as a
real screenshot. Wire the buttons, fields and steps so he advances through them himself.

## Walk every state — simulated, seeded, no real requests

**DO cover every step of the proposed journey**, enumerated from `references/user-journey-review.md`
(first contact → set-up → trigger → the wait → the result, and the empty, loading and error state of
every surface). He can only tell you which parts need changing if he can reach every state; a first
screen with nothing beyond it sends the fix back to after the build — the exact cost this skill removes.
**DON'T stop at the first state, and DON'T leave a button dead.**
**DO simulate every transition with local state and seeded data** — no network, no persistence, no auth,
no real requests. He is walking the flow, not operating a live app.

## Assemble the artifact

**DO make it self-contained** — the screenshot embedded as a `data:` URI, all CSS and JS inline —
because the artifact CSP blocks every external request. Load the `artifact-design` skill before
writing the page, and give it a title, a favicon, a theme-aware palette and a responsive layout.

**DO give the artifact a BEFORE/AFTER toggle defaulting to AFTER.** Before is what the screen does
today; after is the proposal. He compares in one click instead of holding two screens in his head.

**DO float every mockup control OVER the screen — fixed, high z-index, styled with NONE of the app's
tokens.** A dark pill in a corner with a `MOCKUP` label reads instantly as scaffolding.
**DON'T style a control to look like part of the app.** A preview whose scaffolding is
indistinguishable from the product teaches him the wrong thing about what was built.

## Cite where each part came from

**DO put a sources line in the artifact**, naming the validated plan part, ticket or decision each
visible difference implements, by link.
**DON'T show a change with no source.** Anything unsourced is scope you invented, and this is the
cheapest moment to notice.

**DO refute, in the artifact's own comments, any part that changed after validation** — what the plan
said, what it is now, and what the evidence was. He validated the plan; a silent divergence spends
that trust.

TEST: every visible difference between before and after traces to a named source, or is explicitly
marked as a refutation with its reason.

## Let him choose among variants, and say what to keep

**DO make a GALLERY of variants he browses** when the mockup exists for him to choose among them — a
grid of options, each selectable (one or more), each with a comment box for what to keep from it and
what to change.
**DON'T make him read a variant's name and type it back.** The picks and comments ARE the decision.

**DO assemble the picks and comments with the response contract from
`/sk:work-ask-reply-in-full-before-after-artifact`**, so he hands back exactly what he selected and
commented without typing a variant name.

**DO dock that panel COMPACT and collapsed, so it never covers the mockup.** He opens it after
browsing, and the options stay fully visible while he decides.
**DON'T float it over the screen he is judging.**
TEST: he picks one or more variants, comments keep-or-change on each, opens the panel and copies, and
the block names every pick, every rejection and every comment.

## Check it against the real app, and fold the fix forward

**DO diff every overlaid and new-state component against a real render before showing him** — screenshot
the same component in the app at the same viewport and seed, and compare size, font, colour, spacing and
radius. A difference means the overlay measured the wrong value or missed one; fix it against the
measurement, never by nudging pixels.
**DON'T show a mockup you have not checked against the real app.** Nearly-right is the whole failure, and
the real render is the ground truth that catches it.

**DO fix the CLASS and fold it forward.** When a divergence traces to how this skill works — a
measurement it skips, a token it never reads, a state it forgets — propose the durable fix to this skill
through `/sk:claude-config-update` so the next mockup is exact from the first render. That is the
`self-healing-config` loop.

**DO iterate on the artifact until he approves it.** Then the second half of this skill starts.

## After he approves: implement it, prove it matches

**A mockup is only worth what ships.** On 2026-08-11 an approved mockup was called implemented three
separate times with three different details still missing, and each was found by Simon opening the
real screen — *"how come you're still missing mockup details"*. The comparison had been done from
memory every time, so whatever was forgotten was invisible to the person forgetting it. That is the
failure this half exists to make impossible.

### Build the inventory BEFORE writing any code

**DO re-read the approved artifact top to bottom and write every visible difference as a numbered
row.** Each row names three things: what changes, the file that must change, and **the CALL SITE that
must pass it**. Rows come out of the artifact, never out of your memory of the round. Walk every
storyboard step, not just the entry screen — a state reached only by clicking through is the one most
likely to be missed.

**DO treat the third column as the real work.** A component that grows a prop no caller passes is the
DEFAULT outcome, not an edge case: the component changes, every test passes, the screen does not move.
Every row whose middle column is a component needs a row-mate that is the caller. The `columns` prop
no grid was asked for, the width constant nothing read, the formatter wired nowhere — one round, three
instances, all of them shaped identically.

**DO give every row a mechanical check** — a DOM query, a count, a computed style, a `data-testid` —
that returns a value you can read, in one line. Not "looks right".

**DON'T let a row exist only in the artifact's markup.** A control the artifact renders that no plan,
ticket or slice ever specified is still a row, and it is the one most likely to be dropped: the
Regenerate button was in the approved mockup, in nobody's spec, and absent from the screen through
three rounds of being told the work was done. Sweep the artifact for controls before sweeping the plan.

**When the work is fanned out, ownership follows the row, not the component.** One slice owns a
change AND its call site, or the wiring is stated as the reconciler's job. A slice that changes a
component and not its caller is individually correct and collectively useless, and every slice passing
its own gate is exactly what the failure looks like from inside.

### Then prove it, against the real screen

**DO open the real screen and run the checklist row by row**, reading the actual value each check
returns. Both screens, side by side, same session, same data.
**DON'T report a match you did not measure.** "Implemented" means every row returned its expected
value on the real screen, not that every file was edited and the suite is green. A green suite is what
the failure looked like all three times.

TEST: every row has a value next to it. A row with no value is an unimplemented row.

**DO tear down any scratch render rig you stood up to measure** — a temporary route or harness — in
the change that lands the work. Nothing else needs deleting: the artifact lives on Claude, not in the
repo, so there is no dev route to clean up.

## Report

Give him the artifact URL, one line on what changed between before and after, and the open questions as
a numbered list — the things you genuinely cannot decide for him, each with the option you would pick.
**DON'T ask him about anything the preview already answers.**
