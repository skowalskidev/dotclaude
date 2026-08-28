---
name: work-humanize-copy-side-by-side
description: Reword an interface's copy in your OWN voice through a two-pane side-by-side tool, then write the humanized text back into the source. Point it at a React/TSX interface (e.g. the landing page); it extracts every user-facing copy string, captures the real rendered screen 1:1 as an on-the-left reference, and builds ONE self-contained HTML file where the LEFT pane is the real screenshot with numbered anchors and the RIGHT pane is editable fields seeded with the original copy, each numbered to match its spot on the left and hover-paired to it. You reword only the fields you want and leave the rest; on hand-back it writes every string back into the .tsx/.ts files it came from. Because untouched fields still hold the original, apply is a safe blanket overwrite (no diffing) and every write is verified present in source afterward. Reuses the data-island and loss-free hand-back mechanics of /sk:ship-mockup-before-after; seeds voice guidance from rules/copy-quality.md but never auto-rewrites, you write the words. Use for "humanize this copy", "reword the landing in my voice", "side-by-side copy editor", "let me rewrite the UI text", "extract the copy so I can edit it", or /sk:work-humanize-copy-side-by-side.
argument-hint: "[interface path or feature dir, e.g. app/features/landing]"
---

# Reword the copy yourself, side by side, then write it back

**Why this exists:** you write copy in your own voice better than any model, but the copy is scattered
across twenty TSX components mixed with URLs, class names and props. Reading each file to find the
human-facing strings, editing them in place, and not breaking the JSX is the friction that stops you
doing it. This tool pulls every copy string out, shows the real screen beside it so you keep the
context, lets you rewrite only what you want, and writes your words back into the exact source
locations, so the whole job is "read the screen, type better words".

**This is a HUMAN-in-the-loop tool, not an auto-rewriter.** The skill extracts, presents, and writes
back. YOU supply the words. `rules/copy-quality.md`'s ban-list seeds optional suggestions when you ask
for them; the skill never replaces your voice with its own.

## What it reuses, do not rebuild it

`/sk:ship-mockup-before-after` owns the mechanics this shares. Read it and reuse them, never restate:

- **ONE self-contained HTML FILE**: inline all CSS/JS, screenshots as compressed `data:` URIs, opens
  from `file://` with no server. Not a Claude artifact (a full-page screenshot blows the size ceiling).
- **The `#spec` data island**: one `<script type="application/json" id="spec">` that IS the entire
  state; a small `render(spec)` builds the UI from it. Nothing user-visible lives outside `#spec`.
- **Capturing the real screen**: screenshot at a fixed viewport, one theme, realistic seeded content;
  compress HARD (WebP q70-80, downscaled) before inlining.
- **The loss-free hand-back block**: the verbatim `#spec` in an XML instruction frame, so the edited
  copy survives the round-trip with zero paraphrase.

This skill OWNS three things that skill does not: extracting copy from TSX, the two-pane REWORD layout
(editable fields seeded with originals), and writing the reworded strings back into source.

## Step 1: extract every user-facing copy string from the interface

**DO read the target TSX/TS files and pull out the human-facing copy, each recorded as a spec entry**
`{ id, file, line, kind, anchor, original, value }` where `value` starts equal to `original`:

- `id`: stable, sequential (`c1`, `c2`, …); it is the number shown on both panes.
- `file`: repo-relative path the string lives in.
- `kind`: `text` (JSX text node), `attr:<name>` (a copy-bearing prop: `aria-label`, `alt`,
  `placeholder`, `title`, `label`), or `data` (a string in a copy-bearing data/const file).
- `anchor`: how apply re-finds this exact string, the `original` plus enough surrounding context
  (the enclosing element/prop, and an occurrence index) to make the match UNIQUE within `file`.
- `original`: the exact source string, unescaped to what the user sees.

**DO include copy that lives in data files, not only JSX.** Landing copy is split across section
components AND `*Facts.ts`-style constants (e.g. `app/features/landing/pricingFacts.ts`). A string a
user reads is copy wherever it is declared. TEST: a headline defined in a `const` and rendered by a
section appears once, keyed to the `const` file.

**DON'T extract non-copy.** Skip URLs, `className`/`style` values, `src`/`href`, keys, ids, test-ids,
enum/route literals, numeric tokens, and anything a user never reads. TEST: no extracted entry is a
URL, a class name, or a style value.

**DO de-duplicate by (file, anchor), not by text.** The same word ("Pricing") in two places is two
entries with two anchors, so rewording one never silently changes the other.

