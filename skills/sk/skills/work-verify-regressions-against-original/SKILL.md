---
name: work-verify-regressions-against-original
description: Prove a branch left the original user flows alone. Record the vanilla web and iPhone flows on main, record the same vanilla flows on the branch against the same local stack and data, and compare logic, visuals and payment logic screen by screen; classify every difference as regression, intended or local artifact with evidence; then walk the new design end to end and confirm it works (design match is Simon's check, not this one). A small fast model reads the page text first, falls back to a screenshot only when the text is not obvious, and describes screenshots; the main model judges every verdict. Use for "verify regressions against the original", "record main's flows and the branch's flows and compare them", "check the vanilla flow is unchanged", "is the payment logic unchanged", "compare base and head flows", or as the stage of /sk:work-full-detailed-workflow and /sk:ship-full-detailed-workflow for any change that touches an existing user flow.
argument-hint: "[flows to compare, e.g. 'web US sign-up to paid, iPhone US onboarding to paid'] [--base <ref>]"
---

# Verify regressions against the original

Answers one question with evidence: does every existing flow the change touches still behave, look
and charge exactly as it did on the base? Then proves the new design works end to end. It does not
judge design fidelity; Simon checks that.

It composes, and does not restate:
- `~/.claude/references/testing-strategy.md` §§ Regression check, Live variants, Human-driven
  sessions, Pre-merge end-to-end on a local stack, Seeding and reset, Native simulator suites.
- `~/.claude/references/screenshot-review.md` §§ Capture and review, Verification run videos, PR
  evidence template (`bin/pr-evidence.py`).
- `~/.claude/references/browser-debugging.md` §§ The test browser, Navigate by the page text first.
- `~/.claude/references/ios-simulator.md` §§ Local backend safety, Drive and capture.
- `~/.claude/references/parallelization.md` § Strong models orchestrate and design; smaller models implement.
- `~/.claude/references/dev-server-hygiene.md` for the lane and capacity lease.

## Stage 1 · Name the flows and the base

DO list every existing user flow the diff reaches (`git diff --name-status <base>...HEAD`, then the
routes, screens and pay steps each changed file serves), per platform: web and iPhone, each in the
storefront or region the ask names (US by default). The base is `origin/<default branch>` after
`git fetch` unless `--base` names another ref.
DO name the vanilla path of each flow: the variant a new person gets with every new switch of this
branch OFF. A flow the diff does not reach records `not reached: <why>`.
TEST: the plan lists each flow x platform with its entry URL or screen and its last step (paid, or
the flow's terminal screen), or a not-reached reason.

## Stage 2 · Build one production-equivalent local stack, then prove the pay step

DO run the comparison on ONE local stack and ONE seed for both refs: the same database snapshot,
fixture accounts, provider test modes, clock and viewport; only the app code differs. Start each
ref's app in its own `git worktree` through the project's launch scripts, pointed at that stack.
When the head adds a schema migration, record every base run first, then apply the head's migrations
to the same stack and reseed the same fixtures; name the step in the plan.
DO mirror production's switches and environment into the local stack BEFORE the first recording:
apply `testing-strategy.md` § Live variants (production's dealt arms, read-only aggregates) and the
§ Human-driven sessions preflight axes 1-4 and 7. Copy every split, flag and price setting the flows
read into the local store, and print local vs production side by side per switch.
DO drive the pay step once on the BASE before recording anything: reach the provider's test checkout
(Stripe test mode `cs_test_`, a StoreKit test purchase), complete it, and confirm the paid state
lands. Fix the setup until it does.
WHY: a local setup gap (a blank key, an unseeded price, a switch left at its default) shows on BOTH
refs, and recorded on one ref alone it reads as a regression.
DON'T record a flow while any switch differs from production without stating it in the plan.
TEST: the plan holds the switch table with zero unexplained differences and one base pay-step run
that reached the paid state, both timestamped before the first recording.

## Stage 3 · Record the vanilla flows on BASE, then on HEAD

DO record each flow x platform on the base worktree, then the same flow on the head worktree with
the branch's new switches OFF: same account state at the start (a fresh account per run, reset per
`testing-strategy.md` § Seeding and reset), same steps, same inputs. Per step capture: the
screenshot, the page text (accessibility snapshot on web, the XCUITest hierarchy or `axe describe-ui`
on iPhone), the network requests with status and body for every API and payment call, and the server
log lines carrying the run's correlation id.
DO run the web flows in the test browser, in tabs this skill opened (`browser-debugging.md` § The
test browser); the iPhone flows on the owned simulator through the project's launch script, after
`xcrun simctl uninstall` and `xcrun simctl keychain <udid> reset` whenever the flow starts from a
fresh install (`ios-simulator.md` § Local backend safety).
DO keep emulation and storage changes off any tab a human is driving (`browser-debugging.md` § The
test browser).
DO save both runs under one evidence folder, `<flow>/<platform>/<base|head>/<step>.{png,txt,json}`,
and record each run raw per `screenshot-review.md` § Verification run videos.
TEST: every flow x platform has a base and a head run with the same step count, or the step where
they diverge is named; zero runs touched production or made a paid call.

## Stage 4 · Compare logic, visuals and payment logic

DO compare each step pair on three axes, and classify every difference:
1. **Logic:** the screen reached, the request sequence, every request's method, path, status and
   body keys, and the stored rows the step writes.
2. **Visuals:** `python3 ~/.claude/bin/design-diff.py <base.png> <head.png> --out <panel.png>` plus
   the measured position of each primary control (`testing-strategy.md` § Regression check); text
   and element differences from the page-text diff.
3. **Payment logic:** the price, currency, trial length, plan id, offer and provider product sent to
   the checkout, the checkout session's mode and line items, and the entitlement granted after pay.
Classify each difference with its evidence path:
- `regression`: the head differs and no ask names the change; fix it at its root, re-record that
  flow on head, and compare again.
- `intended`: the head differs as an ask clause names; quote the clause.
- `local artifact`: the difference comes from the stack, not the code; prove it by showing the same
  difference on base, or the setting that caused it, then fix the setup and re-record both refs.
NUMBER: zero `regression` rows at hand-back; a payment-logic difference is never `local artifact`
without a base run showing the same value.
DON'T call two runs equal from green suites or a code read; the step pairs are the evidence.
TEST: every differing step has one class and one evidence path; every payment-logic row names its
base and head values.

## Stage 5 · Walk the new design end to end

DO switch the branch's new flow ON (its flag, arm or route) and walk it from the real entry point to
its last step on each platform the ask names, on the same stack, per `testing-strategy.md`
§ Pre-merge end-to-end on a local stack: every screen renders, every control responds, every request
succeeds, and the pay step reaches the paid state in test mode.
DON'T judge it against a design source; Simon checks design match. Report a defect that breaks the
walk (a dead control, a failed request, a stuck screen, a wrong charge).
TEST: one pass-table row per new flow x platform with its evidence path; a failed step loops fix,
then re-walk, at most 3 cycles on the same failure before reporting it.

## Fast navigation and the model split

DO navigate per `browser-debugging.md` § Navigate by the page text first, web and iPhone.
DO dispatch step navigation and screenshot description to the small tier: an in-session agent with
`model: haiku` on Claude, `agent_setup.resolve_tier(provider, 'small')` on another host, on the
subscription. Brief it with the flow, the steps, the evidence folder and a fixed return shape per step
(screen name, visible prices and plan text, primary controls, errors shown). Give it no verdict.
DO keep every classification and every verdict on the main model: open the screenshot pair yourself
for every differing step and every pay step.
DON'T call any model API from the shell for this (`rules/spend-approval.md`, `rules/connectors.md`).
TEST: each small-tier brief holds no verdict request, and every `regression`, `intended` or `local
artifact` row was set by the orchestrator after viewing its pair.

## Stage 6 · Post and hand back

DO post the result under the PR's `## Regression check` as a `### Flow walk` table, `Flow | Platform
| Step | Axis | Base | Head | Class | Evidence`, plus the switch table and the Stage 5 pass table,
images and runs composed through `bin/pr-evidence.py` (`screenshot-review.md` § PR evidence
template). With no PR, hand the same tables back in chat with the evidence folder path.
DO shut down every server, tab and simulator this skill started, and remove both worktrees once the
evidence is copied out (`rules/process.md` § Clean up after yourself).
TEST: the posted table has a row for every differing step and a `no difference` line per flow x
platform that matched throughout.

Sources (checked 2026-11-25), for the model split; the navigation sources sit in
`browser-debugging.md`:
[Claude models overview](https://platform.claude.com/docs/en/about-claude/models/overview) (every
current model takes image input; the Haiku tier has the fastest comparative latency),
[Claude vision](https://platform.claude.com/docs/en/build-with-claude/vision) (resize before sending to cut latency),
[Claude Code subagents](https://code.claude.com/docs/en/sub-agents) (`model: haiku` alias for lower-cost tasks),
[Playwright visual comparisons](https://playwright.dev/docs/test-snapshots) (compare in the same
environment as the baseline, hence one stack for both refs).

Extra context for this run (if any): $ARGUMENTS
