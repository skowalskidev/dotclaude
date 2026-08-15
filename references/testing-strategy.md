# Testing strategy

Write tests first, then implement.

- Structure testing as a tree: unit → integration → e2e per section. Verify each part individually first, then collectively — higher-level tests build on locally-tested parts.
- Plan both unit and e2e suites so they can run in parallel.
- Split tests into "runnable now" vs "needs extra resources" (second accounts, other platforms). The latter become prioritized follow-up tickets with instructions — or an immediate flag if blocking.
- Write the test plan simple → complex: seed scenarios for every case, happy path first, then edge cases. Save progress to a file so every part is tracked and ticked off.
- Never assume someone else's code or branch works as described — test it, and budget time to fix it.

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
  loading state, auth-guard behaviour, validation and boundary cases.
- **Sequence slow whole-repo gates to protect the iteration loop** — run them once before the
  final commit, not after every commit.

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
- This catalog is the generic philosophy. The project-SPECIFIC how-to (the test commands, where tests go, which runner, test accounts, password-free login, dry-run/e2e, money-path) lives IN the project — never in `~/.claude`. Read it before running or writing a test, in this order: the repo's committed `CLAUDE.md`, its gitignored `CLAUDE.local.md`, then a dedicated playbook (`docs/testing-playbook.md`) where one exists. `CLAUDE.md` is where a repo normally states its commands and its test layout, so a missing playbook is not a missing setup: it is never a reason to install a runner, invent a directory convention, or stop and ask.
- **A fresh checkout is usually NOT ready to run tests, and its failures are not a baseline.** Those same docs carry the one-time setup (dependency install, native or codegen builds, the pinned runtime version, emulators). Run it before reading anything into a red suite. An unprepared tree fails identically to broken code, so recording that as the starting state silently blocks every later verdict, and arriving late in a piece of work is no evidence anyone prepared it: a new worktree or a new session starts from nothing. Prepare first, then decide what red means.
- Treat the project playbook as a LIVING doc: if a step is wrong or a scenario is missing, fix it empirically, confirm it works, then update the playbook (correct the step / append the scenario) so the next run doesn't re-solve it. A solved testing problem must end up documented in the project's playbook.
- Machine-local secrets (test-account passwords, local paths) stay in the project's gitignored `CLAUDE.local.md`, referenced by name — never write a secret value into the committed playbook.
