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
| Light | A small change: at most 200 changed product lines (tests, fixtures, snapshots, docs and lockfiles not counted) on ONE surface or a team-only surface (an admin page, an internal tool); zero Deep trigger, API-contract change or native-build change. Editing or extracting a shared UI component stays Light while every existing caller keeps its behaviour and its tests pass | The affected unit tests; one BEFORE/AFTER pair of the changed state at the default phone viewport (390×844); the project's gate list; CI; one verdict per ask clause in the ledger | Full matrix, prod data, deploy-safety merge train, ship-report journey tests, multi-model and security review, videos, multi-width and multi-state captures |
| Standard | Logic inside one feature past the Light size, an API-contract change, or a change to a shared component that alters what an existing caller does (one pair per surface it renders on); no Deep trigger | Light, plus a test per changed behaviour, § Pre-merge end-to-end on a local stack for each changed journey, one review pass, `/sk:ship-verify-with-prod-data` Phase 1 applicability, ship-report with a test per criterion, a pair per changed state, a video and a verification run only for a changed journey | Full matrix, multi-model review, captures at widths no breakpoint in the diff touches |
| Deep | Money, price, charge, entitlement, auth, stored data, migration, a § Production compatibility gates decision, a behaviour change in a component or helper that 2+ customer-facing surfaces render, a native build, cross-platform, release or production-gate change, or a blast radius the diff cannot bound | The whole `/sk:ship-full-detailed-workflow`: full matrix, § Pre-merge end-to-end on a local stack, prod data, § Deep-tier discovery rounds, deploy safety, § Value safety, journeys, videos, verification runs, multi-model and security review, the full screenshot matrix | Nothing |

**DO take the deeper tier when a trigger is unclear.** WHY: a missed regression costs more than one
extra pass. A shared-component extraction whose callers' tests pass, or a team-only page, is not
unclear: size it by its lines and triggers. TEST: a PR under 200 product lines with no Deep trigger,
API-contract or native-build change records Light (the fix for a 120-line admin Refresh button sized
Standard because it folded three identical buttons into one shared part).
**DO escalate the moment a lower tier turns up something unexpected:** a failing test outside the
changed lines, the change rendering on a second surface, a Deep trigger found while reading, a review
finding in logic, or prod-data Phase 1 finding a stored-data dependency. Re-classify, record the
escalation and its cause, run the added checks and keep the evidence already taken.
**DO apply a tier or check Simon names** ("just screenshot it", "run the full matrix"); when it sits
below a trigger present in the diff, name that trigger once and run what he named.
**DO record the tier, its trigger and every skipped stage, in one line each,** in the PR body's
`## Test matrix` section (each skipped section's heading stays, holding `Skipped (tier light): <trigger>`)
and in the gate reason: `intent-ledger.sh gate <branch> HEAD PASS light "<trigger>; skipped: <stages>"`;
a Standard or Deep BLOCKED reason names its unrun required stages as `Not run: <stages>` or states
`All stages ran`; a Standard or Deep PASS states `All stages ran` and the gate refuses one with a
`Not run:` list (a tier-skipped stage goes in the `skipped:` line, never under `Not run:`). Every PASS
names its tier, and the gate refuses it until each stage that tier requires has a receipt on the gated
sha (`hooks/intent-ledger.sh` owns the per-tier stage list; `intent-ledger.sh stages <tier> HEAD`
prints what is missing).
**DON'T skip a stage silently, or drop the gates every tier keeps:** CI and required hooks, the gate
list in § Defects first, § Regression check, PR feedback handling, the Deploy TLDR, read-only production, spend approval
(`rules/spend-approval.md`) and `references/git-pr-deploy.md` § Prod check after every production deploy.
TEST: every PR and gate record names one tier and its trigger; a Light or Standard PR shows a skip
line per skipped stage; a diff holding any Deep trigger shows the full harness's results. (e.g. Light
is the fix for centring a wrapped word in one table cell, which ran a matrix, prod-data checks and
multi-width captures; Deep is the fix for a price label on shared paywall code, where the full pass
found a trial showing $0.00/mo.)

**DO size a monitoring-only change at Standard plus the monitoring-only bar.** The class and its merge
live in `references/git-pr-deploy.md` § Monitoring-only changes. The bar, all on the PR's final head:
1. both § Independent judges (`references/research.md`) return SHIP: OpenAI through Codex on the
   subscription and a fresh Claude subagent, never a headless self-review; each confirms the diff stays
   inside the class boundary (`references/git-pr-deploy.md` § Monitoring-only changes), workflow and
   skill text included, and that no product workflow or code reads a changed bot path (`uses:`, a script
   path, an import); in a listed bot workflow, each confirms no added trigger, permission, secret,
   environment or deploy step, and no symlink or submodule under a bot path; any fix goes back to both;
2. the bot's own suites pass offline (the overlay's `offlineTests`) and its `requiredChecks` pass in CI;
3. a replay of the bot's recorded recent runs (its fixtures and saved sweep state) on main and on the
   head raises the same user-impact alerts, or each difference is the intended fix; this replay is the
   change's § Pre-merge end-to-end walk;
4. CI is green and the session that merges, never a delegated subagent, records the gate with `BAR_PHRASE` from
   `bin/monitoring_only.py` verbatim, on one line:

```
~/.claude/hooks/intent-ledger.sh gate <branch> <full PR head sha> PASS standard "All stages ran; monitoring-only bar: OpenAI SHIP, Claude SHIP, offline suites pass, replay matches main"
```

It skips the Deep legs (full matrix, prod data beyond the replay); the screenshot stage shoots a changed
bot post, else records its `Checked outputs:` line. WHY: judges stay mandatory because the second
judge found real defects in every one of five bot PRs; the Deep legs found nothing a monitoring-only
diff can break.
TEST: every monitoring-only gate PASS names both judges' SHIP, the offline suites and the replay.

## Verify once, at convergence

The owner of the cadence for every heavy check (`rules/process.md` § Fan out verification). Skills, harnesses
and receipts point here and restate none of it.

