# Advanced screenshot review

DO produce one private, offline review for the declared scope, using the existing installed capture
stack. Read `references/browser-debugging.md`, `references/testing-strategy.md`, and
`references/user-journey-review.md`; apply `references/ios-simulator.md` only for explicitly requested
native capture. Follow those owners for connectors, auth, source fidelity, ports and device lifecycle.
DON'T install a second framework, alter app DOM to add captions, or replace independent tests with images.
TEST: each capture identifies its source and real UI state, and captions exist only in the report.

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

DO capture authentic base/head evidence for visual comparisons with matching data, viewport and
conditions. Use separate cases with variant `before` and `after`, recording revisions in conditions.
Label any CSS reconstruction `simulated-before`; never present it as a base checkout. Keep original
images unaltered and uncropped in the gallery. TEST: each comparison discloses its source and any mismatch.

## Record useful walkthroughs

DO add native video for multistep journeys, transitions or motion when the installed stack supports it.
Explore first, save the explicit replay, reset state, then record a deliberate pass. Preserve findings
from exploration even when the final recording succeeds. In Playwright use
its supported video configuration or feature-detected `page.screencast`; retain successful demo videos,
not only failures. Match recording size to viewport, finalize by closing the context or stopping the
recorder, then inspect playback from first to last state and check readable labels. Native action
annotations are optional when the installed API supports them. TEST: a linked video opens and shows the
actual replay, not exploration or an unfinished file.

DO use the native simulator owner’s recording procedure for explicitly requested simulator video.
Use keyframes and record the missing video capability when the existing browser tool only captures
screenshots; do not invent a recorder or install one. Keep traces as optional investigation evidence,
never call a trace an executable replay. TEST: native opt-in and ownership remain intact, and no recording
process survives hand-back.

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
The report renders ONE ROW per point, with one cell per column in the same order on every row. Each
cell holds that column's screenshots and videos, each case keeping its own conditions above its image;
before/after variants and extra breakpoints in one column stack inside that cell. Every point needs at
least one case in every declared column: a platform or size the point does not cover gets a
`not-applicable`, `blocked` or `not-run` case whose `reason` shows in the cell, never a dropped cell
and never a separate list. Mobile and iOS images render at most 300px wide, desktop at full cell width.
TEST: rendering fails when a point lacks a case for any declared column, and each point appears once. TEST: invalid status, duplicate id, missing evidence or unsafe path fails rendering clearly.

DO inspect the generated report in the available browser: TLDR table first (one row per point, one
status cell per column), then the gallery table (one row per point, all cases inline in their column
cell), conditions immediately above each screenshot, original aspect ratio preserved, readable desktop and mobile page.
The renderer embeds exact asset bytes in one offline HTML file, uses no network or external scripts,
escapes metadata and derives counts from cases, not supplied percentages. Retain the manifest and
capture scripts for reproducibility; sharing the HTML shares all embedded evidence. Keep secrets and
real-user captures private; screenshot masking does not sanitize trace network payloads.
TEST: the report works offline and exposes findings, unreviewed captures and all gaps without manual app clicking.

DO hand back the local report link plus a compact Point · Verdict/gap · Next action table, one row per point with each column's status in it. State counts
for capture statuses and review statuses separately, disclose sampled coverage and missing video, and
name any reviewer decision. Publication requires explicit authorization for destination and content.
TEST: Simon can review the intended UI journey from the report without driving the app himself.

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
