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

### Default to a label. Cut the NUMBER of text blocks, never just their length.

**Count the prose blocks in a region before and after your edit. If the count didn't drop, you
compressed instead of deleting and the screen is still cluttered.**

- **One text block per region, and it is a LABEL: 2-5 words, no verb.** "Read from Acme". "Voice".
  "3 locations". Never a sentence.
- **A sentence is allowed only when it states behaviour invisible on screen AND losing it costs
  money, data, or a wrong choice.** One line, once, never a second under it.
- **Detail needed occasionally goes behind a disclosure.** Label + Details toggle; the paragraph
  moves inside.
- **Delete outright, do not shorten, any block that restates a label, a placeholder, an adjacent
  control, or what a clickable thing obviously does.** Four clickable cards need no "pick one".
- A container's subtitle must hold for every state it renders: a modal description written for the
  first step goes stale when a later step replaces the body under it.
