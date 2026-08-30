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

**DO make EVERY deliverable open from `file://` with no server — self-contained, no external requests,
no sibling-file dependencies — whether it is one `#spec` document or the consolidation gallery over many
files (§ below).** The same anti-pattern as the dev route above, one level up: a gallery that needs
`http://localhost` to show its tiles hands a recipient blank tiles.
TEST: with every server off, opening the file renders it fully. A deliverable that needs a running
server is not shareable and is not done.

A change with NO screen — a schema, a prompt harness, a pipeline ordering — has nothing to screenshot;
diagram the before and after instead. The rule is the medium follows the subject.

**When the screen ALREADY EXISTS, the BEFORE is that real screen — always.** A "blind", "exploratory"
or "independent-directions" round is free to reinvent the LAYOUT, but it NEVER licenses a fabricated,
generic, or from-memory before/after. The BEFORE is the real screenshot (or the real component
measured); the AFTER's tokens, chrome and theme trace to the measured real app; only the layout is
open. The no-screen escape above is ONLY for a surface that does not exist yet. Round 1 of the RR
redesign was run blind with zero app grounding and every direction was rejected for not looking like
the product — the exploration belongs in the layout, not in the fidelity. TEST: the BEFORE traces to
the real screen, and every colour/font/radius/theme in the AFTER traces to a measured value, even in a
blind round.

## One mockup file per surface — a new exploration is a new variant, never a new file

