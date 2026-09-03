---
name: ship-screenshot-changes
description: Quickly screenshot the changed frontend surfaces for documentation — no bug-hunting, no waiting for anything you don't need. Figures out what changed (git diff), seeds the account into the state the change is meant to be seen in, drives each changed surface in a real debug browser with realistic example inputs, captures each at BOTH desktop AND mobile (390×844) widths — circling the change with a rounded-rectangle callout, and for a visual change a BEFORE/AFTER pair — hands them back (opened in Finder), and — opt-in, only with an open PR and Simon's yes — posts them (desktop + mobile per surface) onto the PR (GitHub-native: gh --attach or the user-attachments CDN, a git-only detached-ref fallback, never an external host). Use for "screenshot the changes", "screenshot changes", "doc the new UI", "capture the new screens", "grab screenshots of what changed", "circle the changes", "before and after screenshots of the change", or "post the screenshots to the PR". Has a JOURNEY mode that captures a user FLOW as an ordered, numbered step sequence (steps derived from the user journey) instead of isolated surfaces — also triggers on "screenshot the user flow", "screenshot the user journey", "show the flow steps". Reused by /sk:test-eyeball for its capture + PR-post; test-eyeball adds the bug-hunt loop on top.
argument-hint: [optional focus, e.g. "the new dashboard section"]
---

# Screenshot the changed surfaces — fast, for docs or a PR

Get the changed frontend surfaces on screen in a real browser, in the state a user would actually see
them, and capture one clean screenshot of each. No bug-hunting, no edge fuzzing, no fix-loop — that is
`/sk:test-eyeball`, which reuses THIS skill for the capture. This is the fast path when you just want the
new things pictured, without waiting for a full QA sweep.

## Step 0 — Log in to the running app (project-specific)