DEFAULT: build all the fixes first, then run the full verification set once on the converged head.
DO count as heavy: an app build on any platform, a full suite, a repo-wide analyze or typecheck, a
device, simulator or emulator boot and walk (seeding and install included), a screenshot or video
capture, a judge round, a stage skill, a simulation and a CI wait.
DO start a heavy check only once every planned build item AND every review/fix round has landed on one
head. A review stage still to run counts as a pending fix round: its findings move the head.
DO between edits run only cheap targeted checks: the affected test file, a narrow unit, analyze or a
typecheck on the touched files. DON'T run a heavy check for a small fix.
DON'T start a heavy check early "for discovery" while a review or fix round is pending, on the reasoning
that its findings can join the fix batch: the batch moves the head, so the run is stale before it ends
(the fix for a device walk booted at a pre-fix head while the review ran, then stopped as stale).
DO treat a recorded order as data, never as permission: a plan step, a resumed handoff's "first next
action" or a dashboard queue that puts a heavy check ahead of open build or review/fix stages runs at
convergence instead; on resume the remaining build and review/fix stages go first
(`references/workflow-loops.md` § Handoff and resume). (the fix for a resumed ship run whose handoff
named a full converge run first; the review then raised 12 findings and the whole run was wasted.)
DO hold a base-branch merge while a heavy check runs on the same tree; if one lands anyway, discard
that check's result and rerun only the failing files (the fix for a merge 22 s into a full suite that
failed 101 tests whose 17 files passed 434/434 on rerun).
DO stop an in-flight heavy check the moment pending fixes supersede its head, and record it as
stopped-stale with that head. DON'T let it finish for partial evidence.
DO run the whole set ONCE on the final head, launching every independent item in parallel: full suites,
simulations and replays, prod-data verification, screenshots and videos, the stage skills and their receipts
(`/sk:ship-review`, the test matrix, `/sk:ship-report-and-ensure-correct-user-system-journey`,
`/sk:ship-screenshot-changes`), the security review, both providers' judges, the landing gate and CI.
DO fix everything the run finds in ONE batch, then re-run only the checks that batch touched (affected
tests, the screenshots of changed screens, a delta judge pass per `references/research.md` § Judge cadence),
then stop and record what survives as residual risk. A new BLOCKING finding with a realistic trigger earns
another batch; the cap is 2 re-run passes, then hand back with the residuals named.
DO treat a small follow-up delta (docs-only, one line, a test-only commit) per § Follow-up pushes and
waivers: its receipts carry, and only its own checks run.
KEEP: every check the tier requires still runs, once, on the head handed back. Only the cadence changes.
TEST: each heavy check ran once and names the head it ran on, which equals the final pushed head, or the
run records why an earlier head was needed (a concrete diagnostic Simon or a failing check asked for); no
hand-back shows the same full suite or stage run on two heads of one PR except after a Deep-path change,
and the judge cap holds.

## Double tap

The owner of how often ONE suite runs per change batch (`rules/process.md` § Fan out verification).
§ Verify once, at convergence owns when the heavy set starts; this owns the runs of a suite inside it.

DEFAULT: tap twice. One full run finds every failure, one run confirms every fix.
DO settle the whole design before the first run: every policy step of the change decided, and every
test expectation it moves written into the tests, so the run tests a finished design rather than one
step of it.
DO run the full suite ONCE collecting every failure. DON'T pass a fail-fast flag (`pytest -x`,
`--maxfail`, `jest --bail`, `vitest --bail <n>`) and DON'T stop reading at the first red: list every
failure before the first edit.
DO fix ALL of them in one batch, then confirm ONCE: rerun the full suite, or rerun only the failed set
(`pytest --lf`, `jest --onlyFailures`, or a config suite's own `--last-failed`) plus the touched files'
tests, then one full run at the end.
DO use a suite's `--only <substring>` and `--last-failed` while fixing, and its parallel workers for a
full run (`hooks/config-contract.test.py` takes both; `hooks/git-commit-guard.test.py` takes `--only`).
DON'T walk a policy change one step per full run (the fix for an 863-case guard suite run six times in
one session, 4-7 min each, while its policy moved one step at a time).
DON'T rerun a suite that already passed on the same tree: `bin/config-land-check.py` reuses the
contract suite's pass recorded for that `HEAD^{tree}`.
NUMBER: at most 2 full runs of a suite per change batch. A third needs a stated new cause written next
to it: a merge from main that touched the suite's files, a finding outside the batch, or a timeout
under load.
TEST: the transcript shows at most 2 full runs of each suite per batch, and every third run names its
cause.

