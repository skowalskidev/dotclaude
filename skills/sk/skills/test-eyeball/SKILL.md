---
name: test-eyeball
description: Drive the changed frontend in a real debug browser with example inputs, find + fix bugs, loop until a clean pass, then hand back screenshots for a human to eyeball — and, when Simon confirms, POST those screenshots onto the branch's open PR (opt-in, GitHub-native: the user-attachments CDN, or a git-only detached-ref fallback, never an external host). Use for "go eyeball / QA / check my UI change in the browser", or "post the QA screenshots to the PR".
argument-hint: [optional focus, e.g. "the RR SMS preview"]
---

Go and eyeball and fix other bugs using the debug browser, then let me know when you
haven't found any more, and show me screenshots of the frontend changes with example
inputs for me to eyeball.

That one line is the whole job. Do it as a loop, not a one-shot.

## Step 0 — Log in to the running app (project-specific)

**For project-specific test-login instructions (test accounts + hands-off, password-free
auth), read that project's `CLAUDE.local.md` first.** Never type a real password into a
login form; use the project's documented token/impersonate recipe. If the project has no
recipe, get a logged-in session the cheapest safe way (attach to an already-signed-in
debug Chrome, or ask for a one-time manual login in the debug window) and then add the
recipe you worked out to that project's `CLAUDE.local.md` so it's instant next time.

Debug browser = chrome-devtools MCP attached to a Chrome launched with
`--remote-debugging-port=9222 --user-data-dir=<throwaway>`.

**Take a lane before booting anything, and before claiming 9222.** Several sessions run at once and all
of them want the same ports, so `~/.claude/bin/port-slot.sh` gives this worktree its own set and
`~/.claude/references/dev-server-hygiene.md` has the protocol (preflight, identity handshake,
teardown). Without it the app you screenshot may be another branch's.

## Step 1 — Figure out what changed

`git diff` the branch vs its base. List the exact frontend surfaces the change touches
(routes, components, states, inputs). Those are what you drive — don't wander the whole app.

## Step 1.5 — Seed the account into the state the change is meant to be seen in

A surface only renders meaningfully once the account is in the state a real user would be in
when they'd actually see it — not an empty or default account. Work out that state from the
change itself (what has to be true for this surface to show its real content), then put the
account there with the data such a user would have, so the human eyeballs the ACTUAL
experience. Seed it the project's documented way (Firebase MCP, a seed script, the API),
scoped to the right project, and record the seed recipe in the project's `CLAUDE.local.md`.

## Step 2 — Drive each surface with EXAMPLE INPUTS, hunting bugs

For every changed surface, exercise it like a user, twice:
- **Realistic inputs** — the happy path a merchant/user would actually type. This is also
  the screenshot you'll hand back.
- **Edge inputs** — empty, very long, special/typographic chars (accents, em dash `—`,
  quotes, `& ( ) + . @`), the boundary values, and the "not-yet-configured" states. These
  are where the real bugs hide (regex breaks, overflow, wrapping, NaN, XSS, wrong gating).

Verify behavior with `evaluate_script` (read the DOM/computed styles/pill spans, not just
eyeball) AND a `take_screenshot`. Check `list_console_messages({types:["error"]})` for
feature-related errors (ignore pre-existing unrelated noise).

While you're in there, read `~/.claude/references/user-journey-review.md` and judge each surface
against it — the empty/loading/error states, a lock with no stated reason, a step with no way on.
A surface that renders perfectly and dead-ends is a bug you're driving straight past.

## Step 3 — Fix what you find, then LOOP

For each real bug: fix it, add/extend a test that fails without the fix, rerun the unit
tests + `tsc`, and re-drive that surface in the browser to confirm. Then go back to Step 2
and sweep again. Keep looping until a full pass turns up **nothing new** (aim for one clean
sweep after the last fix). Commit each fix as its own logical unit.

## Step 4 — Report + screenshots

When a sweep is clean, tell me plainly: "no more bugs found." Then show me the screenshots
of each changed surface **with the example inputs visible** (save them inside the workspace
root, e.g. `.context/…`, and reference the files) so I can eyeball the result. List what you
tested (realistic + edge) and any bugs you fixed with commit refs.

**When the branch is large or consolidated** (spans many surfaces, not one component), also
give me a compact TOUR: a table of every surface/change worth walking through — columns like
Area · What changed · Where to find it · What to look at. Brief but complete, no word vomit,
so I can review the whole branch's impact in order.

**Finally, `open` the screenshots directory in Finder** (macOS: `open "<abs path to the
screenshots dir>"`) so I can flip through them without hunting for the files.

## Step 5 — Post the screenshots to the PR (OPT-IN, GitHub-only)

By default the screenshots are handed back locally (Step 4). Post them ONTO the PR only when BOTH hold:
the branch has an OPEN PR (`gh pr view --json number,url,isDraft`) AND Simon says yes — posting to a work
PR is outward-facing (ptrandev sees it). ASK first; never auto-post.

**GitHub-only — never an external host.** In a PRIVATE repo (a work repo usually is), GitHub's Camo proxy
can't authenticate: `raw.githubusercontent.com`, release assets and external hosts all render as a BROKEN image
in a comment. Only two URL forms render inline in a private-repo comment, and both live on github.com.
Post via the first that works, and FAIL LOUD (non-zero, drop to the next) — never post broken-image markdown:

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
   github.com, but the blobs live in the repo). Hash each PNG into a blob with a SCRATCH index (never
   touch the working tree), assemble a tree, `commit-tree` an ORPHAN commit, and
   `git push origin <commit>:refs/test-eyeball/pr-<n>-<sha>` (FLAT, hyphenated — a nested ref name
   collides). Embed `github.com/<owner>/<repo>/raw/<commit>/<file>` (the viewer's session cookie authorizes
   it; github.com URLs aren't camo-rewritten, so it renders in private). **Check the push EXIT CODE, never
   its output or the URL** — a rejected push still transfers the objects, so the blob is fetchable while the
   ref was never created. If the custom ref is 403'd (some git proxies allow only `refs/heads/*`), retry as
   `refs/heads/claude/test-eyeball-pr-<n>-<sha>`. This leaves blobs in the repo forever — cap at ≤ 8 images
   and prune closed PRs' refs later (`git ls-remote origin 'refs/test-eyeball/*'` → `git push origin --delete <ref>`).

**VERIFY before reporting done** — read the posted comment's rendered HTML and confirm the images are there
and NOT camo-broken:
```bash
gh api -H "Accept: application/vnd.github.full+json" "repos/$REPO/issues/comments/<id>" --jq '.body_html' > /tmp/c.html
grep -c 'camo.githubusercontent' /tmp/c.html   # expect 0; nonzero = renders broken
```
TEST: the PR comment shows every posted screenshot inline, and nothing was hosted outside github.com.

## chrome-devtools tips (save time)

- `take_snapshot` on a page with a big textarea/editor can dump tens of KB every call —
  prefer `evaluate_script` for DOM inspection and `take_screenshot({filePath})` for visuals.
- Screenshots must be saved **inside a workspace root** (a repo path), not `/tmp`.
- Set React controlled inputs with the native value setter + a dispatched `input` event, or
  the `fill` tool (which needs a `uid` from a snapshot).
- Multi-step/wizard flows are often gated — you may have to click through a step to reveal
  the one you're testing. Note the reveal path in the project's `CLAUDE.local.md`.
- Don't go overboard: scope to the diff, a handful of representative inputs, one clean sweep.
