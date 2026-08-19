---
name: ship-screenshot-changes
description: Quickly screenshot the changed frontend surfaces for documentation — no bug-hunting, no waiting for anything you don't need. Figures out what changed (git diff), seeds the account into the state the change is meant to be seen in, drives each changed surface in a real debug browser with realistic example inputs, captures a screenshot of each, hands them back (opened in Finder), and — opt-in, only with an open PR and Simon's yes — posts them onto the PR (GitHub-native: gh --attach or the user-attachments CDN, a git-only detached-ref fallback, never an external host). Use for "screenshot the changes", "screenshot changes", "doc the new UI", "capture the new screens", "grab screenshots of what changed", or "post the screenshots to the PR". Reused by /sk:test-eyeball for its capture + PR-post; test-eyeball adds the bug-hunt loop on top.
argument-hint: [optional focus, e.g. "the new dashboard section"]
---

# Screenshot the changed surfaces — fast, for docs or a PR

Get the changed frontend surfaces on screen in a real browser, in the state a user would actually see
them, and capture one clean screenshot of each. No bug-hunting, no edge fuzzing, no fix-loop — that is
`/sk:test-eyeball`, which reuses THIS skill for the capture. This is the fast path when you just want the
new things pictured, without waiting for a full QA sweep.

## Step 0 — Log in to the running app (project-specific)

**For project-specific test-login instructions (test accounts + hands-off, password-free auth), read
that project's `CLAUDE.local.md` first.** Never type a real password into a login form; use the
project's documented token/impersonate recipe. If the project has no recipe, get a logged-in session the
cheapest safe way (attach to an already-signed-in debug Chrome, or ask for a one-time manual login in the
debug window) and add the recipe you worked out to that project's `CLAUDE.local.md` so it's instant next time.

Debug browser = chrome-devtools MCP attached to a Chrome launched with
`--remote-debugging-port=9222 --user-data-dir=<throwaway>`.

**Take a lane before booting anything, and before claiming 9222.** Several sessions run at once and all
want the same ports, so `~/.claude/bin/port-slot.sh` gives this worktree its own set and
`~/.claude/references/dev-server-hygiene.md` has the protocol (preflight, identity handshake, teardown).
Without it the app you screenshot may be another branch's.

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

## Step 4 — Hand them back

Show the screenshot of each changed surface with the example inputs visible, list what each shows, and
`open` the screenshots directory in Finder (macOS: `open "<abs path>"`) so Simon can flip through them.
**When the branch is large/consolidated** (spans many surfaces), also give a compact TOUR table
(Area · What changed · Where to find it · What to look at) — brief but complete, no word vomit.

## Step 5 — Post them to the PR (OPT-IN, GitHub-only)

By default the screenshots are handed back locally (Step 4). Post them ONTO the PR only when BOTH hold:
the branch has an OPEN PR (`gh pr view --json number,url,isDraft`) AND Simon says yes — posting to a work
PR is outward-facing (the reviewer sees it). ASK first; never auto-post.

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
