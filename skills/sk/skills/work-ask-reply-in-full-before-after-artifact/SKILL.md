---
name: work-ask-reply-in-full-before-after-artifact
description: >
  Explain a confusing reply or compare proposals with compact BEFORE and AFTER cards.
  Show one proposed change per card with its context TLDR, what Accept and Decline do, and
  its BEFORE and AFTER, details collapsed; collect choices and comments with
  one Generate & copy action when the proposal asks for a response. Run it unprompted, in the
  same reply, whenever Claude proposes or recommends a visible change (copy, a notice, a layout
  tweak). Use for "show me a screenshot of the proposed change", "I don't know what you're
  talking about", "explain this so I can decide", "show me the design options", "give me a
  before and after design viewer", or an explicit /sk:work-ask-reply-in-full-before-after-artifact.
---

# Explain with proposal cards

DO build an artifact when Simon needs to see a design or compare options to understand a reply.
Set `feedback: true` when the proposal asks him to choose or comment; infer this from the task,
without asking him to enable it. Leave feedback absent for a pure design viewer.

## Build the artifact

DO author a spec and run `python3 ~/.claude/bin/decision-artifact.py build <spec.json> <out.html>`.
Use `example` for the schema and `extract <artifact.html> <spec.json>` for lossless CLI editing.
The builder composes `bin/presentation-shell.html`, shared with mockups and design boards. Do not
hand-roll chrome. Keep images inline as data URIs and behavior offline.

DO shape every card per `references/tldr-report-formats.md` § Before/after unit. Give each section
and card a unique `id`. Sections carry `title`, optional `lead` and `cards`. Cards carry `title` (the
change), `tradeoff` (the unit's context TLDR), `accept`, `decline`, `before`, `after`, `research` and
optional `detail`, which holds supporting evidence collapsed. Delete repeated What it does, Contrast and
Verdict paragraphs rather than shortening each one.
TEST: each collapsed card shows its title, research stamp and TLDR, one context line, Accept and
Decline lines and labelled BEFORE/AFTER previews, and no other prose; with `feedback: true`,
`decision-artifact.py build` refuses a card missing any of them.

DO attach real screenshots, captured per `/sk:ship-screenshot-changes` at desktop and 390 wide, to
every card whose option changes or keeps something a person sees. BEFORE is the current rendering
captured now. AFTER is the built rendering; for a not-built option it is a Preview rendered from the
real app code or an HTML/CSS overlay on the real screenshot per `/sk:ship-mockup-before-after`, made
per § Mock up each suggestion on the design tier when it changes a design, and labelled Preview.
Map width labels to image data URIs in `before` and `after`; `{text: "..."}` holds a concrete
code/config snippet. Omit previews only for a pure logic or data rule without a visible
surface. Never fabricate a missing capture or draw a stand-in.
TEST: every card whose option changes or keeps a visible surface carries a desktop and a 390px image
in before and after; a card with only text for a visible surface fails.

## Research every option online

DO research every option online before building its card, automatically and unprompted: find the
mainstream practice for that choice in primary sources per `references/research.md` § Source order
(the vendor's, platform's or standard body's own page) and attach `research` to the card:
`{"verdict": "recommended" | "not-recommended" | "mixed" | "unverified", "tldr": "<one line>",
"details": ["..."], "sources": [{"title": "...", "url": "https://..."}]}`. The viewer renders a
Researched stamp, the visible TLDR and a collapsed Research disclosure holding details and links.
NUMBER: a TLDR of at most 20 words, at most 3 detail paragraphs, at least 1 primary-source link on
every verdict except `unverified`.
DON'T cite a blog, forum answer or recalled fact; when no primary page settles it, set `unverified`
and say so in the TLDR. (e.g. an option to collapse detail cites the platform's own `details` docs.)
TEST: every card carries `research` with a source link, or verdict `unverified` with a TLDR stating
it; `decision-artifact.py build` refuses any other verdict without an http(s) source.

## Mock up each suggestion on the design tier

DO dispatch the design tier to create the AFTER Preview for every suggested option that adds or
changes a visible design (a layout, component or visual treatment) and has no built rendering: the
Agent tool with `model: "fable"`, or `model_route: design` from a GPT orchestrator, per
`references/parallelization.md`. Brief it with the real BEFORE capture path, the option, its research
TLDR and the PNG output paths; it builds the overlay with the app's own measured styles, renders both
widths to PNG and edits no app code. Launch one worker per option, all in parallel.
DO open every returned PNG on disk yourself, embed it labelled Preview and run `bin/visual-check.py`
on the built artifact before hand-back.
NUMBER: 1 design worker per option, 2 widths each; a copy-only text swap on the real page stays in
the main session per § Fast before/after.
DON'T draw a design Preview on the orchestrating or mid tier, or ship a Preview nobody opened.
TEST: every not-built design option's AFTER image traces to a design-tier output file and appears in
the visual-check pass table.

## Fast before/after for a proposed visible change

DO show a proposed or recommended visible change (UI copy, a notice, a layout tweak) as a BEFORE and
AFTER screenshot card in the SAME reply that proposes it, unprompted. Speed first:
1. BEFORE: reuse this session's capture of that screen and state when it still shows the current
   code; otherwise capture the real screen now from the running stack or preview.
2. AFTER: for a copy-only change, edit the text on that same real page in the test browser with the
   app's own classes and capture it at the same viewport, labelled Preview. A change of layout,
   component or styling goes to the design tier per § Mock up each suggestion on the design tier.
   Use a measured overlay per `/sk:ship-mockup-before-after` only when the state cannot be rendered.
3. Build one card per § Build the artifact, run `bin/visual-check.py` on it, return it through the
   session dashboard per § Hand back, and link the AFTER image path in the reply.
NUMBER: one card per changed region, the two widths above; target under 5 minutes from proposal to
linked artifact. Keep `mockup-build.py`, storyboards and design boards for a full mockup ask.
DON'T describe a visible change in words alone, or wait for Simon to ask what it will look like.
TEST: a reply proposing a visible change links a before/after card built that turn; a words-only
proposal fails (the fix for a sign-in notice proposed in words across three replies until Simon
asked for a screenshot).

## Collect a response

DO keep one Generate & copy button in the proposal's top-right corner, in a reserved row above the scrolling cards. Generate
from current choices and comments and copy in that same click. Show Copied only after clipboard
success; on failure show a selected, labelled manual-copy field in flow. Keep it hidden otherwise.
DON'T add a fixed footer, persistent response textarea, separate Generate/Copy actions or controls
that cover content. Keep native keyboard controls and 44px minimum height for the action.
TEST: changing a choice or comment then clicking again copies the new response; denied clipboard
access never reports success, and at 390px every card stays readable without overlap.

DO retain the full original `#spec`, including legacy control/runtime/comments metadata, unchanged
for CLI extraction and rebuilding. Those old fields stay inert; feedback uses only current inputs
and the explicit `feedback: true` flag. Keep pure mockups and design boards viewer-only.
TEST: absent feedback yields zero response controls; extract/build preserves metadata and images.

## Hand back

DO return the artifact through the existing session dashboard. Receive the copied response in chat
and update the spec from the agreed decision. Copying a response does not submit or approve it.
