# Screenshot review and PR evidence

DO produce one private, offline review for the declared scope, using the existing installed capture
stack. Read `references/browser-debugging.md`, `references/testing-strategy.md`, and
`references/user-journey-review.md`; apply `references/ios-simulator.md` only for explicitly requested
native capture. Follow those owners for connectors, auth, source fidelity, ports and device lifecycle.
DON'T install a second framework, alter app DOM to add captions, or replace independent tests with images.
TEST: each capture identifies its source and real UI state, and captions exist only in the report or
in the § PR evidence template bands.

## Discover the complete matrix

DO default scope to all changed routes and journeys from the diff and acceptance criteria; retain an
explicit whole-app request. Read render branches, permission checks, flags, account and billing state,
then explore the real UI before finalizing the matrix. Inventory each materially distinct implemented
state: empty, full, one-item, large sets, account/role/permission, flags, billing, onboarding, loading,
error/recovery, partial data, offline, filter-zero, overflow/long content, overlays, validation and success.
Define full as representative populated data exercising the surface’s relevant features; distinguish a
true empty account from filtered zero results and unavailable data. Include conditions that hide or
disable UI. Map complete journeys from entry through outcome.
TEST: every source branch or discovered state maps to a case or a named not-applicable reason; no
happy-path sample silently replaces broad scope.

DO derive layout profiles from existing test/device config and CSS media/container query breakpoints.
For each breakpoint b capture b−1, b and b+1 CSS pixels, plus supported minimum/maximum sizes; exercise
container widths in their real parent layout. Record actual viewport width, height and DPR, device
emulation versus physical hardware, browser, theme, locale and text zoom. If no bounds exist, document
fallback profiles 320×812, 390×844, 768×1024 and 1440×900 at DPR 1 and the reason for those choices.
Treat these as sampled widths, never proof across infinitely many sizes. TEST: every applicable surface
has empty and full cases at every selected supported layout, with long-content cases where meaningful.

DO enumerate applicable supported engines, themes, locales, text zoom and account states. Fully cross
known critical interactions (permissions × role, billing × account, breakpoint × overflow); use constrained
pairwise sampling only for secondary combinations. Name constraints, omitted combinations and residual
risk in coverageStrategy/exclusions. Keep exclusions and blocked/not-run rows visible rather than
removing required cases. TEST: a sampled matrix never calls itself exhaustive, and each gap has a next action.

## Capture and review

DO use the project's installed automation first: integrated Playwright when present, existing Cypress
or equivalent next; use Storybook fixtures only as labeled supplemental component evidence. Verify the
installed API before choosing a capture feature. Save a reproducible script or command for each journey.
Reset isolated accounts to the entry state, then perform the actions being demonstrated; do not seed
past the action the walkthrough claims to prove. Label fixture, mocked, copied-production or live data.
Production writes and paid calls retain their existing authorization gates. TEST: another agent can
repeat each case from the recorded conditions and steps without hidden session state.

DO wait for the intended app state, fonts, images and layout to settle; record animation suppression,
frozen time, masks and other capture changes in conditions. Assert both expected visible content and
expected absent content before capture. Inspect every image for clipping, wrong viewport and accidental
loading state. Let AI propose missing cases and classify findings, never silently rewrite expected
outputs, baselines or skips. TEST: captured is separate from pass; a missing image cannot pass.

DO capture every changed surface and journey BEFORE (the base branch or `origin/main`) and AFTER (the
change), screenshots and video both, with the same seeded state, data and viewport. A new surface shows
`n/a: new, no before` in its before slot, never a missing slot. Compose and post each pair through
§ PR evidence template. Record BEFORE on a local or preview build of the base branch with the AFTER's
fixtures, never on the production site: a walk that signs up or pays there writes real data or charges.
TEST: an evidence post with an after but no before and no `new, no before` note, or a before whose
recorded URL is a production host, broke the rule.

