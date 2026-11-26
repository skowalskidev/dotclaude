---
name: work-investigate-and-fix
description: Front door for production alerts and error reports. Takes pasted alerts, an error report, a Slack alert link, a teammate's or bot's pasted report of a production defect ("take a look and file it"), a provider-outage side effect or "investigate X and fix it"; checks the report's premise and whether an open or merged PR already fixes it; gives every symptom a verdict, finds the root cause from corroborated production data, logs, provider records, git history and the ticket's stated intent, fixes it at the owning source with a regression test, ships the PR, proves users gain from the fix, sweeps the recent deploys for regressions and verifies the deploy. Use for "investigate these alerts and fix them", "investigate X and fix it", "hotfix this", "prod is broken, ship a hotfix", a pasted Slack alert, "why is this failing in production", "is this really happening", "do we already have a PR for this", "is prod ok", or "any regressions since the deploy". Composes /sk:work-full-detailed-workflow as the build spine; does not restate it.
argument-hint: "the pasted alerts, error report, alert link, or the symptom to investigate"
---

# Investigate production alerts and fix them

DO run this as the front door, then hand the fix to `/sk:work-full-detailed-workflow` as the spine.
It composes the owners below and does not restate them. Prod stays read-only (`rules/connectors.md`);
a paid provider call follows `rules/spend-approval.md`.

## 0 · Hotfix mode

DO switch to hotfix mode when production is broken now and the fix meets the Hotfix trigger in
`references/testing-strategy.md` § Size the checks to the change; run § Hotfix tier there as the
whole build-and-ship path, and say so in the first reply.
DO keep steps 1-4 and 5's fix evidence, and cut what that section skips:
`/sk:work-does-this-make-sense-to-build`, the spine's planning and ticket stages, and every Standard
or Deep stage. Run step 7 after the merge, never before it.
DON'T let a hotfix grow: a second product file, a migration or a new surface ends hotfix mode and
re-sizes the PR at its new tier.
TEST: a hotfix run's PR records `Tier: hotfix`, its gate names `hotfix`, and no skipped stage ran
before the merge.

## 1 · One item per symptom

DO open the session record (`rules/living-plan.md`) and record every alert, error and symptom in the
paste as its own item. Close each with one verdict: root-caused, already fixed, expected, or needs
Simon's decision.
TEST: the count of items equals the count of distinct symptoms in the paste, and each has a verdict
with evidence.

## 1b · Check the premise before building on it

DO verify each number in the report (counts, rates, dates, amounts) against production data read-only
and recompute it yourself. DO verify any claimed provider outage from the provider's own status page
and our own telemetry (error rate, latency, the provider's job or event record) for the same window.
DON'T build on a figure or an outage you have not reproduced. A premise that fails is a finding:
report the corrected facts.
TEST: every number and outage claim in the report has a verdict (confirmed, corrected, refuted) with
its 2 sources.
DO hand a builder only a cause this step or step 2 verified, cited, or one labelled `Unverified
hypothesis:` per `references/parallelization.md` § Give every agent a precise, self-contained spec.

## 2 · Corroborate from every relevant source, and loop until sure

DO discover the provisioned connectors first: `rules/connectors.md` and
`references/connectors-setup.md` §§ Capability diagnosis and Production log reads.
DO run `connector_registry.py resolve <capability>` for EVERY capability the symptom touches
(database, logs, payments provider, analytics, ticketing, chat, CI, hosting), Vault-pointer routes
included through `connector_registry.py run`. Read each one that bears on a load-bearing claim.
Record every route outcome.
DO back every load-bearing claim with at least 2 independent sources: the production database
read-only, function or server logs, the provider's own record of the run or job (read-only), CI run
logs, git history and PR diffs, and the ticket and its comments. 2 is the floor, not the target.
DO state a confidence (high, medium, low) beside each claim.
DO loop: when sources disagree, or confidence is below high, pull another source or a narrower slice
(one account, one hour, one code path) and re-test. Stop when the claim holds at high confidence.
DO report a disagreement that survives 2 rounds as residual, with its stated confidence and the
source that would settle it.
DON'T conclude from a code reading or one log line.
TEST: each claim the fix rests on names its sources and confidence; every relevant resolved route was
read or has a recorded reason it was not; no claim below high confidence is stated as fact.

## 3 · Root cause from data

DO compare the rate before and after the suspect deploy, each with its denominator. Trace the alert
to the code that raises it, find the commit that changed it (`git log -L`, `git log -S`) and read
that ticket's stated intent (`references/planning-and-tracking.md` § A pre-existing ticket is a claim
about the past) before calling it a bug.
DO classify each cause: code bug, deliberate decision, external provider, or our own CI or test
traffic (`references/research.md` § Attributing behaviour to an outsider).
TEST: a "bug" verdict cites the commit and the ticket intent it contradicts; an "external" verdict
names the runtime identifiers it was compared against.
DO reproduce each "bug" verdict, with its control, before step 5's fix:
`references/testing-strategy.md` § Reproduce a reported bug first, then prove the root cause.
DO write each root cause as an evidence chain, one link per line, from the production symptom (the
status code, error or wrong record, with its count) through each hop to the line that causes it,
every link citing its source (log query, row, commit, file:line).
DON'T stop at the line that raises the error when another line decides it (e.g. a 403 raised by an
allowlist check whose cause is the new caller missing from the list).
TEST: every chain ends at the line the fix changes, and the reproduction fails on the base at that
link.

