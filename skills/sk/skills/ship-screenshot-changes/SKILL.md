---
name: ship-screenshot-changes
description: Screenshot every changed frontend surface and journey as an advanced screenshot review — empty and full states, all conditional screenshot scenarios, responsive screen sizes, one posted viewport per state (mobile 390×844 by default, desktop only where its layout differs) — with a BEFORE/AFTER pair for every changed surface and journey and a trimmed before/after video per affected user-journey scenario, composed through the shared PR evidence template (bin/pr-evidence.py) so captions sit in bands above the UI and callouts circle the change, plus one raw verification run video per main happy path (0 to 100 on seeded success data, zero paid calls) that it reviews frame by frame, fixes and re-records until clean before posting under ## Verification runs. Figures out what changed (git diff), seeds the account into the state the change is meant to be seen in, drives each surface in a real debug browser with realistic example inputs, hands back an offline report with conditions above screenshots and an actionable TLDR table (opened in Finder), and — whenever the branch has an open PR — refreshes the composed images and playable inline videos in the PR description by default after the full ticket follow-up batch, using a comment only when description embedding is unsupported or blocked (GitHub-native: gh --attach or the user-attachments CDN, a git-only detached-ref fallback, never an external host). Use for "refresh screenshots after all ticket follow-ups", "screenshot the changes", "screenshot changes", "doc the new UI", "capture the new screens", "grab screenshots of what changed", "circle the changes", "before and after screenshots of the change", "post the screenshots to the PR", "advanced screenshot review", "all conditional screenshot scenarios", "screenshot coverage matrix", "record the happy paths", "happy path videos", or "verification run videos". Has a JOURNEY mode that captures a user FLOW as an ordered, numbered step sequence (steps derived from the user journey) — also triggers on "screenshot the user flow", "screenshot the user journey", "show the flow steps". Reused by /sk:test-eyeball for its capture + PR-post; test-eyeball adds the bug-hunt loop on top.
argument-hint: [changed routes or journeys; whole app only when requested]
---

# Screenshot the changed surfaces and journeys, before and after

Get every changed frontend surface and journey on screen in a real browser, in the states a user would
actually see them, before and after the change, and hand back one review plus PR evidence that looks the
same on every PR. No bug-hunting or fix-loop: that is `/sk:test-eyeball`, which reuses THIS skill for the
capture.

DO read `~/.claude/references/screenshot-review.md` first and execute its procedure for the requested
scope: the complete matrix (empty and full states, conditional scenarios, responsive sizes, complete
journeys), capture, walkthroughs, the offline report and § PR evidence template.
TEST: N points have N heading/table blocks in the report with a cell for every column (a gap shows its
status and reason), each case's conditions sit above its evidence, and every posted pair came out of
`bin/pr-evidence.py`.

DO size the case matrix to the change's tier, per `references/testing-strategy.md` § Size the checks
to the change: the complete matrix is the Deep tier, and a Light change gets one BEFORE/AFTER pair of
its changed state at 390×844 with no video. A direct ask from Simon for the full review runs it whole.
TEST: a Light run posts one pair and a one-line `Skipped (tier light)` reason for the rest of the matrix.

DO take AFTER captures once, on the batch's final head, per the reference's § Refresh after the
follow-up batch. Invoked before review and fix rounds converge, plan the matrix and seed data only
(Steps 1-2) and a base-branch BEFORE capture, then capture after the last fix lands.
TEST: no AFTER capture's source revision precedes the batch's last fix commit.

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

