---
name: work-ask-reply-in-full-before-after-artifact
description: >
  When Simon is lost on what a reply means, or is weighing several options to decide among, answer
  with an INTERACTIVE decision ARTIFACT instead of chat prose: a plain-English explainer plus a
  BEFORE and AFTER preview and a verdict per option, grouped into sections. Every card and section is
  SELECTABLE with a COMMENT box, and Simon can PICK the items he wants and hand back exactly what he
  selected and commented (a copy-paste block, or a submit button when the runtime allows). Use for
  "I don't know what you're talking about", "explain this so I can decide", "give me the before/after",
  "make it selectable", or an explicit /sk:work-ask-reply-in-full-before-after-artifact.
---

# Reply as an interactive before/after decision artifact

Use when Simon can't tell what a reply means, or when a reply offers several options or changes he has
to choose among. Answer with a BUILT artifact he reads, selects from, and comments on, not a wall of
chat prose. Reference format: the "Borrowed Parts" artifact (explainer + before/after + verdict cards).

## Build it
DO apply the visual craft directly — no separate design skill to load: theme-aware light+dark,
self-contained (all CSS/JS inline), real content never lorem. The copy-paste response block (below) is
the default, always-available path; a submit-to-chat button is added only when the runtime is already
known to support a post-back to chat (see § Submit-to-chat).

Structure every thing under discussion as a CARD, grouped into SECTIONS (tiers):
- **What it does** — FIRST, a plain-English explainer that assumes Simon does NOT know the jargon.
- **Before / After** — where a change is involved, the current state beside a concrete preview snippet
  of the change (real config or code, side by side). Omit for a card that is pure explanation.
- **Verdict / why** — one line: the call and the reason.

## Make it selectable — a CHOICE is a radio, an INCLUDE is a checkbox (checked by default)
Two different decisions look identical if you give them the same control, and Simon has confused them.
Give each its own:
- **A CHOICE among mutually-exclusive options (pick ONE — option A vs B vs C)** → RADIO buttons in a
  named group, visually distinct (radio dots, exactly one selectable), so it reads instantly as "pick one
  of these," never as an include toggle. Pre-select the recommended option.
- **An INCLUDE / EXCLUDE edit (apply this change or not)** → a CHECKBOX, DEFAULT CHECKED. Every proposed
  edit starts applied; Simon UNCHECKS the ones he does not want (opt-out, not opt-in) — the default set
  is the recommendation, and unchecking is the exception.
- **DON'T use a checkbox for a pick-one choice, or a radio for an include** — that mismatch is the exact
  confusion this fixes.
DO give EVERY card a comment textarea, and every SECTION a select-all (over its checkboxes) plus its own
comment textarea, so Simon can act on one item or a whole section.
TEST: a pick-one choice shows radio buttons with one pre-selected; every apply/edit checkbox starts
checked; the two controls never look the same.

## The response contract — never lose a keystroke
DO include a "Generate my response" button whose self-contained JS assembles ONE delimited,
copy-pasteable block, shown in a readonly box with a Copy button. The block MUST carry, with zero
ambiguity:
- a header naming the source artifact,
- **Choices:** each radio group with the option Simon picked, as `group → chosen — comment`,
- **Kept edits:** each checkbox left CHECKED (the default), as `edit — section — comment`,
- **Dropped edits:** each checkbox Simon UNCHECKED, plus any comment on it, same shape,
- **Section comments:** any whole-section notes.

DO put EVERY non-empty input into the block — every selection AND every comment, on selected cards and
unselected ones alike. A comment on a rejected option, or on no option at all, is a first-class answer.
TEST: type a comment on an unselected card, hit Generate, and it appears in the block; if it does not,
the contract dropped input.

DO let Generate run with nothing selected. A no-pick-plus-comment (a question, a redirect) is a valid
response. DON'T gate Generate on a selection — that is how a real answer gets thrown away.

DO make every keystroke impossible to lose — all three, always:
- **Hold every field in in-memory state as the source of truth:** keep EVERY input — every radio and
  every textarea — in one JS state object the Generate block reads from. Do NOT use
  localStorage/sessionStorage: they are BLOCKED in the Claude artifact sandbox and fail silently. The
  always-visible block below, not browser storage, is what makes the input impossible to lose — so tell
  Simon to copy it before he reloads.
- **Always-visible block:** Generate renders into a visible, selectable, readonly textarea, so Simon can
  select-all and Cmd-C by hand even if the button does nothing.
- **Copy that reports:** the Copy button tries `navigator.clipboard.writeText`, falls back to
  `execCommand('copy')`, and shows "Copied ✓" only on success — else "Press Cmd-C", so a silent
  `file://` failure is visible, not lost.

DO keep that JS free of external calls, so it works with zero runtime capabilities. This is the
always-available path; never make it the fallback.

## Submit-to-chat — only when the runtime allows
DO wire a "Submit to chat" button ONLY when the runtime is already known to support a post-back to chat
(e.g. a claude.ai artifact); it emits the SAME block. A Claude Code terminal artifact — an HTML file
opened in the browser — has no such post-back, so there the copy-paste block stands alone. Never make
submit the only path.

## Hand-off
The artifact is the deliverable. Simon pastes his response block (or submits it) and the chat acts on
exactly his selections and comments — TEST: the pasted block names each pick, each rejection, and each
comment with its section, so nothing he chose is ambiguous.
