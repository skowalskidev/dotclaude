# Testing strategy

Write regression tests early, then implement; execute them under § Defects first.

- Structure testing as a tree: unit → integration → e2e per section. At final verification, run lower-level coverage before dependent higher-level checks.
- Plan both unit and e2e suites so they can run in parallel.
- Split tests into "runnable now" vs "needs extra resources" (second accounts, other platforms). The latter become prioritized follow-up tickets with instructions — or an immediate flag if blocking.
- Write the test plan simple → complex: seed scenarios for every case, happy path first, then edge cases. Save progress to a file so every part is tracked and ticked off.
- Verify someone else's code or branch at the batch gate; budget time to fix failures.

## Size the checks to the change

DO classify every change into ONE tier before dispatching any check, from `git diff <base>...HEAD`,
its tickets and what each changed file reaches (`git grep -l` its exports for importers, routes and
callers). The diff's tier is its highest trigger. This section is the one home of the tiers: every
rule, skill and gate that runs checks applies it and restates none of it.

| Tier | Trigger | Runs | Skips |
|---|---|---|---|
| Light | Copy, style or layout on ONE surface; zero logic, data, money, auth, API or shared-component change | The affected unit tests; one BEFORE/AFTER pair of the changed state at the default phone viewport (390×844); the project's gate list; CI; one verdict per ask clause in the ledger | Full matrix, prod data, deploy-safety merge train, ship-report journey tests, multi-model and security review, videos, multi-width and multi-state captures |
| Standard | Logic inside one feature, or a style-only change to a shared component (one pair per surface it renders on); no Deep trigger | Light, plus a test per changed behaviour, one review pass, `/sk:ship-verify-with-prod-data` Phase 1 applicability, ship-report with a test per criterion, a pair per changed state, a video and a verification run only for a changed journey | Full matrix, multi-model review, captures at widths no breakpoint in the diff touches |
| Deep | Money, price, charge, entitlement, auth, stored data, migration, a § Production compatibility gates decision, logic in a component or helper used on 2+ surfaces, cross-platform, release or production-gate change, or a blast radius the diff cannot bound | The whole `/sk:ship-full-detailed-workflow`: full matrix, prod data, deploy safety, § Value safety, journeys, videos, verification runs, multi-model and security review, the full screenshot matrix | Nothing |

**DO take the deeper tier when a trigger is unclear.** WHY: a missed regression costs more than one
extra pass.
**DO escalate the moment a lower tier turns up something unexpected:** a failing test outside the
changed lines, the change rendering on a second surface, a Deep trigger found while reading, a review
finding in logic, or prod-data Phase 1 finding a stored-data dependency. Re-classify, record the
escalation and its cause, run the added checks and keep the evidence already taken.
**DO apply a tier or check Simon names** ("just screenshot it", "run the full matrix"); when it sits
below a trigger present in the diff, name that trigger once and run what he named.
**DO record the tier, its trigger and every skipped stage, in one line each,** in the PR body's
`## Test matrix` section (each skipped section's heading stays, holding `Skipped (tier light): <trigger>`)
and in the gate reason: `intent-ledger.sh gate <branch> HEAD PASS light "<trigger>; skipped: <stages>"`.
**DON'T skip a stage silently, or drop the gates every tier keeps:** CI and required hooks, the gate
list in § Defects first, § Regression check, PR feedback handling, the Deploy TLDR, read-only production, spend approval
(`rules/spend-approval.md`) and `references/git-pr-deploy.md` § Prod check after every production deploy.
TEST: every PR and gate record names one tier and its trigger; a Light or Standard PR shows a skip
line per skipped stage; a diff holding any Deep trigger shows the full harness's results. (e.g. Light
is the fix for centring a wrapped word in one table cell, which ran a matrix, prod-data checks and
multi-width captures; Deep is the fix for a price label on shared paywall code, where the full pass
found a trial showing $0.00/mo.)

## The suite must never spend money

**A full test run triggers zero billable API calls.** Every paid dependency — video, audio, image
generation, any metered model or third-party call — is mocked or stubbed by default, so the ordinary
command is always safe to run, in a loop, in CI, by anyone.

Real-call coverage is worth having, and it lives behind an explicit environment gate that is off by
default, so reaching it is a decision rather than an accident. Where a whole class of call must never
escape, mock it globally in the test setup file rather than per-test: a per-test mock protects the
tests that remember it, and the one that forgets is the one that sends the email.

Verify this claim rather than asserting it. A mock wired to the wrong module path silently falls
through to the real client, and the first evidence is the bill.

## Test gates — make an unreachable flow reachable in a minute

A flow that takes a day to reach never gets tested properly. Build dev-only, clearly-guarded
bypasses for anything blocking a fast loop:

- **Collapse time for manual reachability; advance clocks for scheduling proof.** A guarded config
  switch can dispatch immediately or compress retry windows for a manual walk. To prove cooldowns,
  jobs, expiry or retries, use § Local time-driven simulations; keep the real delays and due checks.
- **A time-collapse switch is INSEPARABLE from an allowlist.** Collapsing time in a shared
  environment makes every stale record suddenly eligible, so you can fire real side effects at
  abandoned test data. Never ship the fast-forward without an "only these subjects" guard —
  and treat "non-allowlisted subject produces zero side effects" as its own test scenario.
- **Audit what already exists before flipping the switch.** Distinct from seeding: what stale
  records will my test mode wake up? Delete them or prove the allowlist blocks them.
- **Seed preconditions directly.** Keep a cheat sheet mapping each precondition to its direct-write
  command and verification command. Exercise the transition under test through its real entry point;
  rewriting due dates or marking jobs complete cannot prove scheduling. A person's first walk follows
  § Human-driven sessions.
- **Stub only external provider boundaries.** Replace the provider transport or adapter in test
  setup; keep the real routing, auth, validation, policy and persistence. A fake must not return ahead
  of the code being proved. Verify unexpected calls fail the test, including when the app catches them.
- **DO trace from the side effect a check must observe back to its entry point, in the mode the check
  runs in (fixture, mock or live), before running it.** A path the fixture returns ahead of is not
  observable in that mode; name in the plan the mode that exercises it. TEST: no check runs twice in
  a mode whose fixture stubs the code under observation (the fix for an event check run three times
  on a fixture that never reached the code firing it).
- **Every test-only bypass needs a defence-in-depth production lock** — gate on
  `flag === on && mode !== production`, checked independently in each layer, so a stray flag in
  a production deploy cannot neuter a real call.
- **Log every short-circuit** once per service, naming the provider, so the log says exactly
  which externals were faked.
- **Test the bypasses themselves.** A QA-only "trigger now" button or test mode is production
  code that can break.

## Seeding and reset

- **Idempotent, fixed ids, relative time.** Overwrite semantics so it re-runs; fixed ids so
  specs can name their rows; timestamps computed relative to now, with far-future sentinels for
  "never expires". A deterministic simulation can fix both its anchor and clock; record them together.
  An absolute fixture date without a controlled clock rots.
- **Baseline seed vs per-test seed.** The global seed holds only what is genuinely shared and
  read-only; per-scenario state is re-established per test.
- **Namespace whatever you create** so parallel work never reads someone else's rows. Assert on
  your named rows, never on global counts — "exactly N items on the page" is a guaranteed flake.
- **Seed the store the server actually reads.** Trace the read path first, and document any
  degraded-mode response shape the harness produces.
- **Seeded records must satisfy the production access rules.** A seed that only works because
  it was written with admin god-mode produces a UI that shows nothing.