DO capture authentic base/head evidence with matching data, viewport and
conditions. Use separate cases with variant `before` and `after`, recording revisions in conditions.
Label any CSS reconstruction `simulated-before`; never present it as a base checkout. Keep original
images unaltered and uncropped in the gallery. TEST: each comparison discloses its source and any mismatch.

## Record useful walkthroughs

DO record one walkthrough video per changed user journey, by default, beside its screenshots, and film
the change inside its flow: start at least one screen before the changed surface, drive the real
trigger (tap, typing, scroll, sheet or modal opening) at human pace, and end at least one screen after
it, where the user lands. The clip exists to show context, transitions and movement; a screenshot
already shows a state. Web: Playwright `recordVideo` or a Chrome for Testing screencast. Verify it
plays: `ffprobe` duration above 0 and one extracted frame showing the real screen. Post it to the PR as
a playable inline video with the screenshots through that skill's attachment and rendered-playback
checks; a text link or thumbnail does not pass.
NUMBER: at least 8 seconds and at least 3 distinct states. States = 1 +
`ffmpeg -i <clip> -vf "fps=1,select='gt(scene,0.15)',showinfo" -an -f null - 2>&1 | grep -c pts_time`.
DO re-record a clip below either number with the surrounding steps. Skip the video only for a change
with no visible UI or no interaction to drive (a static copy or style change carried by its screenshot
pair), and state that skip in the report.
DON'T hand back screenshots alone for a changed journey because video looked optional (the fix for a
four-PR evidence run that posted images and no clips), and DON'T post a clip of one unchanged screen
(the fix for PR clips that were 3 seconds of one success screen).
TEST: a journey report or PR post with screenshots but no playable inline video, explicit blocked
reason or stated skip broke the rule; so does any posted clip under 8 seconds or 3 states.

DO run every automated playback check, local or on the posted comment, in a browser that decodes the
clip: branded Chrome (`chromium.launch({channel:'chrome'})`) for MP4/H.264, because open-source Chromium
builds ship without proprietary codecs, or record and verify VP9/WebM. Prove the harness first: one
known-good local clip plays in the same browser through the same play action. Start playback with a
click on the video's centre or focus plus Space; a click at a fixed native-controls offset can miss
the play button. NUMBER: every posted video shows advancing `currentTime` and differing first and last
frames. TEST: the verification record names the browser channel, its version and the control clip's
result. Zero videos played while metadata loads, or a failing control clip, is a verifier defect, not a
media defect (the fix for a 66-video check where every clip timed out while all 79 images decoded).

DO also add video for transitions or motion outside a journey when the installed stack supports it.
Explore first, save the explicit replay, reset state, then record a deliberate pass. Preserve findings
from exploration even when the final recording succeeds. In Playwright use
its supported video configuration or feature-detected `page.screencast`; retain successful demo videos,
not only failures. Match recording size to viewport, finalize by closing the context or stopping the
recorder, then inspect playback from first to last state and check readable labels. Native action
annotations are optional when the installed API supports them. TEST: an inline video plays the
actual replay, not exploration or an unfinished file.

DO put a caveat of at most two sentences beside each clip showing an injected error or test-only end
state. Name that state and the verified recording environment. Check the capture setup and network
evidence before calling an error injected or stating `not production` / `no live actions`; a local
page URL alone is not proof. For a verified offline recording, e.g. "Local mocked test, not production.
The final timeout was deliberately injected; no live actions occurred during this recording."
Keep genuine or unexplained failures visible as findings; state uncertainty when provenance is unknown.
TEST: the caveat identifies the demonstrated state and its evidence-backed scope, without implying
production is bug-free or dismissing an unverified error as a test artifact.

DO record simulator video with `xcrun simctl io <udid> recordVideo` under the native simulator owner's
slot rules, only when native capture is explicitly requested; apply the same verify-it-plays check.
Use keyframes and record the missing video capability when the installed tool cannot record; do not
install a second recorder. Keep traces as optional investigation evidence,
never call a trace an executable replay. TEST: native opt-in and ownership remain intact, and no recording
process survives hand-back.