## 4 · Check for an existing fix, then judge the rest

DO search open PRs and PRs merged in the window for the same cause, by file path and by symptom
(`gh pr list --search`, `git log -S` on the raising code). Read each candidate's diff, not its title.
DO give each candidate one verdict: fixes it, partly, or no. Build only the uncovered part, on top of
a partial PR when it is open.
DO file or update the ticket when the report asks for one, linking the covering PR and the corrected
facts.
TEST: every candidate PR has a verdict citing the diff lines it read; the build covers only what no
PR covers.

DO then judge the fix before building it.

DO run `/sk:work-does-this-make-sense-to-build` on the proposed fix and research the mainstream
practice (`references/research.md`), citing primary sources.
TEST: the PR body's `Mainstream practice:` line holds at least 1 primary-source link, or `departs:`
with the reason this fix differs.

## 5 · Fix at the root and ship it

DO fix the single owner of the value or behaviour (`rules/engineering-standards.md` § Single source
of truth) and the class of failure (`rules/process.md` § Fix the CLASS of failure).
DO keep step 3's reproduction and control as the regression tests; the hand-back carries that
section's old-code and fixed-code results.
DO check the happy paths AND the paid paths the touched code serves, on base and head:
`references/testing-strategy.md` § Regression check, its pay-path pass included.
TEST: the PR body's `## Regression check` holds `Happy paths:` and `Paid paths:` lines, each path
with a test passing on base and head, or `none: <why>`.
DO sweep the class: the sibling callers of the fixed rule (`git grep` its key, list or check) and
the sibling symptoms of the same flow (`references/testing-strategy.md` § Production compatibility
gates); a guard each sibling needs lands in this PR or a test that fails when a sibling misses it.
TEST: the hand-back names the class, the siblings checked with their count, and the class test.
DO run the repo's local gates (`references/testing-strategy.md` § Defects first), open the PR with
`/sk:ship-pr` and run `/sk:ship-full-detailed-workflow` on it.

## 6 · Prove users gain, not only that the alert stops

DO show the fix changes the outcome in a real environment where authorized, e.g. rerun the failed
jobs against the real provider under `rules/spend-approval.md`. Quantify what users gain and what
stays unchanged, with denominators.
DON'T report a silenced alert as a fix.

## 7 · Sweep every recent deploy for regressions

DO dispatch a read-only parallel agent (`references/parallelization.md`) over every deploy in the
window (yesterday and today by default): before and after rates per surface, each with its
denominator. Fold in-scope fixes into the same PR.
TEST: every deploy in the window has a per-surface before/after line or a stated reason it has none.

## 8 · After merge

DO verify the deploy run for the merge sha and run a read-only production smoke against the changed
behaviour (`references/git-pr-deploy.md` § Shipping is not done until the deploy is verified), and
§ Live request path after every switch flip after any switch the fix or its Deploy TLDR flips.
Reply to the alert channel only when Simon asks (`references/connectors-setup.md` § Official account
connectors and completion messages).
TEST: the report names the deploy run, the live build and the smoke result for each fixed item.
