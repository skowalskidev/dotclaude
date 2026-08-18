---
name: ship-mockup-before-after
description: Show Simon what a planned change will LOOK like, before it is built, as a shareable before/after mockup instead of a plan he has to read and imagine. The mockup is ONE self-contained HTML document whose entire state lives in an embedded JSON spec (a data island) and whose UI renders from it — so another Claude can rebuild it with zero loss. It is pixel-true to the real app: a compressed real screenshot of the target screen as the BEFORE, an HTML/CSS overlay sized from the real components' MEASURED styles as the AFTER, one per ticket or plan part, each citing the validated plan it came from. It ships as the medium that fits — a downloadable HTML FILE (default for collaborative, versioned, multi-screenshot round-trips) or a Claude artifact URL (frictionless when small and un-gated). Recipients are guided to browse variants in a bird's-eye grid with a HUD, select the ones they like, pin comments asking for changes, and approve or request changes; the copy-paste block they hand their Claude IS the complete build spec, so it updates or recreates the mockup as a new author-attributed version and passes it back, and every version stays inside the mockup, switchable and diffable. Use for "mock this up", "show me before and after", "what will this look like", "preview the plan", "share this mockup for feedback", "I want to see it before you build it", or whenever a plan proposes a visible change. Then, once he approves it, this same skill owns the implementation: it inventories every difference, wires each one's call site, and proves each on the real screen. Use it again for "implement the mockup", "build what I approved", or "the screen doesn't match the mockup".
argument-hint: "[optional: ticket id, plan path, or which part to mock]"
---

# Show him the change, don't describe it

**Why this exists:** a plan describes a screen and Simon has to hold it in his head to judge it.
He cannot, so he approves something he has not seen and corrects it after it is built, which is the
expensive end. A preview moves every correction to before the work.

**DO ship the preview as ONE self-contained HTML document, built from real app pixels, whose state is a
data island (below).**
**DON'T hand-write the screen from scratch, and DON'T build a dev route just to view it.** A rebuilt
screen is always nearly right, and nearly right is what wastes the round — the artifact and the
hand-rebuild were both rejected on 2026-08-10, in his words: *"it's not looking like the real app"*,
then *"still not reusing existing components... I want you to use the exact components not remake
them"*. The rule that survives both rejections: **the mockup's fidelity comes from the real app, never
from eyeballing.** A document that starts from a real screenshot and measured real-component styles IS
exact, and it needs nothing running to open or share.

A change with NO screen — a schema, a prompt harness, a pipeline ordering — has nothing to screenshot;
diagram the before and after instead. The rule is the medium follows the subject.

## Choose the medium — a downloadable HTML FILE, or a Claude artifact URL

The deliverable is one self-contained HTML document; ship it as whichever medium serves THIS mockup.
The Claude-artifact medium is genuinely limited, and the limits pick the medium (all measured 2026-08):

- **A downloadable HTML FILE — the DEFAULT for a collaborative, versioned, multi-screenshot round-trip.**
  It has no size ceiling, opens in any browser, and the recipient's Claude edits the ACTUAL file with
  zero regeneration loss. Write it to a path and hand Simon the file to share.
- **A Claude artifact URL — the frictionless option when the mockup is SMALL and un-gated.** Publish it,
  send the link; non-account viewers get full interactivity, nothing to run.

**DO pick the FILE the moment any of these is true**, because the artifact medium breaks on them:
- **Size:** a full-screen base64 PNG is ~1M+ text tokens; a few inlined screenshots plus version history
  can exceed the context window and make the artifact impossible to rewrite in one turn. A file has no
  such ceiling.
- **`localStorage`/`sessionStorage` are BLOCKED in the artifact sandbox** — state must be in-memory. A
  file can use storage, but keep state in-memory + the embedded spec so it is portable either way.
- **Publishing gotchas:** the one-click "Remix" is gone (a recipient copies the source into their own
  Claude — a fork, not a live shared doc); **Team/Enterprise accounts cannot publish publicly** (org
  only), so if Simon is on a work org, use the FILE; published links do not expire and carry no
  password, so never put anything sensitive in a mockup.

TEST: a mockup with more than one screenshot, more than one version, or a review round-trip ships as a
FILE, not an artifact.

## Make it a DATA ISLAND — the embedded spec is the single source of truth