- **Code-as-seed beats a saved data snapshot.** Snapshots rot and break clean checkouts.
- **Record every forced state and remove exactly what you wrote.** DO note the id of each row you write
  to force a state (a usage row, a temporary limit, a flag) when you write it, delete those ids and no
  others, read the count back, and state it ("wrote 6, removed 6, 0 remain"). DON'T clean up with a
  condition you invent afterwards. TEST: the written count equals the removed count and a re-read finds
  none (the fix for a time-based cleanup condition that matched nothing one second later and left the
  rows behind).
  DO apply the same to every external test object a run creates (Stripe customers, coupons,
  subscriptions, Auth users, uploads): record its id the moment it is created and delete only those
  ids at teardown. DON'T select deletions by time window, name prefix or "all test-mode" on a shared
  account, which also removes other live sessions' objects. TEST: every teardown deletion traces to an
  id this run recorded (the fix for 29 test customers deleted by "created since" that included other
  sessions' objects).

## Local time-driven simulations

**DO assess simulation applicability for every feature in the full matrix.** Run an isolated local
simulation when the changed behavior depends on elapsed time, scheduled/queued work, pagination,
retries, changing eligibility or a multi-step external side effect. Record one simulation subrow with
its scenario evidence, or `N/A` with the concrete reason; N/A describes applicability, not a passing
verdict. Select the relevant cases below, not their full cross-product for every change. Mark a required
but unrun case GAP or SKIPPED with its reason. TEST: no affected feature lacks this assessment.

**DO execute the real entry point, workers, policy and any persistence in an isolated runtime.**
When the path uses a database, load its relevant production schema, migrations, defaults and stored
functions into an isolated database. Replace only external provider boundaries. Give the runtime zero
production credentials and deny external network access by default, allowing only its local test
services. Verify destination refusal offline. Prove
lock/concurrency claims with independent connections and the engine semantics they require; a serial
emulator cannot establish them. TEST: effects and any persisted states come from production code, zero
external requests escape, and unsupported database/runtime behavior is an explicit coverage gap.

**DO drive all consulted clocks from one recorded virtual timeline.** Control application time,
database time/defaults/stored functions when used, and timers or monotonic clocks the path reads.
Install controls before startup captures time. Advance through real due checks without rewriting due
fields or bypassing guards. Assert each consulted clock and any written timestamps after each advance.
Use timer execution when callbacks matter; freezing Date alone does not execute timers. Check catch-up
behavior after a clock jump when callbacks can accumulate. Test immediately before, at and after each
changed time boundary, plus timezone/DST crossings when calendar time affects the result. Restore clock
and timer hooks after each run. TEST: an advancing application clock cannot pass with a frozen database
clock or an unexecuted callback hidden underneath it.

**DO seed named synthetic cohorts and compute expected outcomes independently of the code under test.**
Exercise 0, 1, limit−1, limit and limit+1 for each changed limit. A paginated path needs enough eligible
records for at least 3 source pages; a batched path needs at least 2 processing batches. Include eligible
and ineligible cohorts and another tenant when tenant scope exists. Check exact entity-and-step sets,
payloads, duplicate counts, persisted outcomes and rejection reasons, not totals alone. TEST: swapping
one recipient for another, losing a later page or sending twice fails even when the total is unchanged.

**DO select failure timelines from the changed mechanisms and record each selected case in the matrix.**

| Mechanism | Required scenarios when affected |
| --- | --- |
| Eligibility and controls | Change eligibility before enrollment, each later step and final dispatch; verify allowed and blocked transitions, opt-out, expiration, kill switch, stale/failed provider reads and recovery. |
| Events and reconciliation | Deliver duplicates, out-of-order events, equal-timestamp events and delayed events; reconcile current authoritative state. Exercise signatures/authentication when event ingestion changes. |
| Queue fairness and limits | Put blocked/poisoned work before healthy work beyond a page or batch boundary; exercise holds, caps, backpressure and recovery; prove healthy work progresses. |
| Workers and leases | Overlap two workers while work is active; expire/reclaim a lease and let the stale worker resume; assert the fencing/ownership rule and per-entity effects. |
| Retry and partial failure | Fail before persistence, after persistence, after provider acceptance and before acknowledgement; exercise transient/permanent errors, timeout, bounded backoff/jitter, total attempts across retry layers, exhaustion and recovery. |
| Idempotency | Replay the same logical operation, retry with a changed payload and cross the provider's documented key-retention window; assert the application's reconciliation policy for each outcome. |

**DO preserve ambiguous provider outcomes in the model.** Distinguish rejected, accepted and unknown
outcomes; an acknowledgement timeout cannot prove the provider did nothing. Model the actual provider
contract, including its idempotency scope and retention, and state any lag or last-read race the app
cannot close. TEST: no exactly-once or never-send claim rests only on a fake provider's stronger behavior.

**DO make provider fakes strict and observable outside application error handling.** Validate method,
path, identity, payload and planned response; accumulate unexpected calls and contract/assertion failures
outside callbacks the app can catch, then fail on that accumulator at the test boundary. Assert the exact
allowed call ledger and zero unintended effects after each phase. TEST: a swallowed assertion or an
unexpected request still fails the test even when the worker reports a handled error.

**DO run every new or changed third-party request shape once against the live provider, read-only,
before merge, and make its fake answer per request.** A new field set, level, breakdown or parameter
combination is a claim about the provider that a fake returning full rows for any request cannot test.
Run the exact request through the provisioned read path, record the answer, then make the fake return
only the fields asked and reproduce any quirk observed. TEST: the old code fails the updated fake, and
each new request shape cites one dated live answer. (the fix for a daily ads read whose provider returned
"0" spend whenever click counts shared a multi-day request, shipped green and caught only in production.)

**DO advance and drain work with explicit limits.** Record maximum ticks/iterations and a wall-time
ceiling before running; process a complete source scan and all due work at each required checkpoint.
Stop only after proving no unexplained due work remains, with delayed retries/holds accounted for, or
fail at the bound. An empty first page is not completion. TEST: the full named cohort reaches its
expected state within the bound, without sleeping through production-sized delays.

**DO add bounded generated action sequences when interacting transitions can invalidate an invariant.**
Use the project's existing stateful/property-test tooling or a small seeded driver; compare each step
with an independent model or invariant. Record the seed, action trace and minimal reproducer for a
failure. Keep fixed regression scenarios too. TEST: rerunning a failing seed reproduces the violation;
new tooling or an exhaustive combination sweep is not a prerequisite for a simple change.

**DO attach reproducible proof to the same matrix.** Record source revision, command, database/runtime,
seed, clock anchor and advances, cohort and exact expected/actual outcomes, mock ledger, drain bounds,
executed counts and known gaps. Preserve counterexamples as regression tests. TEST: the judge can trace
each verdict from an input through the real transitions to stored state and side effects; simulated
provider success never claims live delivery or production lock behavior that the harness did not prove.

Apply the relevant provider/runtime's current contract. Sources checked 2026-10-19:
[clock modes](https://playwright.dev/docs/clock),
[event delivery](https://docs.stripe.com/webhooks),
[idempotent requests](https://docs.stripe.com/api/idempotent_requests),
[bounded retries](https://docs.aws.amazon.com/wellarchitected/latest/framework/rel_mitigate_interaction_failure_limit_retries.html),
[stateful testing](https://hypothesis.readthedocs.io/en/latest/stateful.html).
These inform the scenarios; they do not require those vendors or libraries.

## Production compatibility gates

**DO verify production compatibility when changed behavior depends on stored data or observed usage,**
including displayed figures and runtime admission, rate limits, request validation, authorization or
retention migrations. Name each changed decision and its inputs even when no figure is displayed.
Declare N/A only after tracing the diff and proving it has no such dependency; a pure function or a
green fixture suite is not an exemption. TEST: a validator rejecting a supported client's legitimate
payload enters this check even with no UI change.

**DO enumerate current legitimate cohorts from authoritative account, entitlement and activity sources.**
Cover every affected cohort and reconcile checked, excluded and unknown counts to the source population.
Include plans, roles, client versions, shared identities and active users depending on older or purged
records when those dimensions affect the changed decision. Separate abuse using evidenced criteria;
do not label rejected high usage abusive solely because it exceeds the proposed limit. Record query
scope, pagination, capture time, event windows and coverage gaps under § Production source fidelity.
TEST: an old record still required by a current legitimate journey remains in scope; age alone never
proves legacy residue harmless.

**DO replay actual client payloads and recent legitimate usage through the changed gates locally.**
Use the real entry point, validation, authorization and retention behavior with isolated copies and
stubbed external providers under § Local time-driven simulations. Reconstruct payloads from supported
client code when captures are unavailable and label that evidence separately. Assert admitted requests,
rejection reasons and preserved workflows for each cohort, alongside unauthorized and abusive rejection
cases. Keep provenance and redactions private; no production credentials enter the replay runtime.
TEST: each changed gate has a reproducible allowed and denied case, and missing client or usage evidence
is UNKNOWN, never zero usage, N/A or a pass.

**DO derive limits from measured demand and declared capacity constraints.** For each changed budget,
record the unit, aggregation key, window, observed peak/distribution, proposed limit and numerical
headroom with its rationale. Include retries, concurrent devices and shared IP/phone/account/global
budgets when used; evaluate their combined effect, not each cap alone. A measured legitimate rejection
is a finding; an intentional eligibility reduction needs an explicit product decision. Missing telemetry
leaves capacity UNKNOWN and names the read/instrumentation needed; do not invent a safe threshold.
TEST: a shared budget exhausted by one legitimate workflow cannot silently block another supported one.

**DO report code verification, activation readiness and live proof separately.** Tie compatibility
verdicts to the source revision, captured population/window, exercised gates and known gaps. Record
deployment order, migrations/backfills and missing telemetry as activation dependencies. Preserve
read-only production access, per-write authorization and per-call spend approval; replay is not a
production write or a real-provider call authorization. State observed regressions or no regressions
found within the verified scope, never a zero-regression guarantee. TEST: green fixtures cannot clear
an UNKNOWN production cohort or an unexecuted activation dependency.

**DO replay every proven production incident case through the new code when the change fixes a
production failure.** Enumerate the incident cohort from production read-only (the selection query,
window and count), export each case's records under § Production source fidelity, and capture
production's live definitions of every database function, trigger and policy the path runs (e.g.
`pg_get_functiondef` over the read-only route). Load both into a scratch database, apply the diff's
migrations on top, run the new entry point once per case, and report `N/N` resolved plus each case
that did not resolve, with its reason.
**DON'T rest the verdict on a synthetic fixture or the repo's migration files alone.** WHY:
production's function bodies can differ from the files, and a fixture holds only the shapes its
author imagined.
TEST: an incident-fix hand-back names `N/N` against the enumerated cohort and the live-definition
capture time; a fixture-only replay is UNKNOWN, never a pass.

## Value safety: four answers before a money or access change is handed back

**DO answer all four questions below, unprompted and with evidence, on the final head of every PR
whose diff can grant, move or revoke value:** money, a charge, credits, an entitlement, an auth or
session decision, or which person owns a record. Post them under `## Value safety`, one line each
labelled `Happy path:`, `Failure re-enacted:`, `Wrong recipient:`, `Incident replay:` and
`Residual risk:`. A Deep PR that moves no value keeps the heading with a reasoned does-not-apply.
WHY: these are the first questions a reviewer asks of a money change; one left unanswered moves the
merge onto Simon.
1. **Happy path.** List every payment, grant and sign-in entry point by file, each marked touched or
   untouched (`git diff --name-only <base>...HEAD` against `git grep -l` of the checkout, webhook,
   grant and session handlers). Prove existing payers still pass: their suites on base and head, plus
   one walk of a returning payer's flow on the real local stack. NUMBER: zero added blocking requests
   and zero new error or warning lines on the happy path, read from the walk's network and console log.
2. **Failure re-enacted.** Re-enact the production failure end to end on a real environment, on every
   platform it occurred on, with the user's own steps (e.g. pay as a guest, leave, come back, sign in):
   the walk fails on the base and passes on the head, per § Reproduce a reported bug first. A PR fixing
   no production failure says so on the line.
3. **Wrong recipient.** Name who can trigger the change (identity, credential, device state) and prove
   refusal for every other identity: a test where a second account presents the first one's guest,
   device, token or link and receives nothing. Put each path you cannot close (e.g. a shared device)
   under `Residual risk:` as a decision for Simon; `none found` names what was checked.
4. **Incident replay.** Run § Production compatibility gates' incident replay inside
   `/sk:ship-verify-with-prod-data`, including the other-identity refusal from question 3 per case;
   the line reads `N/N resolved, N/N refused for another account` plus the cohort.
**DON'T answer any line from a code reading or wait for Simon to ask:** each cites a test, a walk or
a replay.
TEST: a Deep PR's fetched body holds `## Value safety` with all five labels and evidence on each, or a
reasoned does-not-apply; `bin/pr-landing-gate.py` fails it otherwise. (the fix for a guest-purchase
linking PR where Simon asked all four by hand; answered, they read: payment paths untouched, web and
iPhone walks PASS, 32/32 production cases linked, 32/32 other-account attempts refused, shared device
named as residual risk.)

## Production source fidelity

Read `~/.claude/rules/connectors.md` and `~/.claude/references/connectors-setup.md`; resolve the
project from git origin and the matching manifest before accessing production. Record the selected
source account/environment and read-only credential identity without exposing credential values.
Run production reads in a separate exporter process using the provisioned read-only credential.
Export the raw records the changed code reads, including dependent records and pagination; record
omissions explicitly. Store the snapshot privately outside tracked files with restrictive permissions.

Record a provenance manifest: source project/account IDs, query scope, capture time in UTC, record
counts, original earliest/latest event dates, timezone, snapshot hash, branch SHA and local destination.
Keep source timestamps unchanged. Record the calculation clock separately; use the real current clock
by default. An explicitly requested historical replay uses a recorded reference clock without changing
source dates. Label synthetic edge cases and identity redactions separately from the production copy.
Do not move old events into today's window, clear contamination or fill absent evidence to improve a
preview. TEST: counts and a field-level comparison against the export match except for the declared
identity/redaction mapping; every windowed result names its calculation clock.

DO corroborate every money, spend or attribution figure the change reads against its external system
of record (the payment processor, the app store's billing service, the ad platform) through the
provisioned connector or secret-store path, over the same window, before calling the figure correct.
Report each source as match or mismatch with both totals. DON'T reconcile the database only against
itself: two queries over the same tables agree even when a writer never recorded an event.
TEST: every money, spend or attribution figure in the hand-back names its external source, both totals
and the window, or the exact access gap. (the fix for store refunds a webhook revoked access on but
never recorded, found only when the billing service's own refund chart was compared.)

## Prepare derived state before capture

Trace the app's read path to the store it actually consumes. Import the production copy only into an
isolated local store or a namespaced development destination; verify the destination identity before
writing. Keep authentication, role and account mapping within that destination. Reject imports or
recomputes whose destination is production before constructing a write-capable client.

Name the data mode before capture:

- **Persisted-source:** run the changed readers against copied production records unchanged, including
  existing derived snapshots. Use this mode to inspect deployment skew or legacy-data rejection; report
  that no production refresh or local recompute was run.
- **Recomputed:** run the changed branch's real writer against complete copied inputs when claiming a
  post-refresh or post-migration result. Keep its output separate from the source snapshot; record
  writer version, calculation time and source hash. An account-only export cannot support a fleet-wide
  recompute. If required inputs are missing, retain persisted-source mode and name the unverified state.

Re-read through the app's normal API and reconcile visible figures to the selected mode's result.
Capture an honest empty, stale or insufficient state when the source supports it.
TEST: the evidence names one data mode and its inputs; API and visible values match that result, and
no post-refresh claim relies on a synthetic recompute from an incomplete subset.

## Local preview using production records

Use `~/.claude/references/dev-server-hygiene.md` and
`~/.claude/references/browser-debugging.md`. Record the changed routes and requested accounts first;
when none are named, choose accounts that cover the changed states and state the resulting coverage.
Reuse existing account-wide verification evidence when its source snapshot and branch still match.

Start the current branch's app/API against the isolated copy. Give the preview runtime zero production
credentials, production auth sessions or production service endpoints; the exporter alone can read
production. Bind local services to loopback. Disable background dispatch and replace external messaging,
billing, webhooks and analytics at their service boundaries so preview interactions produce zero live
side effects. A hidden button or a read-only database flag is not a runtime boundary.
TEST: inspect resolved destinations and credential identities without values, and test rejection of a
production destination offline. Confirm browser network and server logs reach only the declared preview
services. Never probe the guard by attempting a production write.

Drive the real changed UI using its normal routing, authentication and data reads. Keep source-derived
states intact for the fidelity pass; run editable/edge scenarios on a second isolated copy. Fix defects
and repeat the affected visual pass, preserving the provenance record after each recompute. For example,
a historical transaction remains on its original date even when that leaves today's chart empty.
Keep raw records and identifying captures local; publish only evidence the user separately requests.

Leave the verified preview available when a local-preview request is active. Record its URL, account,
route, source capture time, date range, data mode, clock mode, screenshots, gaps, process IDs, log paths,
and exact stop/restart commands in the local evidence file. Retain only those preview processes and
artifacts requested for review; stop exporters and unrelated test workers, and clear task authorization
sentinels. TEST: reopen the handed-back URL and confirm the branch, account and source-derived values;
the cleanup command targets only this preview and releases its claimed ports.

## Logging that makes negative paths provable

- **Tag every log line for a workflow** with a bracketed `[feature:phase]` and a lifecycle state
  word (`armed` → `status:sent` / `status:skipped` / `status:failed`), so one feature's whole
  lifecycle greps out of a noisy log.
- **Every skip and every rejection logs a machine-readable REASON** — `status:skipped
  reason:already_sent`, `reason:not_allowlisted`, `reason:above_threshold`. This is the single
  highest-value convention: half of a good scenario matrix is "the guard correctly did
  nothing", and "nothing happened" is otherwise unprovable. With a reason code it becomes a
  pass; without one you cannot tell correctly-suppressed from silently-broken.
- **Log level derives from mode, not a code edit.** Turning logging up for a test is a mode.
- **Correlation id on every line** (and per-actor identity), so one session filters out of a
  shared log.
- **Triangulate three signals after every scenario:** the runtime log, the dev-server console,
  and a re-read of the persisted records. The UI can look right while the write is wrong.

## Live variants: walk and judge what production deals now

DO run this before planning any walk, review or capture of a journey that passes through something
dealt per person or per device: an experiment arm, a feature flag, a pricing or onboarding variant, a
platform split. Skip it only when the code on the path shows no such dimension.

DO read what production deals NOW, read-only, through the provisioned path (`rules/connectors.md`),
as aggregates and never one person's row: per dimension and per platform, each arm dealt in the last
72 hours with its share, and each arm with zero deals in that window marked `stopped` with its last
deal date. Compare with the branch: an arm production deals that the branch lacks is `missing here`.
Take the arms from the data. A config file, a memory, or Simon's own account of which arms are live
is a claim to check against it.

DO compare it, before step 1 on EACH platform of a human walk, with the arms the local server dealt
this device (read from the server's log or the store it writes): print both side by side per dimension.
When they differ, copy production's split settings into the local stack (an isolated local store only,
per § Prepare derived state) and read the dealt arms again. No step 1 is sent until the two match or
the difference is stated in the walk's opening line. A platform whose local settings table is empty
deals no arm at all.

DO report it before the walk starts in at most 6 lines: the dimension, the live arms and shares per
platform, every `stopped` arm and every `missing here` arm.

DO pin the walk to an arm production is dealing: the largest share unless Simon names another, the
nearest live arm when the branch lacks the largest. Name the arm, how it is pinned and its share in
the plan (a paced walk's charter). DON'T pace a person through, review or capture an arm with zero
deals in the window unless he asks for that arm by name.

TEST: the plan names a dimension, an arm, its 72-hour share and the read's UTC time, and no walked
arm has zero recent deals. For each platform walked it also holds the local-dealt and production arms
side by side, matching or with the difference stated (the fix for a walk planned on an arm production
had stopped dealing days earlier, and for a second platform handed over with no arms dealt locally
because its settings table was empty).

## Human-driven sessions — prove the environment and the provider identity

A person clicking through a journey while Claude watches logs only works when both sit on the SAME
server and the SAME external accounts. Prove that before the first step with a side effect, not after
something has gone wrong.

**DO hand him a production-equivalent stack, proved by one preflight before step 1.** Check every axis
the journey touches and fix each miss before he starts:
1. Provider keys come from the source the project's launch path reads (its vault or secret store). Run
   `dev-server-hygiene.md` § Dependency handshake; a 401 or 403 is a stale override to fix, not a finding.
2. Every flag, experiment and split on the path deals what production deals (§ Live variants).
3. A fresh test account reaches the plan, trial and entitlement production gives a new account on that
   platform, read read-only from production as aggregates.
4. Every app and server starts through the project's own launch scripts, never a hand-rolled command
   that drops their environment.
5. The branch holds what will deploy: after `git fetch`, `git merge-base --is-ancestor origin/<default>
   HEAD` exits 0 (merge the default branch in first when it is behind, so one walk covers the
   assembled release), and each `git merge-base --is-ancestor "$(gh pr view <n> --json headRefOid -q
   .headRefOid)" HEAD` exits 0 for every PR under test. (the fix for a walk started on a PR branch 12
   commits behind main, restarted once Simon asked whether main was merged in.)
6. The journey's first 3 steps, and the first step that reaches each provider, run end to end in his
   state (a search returns results, a typed date parses, a new account lands on the expected plan).
**DON'T blank, fake or strip a key, flag or service to save cost or time.** A degraded stack fails like
a product bug and he cannot tell which. When cost is the concern, ask once in the front-loaded block
whether the session runs on billable keys; his yes covers the actions he drives, and each billable call
you fire still needs its own yes (`rules/spend-approval.md`). For a declined call, run its free half
(the handshake) and list the step as a gap.
**DO list every remaining non-production gap in the session overview once, one line each** (a checkout
with no test key, a bypass he picked), so he never meets one as a bug.
TEST: no step fails for an environment reason a preflight of that step would have caught, and every gap
he meets was in the overview (the fix for a local stack whose search and model keys were blanked to
avoid billing, so every typed search failed during a human test and read as a product bug).
This governs the stack the project's launch scripts start; a preview over imported production records
keeps § Local preview's credential boundary and lists its stubbed providers as gaps.

**DO start the default walk where a real person starts:** the real entry point, a fresh account or
device, and the whole lead-up that produces the state under test, so he judges the change in its
context. Seed a state directly only when walking cannot reach it in under 15 minutes (a used-up quota,
a later billing state), and label each such step `seeded` in the plan and when he reaches it.
**DO drive the entry yourself before giving step 1:** load the exact address step 1 names, in the
state he will be in (signed out, fresh device or profile) and the environment he will use, and confirm
the expected first screen renders with no redirect away, no failed call the page needs and no missing
local service. Fix or re-route the entry before he sees it. TEST: step 1's address was loaded by
Claude in that state this session, and what rendered matches the step's Expect line.

**DO run every later step yourself before you send it, the same way:** in your own browser, from the state
he is in (same storage, same account), and send it only when the Expect screen appears. DON'T write a
step from the code's happy path. TEST: each step sent has a run by Claude from his state with its Expect
line observed (the fix for three steps that bounced to another screen, reused storage in a "new" private
window, or made an account outside the plan, each costing him a round trip).

**DO perform every simulator relaunch yourself, and start his step from the screen you confirmed:**
terminate the app (`xcrun simctl terminate <udid> <bundle>`), launch it through the project's own launch
script, which passes the local server address and the rest of its environment (`references/ios-simulator.md`
Launch row), and screenshot it (`xcrun simctl io <udid> screenshot <file>`). DON'T run a bare
`xcrun simctl launch` when the project has a launch script: it drops that environment. DON'T tell him
to reopen the app from the home screen: only your launch points at the local server. TEST: no step to
the tester says to reopen or relaunch the app, every launch traces to the project's script, and each
step that follows a relaunch names the screenshot that confirmed its starting screen (the fix for a
tester told to reopen the app, and for a bare launch without the script's environment, both a white
screen).

**DO keep him signed in and give him a reset he can run.** Never delete or reset an account he may be
signed into. A reset step hands him the one line that clears the browser's storage and names the next
URL. Private windows of one browser share storage, so "open a private window" is not a reset; a
different browser or profile is. TEST: no account is deleted while he may hold its login, and every
reset step is one line plus the URL that follows it.

**DO name the host he must see in the address bar, and make his first request the proof.** Give the
exact URL (the tailnet or LAN preview, never a bookmark), have him load it, and find that request in
the watched log, with its correlation id, before step 2.
**DO stop the walkthrough the moment a step's expected request is absent from the log.** Silence from
the watched server means he is on a different server, such as production; treat it as a blocker, not a
quiet success.
**DO treat a payment step as gated.** Read the checkout session id from the server log or the
provider API before telling him to pay: a test-mode id (Stripe `cs_test_`) is a go, a live-mode id
(`cs_live_`) is a stop, and nobody pays.

**DO derive every local forwarder or listener for an external provider (Stripe `listen`, a webhook
relay, a tunnel) from the APP's own credentials**, read from the app's env file and passed explicitly
(`STRIPE_API_KEY` or `--api-key`), never from a CLI profile that merely points at the same vendor.
**DO prove account identity on both sides before the session**: fetch the account id with the app's
key and with the forwarder's key (Stripe `GET /v1/account`) and require them equal. A separate sandbox
account per key is normal, so equal vendor name proves nothing.
**DON'T override the app's configured secret or key because it disagrees with a counterpart you have
not identity-checked.** A hash comparison against the wrong account's listener reports a healthy
config as broken, and the "fix" then breaks delivery. Re-check any finding built on an unverified
counterpart before reporting it.
**DO replay a missed event instead of re-running the action** (Stripe `events resend <evt>` reaches a
running listener).

**DO reconstruct skipped steps when he reports a later step than the one you gave him.** Read the log
and the persisted state for each skipped step and check it, before continuing; never assume the steps
he did ahead of you ran against the watched server.

TEST: before any side-effecting step, the log holds his first request and the provider identities
match; a step whose expected request is missing halts the run.

**DO order work around a pending human re-walk: fix, then his walk, then the red tape.** When a human
walk (`/sk:test-copilot`, or Simon re-testing a flow) produced fixes and he will walk again:
1. Fix, and run the quick local checks (the touched unit tests, the typecheck).
2. Rebuild the local stack or preview from a fresh seed and hand him the re-walk.
3. Fix what he finds and repeat 1-3 until a walk passes.
4. Only then the red tape: verification run videos, push, CI waits, PR body and evidence, the landing gate.
**DON'T record a video, wait on CI or edit PR evidence before his re-walk passes.** Evidence captured
ahead of the walk is recaptured after every fix he triggers. A push he needs to open the build (a
remote preview) is the one exception.
TEST: in a plan with a pending human re-walk, no video recording, CI wait or PR evidence step is
ordered before the walk (the fix for videos and CI waits run ahead of his re-test).

## Layering and coverage arguments

- **Cheapest first.** Pure/offline checks before anything live.
- **Anything needing real credentials or costing money is a separate, named command behind an
  env var.** The default test command must be free, offline and safe on any machine.
- **Make an explicit coverage argument rather than blindly re-running expensive paths.** For a
  costly or irreversible side effect, state which unit tests already cover the branch and why it
  is deliberately not re-run live.
- **Separate behaviour regression from visual regression.** The automated suite proves outcomes
  survive refactors and re-skins; an intentional visual change must never fail a behaviour spec.
  The visual and UX half is precisely what a human pass is for.
- **Default scenario matrix for any user-facing feature:** happy path, error state, empty state,
  loading state, auth-guard behaviour, validation and boundary cases. DO exercise failure and recovery
  in the real client at final verification, at the smallest supported viewport and largest supported text,
  subject to § Native simulator suites. TEST: record visible recovery evidence or an explicit native
  runtime skip; unexecuted cases are never green.
- **DO run diff-scoped static audits (complexity, dead code, duplication) at the final gate before
  whole suites or builds.** Fix audit findings with the affected audit alone; carry its passing evidence
  into the gate. TEST: a passing audit is not rerun unless its inputs changed.
- **DO run the project's own cheap static gates exactly as its CI invokes them, before every push or
  ready-flip that starts CI.** Read the CI workflow for the command and scope: its type-check
  task, lint and duplicate/dead-code steps, over the same paths. DON'T substitute a hand-picked subset
  such as entry files only; it passes while CI fails, and each CI round trip costs 20+ minutes. This is
  the convergence gate before CI runs, not a per-edit run. TEST: each head CI runs on has a local pass of
  every static step CI runs, with CI's own command (the fix for two failed CI runs in one session: a
  duplicate-code step never run locally, and a type error in a test file missed by checking entry files
  while CI checked every file under the functions tree).
- **DO add a second-device row to the journey matrix of any account feature:** sign in as the same
  account in a second browser profile or device with empty storage and repeat the feature's core action.
  DON'T read a fact the server owns (plan, quota, entitlement, a saved choice) from device storage.
  TEST: the row passes with empty storage, and no client-side store read stands in for a server-owned
  fact (the fix for a member who could not search from a second browser because a request id was set
  only where onboarding had run).
- **DO verify a pay path for every account state that can reach a pay button before reporting it
  safe.** List each arm, each sign-up route, and guest and verified accounts; read the server's
  preconditions for each state; check production for each state's press-to-session rate over the last
  7 days. A state with presses and zero sessions is a finding, whatever the diff says. DON'T report a
  path working after walking it from one account state, or locally with no payment provider. TEST: the
  report has one row per account state with the precondition read and the production rate (the fix for
  a payment path called low risk from an empty diff, while one class of account had been refused by the
  checkout since an arm launched).
- **DO include the WHOLE package suite when a shared module changes.** A same-named test does not cover
  sibling consumers. Schedule this once at the batch gate, or reuse matching full-package evidence.
  TEST: a shared-module green verdict names full-package coverage, not one matching test file.
- **DO time every new or changed time budget on a read against production before release.** Run the same
  read read-only through the provisioned path, record the measured figure beside the constant, and
  treat a budget under 2x the measured time as a finding. DON'T accept a budget checked only against
  local data, where a warm local cache answers in milliseconds. TEST: each changed budget has a
  production-measured figure next to it (the fix for a 2 second budget on three parallel cache reads
  that took about 3 seconds in production, so a feature passed every local check and was missing live).
- **DO judge a nondeterministic system (an LLM agent, a ranker, any sampled output) against its baseline
  with at least 3 runs per side and a per-case paired diff.** Compare each case's checks and outcomes
  across the runs on both sides; a case that drops in most runs on one side is a regression even when
  the aggregate pass count matches. DON'T report "no regression" from one run's totals; report the
  per-case direction and the run count. TEST: every no-regression verdict on sampled output names the
  runs per side and lists the cases that moved (the fix for an agent prompt change declared clean on
  67/89 vs 68/89 totals, while one long conversation passed 47/66 vs 53/66 and asked 7 needless
  questions vs 1 over six runs).
- **DO tie a coverage verdict to its source revision, collection directory and complete test invocation.**
  Use partial reruns to diagnose failures; they do not replace full-run coverage. TEST: the reported
  percentage traces to complete collection for the same revision being judged.

## Regression check: prove the diff left existing paths alone

**DO run a regression check on every diff, at every tier, before calling its PR done.** List each
pre-existing file the diff modifies, renames or removes (`git diff --name-status --diff-filter=MRD
<base>...HEAD`; added files are exempt). For each file: its hunks, the existing callers each hunk
reaches (`git grep -n` its changed exports, components, routes, styles and keys), and proof that every
path outside the feature behaves as on the base. Proof is one of:
- a test over that path that passes on the base (run it in a base worktree) and on the head;
- for anything rendered, a base-vs-head screenshot pair of each existing screen the hunk reaches, same
  data, viewport and state, compared with `python3 ~/.claude/bin/design-diff.py <base.png> <head.png>
  --out <panel.png>` and by the measured position of its primary controls.
A changed existing behaviour that the ask wants is stated as INTENDED, naming the ask.
**DON'T take green unit tests, typecheck or e2e as proof for a rendered path:** none of them measures
where a button sits. NUMBER: one row per file; every caller, or above 10 callers every caller on a
distinct screen or route plus the count of the rest.

**DO compare an existing screen rendered in a NEW place against the same screen in its original
place, by measurement.** Capture both at the same viewport and data; for each primary control record
`getBoundingClientRect()` top and bottom, its distance to the viewport bottom (pinned or not) and its
container's scroll height. A difference above 2 CSS px is a finding unless stated INTENDED. Native
screens use their test frames under § Native simulator suites. Mount the part as its callers do first:
`references/code-best-practices.md` § Mount a shared part the way its existing callers do.

**DO add an independent pay-path pass when the diff touches code a pay path runs through** (paywall,
onboarding, checkout, a payment webhook, an entitlement grant), at every tier. A reviewer who did not
write the diff lists every pay path, proves each behaves as on the base with the feature switched off
by a test passing on base and head, and writes the test for any path without one; each path is a row
in the table below. TEST: every pay path the diff reaches has a row naming its test (the fix for a
flag-gated change whose pay-path pass found an unbounded session read holding payers before the paid
state moved on, under green suites).

**DO post the result in the PR body under `## Regression check`:** a table
`File | Hunks | Existing callers checked | Base-vs-head evidence | Result`, one row per modified
pre-existing file, Result `PASS` (outside paths unchanged) or `INTENDED: <change>`; then one row per
newly mounted shared part naming the caller it mirrored, and one measured row per screen reused in a
new place. A diff modifying no pre-existing file states that with its reason.
`bin/pr-landing-gate.py` fails the gate when the table has no Base-vs-head evidence column, a modified
pre-existing file has no row, its row has an empty evidence cell, a row holds neither PASS nor
INTENDED, or a row records FAIL.
TEST: the PR's `## Regression check` table has one row per modified pre-existing file with a
base-vs-head result (the fix for a reused sign-in screen whose buttons floated mid-screen at its new
call site while every automated suite passed; a human found it on a walk).

## Reproduce a reported bug first, then prove the root cause

**DO reproduce every reported bug on the unchanged code before writing its fix:** one failing test or
scripted run showing the user's symptom. It is the recorded concrete diagnostic § Defects first
allows; record its command and output in the plan.
**DO run that reproduction under the user's real conditions:** their engine and runtime (browser
engine, OS, app build), production-shaped input sizes and data, and their entry path, read from the
report, logs or production read-only. Name every condition you could not match.
**DON'T reproduce on a convenient substitute.** WHY: a substitute can pass on the buggy code (e.g.
WebKit localStorage refuses a ~2.5M-character value holding one non-Latin-1 character and Chromium
stores it, so a Chromium-only repro passed on the broken build).
**DO pair it with at least 1 control:** an input that worked for a real user before the fix, through
the same test (e.g. the smaller record that opened fine). The repro fails and the control passes on
the old code; both pass on the fix. That split proves the named cause is the discriminating factor.
**DO revert the fix locally once and watch the repro fail again, then restore it.**
**DON'T write the fix before the repro:** a test written to the fix can pass on both versions. When
the bug will not reproduce under matched conditions, list each condition tried and report the fix
as unproven, never root-caused.
**DO make the repro assert what the user sees, and state that outcome before and after the fix.** A
fix whose user-visible outcome is the same before and after (the same error, page or message) moved
a symptom: keep going to the cause the user feels, or name in the hand-back why that outcome stays.
TEST: a bug-fix hand-back cites the repro failing and the control passing on the old code under
named user conditions, and both passing on the fix; a missing control or an unnamed condition gap
is an unproven root cause. A before/after table whose user-outcome row reads "same" is not a
root-cause fix (e.g. a size check aligned with the database while the member still got the 503).

## Defects first

**DO default to zero automated tests, typechecks or verification builds during the whole authorized
task batch.** A batch includes every authorized feature and its review fixes, not one feature, commit or edit. Write regression
tests early without executing them. Run an early targeted diagnostic only for a concrete issue that
needs it or Simon's explicit request; record the reason and scope. Compile an implementation dependency
only when required to continue the work. DON'T turn cheap checks or dependency builds into a per-edit
verification loop. Leave required hooks and CI enabled and unchanged.

**DO read the project's CI configuration at intake, and again after every merge or rebase of the base
branch, and write its gate list into the plan:** every command CI runs that can fail the change (lints,
audits, design-system checks, type checks, pinned source tests), each with its local command. Diff the
re-read list against the recorded one and add every new gate; the base can add a gate at any merge.
Run each gate that takes under 2 minutes once on the untouched branch and record what it forbids; this
is the one diagnostic the batch runs by default. Write those constraints into every builder brief.
DON'T learn a gate from a failed CI run. TEST: the plan's gate list names the base sha it was read at,
and that sha is the latest base merged into the branch (e.g. an i18n coverage gate the base added
after intake, missed across two base merges).
**DO derive that list mechanically from the workflow files with `python3 ~/.claude/bin/ci-gate-list.py`
in the repo root:** every `run:` step of every job triggered by `pull_request` or `merge_group`, with its
working directory, one row each. Run a marked `CI-only?` step locally when its container runtime is
available; otherwise name it skipped with that reason, as for a job whose `if:` excludes pull requests.
**DON'T hand-build the list from reading the workflow:** a hand-built mirror drops steps (the fix for one
that missed a coverage-audit job, then a migration-order step that then failed CI).
TEST: the gate list's row count equals the helper's `TOTAL` run steps, and every skipped row names
its reason.

**DO run the whole gate list locally in one pass at merge prep, the last step before the ready-flip
that starts CI, a merge-queue enqueue, a merge or a deploy** (`references/git-pr-deploy.md` § CI runs
once, at merge prep). Re-derive it with `bin/ci-gate-list.py` on the final head and run every row,
over CI's own scope: every static gate, typecheck, lint and format, the secret scan over the branch's
commit range (e.g. `gitleaks git --log-opts="origin/<base>..HEAD"`), design and i18n checks, unit and
database/migration suites, e2e specs against a built site, and the native compile when the diff
touches native code. A row whose workflow `paths:` filter or job `if:` excludes this diff is named
skipped with that reason. Fix every failure before the flip or enqueue, so CI confirms rather than
discovers. Lease each heavy row through `local-capacity.py run --owner <session-id>`; its exit 75
is a wait, never a pass or a skip. A failure in a test the change did not add or edit that passes
when rerun alone is a load flake: record it by name with both results. Run the whole list again
before every later push to a ready PR whose diff touches files any gate reads: a review fix that edits
a test still owes the duplicate-code and dead-code gates, not only the suite it touched.
**DON'T run a hand-picked or remembered list at merge prep.** TEST: the merge-prep record lists each
CI job step it mirrored, by helper row, with its result, names every step not run locally with its
reason, and its row count equals the helper's `TOTAL`; no CI run on the pull request, first or later,
fails on a gate that has a local command (the fix for five gates found one push at a time, for
review-fix pushes that reran one gate and failed CI on another, for a secret-scan false positive on a
test fixture token caught only by CI, and for a hand-picked list that passed while CI's design job
failed on its i18n coverage script).

**DO finish the defect finders and their fixes before final execution:** code review (`/sk:ship-review`),
PR-thread resolution, the test-matrix Stage-2 judge and the journey judge. Then run the full relevant
suites and builds ONCE on the converged, reviewed batch, followed by the real-app check within its
platform scope. Include native compile checks for native changes and relevant backend payment, auth
and data coverage. Apply § Native simulator suites before scheduling device/simulator work.

**DO reuse passing local or CI evidence for the same relevant source, dependencies, configuration and
environment.** Record each command, scope, revision or source fingerprint, input match and result/log
proof. Map that evidence to the final batch; a new commit SHA alone does not invalidate unchanged inputs.
A prior partial run covers only its recorded scope, never the whole suite. Final verification remains
mandatory: run every uncovered relevant check, and report blocked or skipped coverage honestly.

**DO report executed, passed, failed and skipped counts per suite or test class.** A class with zero
executed tests is `not run`, listed with the flag or service it needs. DON'T accept or pass upward
"0 failures" alone. TEST: every verification line carries the four counts, and no class with zero
executed tests counts as passing (the fix for opt-in classes accepted as green at 50 skipped, 0 failed).

**DO root-cause any failure in a test the change added or edited before merging.** A green rerun does
not clear it; only a failure that also reproduces on the unchanged base counts as an existing flake.
TEST: every rerun past a PR's own test names the cause (the fix for a new browser test that failed once
on its PR, passed on rerun, then blocked every deploy on the default branch three runs in a row).

**DO fix final-gate failures and rerun the affected checks** (native: the failed classes only, with
`xcodebuild -only-testing:<target>/<class>`; the full suite runs once, at convergence, from the
orchestrator). Reuse the passing remainder; rerun a broader
suite only when a source, dependency, configuration or environment change invalidates its coverage.
TEST: no routine mid-batch run, no duplicate final suite from a later workflow stage, and every rerun
names its failure or invalidated inputs. Every completion claim links the full relevant evidence.

## Native simulator suites

**DO default iPhone/iOS simulator runtime tests, UI tests and screenshot capture to SKIPPED unless Simon
explicitly requests that native activity.** “All tests”, a full automated matrix or a generic UI change
is not opt-in. Do not boot a simulator, launch the app or capture native screenshots to complete an
unrequested check. Keep compile-only native checks for native changes and backend payment, auth and data
tests in the final gate. Record unrun runtime/UI cases and their reason separately from passing checks;
never infer a runtime pass from a compile. TEST: each native runtime/UI/capture run cites Simon's request,
and a default native batch completes with compile/backend evidence and honest runtime skips.
DO ask for the opt-in at intake, in the front-loaded question block, when a supplied design source covers
native screens; a grant covers scoped captures and the frame-assertion test classes of those screens,
never the runtime suite. TEST: no
builder of a native screen is briefed blind for want of an unasked opt-in.

DO apply `references/dev-server-hygiene.md` § Machine-wide capacity before booting a simulator or
starting native verification. Retain the lease across tool calls until the owned device is shut down.
TEST: a compile command exiting does not release a still-running simulator's capacity.

DO use `references/ios-simulator.md` for simulator execution. Apply the following runtime procedure
only after that opt-in.

**DO distinguish compile-only artifacts from runtime-test artifacts.** Before a full native suite,
run one scoped fixture for each required platform service with the same app, signing and simulator
configuration. Isolate test defaults, auth, singletons and host state from other app sessions. TEST:
each service fixture and any persisted-state assertions pass before the full suite starts.

DO treat `CODE_SIGNING_ALLOWED=NO` as compile-only evidence, never proof that Keychain or another
entitlement-dependent service works at runtime. For those tests, use the project's supported simulator
signing and existing entitlements; `CODE_SIGNING_ALLOWED=YES CODE_SIGN_IDENTITY=-` selects ad hoc
signing when that project supports it. Inspect the built host's signature and entitlements with
`codesign --display --entitlements :- <App.app>`, then run
the scoped service fixture before expanding coverage. DON'T require signing for every simulator test,
add entitlements blindly or weaken product authentication to repair a test host. TEST: the fixture
uses the same signed host as the suite and proves its required service operation. Apple documents
[entitlements in the code signature](https://developer.apple.com/documentation/bundleresources/entitlements),
[entitlement inspection](https://developer.apple.com/documentation/bundleresources/diagnosing-issues-with-entitlements)
and the [ad hoc pseudo-identity](https://developer.apple.com/documentation/security/seccodesignatureflags/adhoc);
ad hoc signing is not a developer identity (checked 2026-10-09).

**Pin the simulator to the CI locale before the full suite.** `xcrun simctl spawn <udid> defaults read -g
AppleLocale` must read `en_US`; a shared simulator left on a UK region failed 6 date tests that pass in CI.
**Pass `TEST_RUNNER_*` variables in xcodebuild's environment (`TEST_RUNNER_X=y xcodebuild …`), never as a
trailing argument.** A trailing one becomes a build setting and the test silently skips itself. TEST: a
full-suite run starts after a locale read, and no `TEST_RUNNER_` appears after `xcodebuild` on the line.
**Wait for the full runner result within the bounded stage timeout.** Redirect any run expected to take
over 5 minutes to a log file (`> "$LOG" 2>&1`) and read progress and failures from that file; DON'T pipe
it through `grep | tail`, which shows nothing until exit and then drops the failure list. Keep the
runner's exit status, complete log and result bundle; for `xcodebuild`, verify the final `** TEST SUCCEEDED **` or
`** TEST FAILED **` banner and the result bundle's test summary against the intended suite. A nested
`Test Suite '…' passed` or `failed` line is only one suite's verdict, not completion; never stop the
runner on that line. If the runner hangs after printing progress, let the stage timeout terminate only
its owned process group, then inspect the result bundle. Report an incomplete run when the full result
cannot be proved. TEST: a green full-suite claim has a completed runner, authoritative result evidence
and the expected test scope; a timed-out run cannot be called green from a nested suite line.

## The full automated test matrix — two stages, run unattended

The exhaustive-coverage method behind `/sk:test-automated-full-matrix`. That skill runs this
AUTONOMOUSLY — no human in the loop, no pacing — so it is safe to leave on a diff overnight. Its users
(`/sk:test-copilot`'s machine pass, `/sk:ship-full-detailed-workflow`, `/sk:work-full-detailed-workflow`)
run it and read its matrix; none of them restate the method.

**Enumerate every feature the diff added; a feature is a matrix ROW, not a file.** Build the work-list
from `git diff <base>...HEAD` cross-referenced with the plan's acceptance criteria
(`/sk:plan-stable-persistent-dynamic-complete-full-plan`) and the Linear tickets — code with no
criterion, or a criterion with no code, is itself a finding. The deliverable is a MATRIX: one row per
feature — `feature · layer (frontend/backend) · simulation applicability/evidence · Stage-1 test(file) ·
Stage-2 judgment · verdict (COVERED / GAP / NEEDS-DRIVING / SKIPPED)`. Apply § Local time-driven simulations
to its simulation subrow. Every feature ends with a verdict; a feature with no row is a hole.
Cover the WHOLE diff — every changed file's features, backend, frontend, tests and docs included; never
sample down to the "high-risk" files and eyeball the rest. TEST: the matrix's row set equals the diff's
feature set, and the run reports covered, gap, needs-driving and skipped counts without calling unrun
cases covered.

**Stage 1 — deterministic coverage for every feature.** Prepare unit/integration/e2e tests early,
covering happy path AND edge cases (empty, huge, unicode, concurrent, boundary, auth guard). Write a
missing regression test to detect the broken behavior; keep execution pending until review converges.
At the final batch gate, run each distinct relevant suite once, cheapest first, or attach matching
passing evidence under § Defects first. A suite shared by several rows runs once for all those rows.
Mark an unreachable rendered interaction NEEDS-DRIVING and hand it to `/sk:test-copilot`; mark unrequested
native runtime/UI cases SKIPPED under § Native simulator suites. Keep code under observation real;
provider fakes prove only the behavior and contract they model.

**Stage 2 — the selected setup's judge, before final execution.** Stage numbers identify coverage and
judgment, not execution order. Judge the code, test design and available evidence while Stage-1 execution
is pending; land the findings before the final batch gate. Afterwards attach its results to the same
matrix without automatically repeating the judge or suites. Reopen affected judgments only for new
findings or changed inputs. Reuse the saved workflow setup under `references/parallelization.md`;
every judge uses the current chat's provider, including after a resume or retry.
A passing assertion proves the code does what
someone thought to assert; it never proves the feature does what it was FOR. So for each feature — with
extra, multi-step reasoning for a complex or multi-call one — the judge reads the real inputs, outputs and
the trajectory (the writes, branches and tool calls it took) and judges two things: does this satisfy
the feature's stated INTENT and acceptance criteria, and would a first-time USER find the result
sensible. Judge even when Stage 1 is green — an invisible loading spinner and a lane that never polls
both pass every unit test. Run several INDEPENDENT lenses (correctness, the money/data path, the user's
read) rather than one long verbose pass, and default a lens to "fails" when unsure: an LLM judge carries
position, verbosity and self-preference bias, so redundancy under diverse lenses is the mitigation. This
is the 2026 default — an LLM judge agrees with human reviewers ~85% of the time, higher than two humans
agree with each other. Sources: openlayer.com/blog/llm-as-judge-evaluation-guide,
confident-ai.com/blog/why-llm-as-a-judge-is-the-best-llm-evaluation-method, deepeval.com/blog/llm-as-a-judge.

**Stage 2 covers the WHOLE diff — every feature, including one already GREEN under automated tests and
one a unit test structurally cannot reach or whose native runtime is SKIPPED.** A rendered frontend
surface is fully judgeable from its code, props and render logic without a browser: what it shows in each state, from what data. So the
"unreachable by a unit test" NEEDS-DRIVING label is a STAGE-1 (deterministic-reachability) marker ONLY —
it never exempts a surface from the Stage-2 reasoning judgment. Reason over that surface from its code; a
surface stays NEEDS-DRIVING for only the pixel/animation/feel a code pass genuinely cannot settle, not
the whole thing. (the fix for a run that punted every frontend render to a browser wholesale.)

**Fan out, save, post.** Fan test preparation and judgments out per feature; the coordinator deduplicates
suite execution at the final batch gate. Dispatch via
`/sk:work-hyperspeed` at 3-5+ slices, else an in-session Workflow under the concurrency cap
(`references/parallelization.md`). SAVE the matrix under the run's `.context/`, and POST it to the PR's
tests section, GitHub-native, on the posting rails `/sk:ship-screenshot-changes` Step 5 owns — so the
coverage and judgments live on the PR, not only in a transcript. Run the same deterministic stage in CI
to block regressions.

## Agent automations: test the runner contract before launch

**DO prove four things before a CI- or cron-run Claude agent goes live (claude-code-action, or
`claude -p` inside a job), and again on every change to its skills or workflow:**
1. **A committed allow-list contract test.** It extracts every command each skill teaches and checks
   it against that job's `--allowedTools` in a form Claude Code's permission check accepts: one line,
   no newline, `&&`, `;` or `|`, no unquoted glob, no shell expansion. Fill each placeholder with a
   probe value holding `?` and `&`.
2. **A local drive of each skill with the job's exact flags and no secrets:** `claude -p /<skill>
   --setting-sources project --strict-mcp-config --allowedTools "<job list>" --output-format json`,
   then read `permission_denials` from the result.
3. **A trigger-by-actor matrix for every Claude step:** each event that can start it and the actor it
   runs as, with every bot actor listed in `allowed_bots`. A scheduled run on a merge-queue repo can
   start as `github-merge-queue`.
4. **A dispatch-only connector check** that reads each credential once through the agent's own code
   path and posts nothing, plus a failure alert that reposts a new failure kind at once instead of
   waiting out the repeat window.

**DON'T widen the allow list to fit a denied command.** Fix the skill's wording or the tool.
NUMBER: zero `permission_denials` across the local drives before launch.
TEST: a launch or change hand-back for such an agent cites the contract test, the local drive's denial
count and the actor matrix. (the fix for an ops agent whose merge-queue actor refusal, a refused
multi-line vendor query and an evidence gate its own monitor-tuning fixes could never pass each
surfaced only in live runs.)

## Failure classes automated tests structurally cannot catch

Worth an explicit check whenever the change touches one:

- **Cross-boundary semantics.** Omitted vs null, partial vs full update, timezone, units. Two
  services can each have green tests while disagreeing: one means "omit = don't change", the
  other deserializes omitted and null identically and overwrites the column. Read the other
  side's source to verify contract semantics; never infer them from your own types.
- **Every runtime in the path must be running the code under test.** A guided run against a
  half-deployed stack produces confident nonsense.
- **Runtime-only declarations** with no build-time warning, e.g. a compound query needing a
  declared composite index.
- **Diff-scoped gates have a damage-caused-elsewhere blind spot** — deleting the last importer
  of a file leaves an orphan no diff-scoped check reports. Pair with a periodic whole-system scan.
- **A gate whose own policy the change can edit is not a gate.** Coverage thresholds, lint
  configs, ignore lists, baselines and skipped tests are all self-reported signals an agent will
  "fix" by weakening them. Baselines shrink, never grow; suppressions need an adjacent
  justification; verify the policy didn't get weaker independently of the check.
- **Silent degradation reads exactly like success.** Verify a quality artifact was actually
  consumed (look for the "real data" marker), not merely that nothing errored.
- **A guard tested only on its builder's own cases proves only what the builder imagined.** DO test
  a content guard (a filter that blocks banned output: a recommendation, a price, a claim) against
  at least 10 cases its builder did not write, from the brief or an independent judge: indirect
  phrasings, follow-up chips and links as well as the direct form, plus the ordinary sentences it
  must leave alone. TEST: the caught-list and the pass-list each hold cases the builder did not
  author. (the fix for a model-output guard whose own tests were green while it missed 14 of 20
  indirect phrasings a judge wrote.)

## Project specifics live in the project — read its own docs FIRST (self-healing)
- Apply `references/project-instructions.md` before the project-doc discovery below. When project instructions are ignored, derive commands from source, executable config and CI.
- This catalog is the generic philosophy. When project guidance is allowed, read the project-SPECIFIC how-to before testing: committed `CLAUDE.md`, then `CLAUDE.local.md`, then a dedicated playbook if one exists. Do not assume a playbook is required: a repo often states commands and layout in `CLAUDE.md`.
- **A fresh checkout is usually NOT ready to run tests, and its failures are not a baseline.** Determine one-time setup from allowed guidance or executable config (dependency install, native or codegen builds, pinned runtime, emulators). Run it before reading anything into a red suite. An unprepared tree fails identically to broken code, so recording that as the starting state silently blocks every later verdict.
- When project guidance is allowed, treat its playbook as a LIVING doc: fix a wrong step empirically and update it so the next run does not re-solve the problem.
- Machine-local secrets (test-account passwords, local paths) stay in the project's gitignored `CLAUDE.local.md`, referenced by name — never write a secret value into the committed playbook.
