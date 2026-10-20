---
name: work-ask-reply-in-full-before-after-artifact
description: >
  Explain a confusing reply or compare proposals with compact BEFORE and AFTER cards.
  Show one tradeoff per option with details collapsed; collect choices and comments with
  one Generate & copy action when the proposal asks for a response. Use for
  "I don't know what you're talking about", "explain this so I can decide",
  "show me the design options", "give me a before and after design viewer", or an explicit
  /sk:work-ask-reply-in-full-before-after-artifact.
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

DO give each section and card a unique `id`. Sections carry `title`, optional `lead` and `cards`.
Cards carry `title`, `tradeoff`, optional `detail`, `before` and `after`. Default to a 2–5 word title
and one tradeoff sentence of at most 25 words. Put supporting evidence in collapsed Details.
Delete repeated What it does, Contrast and Verdict paragraphs rather than shortening each one.
TEST: each collapsed card has at most one prose block alongside its title and labelled previews;
that block states a consequence that changes the choice.

DO use real screenshots for a user-visible change, captured per `/sk:ship-screenshot-changes`.
Capture each state at desktop and mobile (390 wide), label a not-built state Preview, and show its
actual application rendering rather than a drawn stand-in. Map width labels to image data URIs in
`before` and `after`; `{text: "..."}` holds a concrete code/config snippet. Omit previews for a pure
logic or data rule without a visible surface. Never fabricate a missing capture.

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
