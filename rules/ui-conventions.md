# UI conventions

<!-- Not path-scoped, and do not add `paths:` frontmatter back: it is silently ignored at
     user level and this file then never loads. Why, and how it was found: README.md § Path scoping. -->


## Scope

Applies when building or editing a user interface: `.tsx`, `.jsx`, `.vue`, `.svelte`, `.css`,
`.scss`, and any template that renders one. Nothing here applies to CLI output, logs, agent docs
or API responses. If the task is not UI, skip this file.

### Button order — negative LEFT, positive RIGHT
In any horizontal button pair, the **dismissive/negative** action goes on the **left** (first in the
DOM) and the **affirmative/positive** action goes on the **right** (last). This applies to:
- Cancel / Save, Cancel / Confirm, Discard / Apply, No / Yes, Back / Continue
- icon pairs: the **✗ (X / cancel)** is left, the **✓ (Check / save)** is right

Whenever you add or edit a button pair, order it this way; never put Save/Confirm/✓ before Cancel/✗.
shadcn `AlertDialog` already does this (`AlertDialogCancel` then `AlertDialogAction`) — follow the
same order in custom `DialogFooter`s and inline edit controls. (Vertical stacks are exempt — this is
about left/right horizontal pairs.)

### Label-first is the default for every region — new and edited (system rule)

A "region" = any titled block (section/card header, modal, step, settings row). The default holds when
a region is BUILT, not only edited — never left for a later sweep.

**DO** default every region to one LABEL — its title alone, 2-5 words, no verb ("Voice").
**DO** add a second block (`subtitle`/`description=`, or a `<p>` under the title) ONLY when it states
behaviour invisible on screen whose loss costs money, data, or a wrong choice — a price, a dry-run
"nothing was billed", an upload limit, a consent target. One line, once.
**DO** put occasional detail behind a disclosure (Details toggle), not inline.
**DON'T** ship a block that restates the title, a label, an adjacent control, or what a clickable thing
obviously does — new or edited. Delete it, don't shorten it; four cards need no "pick one".
**DON'T** let a container's subtitle go stale: a first-step description must still hold when a later
step replaces the body.

TEST: a title+subtitle region has NO subtitle, or one naming a cost/data/wrong-choice consequence.
Count blocks before/after — no drop means you compressed, not deleted. e.g. the app-wide sweep kept
only the billing, consent, dry-run and upload-limit subtitles.

### Illustrations are generated images, not hand-drawn SVG
**DO make every new illustration or scene a generated raster from the Codex subscription image
tool** (`references/agent-hosts.md` § Image generation, no spend). Hand-written SVG stays for icons,
logos and simple shapes.
TEST: no new illustration in the diff is a hand-authored `<svg>` path drawing.

### Motion where it fits, checked against the platform
DO add brief motion tied to the person's action without being asked (a dismissed card fades and
collapses, a state change cross-fades), only after checking the platform owner's guidance (Apple HIG
Motion, Material motion); off under Reduce Motion. DON'T animate on every screen open (rings, charts).
TEST: each new animation cites its guidance page and has a Reduce Motion path.
