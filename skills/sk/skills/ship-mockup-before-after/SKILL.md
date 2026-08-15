---
name: ship-mockup-before-after
description: Show Simon what a planned change will LOOK like, before it is built, as a clickable before/after preview instead of a plan he has to read and imagine. Builds a dev-only route inside the project that renders the change with the project's OWN components, one preview per ticket or plan part, each citing the validated plan it came from and flagging anything that changed after validation. Use for "mock this up", "show me before and after", "what will this look like", "preview the plan", "I want to see it before you build it", or whenever a plan proposes a visible change. Then, once he approves it, this same skill owns the implementation: it inventories every difference from the mockup file, wires each one's call site, proves each on the real screen, and only then deletes the preview. Use it again for "implement the mockup", "build what I approved", or "the screen doesn't match the mockup".
argument-hint: "[optional: ticket id, plan path, or which part to mock]"
---

# Show him the change, don't describe it

**Why this exists:** a plan describes a screen and Simon has to hold it in his head to judge it.
He cannot, so he approves something he has not seen and corrects it after it is built, which is the
expensive end. A preview moves every correction to before the work.

**DO build the preview as a dev-only route INSIDE the project, using the project's own components.**
**DON'T hand-write HTML, and DON'T publish an artifact, for anything that has a real screen.** Both
were tried on 2026-08-10 and both were rejected, in his words: *"it's not looking like the real app"*,
then *"still not reusing existing components... I want you to use the exact components not remake
them"*. A rebuilt screen is always nearly right, and nearly right is what wastes the round.

An artifact stays correct for a change with NO screen — a schema, a prompt harness, a pipeline
ordering. There, diagram the before and after. The rule is the medium follows the subject.

## The shape that worked

```
app/<routes-dir>/mockup-<subject>/page.tsx   + data.ts
```

**DO gate it on development** — `if (process.env.NODE_ENV !== "development") notFound();` — so it
cannot ship even if the deletion is forgotten.

**DO put it where the app's own layout wraps it**, so the sidebar, top bar and theme come for free
rather than being rebuilt.

**DO give every preview a BEFORE/AFTER toggle**, defaulting to AFTER. Before is what the code does
today; after is the proposal. He compares in one click instead of holding two screens in his head.

**DO float every mockup control over the app — fixed, high z-index, styled with NONE of the project's
tokens.** A dark pill in a corner with a `MOCKUP` label reads instantly as scaffolding.
**DON'T put a control inside a real component.** The before/after toggle went into a node header
first and immediately read as a shipped feature: *"it should be a floating mockup interface element,
not part of the app"*. A preview whose scaffolding is indistinguishable from the product teaches him
the wrong thing about what was built, and screenshots as if the control were real.

## Use the real components. All of them.

**DO import the actual components — the shells, the headers, the inputs, the cards, the buttons.**
**DON'T re-create a single one, however small.** The bar at the top of a panel is a real component
with real state; a div that looks like it is a lie that costs a round.

**DO stub the context rather than the components** when a component needs a provider. Read what it
actually consumes first: on 2026-08-10 a node shell needed exactly one field, so a one-field cast
replaced standing up an entire fake context.

**DO use real data**, read out of the project's own database or fixtures, and say in the file where
it came from and when. Invented copy hides the wrapping, the truncation and the empty states that
are the whole reason to look.

**DO reuse existing behaviour rather than reimplementing it in the preview.** If the preview needs
a component to change, CHANGE THE COMPONENT — that change is part of the work anyway, and a preview
that forks it proves nothing about the real screen.

## Cite where each part came from

**DO put a sources line on every preview**, naming the validated plan part, ticket or decision it
implements, by link.
**DON'T show a change with no source.** Anything unsourced is scope you invented, and this is the
cheapest moment to notice.

**DO refute, in the preview's own comments, any part that changed after validation** — what the plan
said, what it is now, and what the evidence was. He validated the plan; a silent divergence spends
that trust.

TEST: every visible difference between before and after traces to a named source, or is explicitly
marked as a refutation with its reason.

## Keep it quick

**DO limit it to what can be judged by eye** — layout, hierarchy, wording, density, state. Wire no
network, no persistence, no auth.
**DON'T build interactivity beyond selecting and toggling.** He is looking, not operating.

**DO make a GALLERY of options selectable in the page** when the mockup exists for him to choose among
them — a grid of variants, not a single before/after. Click a card to toggle it (the component's own
selected/active state plus a checkbox), a fixed bar lists the picks, and a Copy button puts them on the
clipboard; persist the set to localStorage so a long compare does not lose it.
**DON'T make him read each option's name and type it back.** That transcription is the error the mockup
exists to remove; the picks ARE the decision the gallery is for.
TEST: he selects the options he wants and hands you the exact list without typing a name.

**DO iterate on the preview until he approves it.** Then the second half of this skill starts.

## After he approves: implement it, prove it matches, then delete it

**A mockup is only worth what ships.** On 2026-08-11 an approved mockup was called implemented three
separate times with three different details still missing, and each was found by Simon opening the
real screen — *"how come you're still missing mockup details"*. The comparison had been done from
memory every time, so whatever was forgotten was invisible to the person forgetting it. That is the
failure this half exists to make impossible.

### Build the inventory BEFORE writing any code

**DO re-read the approved mockup file top to bottom and write every visible difference as a numbered
row.** Each row names three things: what changes, the file that must change, and **the CALL SITE that
must pass it**. Rows come out of the file, never out of your memory of the round.

**DO treat the third column as the real work.** A component that grows a prop no caller passes is the
DEFAULT outcome, not an edge case: the component changes, every test passes, the screen does not move.
Every row whose middle column is a component needs a row-mate that is the caller. The `columns` prop
no grid was asked for, the width constant nothing read, the formatter wired nowhere — one round, three
instances, all of them shaped identically.

**DO give every row a mechanical check** — a DOM query, a count, a computed style, a `data-testid` —
that returns a value you can read, in one line. Not "looks right".

**DON'T let a row exist only in the mockup's markup.** A control the mockup renders that no plan,
ticket or slice ever specified is still a row, and it is the one most likely to be dropped: the
Regenerate button was in the approved mockup, in nobody's spec, and absent from the screen through
three rounds of being told the work was done. Sweep the mockup for controls before sweeping the plan.

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

**DO delete the mockup route only once every row is green**, in the same change that lands the work. A
preview kept past that drifts from the screen it claims to show; one deleted before it is proven takes
the checklist with it.

## Report

Give him the URL, one line on what changed between before and after, and the open questions as a
numbered list — the things you genuinely cannot decide for him, each with the option you would pick.
**DON'T ask him about anything the preview already answers.**