**DO keep every exploration for one surface inside the SINGLE existing mockup file for that surface: a
new idea, a section redesign, or "another version of X" is a new switchable variant (or version) added
to that one file.** The file runs N switch axes at once — a PERSONA / data axis (which captured page or
seeded state is shown) and a per-section DESIGN-VARIANT axis (each region's alternative designs). A
section variant is swapped INTO the live captured page in context via a nested `iframe.srcdoc`, and the
`Current` option restores the pristine capture, so a redesign is judged against the real surrounding
page. Adding "versions of another part of the page" is adding another SECTION entry on the design axis,
still in the one file.
**DON'T create a second mockup file for a new idea, a section redesign, or another version** — no
`*-redesign.html`, no `*-variants.html` sibling. A second file splits the exploration so he can no
longer flip between versions of any part of the page in one place, which is the whole reason the single
file exists. The fix for exactly that: fold both spun-off files back into the one gallery, where the
redesigned region is just one more SECTION with its variants on the design axis.
DEFAULT: one mockup file per surface, forever; every later exploration lands in it as a variant/version.
TEST: after any mockup iteration, the surface still has exactly ONE mockup file and the new exploration
is reachable as a variant/version toggle inside it; a second `*-mockup`/`*-redesign`/`*-variants` `.html`
file for the same surface is the violation.

## One stable link — the mockup's path never changes across iterations

**DO give the surface's mockup ONE canonical entry point whose path never changes — a fixed filename, or
a stable alias like `mockup.html` that always resolves to the current build — and write every rebuild IN
PLACE to that same path.** Simon bookmarks it once and hits refresh; the link he opened last round opens
this round's build.
**DON'T rename the file, and DON'T point "the current version" at a new filename across iterations** — no
`-redesign` today, `-variants` tomorrow, `-gallery` the day after. A renamed file breaks the bookmark and
sends him hunting for the new one every round.
WHY: the single-file discipline (§ above) exists so he flips between versions in ONE place; a path that
moves defeats it before he even opens the file.
DEFAULT: one fixed path per surface, forever; a rebuild writes over it, never beside it under a new name.
TEST: the path Simon opens is byte-identical across every iteration (the fix for a mockup he had to
re-find when a `-redesign` file became a `-variants` file became a `-gallery` file); a rebuild that makes
him find a new filename is the violation.

## Variants while EXPLORING; a DECISION collapses to a default

**DO turn every design option you would otherwise ASK about into a VARIANT in the mockup — the user picks
from the mockup's own variant switcher + pick/comment UI, never from a chat question.** Whenever you can
see two or more ways to do a design thing (a shape, a layout, a scroll model, a colour, a placement),
build ALL of them as variants and ship them together in the one mockup. A design suggestion is a variant,
not a question.
**DON'T ask a design-decision question in chat — no AskUserQuestion "A or B?", "which layout?", "which
colour?".** Showing beats asking; that is the whole point of a mockup. Only forks a mockup CANNOT answer
stay chat questions (build-now-vs-mock-first, which repo, a credential, prod approval).
DEFAULT: N design options → N variants in the mockup; zero design-choice questions in chat.
TEST: every option you considered is a variant in the mockup and no chat message asks the user to choose
between design alternatives (the fix for asking a sidebar A/B and a scroll model in chat instead of
rendering them as variants).

**DO offer multiple variants to choose from ONLY while an open question is still open.** The moment Simon
picks one — or when the change was a decided edit from the start, never an exploration — make the chosen
design the DEFAULT the mockup OPENS ON, and demote every superseded design to a labelled `Before — …`
reference.
**DON'T keep a decided change as one equal option among many, and DON'T leave the mockup opening on the
old design after a decision.** Once he picks "severity-tiered list" it is THE view, not option 4 of 10; a
2→4 tab split that was decided up front opens on the 4-tab design, not as a "Current vs New" toggle
defaulting to the 2-tab.
WHY: a settled design shown as one equal option reads as still-open and invites re-litigating what he
already decided.
DEFAULT: exploring → N variants; a decision, or a decided-from-the-start edit → the chosen design is the
open-on default, the old kept only as a before-reference.
TEST: after Simon states a decision, the mockup opens by default on the chosen/decided design with the
old kept only as a labelled before-reference; a decided change presented as one of N equal options, or a
mockup still defaulting to the superseded design, is the violation.

## Ask for the direction FIRST — reference images

Before designing an AFTER, ASK the user for reference images of interfaces they like — it is the
fastest route to a direction they accept and it stops you inventing one they reject. Suggest they
browse **Dribbble** (dribbble.com) and copy-paste the shots or directions they want to emulate (app
screenshots work too). Ground the AFTER in those references — reproduce their layout, hierarchy and
component patterns — alongside the real app's measured tokens. When references exist, PASS EVERY ONE to
each builder by absolute path and have the builder READ them before designing; a reference that
silently never reaches a builder wastes the whole round, so **FAIL LOUD** — stop and report which
reference is missing — rather than building without it.

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

**DO CAPTURE an existing screen as a 1:1 self-contained HTML first — that capture IS the before-base,
not a screenshot to rebuild from.** A headless real browser (Playwright) authenticates via the project's
own auth path and navigates to the seeded screen; then SingleFile (gildas-lormeau) serialized IN-PAGE —
inject its `single-file-bundle.js` with `addScriptTag`, call `singlefile.getPageData({ blockScripts:true,
… })` — inlines every stylesheet, font and image as a `data:` URI. The output opens from `file://` with
ZERO external requests and is pixel-identical to the live render, because it IS the render, not a
re-description of it.
**DON'T rebuild an existing screen from component code + measured styles.** A rebuild drifts on exactly
the details invisible to the rebuilder: the fix for a mockup that showed a fabricated "$1,088/Pending"
where the real account read "Free access", and dropped a real banner and two table rows — each caught
only by capturing the real page. Reserve the screenshot-raster + measured-styles path below for a surface
that does NOT exist yet, or for building the AFTER overlay on top of a capture.
TEST: for an existing screen, the before-base opens offline with 0 external requests and every string on
it traces to the live render, not to a component read.

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

**DO fan out the capture across parallel agents and separate seeded accounts by default.** Each
persona/state is an independent seed→capture, so run them at once — one agent per state, on its own
seeded account where two or more exist, falling back to a sequential re-seed on ONE account only when no
second account is available. Parallelise the other independent steps (seeding, verifying, the per-tile
checks) the same way.
TEST: N persona states are captured by N concurrent agents, not a serial loop, whenever N accounts exist.

**DO offer real PRODUCTION merchant profiles as preview personas when the value is seeing REAL data.**
Read a merchant's owner-scoped records from prod with a READ-ONLY key (never write to prod, never
authenticate as a prod user), copy them into a dev account with the owner id remapped, and capture on
DEV — so the page renders the real data under dev auth while prod stays untouched. Copy EVERY collection
the screen reads, not the obvious ones: a page that reconciles money reads more than the funnel does (the
fix for a capture that showed "0 recovered" in the funnel while the commission card read $1,617 — a
rolling measurement snapshot plus its `saves` subcollection were the missing sources; grep the page's
hooks for every read before copying). Preserve the doc IDs any cross-doc reconcile depends on (a snapshot
row keyed to an enrollment id), and write a connected-state stand-in for a live provider connection that
cannot be copied. Capture the TAB that shows the data — a merchant whose primary tab is empty renders its
real numbers on another tab, so click into it before serializing.
TEST: the dev-rendered page reconciles to the same numbers prod shows, and prod received zero writes.