This is what makes the mockup rebuildable without loss, diffable across versions, and faithful on a
hand-back. It is the Next.js `__NEXT_DATA__` / SingleFile hydration pattern applied to a mockup.

**DO embed ONE `<script type="application/json" id="spec">` block that IS the mockup's entire state** —
`schemaVersion`; a `manifest` (version count + every variant id); design tokens; and `versions[]`, where
each version carries its before/after variants as STRUCTURED component data + measured styles, plus its
author, timestamp, selections, comments and verdicts. A small `render(spec)` builds the whole visible UI
from it.
**DON'T author any label, prop, or state directly into the markup.** A string baked into HTML instead of
`#spec` is a string the next regeneration silently drops — that is the whole failure mode this prevents.
WHY: regeneration then becomes "re-render this JSON" (mechanical, loss-free) instead of "re-describe the
UI" (lossy — verbatim structured data survives an LLM round-trip 91% vs 14% for a summary).
TEST: with the render layer deleted, `#spec` alone still holds every variant, version, selection and
comment; re-running `render(spec)` reproduces the mockup exactly.

## Capture the BEFORE from the real app

**DO screenshot the target screen at a FIXED viewport, in one theme, populated with realistic data.** A
seeded demo is fine and preferred — seed the screen and everything it references with realistic values
(plausible names, lengths, counts) so it looks like the app in real use. Record the route, viewport
size and theme in the spec. That raster is the substrate the AFTER sits on, so every pixel around the
change stays true to the app.
**DON'T screenshot placeholder, lorem or empty-stub content.** The wrapping, truncation and populated
states are the whole reason to look, and only realistic content shows them.

**DO compress every screenshot HARD before inlining — WebP q70-80, downscaled to display size (long edge
~1280px), never a full-res PNG.** A full-res PNG as base64 can exceed the whole context window on its
own; a downscaled WebP is roughly 40x smaller. Cap inlined screenshots at about 1-3 and keep the total
base64 well under the model's output cap, or the document cannot be rewritten in one turn. Prefer
rendering a state from measured-style DATA over screenshotting it wherever the state is reachable.

## Measure the real components — never eyeball the AFTER

**DO measure the real rendered components before drawing anything** — `getComputedStyle` and
`getBoundingClientRect` for box size, font, colour, spacing, border-radius, shadow — and size the
AFTER from those exact values, stored in `#spec`. The app itself is the render rig; stand up a scratch
route ONLY when a component the AFTER needs is not reachable on any real screen.
**DON'T set a dimension, colour or font in the overlay by eye.** Eyeballing is the nearly-right failure
that got the rebuild rejected; a measured value cannot be nearly right.
TEST: every dimension and colour in the overlay traces to a value you measured this run.

## Render the AFTER: overlay a screen, storyboard a flow

**DO overlay the change on the BEFORE screenshot when it is a single screen** — HTML/CSS positioned and
sized from the measured values in `#spec`, changing ONLY the region the plan touches. Everything outside
the change stays the untouched screenshot, so it is real pixels by construction.
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

## Assemble the document

**DO make it self-contained** — screenshots as compressed `data:` URIs, all CSS and JS inline — so the
one file (or the CSP-locked artifact) needs no external request. Apply the visual craft directly — no
separate design skill to load: give the page a title, a favicon, a theme-aware light+dark palette, a
responsive layout, and realistic seeded content (never lorem).
**DO keep ALL state in-memory and in `#spec`; NEVER use `localStorage`/`sessionStorage`.** They are
blocked in the artifact sandbox and fail silently; the embedded `#spec` is the durable record either way.

**DO give the document a BEFORE/AFTER toggle defaulting to AFTER.** Before is what the screen does
today; after is the proposal. He compares in one click instead of holding two screens in his head.

**DO float every mockup control OVER the screen — fixed, high z-index, styled with NONE of the app's
tokens.** A dark pill in a corner with a `MOCKUP` label reads instantly as scaffolding.
**DON'T style a control to look like part of the app.** A preview whose scaffolding is
indistinguishable from the product teaches him the wrong thing about what was built.

## Browse the variants — grid, focus, filmstrip, present mode