## PR evidence template

DO build every before/after image and video posted to a PR with `bin/pr-evidence.py`, the one template
every run reuses, so evidence looks the same on every PR:

```sh
python3 ~/.claude/bin/pr-evidence.py shots --before B.png --after A.png --pr <n> \
  --before-caption "<what happens on the base>" --after-caption "<the result on this PR>" \
  [--context "<shared action>"] [--before-callout x0,y0,x1,y1] [--after-callout x0,y0,x1,y1] \
  --out .context/pr-evidence/<point>-<platform>.png
python3 ~/.claude/bin/pr-evidence.py video --before B.mp4 --after A.mp4 --pr <n> \
  --before-caption "<what happens>" --after-caption "<the result>" --out .context/pr-evidence/<journey>.mp4
```

DEFAULT: capture clean, unannotated frames; the engine adds everything else. A red BEFORE band titled
`BEFORE  <base>` (default `main`) and a green AFTER band titled `AFTER  #<n>` sit STACKED ABOVE their
frame, each with a one-line caption: what happens on the base, then the result on this PR. Callouts
are outline-only rounded rectangles around the change, red on before and green on after, given in
source pixels (`getBoundingClientRect()` x device pixel ratio).
DON'T overlay a caption on the UI, inject a DOM banner or ring `<div>`, or hand-roll a PIL/ffmpeg
compose: an overlaid label hides the interface it explains (the fix for a side-by-side clip whose
labels covered the app header).
NUMBER: portrait frames side by side, 780 px each, 40 px gap, 150 px bands; landscape frames stacked,
1280 px wide, 30 px gap, 130 px bands; title 44 px, caption 30 px, at most 60 characters. Video: each
side plays 10-15 s (speed factor = duration / target, default 12 s, never slowed), holds its final
state 4-5 s (default 4.5), the shorter side holds its last frame so both end together; H.264,
yuv420p, `+faststart`.

DO post one block per point in the PR comment: `### <point>`, one line naming what the left (or top)
and right (or bottom) frames show, then per captured platform a `**Desktop**` / `**Mobile**` / `**iOS**`
label over its composed image (`<img src="<url>" width="800" alt="<point> <platform> before and after">`),
then the composed video alone in its own paragraph. A new surface posts its AFTER frame under
`Before: n/a: new, no before`; a platform without evidence shows `not run: <reason>` or
`blocked: <reason>`. Post with `gh pr comment <n> --body-file body.md --attach <png> --attach <mp4>`
and verify through `/sk:ship-screenshot-changes`'s VERIFY checks: each image URL returns 200 `image/png` with
nonzero size and each video is served as `video/mp4`, then the browser playback checks still decide.
TEST: every posted pair shows both bands above its frames and no caption over the UI, every changed
journey has one composed video, and `python3 ~/.claude/bin/pr-evidence.test.py` passes.

## Build the review

DO save a JSON manifest and captures under a private workspace `.context/` directory. Render with:

```sh
python3 ~/.claude/bin/screenshot-report.py .context/screenshot-review/manifest.json --output .context/screenshot-review/review.html
```

DO use schemaVersion 1 and the following shape (illustrative unrun case, not product evidence):