Debug browser = chrome-devtools MCP attached to the test browser, launched per
`browser-debugging.md` § The test browser (Chrome for Testing, never Simon's own Chrome).

**Take a lane before booting anything, and before claiming 9222.** Several sessions run at once and all
want the same ports, so `~/.claude/bin/port-slot.sh` gives this worktree its own set and
`~/.claude/references/dev-server-hygiene.md` has the protocol (preflight, identity handshake, teardown).
Without it the app you screenshot may be another branch's. **On teardown, scope every process-kill to
THIS worktree's/session's path** — a broad pattern (the app or repo name) can match and kill another
running session's server.

## Step 1 — Figure out what changed

`git diff` the branch vs its base. List the exact frontend surfaces and journeys the change touches
(routes, components, states, inputs). A backend or data change whose output renders on a screen (copy,
translations, prices, counts) has a surface too: list the screen that shows that output and capture it
with production-shaped data before and after; "no frontend files changed" is not "no visible surface".
(the fix for a translation-backend PR first evidenced with a CI table until Simon asked for the
translated screen.) Then build the case matrix per the reference's § Discover the
complete matrix: empty and full states, every conditional scenario, responsive sizes and complete
journeys. One case per scenario × viewport × variant, blocked and unrun cases included. Scope to the
diff unless Simon asks for the whole app.

## Step 2 — Seed the account into the state the change is meant to be seen in

A surface only renders meaningfully once the account is in the state a real user would be in when they'd
actually see it — not an empty or default account. Work out that state from the change itself, then put
the account there with the data such a user would have, so the screenshot shows the ACTUAL experience.
Seed it the project's documented way (Firebase MCP, a seed script, the API), scoped to the right project,
and record the seed recipe in the project's `CLAUDE.local.md`.

## Step 3 — Drive each surface with REALISTIC inputs and screenshot it

For every case in the matrix, put the surface in that state with the inputs a real user would type
and `take_screenshot({filePath})`. One clean shot per case with the example inputs visible; that shot IS
the documentation. Save screenshots INSIDE a workspace root (a repo path,
e.g. `.context/…`), never `/tmp`. Use `evaluate_script` for DOM/state, not `take_snapshot` (which dumps
tens of KB). No edge inputs, no bug-hunt here — `/sk:test-eyeball` adds those.

**Circle the change so the reviewer sees what moved, through the template, never in the DOM.** Capture
the frame clean, record the changed element's `getBoundingClientRect()` × `devicePixelRatio` as
`x0,y0,x1,y1`, and pass it to `~/.claude/bin/pr-evidence.py shots` as `--before-callout` /
`--after-callout`. The engine stacks the captions in bands above the frame and draws outline-only
callouts, per the reference's § PR evidence template.

**Capture BEFORE and AFTER of every changed surface and journey, video included, not just the end state — the reviewer wants the delta.**
The default and the `new, no before` case are in `~/.claude/references/screenshot-review.md`. Mechanics for how to get the BEFORE:
- A visual/style change (colour, spacing, border): AFTER is the live element; for BEFORE, force the
  element back to its previous value with an inline override and screenshot, then restore. Guardrails
  that hold in any framework that re-renders: set the property and screenshot in immediate succession
  (a re-render wipes an inline style), set it with top priority (`element.style.setProperty(prop, val,
  'important')`), override EVERY property that composites (e.g. both the background colour and any
  background image/gradient), and target the EXACT element carrying the changed style — an ancestor can
  match the computed value by coincidence, so confirm with `getComputedStyle` that it actually changed
  before shooting.
- A structural/DOM change: render BEFORE from the pre-change code in its own tree (`git worktree add
  <dir> <base>`), screenshot, then remove that tree. Never `git stash` or a checkout in the working tree:
  the stash stack is shared by every worktree of the repo.
- Name each pair `ba-<n>-<surface>-BEFORE.png` / `-AFTER.png`, then compose it with
  `pr-evidence.py shots` into `ba-<n>-<surface>-<platform>.png`. If the app has themes (light/dark) and
  the change reads differently between them, shoot the theme where the difference is clearest — a subtle
  change can be near-invisible in one and obvious in the other.

**Post one viewport per state; check the other.** Capture each surface at the viewport the change
targets (usually mobile 390×844) and check the other viewport; post the second only when its layout
visibly differs, with one line saying what differs, per the reference's § PR evidence template. Name
files `<surface>-desktop|mobile.png` (`ba-<n>-<surface>-BEFORE-desktop|mobile.png`, journey steps
`step-<n>-<label>-desktop|mobile.png`). Set the mobile viewport EXPLICITLY with a Playwright/CDP device
viewport (or the framework's mobile project), NEVER `resize_page`: window width is unreliable
(`browser-debugging.md`), so a resized window silently shoots at desktop width. TEST: every `-mobile`
file's `window.innerWidth` was 390, and no posted desktop/mobile pair shows the same layout.

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

### Film one clip per affected scenario

DO record one clip per affected user-journey scenario on the base and one on the change, the same steps
and seeded state on both, shaped and verified per `~/.claude/references/screenshot-review.md` § Record
useful walkthroughs (first frame is the real UI, trigger, outcome, nothing after; no text slide, the
TLDR is PR text above the video). Name them
`scenario-<label>-BEFORE.mp4` / `-AFTER.mp4`, then compose them side by side with
`~/.claude/bin/pr-evidence.py video` into `scenario-<label>.mp4`; that composed clip is the one posted,
under its own `### <scenario>` block and a row in the scenario table. Carry each required caveat beside
its clip in the local hand-back and PR; keep the attachment URL in its own paragraph.
TEST: each affected scenario has a composed clip passing that section's frame-sample checks with its
required caveat, or the hand-back states the skip.

### Record the verification runs

DO run `~/.claude/references/screenshot-review.md` § Verification run videos by default at the tiers it
names, after the short clips: plan each main happy path 0 to 100, seed success data with zero paid
calls, record each run raw, review, fix and re-record until clean, pass the independent review, then
post only the final clean runs under `## Verification runs`. They are a separate deliverable from the
short clips above; neither replaces the other.
TEST: a PR whose `## Screenshots` posts a video also carries `## Verification runs`, and
`~/.claude/bin/pr-landing-gate.py` passes that section.

## Step 4 — Hand them back

Render the offline review with `~/.claude/bin/screenshot-report.py` per the reference's § Build the
review, and hand back its link with the actionable TLDR table (Point · Verdict/gap · Next action), the
composed before/after image of each changed surface and each journey's composed clip, then `open` the
evidence directory in Finder (macOS: `open "<abs path>"`) so Simon can flip through them.
**When the branch is large/consolidated** (spans many surfaces), also give a compact TOUR table
(Area · What changed · Where to find it · What to look at) — brief but complete, no word vomit.

## Step 5 — Post them to the PR (ALWAYS when a PR is open; GitHub-only)

DO apply the reference's § Refresh after the follow-up batch before final capture and publication.
When the branch has an OPEN PR (`gh pr view --json number,url,isDraft`), publish screenshots, journey
videos and verification runs by default unless Simon explicitly waives them. Do not ask again. No open PR means the local
hand-back is the destination. Preserve the shared native opt-in rule.

DO embed the complete current evidence in the **PR description first**, in one bounded
`<!-- sk:screenshot-changes -->` / `<!-- /sk:screenshot-changes -->` section. Read the fresh description,
preserve all unrelated text and automation footers byte-for-byte, and verify its saved rendered media.
A link to an evidence comment is not description embedding. Use one consolidated comment only when
capability checks prove description embedding unsupported or blocked; record the exact reason and
link that comment prominently from the description when editing it is available.
TEST: a supported description contains the actual images and inline videos; a comment fallback carries
a verified limitation, never an assumption from a missing CLI upload flag.

**Post one block per point, laid out by the reference's § PR evidence template.** A point is the surface,
scenario or journey step being shown (e.g. "Settings: empty list"). Each block holds the composed
before/after image per captured platform and the point's composed video. Journey mode: one block per
step, in step order.

DO publish each composed video as an inline player with playback controls, alone in its own
paragraph, never an ordinary `[video](url)` link or a linked thumbnail. Use the attachment route below;
a failed upload shows `blocked: <reason>` in its place.
TEST: every published clip plays within the chosen description or comment; a click that navigates away or downloads a file
is a failed inline-video check; a posted pair with an after but no before and no `new, no before`
note broke the rule.

DO keep one consolidated current evidence section in the description, or one fresh consolidated
marker-tagged comment for a proven fallback. Apply existing posting authorization to replacement and
cleanup. Keep all current point blocks and videos together; an upload-only comment is temporary and
must not remain as duplicate evidence after the description passes verification.

1. **Inventory and assemble.** Fetch every page of `repos/$REPO/issues/$PR/comments` and confirm the
   authenticated author. Fetch the PR description too. Read saved bodies, never reconstruct them from memory. Select only comments
   by that author with `<!-- sk:screenshot-changes -->`, or unmarked legacy comments whose screenshot
   layout, media and recorded publication history establish the same workflow ownership. Preserve other
   authors, review discussions, mixed-purpose comments and uncertain matches. Record candidate IDs and
   bodies locally before cleanup. Carry forward every still-current untouched point block, video, caveat
   and gap; replace re-captured points and drop only points that left the diff. Migrate older layouts
   into point blocks without losing current evidence.
2. **Create or resume this refresh.** Start the body with `<!-- sk:screenshot-changes -->`, followed by
   `<!-- evidence-refresh:<id> -->`; save that unique refresh ID and final body locally before posting.
   For description publication, replace only its bounded owned section and recheck the fresh body
   before writing; preserve concurrent unrelated edits. For fallback comments, use the create/resume
   procedure below. Start each point block with `<!-- point:<slug> -->` and end it with `<!-- /point:<slug> -->`. Before every create or retry, list
   the chosen destination again for this author's refresh ID. Resume its replacement when found, including after a
   timeout or interrupted attachment upload; create only when absent. A later refresh gets a new ID.
   Use `--body-file` or `-F body=@<file>`; patch only this refresh's replacement while finishing uploads
   or correcting its saved layout. Never use `--edit-last` against an unrelated or obsolete comment.
3. **Verify before deleting.** Apply the rendered-media and browser-playback checks below to the saved
   replacement. Retain the prior evidence on any incomplete check, report the verification gap and
   resume the same refresh. A successful create response alone never authorizes cleanup.
4. **Retire and reconcile.** After the replacement passes, update workflow-owned PR-body, plan and
   report links to its URL. Re-fetch each obsolete candidate and confirm its author and body still
   match the inventory before `gh api -X DELETE repos/$REPO/issues/comments/$ID`; preserve and report
   concurrent edits. Include clearly owned unmarked legacy evidence in cleanup, without another
   permission question. Re-list every page and verify exactly one current workflow-owned evidence
   section remains in the description with zero duplicate evidence comments, or exactly one fallback
   comment remains; all intended obsolete IDs are absent and unrelated comments are intact.
   On interrupted cleanup, locate the verified replacement and delete only the remaining candidates.

TEST: a completed refresh has one complete current description section or one verified fallback
comment, and zero obsolete or upload-only workflow-owned evidence comments. A retry reuses its recorded refresh ID; failed verification deletes
nothing; unrelated or other-author comments survive. Record the replacement URL and cleanup result.

**GitHub-only — never an external host.** DO use a GitHub-native attachment route and verify the
rendered destination with the intended repository viewer's access. A successful upload or reachable raw
file does not prove inline rendering, especially in a private repository.
Apply `rules/connectors.md` before an auth question or an unsupported-capability claim.

1. **Feature-detect description editing/upload and `gh pr comment --attach` (gh 2.99+)** with
   `gh pr edit --help` and `gh pr comment --help`. Use `--body-file` and
   `--attach` with `gh pr edit` when supported; otherwise use the verified attachment fallback.
   DO use supported Markdown local references for upload: `![label](PATH/TO/IMAGE)` for an image and
   `![](PATH/TO/VIDEO)` alone in its own paragraph for a video. Do not expect `--attach` to rewrite
   raw HTML `<img src="/local/path.png">`; it can leave that broken and append a duplicate upload.
   After upload, fetch the saved body and map each returned native URL to its point/platform. If
   width-controlled HTML is needed, replace the Markdown with `<img src="<returned-url>" ...>` only
   after upload. Remove only uploader-appended duplicates proven by the saved before/after bodies;
   preserve unrelated text and automation footers. Before completion verify zero local media refs,
   exactly the intended media counts and no duplicate appended media. A video reference within a sentence renders
   as a link. Follow [GitHub's attachment instructions](https://docs.github.com/en/github-cli/github-cli/attaching-files-with-github-cli#embedding-a-video),
   then apply the point-block layout above and verify the final rendered result. Let the attachment
   command create this refresh's replacement, or target its recorded ID to finish it. Reconcile that
   ID before retrying so uploads do not create duplicate replacements. If attachments require a
   comment, use a recorded workflow-owned staging comment, embed its returned attachment URLs in the
   description, verify the description, then retire staging. A missing description-upload flag alone
   does not prove existing attachment URLs cannot be embedded there.
2. **Else use GitHub's browser attachment control** in the authenticated test browser. Upload the
   image or video to the intended repository's comment editor and preserve its generated attachment
   URL. Collect URLs, then publish this refresh's replacement with its complete media layout, or finish
   the replacement already recorded for this refresh.
   An undocumented upload endpoint is not a proven fallback: use it only after a successful upload
   and rendering check in this run; never assume its URL is playable. If no attachment route works,
   retain the screenshot evidence and mark each affected video `blocked: <reason>`.

3. **For images only, the git-only detached-ref fallback** (ptrandev's `ui-walkthrough` method — still
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

DO use MP4/H.264 for published clips by default, retaining the original recording; use another
supported format only after playback passes in the target browser. Check current
[GitHub file limits and codec guidance](https://docs.github.com/en/get-started/writing-on-github/working-with-advanced-formatting/attaching-files)
before uploading. TEST: each clip is within the applicable limit and passes the playback check below.

DO treat the detached-ref route as image storage only. A raw video blob or release download is not
an inline player; do not publish one as a substitute for a verified GitHub video attachment.

**VERIFY before reporting done** — fetch the saved PR description at `repos/$REPO/pulls/$PR`, or the
fallback comment at `repos/$REPO/issues/comments/<id>`, with
`gh api -H "Accept: application/vnd.github.full+json" <endpoint>` into a
mode-0600 evidence file and inspect `body_html` locally. Report counts and playback outcomes only;
private media URLs can carry short-lived credentials, so never print the HTML or signed URLs.
Confirm one block per point, correct point/platform mapping, and a rendered
video player for every published clip; an anchor alone fails. Open the posted description or comment in the
authorized test browser. When that browser lacks access but the authenticated connector/API can read
the saved description or comment and its media, render its exact returned `body_html` unchanged in an isolated browser
with the same remote media. Keep authentication headers/tokens outside page markup and private signed URLs out of
logs/reports. Do not reconstruct the comment, insert players or substitute local media.
Label this route `API-rendered description verification; full-page UI unchecked` or
`API-rendered comment verification; full-page UI unchecked`; it proves that destination's
media, not the signed-in site's surrounding UI. If unchanged markup cannot load its players, retain
the verification gap. Both routes require the same checks before reporting success or retiring prior
evidence. Check every screenshot loads (each `<img>` reports `naturalWidth > 0`), and play every video
using its visible player, in the browser and with the control clip that § Record useful walkthroughs sets:
confirm duration > 0, playback time advances, and the expected first and last states appear without
navigation or media errors. Save the comment URL, verification route and playback results with the evidence report.
TEST: all screenshots remain visible and every expected video is playable inline, or its cell reports
`blocked: <reason>` and the hand-back names the missing evidence; HTTP 200, local ffprobe success and
the absence of Camo URLs alone do not pass publication.

## chrome-devtools tips (save time)

- `take_snapshot` on a page with a big textarea/editor can dump tens of KB every call — prefer
  `evaluate_script` for DOM inspection and `take_screenshot({filePath})` for visuals.
- Screenshots must be saved **inside a workspace root** (a repo path), not `/tmp`.
- Set React controlled inputs with the native value setter + a dispatched `input` event, or the `fill`
  tool (which needs a `uid` from a snapshot).
- Multi-step/wizard flows are often gated — you may have to click through a step to reveal the one you're
  capturing. Note the reveal path in the project's `CLAUDE.local.md`.
- Don't go overboard: scope to the diff, a handful of representative inputs.