Overview first, then focus (Shneiderman's mantra): a bird's-eye view lets him get his head around the
whole set before drilling in.

**DO open on a BIRD'S-EYE grid — variants as thumbnails, 3 to a row — so he decides at a glance which to
look at closely.** Each thumbnail is the variant's AFTER, labelled and selectable right there.
**DON'T make him scroll past full-size variants to compare them.** Comparing is the whole job of the
grid; a stacked scroll defeats it.

**DO click a thumbnail into a FULL view**, and keep a PERSISTENT thumbnail filmstrip (a rail) visible in
focus mode with the current variant highlighted, so orientation is free. Add next/previous, a "back to
grid" control, and keyboard nav (←/→ move, Esc back to grid, Home/End first/last).

**DO offer a PRESENT / full-screen mode that hides all chrome, with fit / fill / 100% scaling**, so a
mockup is judged uncovered by UI.

**DO SEPARATE variants by TYPE — tabs or titled lanes, each type its own section** (the dashboard's
variants in one, the modal's in another), so several different changes live in one document without
blurring together. Keep types to a handful; a type is a chunk, a variant is an item inside it.

**DO put secondary detail (specs, notes, rationale) behind a per-variant DETAILS drawer** — progressive
disclosure keeps the canvas clean.

**DO float a HUD — fixed, high z-index, styled with NONE of the app's tokens — that ALWAYS shows where he
is:** the current type, variant N of M within it, the current VERSION, and quick nav. He never loses
his place.
TEST: at any moment the HUD names the type, the variant position (N of M), and the version being viewed.

## Compare — side by side, and diff what changed between versions

**DO give a 3-up SIDE-BY-SIDE compare mode (cap 3-4 variants)** so he judges options head to head without
holding them in memory, plus an onion-skin opacity slider (or a before/after wipe) for two close variants
where a small positional shift matters.

**DO DIFF two versions at the FIELD level — green added, yellow modified, red removed** — derived from
`#spec`, since the state is structured data. This is the single highest-value comparison feature and the
reason the data island is worth it: it shows exactly what a recipient changed between v1 and v2, which
even design tools built on rasters cannot do on their own content.
TEST: switching to "compare v1 → v2" marks every added/modified/removed field, and the marks come from
`#spec`, not from eyeballing two screenshots.

## Point at what's new

**DO gently highlight the CHANGED region of each variant, so a small new section is not missed.** When a
variant first opens, flash the changed area ONCE — a brief 150-300ms outline or glow — then HOLD a static
marker (a persistent outline on the changed region, the rest dimmed). Give a "What's new" control that
re-flashes on demand, and respect `prefers-reduced-motion` (fall back to the static marker, no motion).
**DON'T pulse it forever or animate the whole screen.** A looping animation dilutes attention and gets
annoying on repeat; one flash then a static marker is what defeats change-blindness without distraction.
TEST: opening a variant flashes only the region the plan changed, once, then a static outline stays; the
"What's new" button re-flashes it, and reduced-motion shows the static marker with no flash.

## Let him — and a recipient — choose, comment, and decide

**DO make the variants selectable (one or more), each with a comment box for what to keep and what to
change, using the response contract from `/sk:work-ask-reply-in-full-before-after-artifact`** — so he
hands back exactly what he selected and commented without typing a variant name.
**DON'T make him read a variant's name and type it back.** The picks and comments ARE the decision.

**DO let him PIN a comment to a specific region** — anchor it to the element's id in `#spec`, not to raw
x/y, so the pin survives a reflow — with a resolve/done state, and an explicit **Approve** or **Request
changes** verdict per variant. Pins, resolve and an approve/request-changes verdict are the feedback
reviewers actually rely on.

**DO dock the picks/comments panel COMPACT and collapsed, so it never covers the mockup.**
**DON'T float it over the screen he is judging.**
TEST: he selects variants, comments and pins keep-or-change on each, sets a verdict, opens the panel and
copies, and the block names every pick, rejection, pinned comment and verdict.

## Share it, and run the LOSS-FREE review round-trip

The document goes to someone who is NOT Simon — a stakeholder, a teammate — and comes back with their
picks and change requests. Send the FILE (their Claude edits it directly, loss-free), or the artifact
URL when it is small and un-gated.

**DO make the document GUIDE a first-time recipient.** A short, dismissible intro on open explains: browse
the variants (grid → full view), select the ones you like, pin comments for changes, and set a verdict.
The guidance is part of the document; the recipient needs no briefing from Simon.

**DO make the copy-paste hand-off block BE the complete build spec — the verbatim `#spec` in an XML
instruction frame**, so nothing degrades on the round-trip:

```text
<task>
Rebuild a versioned UI mockup from the spec below. The <spec> JSON is the SINGLE SOURCE OF TRUTH.
Render it exactly. Do NOT paraphrase, summarise, invent, reorder, or drop any field.
Produce ONE self-contained HTML file. No external calls; inline or pin every dependency.
</task>
<spec> …the FULL #spec JSON, verbatim: manifest, designTokens, versions[] with before/after, selections,
comments, verdicts… </spec>
<build>
1. Embed <spec> unchanged as <script type="application/json" id="spec">.
2. render(spec): build the grid, focus view, filmstrip, HUD, compare/diff and comment UI PURELY from #spec.
3. Nothing user-visible may exist outside #spec; style only from designTokens.
</build>
<invariants>
- Output the ENTIRE file. No placeholders, no "// unchanged", no elisions.
- Every string in #spec must appear in the rendered output.
- versions rendered == manifest.versionCount; all manifest.variantIds present.
- When handing back, RE-EMBED the updated #spec verbatim — never a prose description.
</invariants>
<selfcheck>
Before returning: parse #spec from your own output, assert the three invariants, report each PASS/FAIL.
</selfcheck>
```

**DO instruct the recipient's Claude, inside that block, to:**
1. Apply the picks + comments as a NEW version — EDIT the file's `#spec` directly if they have the file,
   or REGENERATE from the block above if they only have the copied text. Change only the relevant `#spec`
   fields and re-render; reserve a full rebuild for when the render layer changes.
2. Increment the VERSION HISTORY in `#spec`, attributed: v1 is the author, v2 is this recipient, and so
   on — each version records who made it, when, and what changed.
3. Tell the recipient to LOOK at the updated mockup and confirm it reflects their asks.
4. Tell the recipient to PASS IT BACK to the original author (the updated file, or the fresh block).

**DO keep EVERY version inside `#spec` — the mockup carries its own history.** The HUD version selector
switches between versions, each attributed to its author, and the field-level diff (above) shows what
each version changed. The author receives ONE document and steps back through v1 (what they proposed),
v2 (what the recipient chose and asked for), and onward — variants and all — never a pile of files.
**DON'T flatten an old version away when a new one is made.** The trail — who changed what, and why — is
exactly what the author needs to resolve it.
TEST: the returned document opens on the latest version, the HUD lists every version with its author,
switching to an earlier version shows that author's variants + picks + comments intact, and the diff
marks what changed between any two.

## Cite where each part came from

**DO put a sources line in the spec**, naming the validated plan part, ticket or decision each visible
difference implements, by link.
**DON'T show a change with no source.** Anything unsourced is scope you invented, and this is the
cheapest moment to notice.

**DO refute, in the spec's own notes, any part that changed after validation** — what the plan said,
what it is now, and what the evidence was. He validated the plan; a silent divergence spends that trust.

TEST: every visible difference between before and after traces to a named source, or is explicitly
marked as a refutation with its reason.

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

**DO iterate on the mockup until he approves it.** Then the second half of this skill starts.

## After he approves: implement it, prove it matches

**A mockup is only worth what ships.** On 2026-08-11 an approved mockup was called implemented three
separate times with three different details still missing, and each was found by Simon opening the
real screen — *"how come you're still missing mockup details"*. The comparison had been done from
memory every time, so whatever was forgotten was invisible to the person forgetting it. That is the
failure this half exists to make impossible.

### Build the inventory BEFORE writing any code

**DO re-read the approved `#spec` top to bottom and write every visible difference as a numbered
row.** Each row names three things: what changes, the file that must change, and **the CALL SITE that
must pass it**. Rows come out of the spec, never out of your memory of the round. Walk every
storyboard step, not just the entry screen — a state reached only by clicking through is the one most
likely to be missed.

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

**DO tear down any scratch render rig you stood up to measure** — a temporary route or harness — in
the change that lands the work. The mockup document itself is not in the repo, so there is no dev route
to clean up.

## Report

Give him the mockup — the file path or the artifact URL — one line on what changed between before and
after, and the open questions as a numbered list, each with the option you would pick.
**DON'T ask him about anything the preview already answers.**