**Read `~/.claude/references/browser-debugging.md` AND the project's `CLAUDE.local.md` FIRST — before
improvising any auth.** They are the definitive login+screenshot how-to; the reference holds the pattern
that actually works and the project file holds the test account + token recipe. Reaching for a hand-rolled
session instead is the trap: a session written straight into browser storage usually does NOT restore
(the app's own auth listener never fires, so a client guard still bounces you), which burns a long time
before you read the docs that already answer it. Never type a real password into a login form; use the
project's documented token/impersonate recipe. If the project has no recipe, get a logged-in session the
cheapest safe way (attach to an already-signed-in debug Chrome, or ask for a one-time manual login in the
debug window) and add the recipe you worked out to that project's `CLAUDE.local.md` so it's instant next time.

Debug browser = chrome-devtools MCP attached to a Chrome launched with
`--remote-debugging-port=9222 --user-data-dir=<throwaway>`.

**Take a lane before booting anything, and before claiming 9222.** Several sessions run at once and all
want the same ports, so `~/.claude/bin/port-slot.sh` gives this worktree its own set and
`~/.claude/references/dev-server-hygiene.md` has the protocol (preflight, identity handshake, teardown).
Without it the app you screenshot may be another branch's. **On teardown, scope every process-kill to
THIS worktree's/session's path** — a broad pattern (the app or repo name) can match and kill another
running session's server.

**Authorize the browser before driving it: `touch ~/.claude/.browser-authorized`.** That sentinel is
what `hooks/browser-launch-guard.py` reads to allow `navigate_page`/`new_page` — invoking this skill IS
the user's approval, so drop it here rather than making them set an env var. `rm -f
~/.claude/.browser-authorized` in the teardown step, so the guard returns to blocking an unrequested launch.

## Step 1 — Figure out what changed

`git diff` the branch vs its base. List the exact frontend surfaces the change touches (routes,
components, states, inputs). Those are what you drive — don't wander the whole app.

## Step 2 — Seed the account into the state the change is meant to be seen in

A surface only renders meaningfully once the account is in the state a real user would be in when they'd
actually see it — not an empty or default account. Work out that state from the change itself, then put
the account there with the data such a user would have, so the screenshot shows the ACTUAL experience.
Seed it the project's documented way (Firebase MCP, a seed script, the API), scoped to the right project,
and record the seed recipe in the project's `CLAUDE.local.md`.

## Step 3 — Drive each surface with REALISTIC inputs and screenshot it

For every changed surface, put it in the realistic happy-path state a merchant/user would actually see —
the inputs they'd type — and `take_screenshot({filePath})`. One clean shot per surface with the example
inputs visible; that shot IS the documentation. Save screenshots INSIDE a workspace root (a repo path,
e.g. `.context/…`), never `/tmp`. Use `evaluate_script` for DOM/state, not `take_snapshot` (which dumps
tens of KB). No edge inputs, no bug-hunt here — `/sk:test-eyeball` adds those.

**Circle the change so the reviewer sees what moved.** A bare surface shot makes them hunt for it. From
the changed element's `getBoundingClientRect()`, inject a fixed-position overlay `<div>` sized to it (a
few px border, rounded corners, a soft box-shadow ring, `pointer-events:none`, top `z-index`) plus a
small label naming the change; `take_screenshot({filePath})`; then remove the overlay. One colour for
AFTER, another for BEFORE. A box + label reads faster than an arrow. Works for any element in any UI.

**Capture BEFORE and AFTER of each change, not just the end state — the reviewer wants the delta.**
- A visual/style change (colour, spacing, border): AFTER is the live element; for BEFORE, force the
  element back to its previous value with an inline override and screenshot, then restore. Guardrails
  that hold in any framework that re-renders: set the property and screenshot in immediate succession
  (a re-render wipes an inline style), set it with top priority (`element.style.setProperty(prop, val,
  'important')`), override EVERY property that composites (e.g. both the background colour and any
  background image/gradient), and target the EXACT element carrying the changed style — an ancestor can
  match the computed value by coincidence, so confirm with `getComputedStyle` that it actually changed
  before shooting.
- A structural/DOM change: render BEFORE from the pre-change code (`git stash`, or check out the base
  commit), screenshot, then restore.
- Name each pair `ba-<n>-<surface>-BEFORE.png` / `-AFTER.png`. If the app has themes (light/dark) and
  the change reads differently between them, shoot the theme where the difference is clearest — a subtle
  change can be near-invisible in one and obvious in the other.

**Capture every surface at BOTH desktop AND mobile — mobile is where the layout re-flows (cards stack,
tables collapse, a two-column hero becomes one), so a desktop-only shot hides half the change.** For each
surface take one shot at the desktop width and one at a mobile viewport (390×844, the app's mobile
breakpoint), named `<surface>-desktop.png` / `<surface>-mobile.png` (a before/after pair becomes
`ba-<n>-<surface>-BEFORE-desktop|mobile.png` / `-AFTER-desktop|mobile.png`; a journey step
`step-<n>-<label>-desktop|mobile.png`). Set the mobile viewport EXPLICITLY with a Playwright/CDP device
viewport (or the framework's mobile project) — NEVER `resize_page`: window width is unreliable
(`browser-debugging.md`), so a resized window silently shoots at desktop width and the "mobile" file is a
duplicate. TEST: every captured surface has both a `-desktop` and a `-mobile` file, and the mobile file's
`window.innerWidth` was 390, not the desktop width.

**Watch for a style scoped to a subtree that a portalled overlay escapes.** Overlays (dialogs, modals,
dropdowns, tooltips) are commonly portalled to the document root, OUTSIDE the element a scoped token/class
is defined on — so a value referencing that token resolves to nothing there and the element renders
unstyled or transparent. If a changed fill screenshots blank INSIDE an overlay, that is the bug, not a
capture glitch: the value must be defined at a scope the portal inherits (the document root), not only on
the app-root element. Capturing the real overlay state is how this class of bug surfaces; unit tests miss
it.

### Journey mode — capture the flow as ordered steps (for a user FLOW)

When the change is a FLOW the user walks (connect → pick → confirm → done), isolated surface shots don't
show the flow — capture it as an ORDERED SEQUENCE. Derive the steps from the user journey, never invent
them: `/sk:ship-report-and-ensure-correct-user-system-journey` writes the user journey for the diff, and
`~/.claude/references/user-journey-review.md` is how it's walked as a first-time user. Drive the flow
through those numbered steps in order and `take_screenshot({filePath})` at EACH — the entry state, each
meaningful interaction (the click that advances it), and the end state — named `step-<n>-<label>.png` so
the files sort into the flow. Callout the element that changed at each step, as in surface mode. TEST:
the shot set, read in filename order, replays the journey with no step missing. Surface mode (Step 3)
still runs for any changed surface a linear flow doesn't reach; the two modes coexist — run journey mode
for the flow, surface mode for the rest.

## Step 4 — Hand them back

Show the annotated shot of each changed surface (its BEFORE/AFTER pair where captured) with the example
inputs visible, list what each shows, and `open` the screenshots directory in Finder (macOS:
`open "<abs path>"`) so Simon can flip through them.
**When the branch is large/consolidated** (spans many surfaces), also give a compact TOUR table
(Area · What changed · Where to find it · What to look at) — brief but complete, no word vomit.

## Step 5 — Post them to the PR (OPT-IN, GitHub-only)

By default the screenshots are handed back locally (Step 4). Post them ONTO the PR only when BOTH hold:
the branch has an OPEN PR (`gh pr view --json number,url,isDraft`) AND Simon says yes — posting to a work
PR is outward-facing (the reviewer sees it). ASK first; never auto-post. For journey mode, post the step
shots in filename (step) order, each captioned with its step, so the comment reads as the flow top to bottom.

**Post BOTH the desktop and the mobile shot of each surface, grouped per surface** — a `**<surface>**`
heading with its Desktop image then its Mobile image (before/after: BEFORE then AFTER, each with its
desktop+mobile) — so the reviewer sees the responsive result, not only the wide layout. TEST: for every
surface posted, the comment carries its `-desktop` AND its `-mobile` image under one heading.

**GitHub-only — never an external host.** In a PRIVATE repo (a work repo usually is), GitHub's Camo proxy
can't authenticate: `raw.githubusercontent.com`, release assets and external hosts all render as a BROKEN
image in a comment. Only two URL forms render inline in a private-repo comment, and both live on
github.com. Post via the first that works, and FAIL LOUD (non-zero, drop to the next) — never post
broken-image markdown:

1. **`gh pr comment <n> --attach <shot.png> … --body <md>`** if the installed `gh` supports `--attach`
   (`gh pr comment --help | grep -q -- --attach`). Official path; it uploads to GitHub's `user-attachments`
   CDN for you. Nothing enters the repo.
2. **Else upload each shot to the user-attachments CDN yourself** (the same CDN `--attach` uses) with a
   PAT/OAuth user token — NOT a GitHub App token (those 404) — and embed the returned URLs:
   ```bash
   TOKEN=$(gh auth token); REPO_ID=$(gh api "repos/$REPO" --jq .id); BODY="### QA screenshots"
   for F in <shots>; do
     URL=$(curl -sf "https://uploads.github.com/user-attachments/assets?name=$(basename "$F")&content_type=$(file -b --mime-type "$F")&repository_id=$REPO_ID" \
       -X POST -H "Authorization: Bearer $TOKEN" -H "Accept: application/json" --data-binary "@$F" | jq -r '.href // .url') \
       || { echo "CDN UPLOAD FAILED for $F"; exit 1; }
     BODY="$BODY"$'\n\n'"**$(basename "$F")**"$'\n'"![$(basename "$F")]($URL)"
   done
   gh pr comment "$PR" --repo "$REPO" --body "$BODY"
   ```
   This keeps NOTHING in the repo — survives merge/squash/branch-delete, needs no pruning. Its one risk:
   the endpoint is undocumented, so `curl -sf` fails on any non-2xx and drops to (3).
3. **Else (CDN refused) the git-only detached-ref fallback** (ptrandev's `ui-walkthrough` method — still
   github.com, but the blobs live in the repo). Hash each PNG into a blob with a SCRATCH index (never touch
   the working tree), assemble a tree, `commit-tree` an ORPHAN commit, and
   `git push origin <commit>:refs/screenshot-changes/pr-<n>-<sha>` (FLAT, hyphenated — a nested ref name
   collides). Embed `github.com/<owner>/<repo>/raw/<commit>/<file>` (the viewer's session cookie authorizes
   it; github.com URLs aren't camo-rewritten, so it renders in private). **Check the push EXIT CODE, never
   its output or the URL** — a rejected push still transfers the objects, so the blob is fetchable while the
   ref was never created. If the custom ref is 403'd (some git proxies allow only `refs/heads/*`), retry as
   `refs/heads/claude/screenshot-changes-pr-<n>-<sha>`. This leaves blobs in the repo forever — cap at ≤ 8
   images and prune closed PRs' refs later (`git ls-remote origin 'refs/screenshot-changes/*'` →
   `git push origin --delete <ref>`).

**Empirically the installed `gh` has lacked `--attach`, so option 2 (the CDN) is the proven path — go
to it as soon as the `--attach` probe comes back empty, rather than re-deriving it. Its returned URLs
resolve to `private-user-images.githubusercontent.com`, which is NOT camo-proxied, so the VERIFY grep
below reads 0.**

**VERIFY before reporting done** — read the posted comment's rendered HTML and confirm the images are there
and NOT camo-broken:
```bash
gh api -H "Accept: application/vnd.github.full+json" "repos/$REPO/issues/comments/<id>" --jq '.body_html' > /tmp/c.html
grep -c 'camo.githubusercontent' /tmp/c.html   # expect 0; nonzero = renders broken
```
TEST: the PR comment shows every posted screenshot inline, and nothing was hosted outside github.com.

## chrome-devtools tips (save time)

- `take_snapshot` on a page with a big textarea/editor can dump tens of KB every call — prefer
  `evaluate_script` for DOM inspection and `take_screenshot({filePath})` for visuals.
- Screenshots must be saved **inside a workspace root** (a repo path), not `/tmp`.
- Set React controlled inputs with the native value setter + a dispatched `input` event, or the `fill`
  tool (which needs a `uid` from a snapshot).
- Multi-step/wizard flows are often gated — you may have to click through a step to reveal the one you're
  capturing. Note the reveal path in the project's `CLAUDE.local.md`.
- Don't go overboard: scope to the diff, a handful of representative inputs.