## Step 2: capture the real screen 1:1 for the LEFT pane

The left pane is the interface **as it actually renders**, so you reword against an accurate picture,
never a reconstruction that drifts.

**DO screenshot the running page** (per `references/dev-server-hygiene.md` for the server, and
`references/browser-debugging.md` if a screen is auth-gated, the public landing is not). Capture the
full page at a fixed desktop viewport with realistic content, compress hard, inline as a `data:` URI.
For a long page, capture per section and stack them, so each numbered anchor sits on a sharp,
readable slice rather than one giant downscaled raster.

**DO overlay a numbered anchor on each captured string's location**: a small pill (`①②③…`) positioned
over where that copy sits in the screenshot, matching the `id` on the right pane. Anchor to the
measured position of the text in the capture.

**DON'T rebuild the screen from the extracted markup as the reference.** A remade screen is nearly
right, and nearly right defeats the point of having an accurate picture. The reference is the real
capture; the editable side is where the reconstruction (fields) lives.

## Step 3: build the two-pane HTML file

One self-contained file, `#spec` holding every entry from Step 1 plus the capture(s) and design tokens.

**LEFT pane (reference, read-only):** the real screenshot(s) with the numbered anchors. Scrolls. Never
editable.

**RIGHT pane (reword, editable):** one field per spec entry, in document order, each showing:
- its number (matching the left anchor),
- the ORIGINAL text as a quiet, non-editable caption (so you always see what you're changing),
- an editable textarea **seeded with the original** (`value`), where you type your version,
- a per-field "reset to original" control and a "changed" dot when `value !== original`.

**DO pair the two panes on hover/focus.** Hovering a right-pane field highlights its left-pane anchor
(and vice-versa), and clicking a field scrolls its anchor into view. This is the "where is this text"
answer. TEST: focusing field ⑦ highlights anchor ⑦ on the left and scrolls it into view.

**DO keep the ORIGINAL visible next to every field**, per the ticket: placeholders are seeded with the
original, so an untouched field already holds it and you can see the original you're rewording.

**DO float all tool chrome (progress, export, filters) OVER the panes, styled with none of the app's
tokens**, so scaffolding never reads as product. Give a filter to show only changed fields.

**DON'T require every field to be touched.** Leaving a field at its seeded original is the expected
case for most of the copy.

## Step 4: hand back the reworded spec

**DO export the loss-free hand-back block** (the `/sk:ship-mockup-before-after` XML-framed verbatim
`#spec`), with each entry's `value` carrying your reworded text (or the untouched original). The block
is the complete, paraphrase-proof record of what to write back. You paste it into the session that
applies it, or, when running the skill live in one session, apply directly from the in-memory `#spec`.

## Step 5: apply, write the reworded copy back into source

**DO overwrite blindly, no diffing.** Untouched fields hold the original, so writing `value` for every
entry is a no-op wherever nothing changed and the correct write everywhere it did. This is the ticket's
override behavior: a blanket overwrite is safe by construction.

**DO write each string at its `anchor`, matched UNIQUELY.** For each entry, find `original` in `file`
scoped by its anchor context/occurrence and replace it with `value`. When a match is not unique after
applying the anchor context, STOP on that entry and report it rather than guessing. A wrong-location
write is worse than a skipped one.

**DO preserve JSX/TS validity.** Re-escape for the context you write into: `{" "}`-style spacing,
entities (`&amp;`, `&apos;`), quotes inside a string prop, and curly-brace text vs attribute strings.
A reworded apostrophe must not break the file's parse.

**DON'T touch anything outside the extracted strings.** No reflow, no reformat, no reordering, only the
copy strings change.

## Step 6: verify every write landed

**DO confirm each written `value` is present in its `file` after the pass** (grep the exact string),
and run `npm run build` + `npm run lint` (or the project's equivalent) so no rewording broke the parse
or a lint rule. Report any entry that did not land or that was skipped as non-unique.
TEST: every changed entry's new text is found in source, the build is green, and the skipped list (if
any) is shown to you with the reason.

## Report

Give the user: the HTML file path, a count of strings extracted / reworded / written / skipped, and
any skipped entries with why. Then, when a build ran, its result in one line.

## Fold the fix forward

When a divergence traces to how this skill works, an extraction that misses a copy kind, an anchor
scheme that mis-locates a write, a capture that drifts, propose the durable fix to this skill through
`/sk:claude-config-update`. That is the `self-healing-config` loop.