```json
{
  "schemaVersion": 1,
  "title": "Changed account screens",
  "scope": "Changed /items route and create-item journey",
  "coverageStrategy": "Empty/full at selected layouts; list breakpoints, critical crosses and secondary sampling here",
  "exclusions": [],
  "columns": [
    {"id": "web-desktop", "label": "Web desktop"},
    {"id": "web-mobile", "label": "Web mobile"},
    {"id": "ios", "label": "iOS"}
  ],
  "run": {
    "revision": "source revision",
    "dirtyFingerprint": "clean or hash of working changes including untracked source",
    "timestamp": "ISO-8601 timestamp",
    "environment": "isolated local preview",
    "dataMode": "fixture"
  },
  "cases": [{
    "id": "items-empty-small",
    "point": "Items: empty list",
    "column": "web-mobile",
    "surface": "Items",
    "route": "/items",
    "account": "new member fixture",
    "variant": "after",
    "conditions": ["Zero items; member permission; feature enabled; text zoom 100%"],
    "steps": ["Reset fixture", "Open /items"],
    "expected": "Empty message visible; item rows absent",
    "observed": "Not executed",
    "viewport": {"width": 390, "height": 844, "dpr": 1},
    "browser": "Chromium, record installed version",
    "theme": "light",
    "locale": "en-US",
    "deviceMode": "emulated CSS viewport",
    "captureStatus": "not-run",
    "reviewStatus": "not-reviewed",
    "reason": "Capture pending",
    "nextAction": "Run saved capture script"
  }]
}
```

DO create one case per scenario × viewport × variant, with a unique alphanumeric/hyphen/underscore id.
Use captureStatus `captured|blocked|not-run|not-applicable` and reviewStatus `not-reviewed|pass|finding`.
Captured cases require `image`; all other capture statuses require `reason` and `not-reviewed`.
Attach optional `video` and `trace` paths to the relevant case. Resolve asset paths relative to the
manifest directory; only contained local PNG/JPEG/WebP, MP4/WebM and ZIP files are accepted, at most
100 MiB per asset and 256 MiB total per report. Split larger runs into explicitly scoped reports with
a common index retaining all cases; never omit evidence silently. Record review assertions and findings in expected/observed, and the next action in
every case.

DO group evidence by the POINT being shown, never by viewport or platform. `point` is the scenario or
claim in plain words (e.g. "Chat card: Advertiser disclosure open"); `column` is one id from the
top-level ordered `columns` list (web desktop, web mobile, iOS, any other size or platform captured).
Render each point as a heading and shared explanation ABOVE its own screenshot table. Repeat
heading → table for every point; reserve table columns for platforms/sizes, with no Point or
description column. Use one cell per declared column in the same order for every point. Each
cell holds that column's screenshots and videos, each case keeping its own conditions above its image;
before and after sit side by side inside that cell, before on the left; extra breakpoints stack. Every point needs at
least one case in every declared column: a platform or size the point does not cover gets a
`not-applicable`, `blocked` or `not-run` case whose `reason` shows in the cell, never a dropped cell
and never a separate list. Mobile and iOS images render at most 300px wide, desktop at full cell width.
TEST: rendering fails when a point lacks a case for any declared column, and N points produce N separate heading/table blocks with no text-only column. TEST: invalid status, duplicate id, missing evidence or unsafe path fails rendering clearly.

DO inspect the generated report in the available browser: TLDR table first (one row per point, one
status cell per column), then each point heading above its own gallery table (all cases inline in their platform
cell), conditions immediately above each screenshot, original aspect ratio preserved, readable desktop and mobile page.
The renderer embeds exact asset bytes in one offline HTML file, uses no network or external scripts,
escapes metadata and derives counts from cases, not supplied percentages. Retain the manifest and
capture scripts for reproducibility; sharing the HTML shares all embedded evidence. Keep secrets and
real-user captures private; screenshot masking does not sanitize trace network payloads.
TEST: the report works offline and exposes findings, unreviewed captures and all gaps without manual app clicking.

DO hand back the local report link plus a compact Point · Verdict/gap · Next action table, one row per point with each column's status in it. State counts
for capture statuses and review statuses separately, disclose sampled coverage and missing video, and
name any reviewer decision. The offline report stays local unless Simon authorizes its destination;
the PR evidence comment follows § PR evidence template.
TEST: Simon can review the intended UI journey from the report without driving the app himself.

## Hand-off check: every state of the artifact you hand over