**DO re-inject a SMALL interaction layer into a static capture so the components that COLLAPSE or toggle
still work.** SingleFile strips the app's JS, so the capture is frozen — but the rendered DOM keeps its
`data-testid`s and framework classes, so a tiny injected script re-wires the interactions whose content
is present in the captured DOM (a collapsible panel: on the header's `data-testid` click, toggle the
framework collapse body). An interaction whose target content is NOT in the capture — a TAB whose other
view never rendered — needs a per-tab capture (capture each tab state, swap between them), not a re-wire.
TEST: the injected layer toggles the collapsible in the captured page; a tab-switch either swaps between
per-tab captures or is left frozen with a note, never a dead control.

## Measure the real components — never eyeball the AFTER

**DO measure the real rendered components before drawing anything** — `getComputedStyle` and
`getBoundingClientRect` for box size, font, colour, spacing, border-radius, shadow — and size the
AFTER from those exact values, stored in `#spec`. The app itself is the render rig; stand up a scratch
route ONLY when a component the AFTER needs is not reachable on any real screen.
**DON'T set a dimension, colour or font in the overlay by eye.** Eyeballing is the nearly-right failure
that got the rebuild rejected; a measured value cannot be nearly right.
TEST: every dimension and colour in the overlay traces to a value you measured this run.

**DO give every inline SVG icon an explicit width/height** — or a clamping rule on its container
(`.x svg{ width:16px; height:16px; flex:0 0 auto }`). An SVG authored with only a `viewBox` and no
dimensions expands to fill its flex parent, so a nav "+" renders as a full-width square. TEST: no
reconstructed icon renders larger than its measured size.

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
separate design skill to load: give the page a title, a favicon, a palette and theme support that MATCH
THE REAL APP'S — measure it, and if the app wires no dark theme, the mockup is light-only; never impose
a light+dark the product does not have — a responsive layout, and realistic seeded content (never lorem).
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

## The consolidation gallery (many self-contained files → one review surface)

When a fan-out (e.g. `/sk:work-hyperspeed`) produces N self-contained mockup FILES rather than one
`#spec` document, the gather builds ONE review gallery over them.

**DO make that gallery a self-contained single file BY DEFAULT — INLINE every mockup into it.** Embed
each file's HTML in a `<script type="application/json" id="mocks">` island and point each iframe at
`fr.srcdoc=MOCKS[key]`, never `fr.src=<sibling-path>`. `about:srcdoc` is same-origin to the gallery, so
every tile renders from `file://` AND the gallery's cross-frame controls still reach in.
**DON'T hand over a gallery that iframes sibling files over `http://localhost`** — `file://` blocks
cross-origin iframes, so a recipient who opens it gets blank tiles (the fix that re-inlined
`gallery-share.html`: 8 mockups inlined, verified rendering on `file://` with zero server). Serving over
http is a DEV convenience for fast cache-busted refresh while you edit the mockups; RE-INLINE before
handoff so the at-rest deliverable always opens standalone.
TEST: open the gallery from `file://` with the server OFF — every tile still renders.

Build it with these controls BY DEFAULT:

- **Bird's-eye GRID with CONFIGURABLE columns (1 / 2 / 3 per row).** Each tile is a small DESKTOP view —
  render the mockup at ~1440px and scale it to fit the tile; NEVER render it narrow (that trips the
  mockup's own mobile breakpoint and looks squished). On a column change, re-scale to the new tile width.
- **Each tile SCROLLS INDEPENDENTLY** — scale the full page into a `scaleinner` sized to the scaled
  height, tile `overflow-y:auto`, iframe `pointer-events:none` so the wheel scrolls the tile and a click
  opens it. He can then scroll two tiles to different sections and compare them.
- **A GLOBAL VIEW (before/after) + SURFACE nav that drives ALL tiles at once.** The fanned-out parts are
  CONTENT-ONLY (no per-part HUD) and expose `[data-mode="before|after"]` + CONSISTENT `[data-surface]`
  values; the gallery hides each part's own control bar and clicks those hooks in every tile, so
  "switch all variants to surface X" is one click.
- **Click a tile → FOCUS** (full-size, filmstrip rail, ←/→/Esc/Home/End) → **Present** (full-screen).
- **A FLOATING HUD** — fixed, styled with none of the app's tokens — showing view · variant N of M ·
  version. NEVER put it inside the header: a wide header scrolls it off-screen and reads as "no HUD".
- **Keep/comment + an Approve / Request-changes verdict per variant**, using the response contract of
  `/sk:work-ask-reply-in-full-before-after-artifact`.
- **A QUIET version box** (per § versioning) — each consolidation checkpoint is a version, newest active.
- **Tile height scales with the column count:** 1 column = one variant fills the screen and must FIT
  without overflow (leave room for the header + tile cap so a single tile needs no page scroll); 2 =
  ~half screen; 3 = a cozy default (~340px). Switching the focused variant RESETS its scroll to the top.
- **Place the floating HUD OFF the mockup's own chrome** — a corner clear of the app's action buttons,
  raised above the filmstrip in focus (it once sat over the app's Upgrade / Buy-Credits buttons).

**CLASS-OF-BUG to avoid: an id selector that sets `display` on a view overrides the `.view{display:none}`
toggle.** `#compare{display:flex}` kept an empty pane displayed over the grid on ALL views — a whole
"blank grid" was actually a gray overlay on top. Scope every view's display to its `.show` class
(`#compare.show{display:flex}`), and when a view looks blank, `elementFromPoint` the empty area before
assuming lost content. Verify the gallery in the browser before handing it over — including a `file://`
open with the server off — and cache-bust the reload (`?t=`) or a served gallery hands you the stale
file mid-iteration.

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

## Version every iteration — grouped, latest-active, and QUIET

Versions are not only for the external round-trip above — every LOCAL iteration checkpoint is a version,
so you can watch your own progression as you edit. The hyperspeed fan-out → consolidation is the
canonical case: each fanned-out pass saves its variant stamped with the CURRENT version, and the
consolidation groups all same-version variants into ONE version group. So each consolidation checkpoint
is one version (round 3 = v3, round 4 = v4, …), each holding that round's variants; the next round
APPENDS the next version rather than overwriting, and older versions stay reachable to show the
progression.

**The newest version is always active; older versions are for looking back only** — open on the latest
version's variants. **Keep the version control COMPACT and quiet — it is NOT a primary interface
element:** a small, low-prominence affordance in a corner (a tiny `v4 ▾` stepper), visually quieter than
the variant switcher, that never obscures the design and is reached only on demand. TEST: the version
control is a small corner affordance, the newest version is active on open, and switching to an older
version shows that version's grouped variants intact.

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

**DO open the finished mockup where its JavaScript actually RUNS, and look at it, before handing it
over** — a real browser, or copy it into the project / serve it over http. A mockup file written to a
scratch dir OUTSIDE the project renders as a STATIC snapshot in the preview pane: the `<script>` never
executes, so the JS-built grid, overlay and controls are invisible there and a blown-up icon or overflow
ships unseen. TEST: you have viewed the rendered mockup with JS run and confirmed no icon is oversized
and nothing overflows, before sending.

**DO fix the CLASS and fold it forward.** When a divergence traces to how this skill works — a
measurement it skips, a token it never reads, a state it forgets — propose the durable fix to this skill
through `/sk:claude-config-update` so the next mockup is exact from the first render. That is the
`self-healing-config` loop.

**DO iterate on the mockup until he EXPLICITLY confirms implementation — mockup-only, no platform
changes, in a loop.** Every change he asks for lands in the MOCKUP (re-capture, re-inject, edit the
spec), never in the app, and the loop continues until he says to implement in his own words ("implement",
"build it", "go build", "the mockup is approved"). A green mockup he has not signed off is not approval;
do not touch app source before the word. Then the second half of this skill starts.

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