Sources (each opened 2026-11-25): pytest `-x` stops after the first failure only when asked
(https://docs.pytest.org/en/stable/how-to/failures.html); `--lf` reruns only the last failures
(https://docs.pytest.org/en/stable/how-to/cache.html); pytest-xdist `-n auto` runs one worker per
physical core (https://pytest-xdist.readthedocs.io/en/stable/distribution.html); Jest
`--onlyFailures`, `--bail` and `--maxWorkers` (https://jestjs.io/docs/cli); Vitest `--bail` defaults
to 0 (run everything) and `--changed` runs the tests changed files affect (https://vitest.dev/guide/cli).

## Follow-up pushes and waivers

**DO carry a light or standard head's stage receipts to a later push of the SAME branch whose own delta
is Light-sized:** another PR's receipts on an ancestor head (reached through a main merge) never count.
At most 200 changed product lines in the PR's own commits since that head, no product file on a money,
auth, stored-data or native path, and no base merge touching a file the PR changes. A test-only
commit, a small review fix, a clean base merge or a small visual tweak qualifies. Run only the delta's
own checks: its affected tests, one BEFORE/AFTER pair when it is visible, the PR body's head sha, and
CI. `hooks/intent-ledger.sh` computes the carry from git (`stages <tier> HEAD` prints `All stages ran
(carried from <sha>...)`), so the gate's `All stages ran (carried from <sha>)` needs no rerun.
**DON'T carry a Deep receipt, or a delta past the bound:** rerun the tier's stages on that head.
TEST: a carried head's gate reason names the sha it carried from, and `stages <tier> HEAD` agrees.

**DO record Simon's explicit waiver of the checks for a PR** ("it's fine", "too much red tape", "just
merge") as `intent-ledger.sh gate <branch> <sha> N/A <tier> "waived by Simon: <his words verbatim>"`,
and stop running the waived stages on that PR. The gate refuses a quote that is not in a recorded ask;
the record covers the branch's later heads until one touches a money, auth, stored-data or native path.
CI, required hooks, spend approval and read-only production still hold.
TEST: every waiver record quotes words from the ledger's asks.

## Deep-tier discovery rounds

**DO run a read-only gap hunt on a Deep change that records, reports or attributes data** (telemetry,
analytics, a ledger, attribution): resolve every connector holding its own view of the same events
(production database, payment processor, app-store billing, ad platform) per `rules/connectors.md`,
read each over one window, and list each data point a question about the feature needs that the change
still does not capture. TEST: the hand-back names every connector read, or its access gap, and the
missing data points found or `none`.
**DO run scenario rounds on every Deep change with a user path:** pick the 10 scenarios the user cares
most about from its § Edge-case hunt before every walkthrough table, across the axes the change touches (new or returning account, device, payment outcome and
retry, return from a hosted page, each live arm, native bridge, embedded browser, a failing or offline
dependency, § Local time-driven simulations clock cases, a shared device). Drive each through the real
client, real server and an isolated local database. Report each round's BUGS and OPPORTUNITIES as two
separate lists, fix the bugs, and run another round until one finds zero new bugs.
**DON'T stop after a round that found bugs, or count a unit suite or code review as a round.**
TEST: the hand-back lists each round with its new-bug count, and the last round's count is 0. (the fix
for pay-path telemetry where two code reviews and green unit suites missed 5 missing data points and
10 bugs that a connector gap hunt and two scenario rounds found.)
**DO finish every Deep discovery stage before the first ready push, then batch their fixes:** the gap
hunt, scenario rounds to a clean round, `/sk:ship-verify-with-prod-data`, `/sk:test-automated-full-matrix`,
one whole-diff review, and a scan for app-wide code that intercepts the new traffic or data (request
guards, support or preview modes, e2e stubs and fixtures, admin counters). Fix every finding in one
batch, pass the local gate list once, then start CI under `references/git-pr-deploy.md` § CI runs once.
**DON'T mark a Deep PR ready and run discovery against it,** where each finding restarts CI.
TEST: on a Deep PR, every discovery stage's evidence predates the first CI run. (the fix for a telemetry
PR whose stages each found defects after it went ready: about 20 commits and 12 CI runs, plus an e2e
failure from a support banner that counted the new beacon.)

## The suite must never spend money

**A full test run triggers zero billable API calls.** Every paid dependency — video, audio, image
generation, any metered model or third-party call — is mocked or stubbed by default, so the ordinary
command is always safe to run, in a loop, in CI, by anyone.

**DO name, in every automated walk agent's brief, each app control that triggers a paid AI call (e.g. a "build my plan" button backed by a paid model) and the free alternative (a seeded record, a stub or the mocked path).** DON'T let a walk agent on a shared test server press such a control. TEST: the brief lists each paid control by label, and the walk's network log shows zero paid-provider requests (`rules/spend-approval.md`).

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

**DO sweep production for every sibling symptom of the same flow before a fix PR is called ready,**
unprompted, inside `/sk:ship-verify-with-prod-data`. This is `rules/process.md` § Fix the CLASS of
failure applied to production evidence: the reported case is one symptom of the flow, not its scope.
1. Name the flow the PR touches end to end (e.g. a checkout fix covers every pay door: paywall,
   wallet sheet, hosted page, member upgrade pages) and every outcome in it that is not success:
   refusals, error codes, drops between steps, client-side errors, retries, timeouts.
2. Read production read-only for each, since the last deploy of that flow and at least 7 days back:
   function and server logs (the newest log fields included, re-read the logging code for fields added
   since the PR started), the flow's tables and the payment provider's own records. Count each by
   reason with its denominator, per § Production source fidelity.
3. Give each symptom one verdict: `fixed by this PR` (name the test), `in scope, not fixed`, `correct
   behaviour` (the refusal reason it protects, per `rules/engineering-standards.md` § Payment paths) or
   `other owner` (ticket and owner).
4. Fold every `in scope, not fixed` symptom into the same PR at its root, through the one shared owner
   of that behaviour (`rules/engineering-standards.md` § Single source of truth), never a per-door
   patch. Research the mainstream practice from primary sources first (`references/research.md`), then
   loop fix, re-read production evidence, research the residual, fix, until every symptom holds a verdict
   other than `in scope, not fixed`.
Post the table `Symptom | Count / denominator | Window | Verdict | Evidence` under `## Prod data`.
**DO run step 1's code half before the first push, at the work harness's root-cause step:** grep every
other caller of the failing mechanism in the flow (e.g. each timer, retry or guard the same fault can
reach), so an in-scope sibling ships in the first build. The prod-data stage then only confirms it.
WHY: a sibling found at the ship harness's stage 6 moves the head after the other stages ran, and each
of them reruns on the new head (the fix for a year-switch timer found by the late sweep, which forced 8
ship stages to run again).
**DON'T call a fix PR ready from the reported case alone, or from logs read before the last deploy.**
TEST: a fix PR's `## Prod data` holds one row per non-success outcome of its flow in the window, each
with a verdict, and zero `in scope, not fixed` rows (the fix for a checkout PR where Simon asked for the
log sweep; it found wallet setup errors, an in-sheet retry refused and a stale-guest refusal, all
folded in through the shared retry owner).

## Value safety: five answers before a money or access change is handed back

**DO answer all five questions below, unprompted and with evidence, on the final head of every PR
whose diff can grant, move or revoke value:** money, a charge, credits, an entitlement, an auth or
session decision, or which person owns a record. Post them under `## Value safety`, one line each
labelled `Happy path:`, `Failure re-enacted:`, `Wrong recipient:`, `Incident replay:`,
`Provider lifecycle:` and `Residual risk:`. A Deep PR that moves no value keeps the heading with a
reasoned does-not-apply.
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
5. **Provider lifecycle.** On every PR that grants, revokes or moves paid access through a payment or
   entitlement provider (a card processor, an app store, a subscription service), enumerate that
   provider's documented lifecycle as a case matrix, unprompted, under `### Provider lifecycle` inside
   `## Value safety`, table `Case | Provider doc | Verdict | Evidence`. List the cases from the
   provider's own docs (its event, state and webhook reference) first, then map the code to each; the
   PR's own code and our incidents never set the case list. Cover these categories:
   - purchase outcomes: success, cancel, decline, pending or deferred (Ask to Buy, SCA, 3-D Secure)
   - renewals: billing retry and grace period
   - refunds, revocations and chargebacks
   - ownership transfers between accounts
   - trials and intro offers
   - sandbox and test environments
   - shared or family access
   - restore
   - provider outage, rate limits and stale reads
   - concurrent events (two webhooks, or a webhook racing a client call, on one purchase)
   - plan changes: upgrade, downgrade, crossgrade
   Each row links the provider's doc page for that case and reads `SAFE` with the `file:line` that
   handles it, `GAP` with the `file:line` that mishandles it, or `N/A` with the reason the provider or
   the diff cannot reach it. Fix every `GAP` before hand-back; one that cannot close goes under
   `Residual risk:` as a decision for Simon and keeps the gate failing. The `Provider lifecycle:` line
   gives the counts (`11 rows: 9 SAFE, 2 N/A`), or a reasoned does-not-apply when the diff touches no
   provider-backed paid access. Give the § Independent judges panel (`references/research.md`) the
   same matrix plus the provider doc links; each judge adds a row for any documented case it finds
   missing and re-verdicts each row from the code.
   NUMBER: every category above gets at least one row or a reasoned `N/A` row: 11 rows minimum.
**DON'T answer any line from a code reading or wait for Simon to ask:** each labelled line cites a
test, a walk or a replay; a matrix row cites its `file:line`, and each `GAP` fix lands with a
regression test that drives that case.
TEST: a Deep PR's fetched body holds `## Value safety` with all six labels and evidence on each, or a
reasoned does-not-apply, and a `### Provider lifecycle` table of 11+ rows, each with a doc link and a
verdict, zero `GAP`, unless its `Provider lifecycle:` line is a reasoned does-not-apply;
`bin/pr-landing-gate.py` fails it otherwise. (the fix for a guest-purchase linking PR where Simon asked all four by hand; answered, they read: payment paths untouched, web and
iPhone walks PASS, 32/32 production cases linked, 32/32 other-account attempts refused, shared device
named as residual risk. And the fix for a server grant of an app-store entitlement that passed all
four answers, a security review and four review rounds; only a by-hand pass over the provider's
documented lifecycle found a refund that left access moved to a second account live, a refund race,
and four more transfer defects.)

**DO give a decision that several doors read one agreement test that drives every door on the
same fixture state,** whenever a change touches a shared verdict (eligibility, price, offer, refusal):
e.g. a trial decision read by the quote, the confirm, the status check and the full-price sale. Each
case asserts the doors agree end to end (the quote's offer is what the confirm sells, and a refusal
leads to a sale that works), never one door at a time. Add every new door and every new fixture state
to the same table, and run it on each fix round.
TEST: a fix to a shared verdict carries a test that calls every door reading it on one fixture and
fails when any two disagree (the fix for three review rounds that each found the quote and the confirm
disagreeing after a fix had changed only one of them).

## Production source fidelity

Read `~/.claude/rules/connectors.md` and `~/.claude/references/connectors-setup.md`; resolve the
project from git origin and the matching manifest before accessing production. Record the selected
source account/environment and read-only credential identity without exposing credential values.
Run production reads in a separate exporter process using the provisioned read-only credential.
DO list the scheduled jobs that read the same vendor (an hourly monitor, a nightly sync) before adding
or running a production read, and run yours outside their window when they share a rate budget.
TEST: each production read run names the shared budgets checked and the window it avoided (the fix for
a post-deploy smoke at :28 that collided with an hourly monitor's sweep and blinded 6 checks).
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

### Tester access path: every user-facing variant ships one

DO ship every change to what real users see (an experiment arm, a new onboarding or paywall, a gated
flow) with a tester access path in the same PR: a code-gated link or a test-account list that lets
Simon or an agent reach that variant on production on demand. Hold it to all five:
1. **No change without the code.** A request without the code makes no database read; a wrong code
   reads only the code check and writes nothing.
2. **Fresh test device only.** It takes over a fresh, signed-out test device; it never re-deals a
   person's own browser, account or existing enrollment.
3. **The real happy path.** Same prices, same payment and confirm path, every step real users take.
   DON'T add a shortcut that skips a step: a tester walk is proof of the real path only without one.
4. **Out of every readout.** The walked device's deal carries a test marker that every readout and
   experiment metric filters out.
5. **One rollback.** Clearing the code switches it off, documented in the Deploy TLDR.
WHY: a path that leaks to one real visitor skews the experiment it exists to prove.
TEST: the PR carries a test that a request without the code makes zero database reads and a wrong
code writes zero rows, and a test that the walked device's deal is marked and excluded from the
readout; its Deploy TLDR names the code-set step, its smoke and its rollback
(`references/git-pr-deploy.md` § Deploy safety, check 3). (the fix for a guided-onboarding experiment
arm Simon could not reach on production: a walk code stored in its switch row, set right after
deploy, let him walk it with normal visitors untouched.)

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
7. Every client and server he touches serves the current head: read the sha each one reports (a
   server's identity handshake, `dev-server-hygiene.md` § 2; the served web build's stamp; the
   installed app's build fingerprint receipt, `ios-simulator.md`) and match `git rev-parse HEAD`.
   Rebuild and re-serve on any mismatch, and repeat the read after every commit before he re-walks.
   (the fix for a walk run on an old build after later fixes were committed.)
8. Every fixture account lasts its whole journey: read its lifecycle (reset on sign-in, expiry, one
   trial per device, a nightly wipe) and check it against each step it walks; a step that needs kept
   state (a returning member, a second sign-in) gets a persistent account. (the fix for a test phone
   number that reset on every sign-in and broke a returning-member step mid-walk.)
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
step from the code's happy path. A step-ahead run is not the whole-journey walk: before step 1, walk
every target to its last stage per `references/planning-and-tracking.md` § Every named part on every
named target. TEST: each step sent has a run by Claude from his state with its Expect
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
1. Fix per `references/workflow-loops.md` § Draft mode: a visible fix runs no check before his
   re-walk; a logic fix he needs for it runs only its touched unit tests.
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
  native screens included under § Native simulator suites. TEST: record visible recovery evidence or a
  recorded skip reason; unexecuted cases are never green.
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
in the table below. A pay path is an entry crossed with each account state that reaches it: a new
buyer (guest, signed-up free), a trial, a paid member upgrading or changing plan, a lapsed or cancelled
member resuming, and an already-paid member. Walk the happy path to paid for each on base and head,
unprompted. A new fallback, ended or error screen also gets the negative case: every valid state on the
happy path never renders it (e.g. a live offer never shows "this offer has ended").
TEST: every pay path the diff reaches has a row naming its test, upgrade and resume paths included (the
fix for a flag-gated change whose pay-path pass found an unbounded session read holding payers before
the paid state moved on, under green suites; and for a PR where Simon asked three times whether happy,
upgrade and resume paths were safe).

**DO check browser support for every web platform API a diff newly reaches on a user path, at every
tier, before ready.** Newly reached means a new call (a global, static method, DOM or CSS feature) OR a
new argument or option that switches existing code onto a branch calling one; read the body of each
helper a new argument enters (e.g. passing a `signal` into a shared fetch wrapper that then runs
`AbortSignal.any`). Take the project's browser floor from its `browserslist` (`.browserslistrc` or
`package.json`), else its framework's documented default target, else the oldest browser versions in
its own analytics over the last 30 days. Read each API's first supporting versions in MDN
browser-compat-data (developer.mozilla.org compatibility table, or caniuse, which imports it).
NUMBER: every browser in the floor supports the API, or the call sits behind a feature check
(`typeof AbortSignal.any === "function"`) whose fallback still sends the request, or a polyfill.
DON'T count a green suite, typecheck or deep gate as browser support: they run on current engines.
Record one `Platform APIs:` line under `## Regression check`: each API, the floor and its source, the
first supporting versions with the BCD link, then PASS, `fallback` or `polyfill`, with a test that
deletes the API (`delete AbortSignal.any`) and runs the path to its request; a diff reaching no new
API records `Platform APIs: none`.
TEST: every API a diff newly reaches on a user path appears on that line, and each one newer than the
floor has a passing API-deleted test (the fix for a pay-path request that threw before it was sent on
browsers older than the API, under a passing deep gate).

**DO prove a change to WHICH results or offers are shown keeps every good one the base showed,**
unprompted: a fallback that fills an empty state, a ranking or eligibility change. Replay a
production-shaped input set (recent real requests, read-only) on base and head and count each output
as kept, new or lost. NUMBER: zero lost good outputs, or each loss stated INTENDED with its ask; every
new output judged sensible by an independent judge (`references/research.md` § Independent judges).
TEST: the PR's `## Regression check` holds the `kept / new / lost` counts with the input window.

**DO post the result in the PR body under `## Regression check`:** a table
`File | Hunks | Existing callers checked | Base-vs-head evidence | Result`, one row per modified
pre-existing file, Result `PASS` (outside paths unchanged) or `INTENDED: <change>`; then one row per
newly mounted shared part naming the caller it mirrored, and one measured row per screen reused in a
new place. A diff modifying no pre-existing file states that with its reason.
`bin/pr-landing-gate.py` fails the gate when the table has no Base-vs-head evidence column, a modified
pre-existing file has no row, its row has an empty evidence cell, a row holds neither PASS nor
INTENDED, or a row records FAIL.
**DO run `/sk:work-verify-regressions-against-original` for the flow-level half when the diff
touches an existing user flow:** it records each vanilla flow on base and head on one local stack and
posts its `### Flow walk` table under the same heading.
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
**DO run a row that needs a tool the workflow installs (a `setup-*` action, a pinned CLI download)
with that tool at the workflow's pinned version, fetched on demand without changing the repo:**
`npx -y <pkg>@<version>`, `brew install`, or a pinned release download into a scratch directory,
removed after. Read the version from the action's `with: version:` input or the step's own pin.
**DON'T name "needs tool X" as a skip reason while the tool can be fetched;** a skip names a tool only
when no build of it runs on this machine (e.g. a Linux-only binary), and the row then waits for CI.
TEST: no skipped row's reason is a fetchable missing tool (the fix for a function-bundle size row,
skipped as "needs supabase CLI", that CI then failed on a 4.7 MB upload-budget breach;
`npx -y supabase@<pinned>` ran it locally).

**DO run the whole gate list locally in one pass at merge prep, the last step before the ready-flip
that starts CI, a merge-queue enqueue, a merge or a deploy** (`references/git-pr-deploy.md` § CI runs
once, at merge prep). Re-derive it with `bin/ci-gate-list.py` on the final head and run every row (a
base-merge-only head runs its touched rows, below), over CI's own scope: every static gate,
typecheck, lint and format, the secret scan over the branch's commit range (e.g.
`gitleaks git --log-opts="origin/<base>..HEAD"`), design and i18n checks, unit and database/migration
suites, e2e specs against a built site, and the native compile when the diff
touches native code. A row whose workflow `paths:` filter or job `if:` excludes this diff is named
skipped with that reason. Fix every failure before the flip or enqueue, so CI confirms rather than
discovers. Lease each heavy row through `local-capacity.py run --owner <session-id>-pr<n>`; its exit 75
is a wait, never a pass or a skip. A failure in a test the change did not add or edit that passes
when rerun alone is a load flake: record it by name with both results. Run the whole list again
before every later push to a ready PR whose diff touches files any gate reads (a base-merge-only push
takes the scoped pass below): a review fix that edits a test still owes the duplicate-code and
dead-code gates, not only the suite it touched.
**DON'T run a hand-picked or remembered list at merge prep.** TEST: the merge-prep record lists each
CI job step it mirrored, by helper row, with its result, names every step not run locally with its
reason, and its row count equals the helper's `TOTAL`; no CI run on the pull request, first or later,
fails on a gate that has a local command (the fix for five gates found one push at a time, for
review-fix pushes that reran one gate and failed CI on another, for a secret-scan false positive on a
test fixture token caught only by CI, for a hand-picked list that passed while CI's design job
failed on its i18n coverage script, and for fix workers' pushes that ran a repo-wide duplicate scan and
skipped the scripts group, so CI failed on the PR's own duplicate test and a migration's reset scan).

**DO scope the local pass on a base-merge-only head to the rows the merge touches.** A head qualifies
when it differs from its last fully gated head (a full local pass or green CI on that sha) only by a
merge of the base plus mechanical renames: migration restamps (pure renames, similarity 100%) and
manifests the repo's own generator rewrote. Check it: `git diff --name-status -M <old-base>...<gated-head>`
and `git diff --name-status -M origin/<base>...HEAD` differ only in those files. Build the touched set
from the PR's own diff (`git diff --name-only origin/<base>...HEAD`), the merge's conflicted files and
every renamed or regenerated file. Run locally each row whose scope holds a file of that set: its
working directory, its workflow `paths:` filter or a path its command names. Always run a row with
none of these (it reads the whole repo), the secret scan over the commit range, the repo's ordering and
migration checks, and every row CI skips on this PR (e.g. heavy jobs on a PR stacked on a non-default
branch). Name every other row `not touched; CI runs it`. A head with any other change is new behaviour
and runs the full list.
WHY: an untouched row reads the same bytes as the base, whose CI already passed them.
**DON'T name a row not touched when its scope is unclear, or when CI does not run it on this PR: it runs.**
NUMBER: rows run, rows not touched and rows skipped sum to the helper's `TOTAL`; zero rows whose scope
holds a touched file are named not touched.
TEST: the merge-prep record names the gated head's sha, the touched set and each row's verdict; a head
with any change beyond the base merge and mechanical renames shows every row run; no CI run fails on a
gate that has a local command (the fix for a merge-only head that ran all 118 rows, an iOS compile
included, and sat 2 h unpushed).

**DO diagnose a red CI run on a head by rerunning only its failed specs, locally, on that same head
first** (e.g. `--repeat-each=5` on the failing e2e specs against the build already made). Build and run
the base only when the head fails; a head that passes every repeat is a load flake, recorded by name,
and the failed CI job is rerun. DON'T rerun locally a gate CI already passed on that sha, or start the
full local gate list to diagnose one red job: the full list runs before a push of a NEW head.
NUMBER: the first local diagnostic step after a red CI run is the failed job's specs, within 15
minutes of reading the log. TEST: no diagnosis rebuilds the base, reruns CI-passed gates or runs the
full suite before the failed specs ran on the head (the fix for a two-hour serial re-run of CI-passed
gates before one flaky browser spec ran once; it then passed 150 of 150).

**DO compile-check native code (Swift, Kotlin, Objective-C) before a review of it counts as done:**
run the narrowest leased build that type-checks the changed files on the reviewed head (the app
target's `xcodebuild build -quiet`, or `./gradlew :<module>:compile<Variant>Kotlin`), once per review
round, as the one native compile this policy allows before convergence; `swiftc -parse` catches syntax
only, so record it as `syntax-only` when no build can run. The full native suite still runs once at
convergence. TEST: every review verdict on native code cites a compile result on the reviewed sha
(the fix for a Swift compile error that passed two read-only reviews and surfaced at the first build
after them).

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

**DO report executed, passed, failed and skipped counts per suite or test class, with the head sha it
ran on, the time it finished and the 1-minute load average while it ran** (`git rev-parse --short HEAD`
at launch, `sysctl -n vm.loadavg` on macOS, `uptime` elsewhere; native and e2e runs read the load at
launch and at the result). A class with zero executed tests is `not run`, listed with the flag or
service it needs. DON'T accept or pass upward "0 failures" alone. DON'T quote a result from a log whose
sha is not the current head as the head's result: quote it with its own sha and time plus the input
match that carries it (evidence reuse, above), or rerun it. TEST: every verification line carries the
four counts, its sha, its finish time and its load, and no class with zero executed tests counts as
passing (the fix for opt-in classes accepted as green at 50 skipped, 0 failed, and for a stale e2e log
reported to Simon as "39/39" after later commits).

**DO rerun a failing test alone before calling it a regression when it waits on wall-clock time** (a
timeout, a retry deadline, a poll or animation wait) **and its run's load average exceeded the core
count** (`sysctl -n hw.ncpu`). Rerun only that test or class (`-only-testing:<target>/<class>`, the
single spec) and record both results with both loads. Pass alone: a load flake, named with both runs.
Fail alone: a regression, handled under § Reproduce a reported bug first. A test the change added or
edited still owes its root cause (below). TEST: every timing-only failure at a load above the core
count shows an alone-rerun row before any regression verdict (the fix for two wall-clock iOS classes
that failed only at load 100 to 383 and passed alone, after time spent judging them as regressions).

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

## Edge-case hunt before every walkthrough

**DO run a read-only edge-case hunt before every walk a human-facing change gets, at the Standard and
Deep tiers:** the full matrix's real-client walk, `/sk:test-copilot`'s machine pass and charter, the
ship-report journey tests, step 2 of § Pre-merge end-to-end on a local stack and the scenarios of
§ Deep-tier discovery rounds all start from its table. A Light change hunts its one changed state
against the failure modes below that it reaches. WHY: a scripted walk proves only the steps someone
wrote down; the practical bugs live in the combinations nobody scripted.
1. **Enumerate from the code's state machines, not from the plan.** List every entry point a person
   reaches the changed flow from (first run, re-entry after leaving, deep link, notification,
   settings, a second device) and every state the code keeps for it (persisted flags, enum states,
   permission and connection states, sync cursors). Cross each entry x state with each failure mode
   the code can meet:
   - a permission denied, partly granted, or revoked later in system settings;
   - no data, late data (arriving after the screen rendered), the same data from two sources;
   - the app killed or backgrounded mid-flow, relaunched, or reinstalled;
   - offline, a 5xx, a slow backend, a timeout in the middle of a write;
   - a double tap, back during a write, two tabs or devices racing;
   - a second account on the same device, sign-out mid-flow;
   - units and locale, timezone, midnight and DST boundaries;
   - platform availability (an OS version or simulator without the capability);
   - a reminder or notification over several cycles: first, repeat, after the action is done, after opt-out.
2. **Write each plausible broken case into the walk list with its expected behaviour,** one row each:
   `Entry x state x failure | Expected | How walked`. Expected names what the person sees: the flow
   carries on, uses what it already knows (syncs in the background, prefills), says what is missing
   and offers the next step. Drop an implausible combination only with its reason.
3. **Walk each row on the real client where it is walkable** (a § Test gates route, the system
   settings toggle, airplane mode, `xcrun simctl privacy` or `terminate`, a stubbed 5xx); prove the
   rest with a unit test on a fake clock or a fake platform adapter. Fix every failure in the batch
   and rerun its row.
4. **Report every row, fine ones included,** as `FIXED`, `FINE`, `UNIT: <test>` or `DROPPED: <reason>`,
   with the count of each, beside the walk's pass table.
NUMBER: at least 1 row per entry point x failure-mode family above that the changed code reaches;
zero rows left open at hand-back.
**DON'T treat Simon's reported bug as the scope of the hunt.** It is one row of a class; hunt the
rest of the table (`rules/process.md` § Fix the CLASS of failure).
TEST: every walk hand-back on a Standard or Deep human-facing change carries the hunt table and its
counts; a later-reported practical bug the table lacks is a missed enumeration, fixed at its source
(the fix for a connect-a-health-data-source flow whose scripted walks and two code reviews passed
while a hunt found 12 practical bugs, 3 high, among them a connect-then-continue that neither synced
gracefully nor prefilled what the source already held).
Sources (checked 2026-11-24). Term: "interrupt testing" for app kills, calls, network and lock
([SmartBear](https://smartbear.com/blog/the-how-and-why-of-interrupt-tests-for-mobile-apps/),
[Perforce](https://www.perforce.com/blog/perfecto/interruption-testing)); an exploratory charter
treating denied and later-revoked permission as separate states
([exploratory testing on mobile](https://dev.to/kelina_cowell_qa/exploratory-testing-on-mobile-the-messy-checks-that-find-real-bugs-2ldg)).

## Pre-merge end-to-end on a local stack

**DO prove every change to a user-visible flow or its backend end to end before its PR is called
ready, web and iPhone alike, at the Standard and Deep tiers (a Light change keeps its real-client
BEFORE/AFTER pair), in four steps:**
1. **Suites.** Run every automated suite the diff reaches (unit, integration, e2e), whole for each
   touched package, locally at the final batch gate; § Defects first owns timing and evidence reuse.
2. **Journey walk.** Walk each changed user journey start to finish, plus every walkable row of its
   § Edge-case hunt before every walkthrough table, on its real client: the browser
   through the project's e2e runner (e.g. Playwright) for web, the iOS Simulator through an XCUITest
   walk under § Native simulator suites for the iPhone app. Point the client at a hermetic local
   stack: the local database or emulators, the payment provider's sandbox or test mode, and a stub for
   every paid or third-party provider. The walk touches zero production rows and makes zero billable calls.
   DO point the client there by construction, web or native: a build setting over a per-launch one,
   every launch and relaunch through one wrapper that refuses to start without the local backend, its
   first request seen on the local host before the first step, and a stop on any production request
   with the rows listed read-only for Simon (`references/ios-simulator.md` § Local backend safety).
3. **Loop.** Fix each failure and rerun the affected checks, then rerun steps 1 and 2 once on the
   converged head. A test passing on the base and failing on the head is a regression, fixed before
   hand-back (§ Regression check); a failure the change did not cause follows § Defects first.
4. **Evidence.** Hand back a pass table, one row per journey x client, `Journey | Client | Backend
   mode | Steps | Result | Evidence path`, and each suite's executed, passed, failed and skipped
   counts on base and head. On a PR it sits under the `Real-environment walk:` line of `## Test matrix`.
NUMBER: stop and report after 3 fix cycles on the same failure (`rules/process.md` fix → verify loops).
**DON'T call a PR ready, or hand back, with a changed journey proven only by unit tests, a compile, a
code read or a plan to check after deploy.** WHY: a gap found in production costs a release, a fix and
a second live verification; the same gap on a local stack costs one loop.
**DO name a step the local stack cannot reach** (a real app-store purchase, a third-party login with no
sandbox) as `not run: <what it needs>`, walk every step around it, and add a § Test gates route when
that takes under a minute. With no local stack, stub the network at the client (Playwright
`page.route`, a UI test `launchEnvironment` pointing at a stub server) and record the mode as
`stubbed client`. A capacity wait (exit 75) is a wait, never a skip.
**DO fill the `Real-environment walk:` line of a Deep PR touching native app code (`ios/`, `android/`)
or a payment or entitlement path with each simulator, device or local-stack walk that ran, PASS or FAIL
each, or a reasoned N/A naming why no user journey changed;** an unreachable step is a `not run:` row,
never the line's N/A. TEST: `bin/pr-landing-gate.py` fails such a PR whose line is bare, rests on unit
tests or gives any other N/A reason (the fix for an App Store purchase PR that passed its gate before
its simulator walk ran).
This section adds no production read or write and no paid call: read-only production,
`rules/spend-approval.md` and the capacity lease hold throughout.
TEST: every Standard or Deep PR touching a user flow or its backend shows one pass-table row per
changed journey on its real client, backend mode `local` or `stubbed client`, a clean final run, and
base-vs-head suite counts with zero new failures (the fix for changes released before an end-to-end
walk, then fixed and verified live); each walk transcript shows the host check before its first step
and no launch outside the wrapper.
Sources (checked 2026-11-16). Term tally, "end-to-end test": Fowler, Google Testing Blog, Playwright
and Kent C. Dodds (4); "acceptance test": DORA (1); "UI test": Apple (1). Environment: emulator
(Firebase), local development (Supabase), sandbox (Stripe), test doubles (Fowler, DORA), network mocks
(Playwright). [Practical Test Pyramid](https://martinfowler.com/articles/practical-test-pyramid.html)
("Avoid integrating with the real production system in your automated tests"),
[DORA test automation](https://dora.dev/capabilities/test-automation/) (no "dev complete" until
acceptance tests pass; dependencies replaced by test doubles),
[Just Say No to More End-to-End Tests](https://testing.googleblog.com/2015/04/just-say-no-to-more-end-to-end-tests.html),
[Testing Trophy](https://kentcdodds.com/blog/the-testing-trophy-and-testing-classifications),
[Playwright best practices](https://playwright.dev/docs/best-practices) ("Only test what you control"),
[Firebase Emulator Suite](https://firebase.google.com/docs/emulator-suite),
[Supabase local development](https://supabase.com/docs/guides/local-development),
[Stripe testing](https://docs.stripe.com/testing),
[XCUIApplication](https://developer.apple.com/documentation/xcuiautomation/xcuiapplication) (launchArguments, launchEnvironment).

## Old app builds against the new backend

**DO run each in-use old app build against the PR head's backend before the PR is called ready, at
every tier, whenever `references/git-pr-deploy.md` § Deploy safety check 4 applies, in five steps:**
1. **Pick the builds.** The store's current live version always, plus every other version holding at
   least 10% of active installs in that check's version table.
2. **Build the old app.** Check out the commit that version shipped from (its release tag, or the commit
   its build number maps to) in its own `git worktree`, build it for the Simulator or emulator (a
   desktop app: the released binary) and install it on an owned device (`references/ios-simulator.md`
   for iOS). DON'T stand in the PR branch's build with its version string edited: it sends the new
   request shapes.
3. **Two runs, same steps.** Walk the old build's main journeys (sign-in, the home screen and every
   journey whose backend the diff touches) once against the local stack at the base branch and once at
   the PR head, same seed and steps, backend override per `references/ios-simulator.md` § Local backend
   safety.
4. **Compare.** PASS = zero 4xx/5xx in the head run's API log that the base run lacks, and every head
   screenshot matching its base pair (design-diff or measured control positions; per-run values such as
   timestamps excluded). A difference is a compatibility break, fixed in the backend; only a
   server-rendered change the PR names INTENDED for old builds passes.
5. **Record** `Old build <version> against the new backend: PASS`, with the run logs and screenshot
   pairs, in the PR's `## Deploy safety` section.
NUMBER: stop and report after 3 fix cycles on the same break (§ Pre-merge end-to-end on a local stack).
**DON'T substitute a walk of the new build, a code read or a contract test for this run:** the new
build sends the new shapes, so it cannot show what an old build breaks on.
**DO record a blocker, never PASS, when the old build's source cannot be found or built.** The walk
touches zero production rows and makes zero paid calls, as in § Pre-merge end-to-end on a local stack.
TEST: every PR check 4 applies to holds one PASS line per picked version with base and head run logs
and screenshot pairs, or a named blocker; a head-only 4xx/5xx or changed screen is never PASS.

## Native simulator suites

**DO run iPhone/iOS simulator runtime tests, UI tests and screen captures by default for every change
the iPhone app reaches:** native source, or a backend, API or shared web change a native screen calls or
renders. Run the touched native unit and UI test classes, the XCUITest journey walk of § Pre-merge
end-to-end on a local stack and the captures the screenshot stage needs, all against the local backend
(`references/ios-simulator.md` § Local backend safety). Keep the native compile and backend payment,
auth and data tests in the final gate. Capture every native screen a supplied design source covers,
with its frame-assertion classes. Skip native runtime work only when the diff reaches no native screen
(record `native: not reached, <why>`) or Simon says to skip it. A backend change a shipped build calls
also runs § Old app builds against the new backend.
**DON'T infer a runtime pass from a compile, or skip the simulator because nobody asked for it.**
TEST: a diff the iPhone app reaches shows per-class executed, passed, failed and skipped counts and the
walk's pass-table rows, or a recorded not-reached or Simon-skip reason; no native run reaches
production or makes a paid call.

DO apply `references/dev-server-hygiene.md` § Machine-wide capacity before booting a simulator or
starting native verification. Retain the lease across tool calls until the owned device is shut down.
TEST: a compile command exiting does not release a still-running simulator's capacity.

DO use `references/ios-simulator.md` for every simulator run and apply the following runtime procedure
to each.

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

**Keep seeded device state across restarts, and re-verify it after every boot.** DO boot any emulator
or simulator that a walk seeds (installed data-seeding tools, records in a platform health store) so
state persists: for the Android emulator omit `-no-snapshot-save`, which reverts the device to its saved
snapshot on every restart. DO re-read the seeded records after ANY device boot, before the first walk
step, and treat "no data" as a reverted device until that check passes. DO finish builds before booting
a long-lived emulator under the lease, or boot it as `references/dev-server-hygiene.md` § Machine-wide
capacity prescribes for long-lived processes, so a rebuild never forces a reboot. DON'T wrap a
long-lived emulator in `bin/native-slot.sh run`: it holds the owner's one lease and every later build
exits 75. TEST: a walk report names the seeded-data check run after the last device boot. (the fix for
35 minutes spent diagnosing a snapshot-reverted emulator as an app bug)

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
native runtime/UI cases SKIPPED only with a reason § Native simulator suites allows. Keep code under observation real;
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
- **A UI test that scrolls to act proves less than a person sees.** An e2e runner's click scrolls the
  target into view first (Playwright's actionability checks), so a button that a sticky bar, a raised
  card or an overlay covers at the person's own scroll position still passes. DO assert, before each
  tap a person makes, that the control is the element at its own centre
  (`document.elementFromPoint`) at the scroll position the screen leaves it, and pair the suite with
  one real walk of the changed journey. TEST: each tapped control in a changed screen's e2e has that
  assertion. (the fix for a coach-mark screen whose raised card covered Continue: the e2e was green,
  the local walk could not tap it.)

## Project specifics live in the project — read its own docs FIRST (self-healing)
- Apply `references/project-instructions.md` before the project-doc discovery below. When project instructions are ignored, derive commands from source, executable config and CI.
- This catalog is the generic philosophy. When project guidance is allowed, read the project-SPECIFIC how-to before testing: committed `CLAUDE.md`, then `CLAUDE.local.md`, then a dedicated playbook if one exists. Do not assume a playbook is required: a repo often states commands and layout in `CLAUDE.md`.
- **A fresh checkout is usually NOT ready to run tests, and its failures are not a baseline.** Determine one-time setup from allowed guidance or executable config (dependency install, native or codegen builds, pinned runtime, emulators). Run it before reading anything into a red suite. An unprepared tree fails identically to broken code, so recording that as the starting state silently blocks every later verdict.
- When project guidance is allowed, treat its playbook as a LIVING doc: fix a wrong step empirically and update it so the next run does not re-solve the problem.
- Machine-local secrets (test-account passwords, local paths) stay in the project's gitignored `CLAUDE.local.md`, referenced by name — never write a secret value into the committed playbook.