DO run `python3 ~/.claude/bin/visual-check.py <artifact.html|URL> --out <dir>` on the exact file or URL
Simon will open, before any hand-off of a visual artifact (design board, mockup, dashboard, report,
HTML artifact, stitched image wrapped in an HTML page). Pass one `--state NAME=JS` per state he can
switch to, one `--viewport WxH` per size he will use (default 1440x900), one `--region CSS` per element
that must show content (a phone frame, a chart, a tile), one `--visible CSS` per element that must only be
whole (a title, a button), and one `--expect TEXT` per key string. Add one `--wait-for CSS` per element a
page that renders its data after load shows once ready (waits for visible after load and after each state's JS,
`--wait-timeout MS` default 30000; a timeout fails the row), and one `--route GLOB=FILE` to serve a local page a
fixture for its API route (content type from the extension, other requests pass through; a missing file exits 2).
DON'T hand-write a separate Playwright script for either. The tool loads the file fresh per row,
screenshots the full page, and exits 1 on any blank page or region, any region or visible element that is
not fully visible, missing string, page error or failed request (a media preload abort is not one; a missing media file is). A stitched image or PR image has no page: wrap it in a one-line HTML
page and check that, then view it.
DEFAULT: cap the table at 24 rows (viewports x states) and list every row; the default state is always row one.
NUMBER: blank means ink share below 0.05%, where ink is the share of pixels differing from the area's
most common colour; regions are inset 12% so rounded corners cannot pass for content. Not fully visible
means zero size, hidden, outside the document, cut by an ancestor with overflow hidden, clip, auto or
scroll (the fix for a Compare view that cropped every phone at half height while its strings were in the DOM),
or an element whose own overflow hides its content. Put the key elements of every view in `--region` or `--visible`.
DON'T accept "the string is in the DOM" or "the pixels are not white" as a pass; each proves one thing only.
DO view the PNG of every distinct view type (default, each variant layout, each compare or detail view),
at least the default state. The tool proves content exists and is whole, not that it is right.
DO, on any failing row, fix the artifact and re-run the whole command, never only the failed row, and loop
until every row passes (the fix for a board that opened blank after one separate render passed).
DO hand over the printed pass table (also at `<dir>/pass-table.md`) and the `<dir>` path with the artifact.
DON'T verify a sibling file, a `setContent` copy or one state in place of the artifact he opens.
DO add, for a screen built from a supplied design source, the measurement report and difference
images from `references/workflow-loops.md` § Build from a supplied design source to the hand-off; this
pass table proves the page renders whole, not that it matches the design.
`design-board.py check <board.html> <dir>` is the preset for design boards;
`bin/mockup-shots.py` stays the per-state capture for mockup shells and does not replace this check.
TEST: every artifact hand-off carries a pass table whose rows cover every switchable state of the file
actually opened, and re-running the command on that file exits 0.

## Research basis

DO verify installed capabilities rather than pinning instructions to a release. Sources checked
2026-10-15: [Playwright snapshots](https://playwright.dev/docs/test-snapshots),
[emulation](https://playwright.dev/docs/emulation), [videos](https://playwright.dev/docs/videos),
[screencast](https://playwright.dev/docs/api/class-screencast),
[agents](https://playwright.dev/docs/test-agents), [traces](https://playwright.dev/docs/trace-viewer),
[responsive design](https://web.dev/articles/responsive-web-design-basics),
[reflow](https://www.w3.org/WAI/WCAG21/Understanding/reflow),
[reference tests](https://web-platform-tests.org/writing-tests/reftests.html), and
[NIST interaction testing](https://csrc.nist.gov/projects/automated-combinatorial-testing-for-software/combinatorial-methods-in-testing/interactions-involved-in-software-failures).
Use [WCAG-EM](https://www.w3.org/TR/WCAG-EM/) as methodological support for scope, states and complete
processes; this screenshot workflow does not establish accessibility conformance.
