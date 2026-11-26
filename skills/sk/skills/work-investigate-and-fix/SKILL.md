---
name: work-investigate-and-fix
description: Front door for production alerts and error reports. Takes pasted alerts, an error report, a Slack alert link, a teammate's or bot's pasted report of a production defect ("take a look and file it"), a provider-outage side effect or "investigate X and fix it"; checks the report's premise and whether an open or merged PR already fixes it; gives every symptom a verdict, finds the root cause from corroborated production data, logs, provider records, git history and the ticket's stated intent, fixes it at the owning source with a regression test, ships the PR, proves users gain from the fix, sweeps the recent deploys for regressions and verifies the deploy. Use for "investigate these alerts and fix them", "investigate X and fix it", a pasted Slack alert, "why is this failing in production", "is this really happening", "do we already have a PR for this", "is prod ok", or "any regressions since the deploy". Composes /sk:work-full-detailed-workflow as the build spine; does not restate it.
argument-hint: "the pasted alerts, error report, alert link, or the symptom to investigate"
---

# Investigate production alerts and fix them

DO run this as the front door, then hand the fix to `/sk:work-full-detailed-workflow` as the spine.
It composes the owners below and does not restate them. Prod stays read-only (`rules/connectors.md`);
a paid provider call follows `rules/spend-approval.md`.

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

## 5 · Fix at the root and ship it

DO fix the single owner of the value or behaviour (`rules/engineering-standards.md` § Single source
of truth) and the class of failure (`rules/process.md` § Fix the CLASS of failure).
DO keep step 3's reproduction and control as the regression tests; the hand-back carries that
section's old-code and fixed-code results.
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
behaviour (`references/git-pr-deploy.md` § Shipping is not done until the deploy is verified).
Reply to the alert channel only when Simon asks (`references/connectors-setup.md` § Official account
connectors and completion messages).
TEST: the report names the deploy run, the live build and the smoke result for each fixed item.
