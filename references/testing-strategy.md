# Testing strategy

Write regression tests early, then implement; execute them under § Defects first.

- Structure testing as a tree: unit → integration → e2e per section. At final verification, run lower-level coverage before dependent higher-level checks.
- Plan both unit and e2e suites so they can run in parallel.
- Split tests into "runnable now" vs "needs extra resources" (second accounts, other platforms). The latter become prioritized follow-up tickets with instructions — or an immediate flag if blocking.
- Write the test plan simple → complex: seed scenarios for every case, happy path first, then edge cases. Save progress to a file so every part is tracked and ticked off.
- Verify someone else's code or branch at the batch gate; budget time to fix failures.

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

- **Collapse time.** For any cooldown, scheduled job, trial window, retry backoff or
  "comes back tomorrow" step, add one switch that dispatches immediately and compresses retry
  windows to seconds. Read it from config, not a code constant, so it flips per scenario
  without a redeploy.
- **A time-collapse switch is INSEPARABLE from an allowlist.** Collapsing time in a shared
  environment makes every stale record suddenly eligible, so you can fire real side effects at
  abandoned test data. Never ship the fast-forward without an "only these subjects" guard —
  and treat "non-allowlisted subject produces zero side effects" as its own test scenario.
- **Audit what already exists before flipping the switch.** Distinct from seeding: what stale
  records will my test mode wake up? Delete them or prove the allowlist blocks them.
- **Force state directly instead of walking the flow.** Keep a cheat sheet mapping each
  precondition to the fastest direct-write command plus its verification command. Don't repeat
  a twelve-step onboarding for every scenario.
- **Stub at the service boundary, never in the test.** `if (isStub()) return <fixture>` at the
  call site inside the app. Intercepting network calls from inside a spec asserts against a
  fiction; a boundary stub keeps routing, auth, validation and persistence in play.
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
  "never expires". Absolute dates in fixtures rot and the suite goes red months later for no
  code reason.
- **Baseline seed vs per-test seed.** The global seed holds only what is genuinely shared and
  read-only; per-scenario state is re-established per test.
- **Namespace whatever you create** so parallel work never reads someone else's rows. Assert on
  your named rows, never on global counts — "exactly N items on the page" is a guaranteed flake.
- **Seed the store the server actually reads.** Trace the read path first, and document any
  degraded-mode response shape the harness produces.
- **Seeded records must satisfy the production access rules.** A seed that only works because
  it was written with admin god-mode produces a UI that shows nothing.
- **Code-as-seed beats a saved data snapshot.** Snapshots rot and break clean checkouts.

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
- **DO include the WHOLE package suite when a shared module changes.** A same-named test does not cover
  sibling consumers. Schedule this once at the batch gate, or reuse matching full-package evidence.
  TEST: a shared-module green verdict names full-package coverage, not one matching test file.
- **DO tie a coverage verdict to its source revision, collection directory and complete test invocation.**
  Use partial reruns to diagnose failures; they do not replace full-run coverage. TEST: the reported
  percentage traces to complete collection for the same revision being judged.

## Defects first

**DO default to zero automated tests, typechecks or verification builds during the whole authorized
task batch.** A batch includes every authorized feature and its review fixes, not one feature, commit or edit. Write regression
tests early without executing them. Run an early targeted diagnostic only for a concrete issue that
needs it or Simon's explicit request; record the reason and scope. Compile an implementation dependency
only when required to continue the work. DON'T turn cheap checks or dependency builds into a per-edit
verification loop. Leave required hooks and CI enabled and unchanged.

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

**DO fix final-gate failures and rerun the affected checks.** Reuse the passing remainder; rerun a broader
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
**Wait for the full runner result within the bounded stage timeout.** Keep the runner's exit status,
complete log and result bundle; for `xcodebuild`, verify the final `** TEST SUCCEEDED **` or
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
feature — `feature · layer (frontend/backend) · Stage-1 test(file) · Stage-2 judgment · verdict
(COVERED / GAP / NEEDS-DRIVING / SKIPPED)`. Every feature ends with a verdict; a feature with no row is a hole.
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
native runtime/UI cases SKIPPED under § Native simulator suites. Never fake green with a network mock.

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

## Project specifics live in the project — read its own docs FIRST (self-healing)
- Apply `references/project-instructions.md` before the project-doc discovery below. When project instructions are ignored, derive commands from source, executable config and CI.
- This catalog is the generic philosophy. When project guidance is allowed, read the project-SPECIFIC how-to before testing: committed `CLAUDE.md`, then `CLAUDE.local.md`, then a dedicated playbook if one exists. Do not assume a playbook is required: a repo often states commands and layout in `CLAUDE.md`.
- **A fresh checkout is usually NOT ready to run tests, and its failures are not a baseline.** Determine one-time setup from allowed guidance or executable config (dependency install, native or codegen builds, pinned runtime, emulators). Run it before reading anything into a red suite. An unprepared tree fails identically to broken code, so recording that as the starting state silently blocks every later verdict.
- When project guidance is allowed, treat its playbook as a LIVING doc: fix a wrong step empirically and update it so the next run does not re-solve the problem.
- Machine-local secrets (test-account passwords, local paths) stay in the project's gitignored `CLAUDE.local.md`, referenced by name — never write a secret value into the committed playbook.
