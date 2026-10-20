---
name: work-ask-reply-in-full-before-after-artifact
description: >
  Explain a confusing reply or several design options with a read-only BEFORE and AFTER design viewer.
  Build headings, explanations, real previews and a verdict per option, grouped into sections.
  The artifact only displays designs; decisions, comments and answers belong in chat.
  Use for "I don't know what you're talking about", "explain this so I can decide",
  "show me the design options", "give me a before and after design viewer", or an explicit
  /sk:work-ask-reply-in-full-before-after-artifact.
---

# Explain with a design viewer

DO build an artifact when Simon needs to see a design or compare options to understand a reply.
Keep its responsibility to viewing. Ask for decisions and discuss comments in chat; the viewer has
no response generation, copy/submit buttons, editable fields, choice/include controls or export tools.

## Build the viewer

DO author a spec and run `python3 ~/.claude/bin/decision-artifact.py build <spec.json> <out.html>`.
Use `example` for the schema and `extract <artifact.html> <spec.json>` for lossless CLI editing.
The builder composes `bin/presentation-shell.html`, shared with mockups and design boards. Do not
hand-roll chrome. The frame owns theme and sidebar; section jump buttons navigate the cards.
Keep images inline as data URIs and behavior offline.

DO give each section and card a unique `id`. Sections carry `title`, optional `lead` and `cards`.
Cards carry `title`, `explainer`, `before`, `after` and `verdict`:
- Explain what the option does in plain language.
- Show current and proposed surfaces side by side, labelled with state and viewport width.
- Give the recommendation and its reason in one concise verdict line.

DO use real screenshots for a user-visible change, captured per `/sk:ship-screenshot-changes`.
Capture each state at desktop and mobile (390 wide), label a not-built state Preview, and show its
actual application rendering rather than a drawn stand-in. Map width labels to image data URIs in
`before` and `after`; `{text: "..."}` holds a concrete code/config snippet. A pure logic or data rule
without a visual surface says “No visible surface”. Never fabricate a missing capture.

## Keep data and interaction separate

DO retain the full original `#spec`, including legacy control/runtime/comments metadata, for CLI
extraction and rebuilding. Treat those fields as inert data. New specs need no `control` schema.
Do not initialize choices, collect feedback, mutate the spec while viewing or recreate old forms.

TEST: desktop and phone viewers show the designs with controls closed; only viewing navigation and
theme remain. No response textarea, comment box, radio/checkbox, select-all, counts, Copy spec or Save
HTML control exists. CLI extract/build preserves legacy metadata and rebuilds deterministically.

## Hand back

DO return the viewer through the existing session dashboard. Discuss the options and receive Simon's
answer in chat. Keep the artifact focused on the designs, and update its spec from the agreed decision.
