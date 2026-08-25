---
name: ship-report-and-ensure-correct-user-system-journey
description: Hand back one glanceable end report when a piece of work is finished, then make sure the code actually does what we planned. Reports what the user goes through, what the system does under the hood in steps, and what changed on this branch against its base, cross-checking the two journeys and stating every mismatch. Then it finds the plan or ticket the work was validated against and judges whether the post-merge journeys still match the plan: every acceptance criterion gets an independent verdict, then it writes, runs and commits tests for those criteria and the journeys so a passing test is the evidence rather than a reading of the code, each gap gets closed with real code follow-ups committed one per gap, and the journeys are then re-derived from the code and judged again. It loops until they hold. Use for "end report", "what did you build", "summarize what this does", "does this match the plan", "check it against the acceptance criteria", "write tests for the acceptance criteria", "prove it with tests", "close the gaps", or as the last step of substantive work. With no plan or ticket to check against it reports only and asks for one, never inventing criteria or tests. Judging quality is /sk:ship-review; deciding whether to build something at all is /sk:work-does-this-make-sense-to-build.
argument-hint: "[optional: the branch, ticket, or plan file to report on and check against]"
---

# End report, and make it true

Two halves, in one run. First the report: what was built, what a person experiences, what the machine
does, and what is new on this branch. Then the part that makes the report worth having — the shipped
journeys are checked against the criteria the plan actually validated, every verdict is backed by a
test that ran, and whatever falls short is fixed here rather than written down for later.

Simon is running several things at once and may not have looked at this for days, so the report has to
re-establish its own context and then be immediately judgeable.

This skill owns orchestration only. It reads and never restates:

- **`~/.claude/references/tldr-report-formats.md`** — Blocks 1, 2 and 3, and the cross-check.
- **`~/.claude/references/planning-and-tracking.md`** — the verdict vocabulary (carried in,
  deliberately dropped, superseded) and the rule that the ORIGINALS get re-read, never a summary.
- **`~/.claude/references/user-journey-review.md`** — how a journey is judged as the person meeting it
  for the first time.
- **`~/.claude/references/testing-strategy.md`** — how tests are written, layered, seeded and gated,
  the scenario matrix, and the failure classes automation cannot catch.
- **`~/.claude/references/contracts-and-outcomes.md`** — a test named after each criterion, and assert
  the artifact rather than the interaction.

## Phase 1 · Gather from the code, never from the session

Read the real thing, even for work you did yourself an hour ago. A report assembled from memory of
what you intended is exactly where an inconsistency hides, because it repeats the intention instead of
what shipped.

- **The scope, resolved before anything else.** Two kinds, and the report says which one it used:
  - **Branch** — the default. Resolve the base (`git merge-base origin/<default> HEAD`), then
    `git diff <base>...HEAD --stat` and the commit list.
  - **Work in progress** — when he asks mid-work, before anything is committed, or names no branch
    and the tree is dirty. Use `git status --short` plus `git diff HEAD` (staged and unstaged), and
    say plainly that this is uncommitted work that could still change.

  When the branch has commits AND the tree is dirty, report BOTH and keep them separate: committed
  work and work in progress are different things to judge, and merging them hides which half is
  safe. Quote the scope, the commit count and the file count so it is checkable.
- **The state after the merge, not the branch in isolation.** The question this skill answers is what
  happens once this lands, so `git fetch` the base first and say whether HEAD is behind it. If the
  branch is behind AND a file it touches also changed on base, stop and say so: that is the one case
  where judging the branch as it stands answers the wrong question. No overlap, no interaction, carry
  on without asking.
- **The user path.** Take the real screen names, button labels and messages out of the code, not out
  of the plan. A label that changed during the work is a label the plan is now wrong about.
- **The system path.** Start at the real entry point and follow each hop by reading it: the route, the
  handler, what it writes, what it calls, what happens on failure. Every early return is a branch for
  Block 2 part 3.

Then write it: one **context line** that lets him re-enter cold (what this is, which branch or ticket,
what state it is in), followed by **User journey** (Block 1), **System journey** (Block 2),
**Mismatches**, **Changes on this branch** (Block 3).

State verification honestly per `rules/process.md`. A report that reads as finished when a step was
skipped is worse than no report.

The mismatch pass is not optional and is not left implicit. Run the cross-check in Block 2: a system
step no user step covers, a user step no system step delivers, an early stop with no user-visible
outcome. One line per mismatch, and one line saying so when there are none.

## Phase 2 · Find the baseline the work was validated against

The report describes what IS. Everything below needs what was AGREED. **Gather from ALL of these, not
the first one that answers** — work routinely spans several tickets, and taking whichever matched
first is how a whole ticket's criteria drop out silently. Start from the `sources` section of
`.context/intent-ledger.md`, which records every source by link precisely so they all stay checkable,
then add anything else here. Tag every criterion with the source it came from, and list the sources,
by link, in the output.

1. A ticket id, plan path or branch passed in the arguments.
2. `.context/<slug>-plan.md` in the repo — the living plan from
   `/sk:plan-stable-persistent-dynamic-complete-full-plan` (ticket- or slug-named); authoritative when
   present, per `rules/living-plan.md`.
3. The Linear ticket or tickets named by the branch, the commits or the PR body — acceptance criteria
   AND the comments, because that is where a build, refute or defer verdict was recorded.
4. The plan file for this workspace under `~/.claude/plans/`.
5. The PR body.
6. The **ratified `plan` section** of `.context/intent-ledger.md`, and only that section. It is what
   makes a no-ticket task judgeable at all: a plan derived from his prompt and approved is a
   baseline, and often the only record of what verification changed.

**Read the ledger's agreed pivots on top, whatever else was found.** A change agreed mid-run lives
nowhere else, because nobody goes back and edits the ticket.

**If none of those exists, stop** — and a ledger holding only asks is none of them. The hook writes
that file in every worktree from the first prompt, so "a ledger exists" is true always and proves
nothing. A verbatim ask is what he WANTED; a baseline is what was AGREED, and an unratified ask is
this phase's own failure mode in his handwriting: it reads as authority and is still a criterion
nobody approved. Print the report, say plainly that there is no baseline to check against, and ask
him to name the plan or ticket. Edit nothing, and write no tests. Inventing acceptance criteria and
then "fixing" code to satisfy them is the worst thing this skill could produce, and it would look
exactly like a successful run. A test invented the same way is worse still: derived from the code, it
asserts whatever the code already does, and it reports green forever.

**A part that was deliberately dropped, refuted or deferred is part of the baseline.** It is not a gap
and it never gets built back. Say who decided it and when, so the verdict is checkable rather than
asserted.

**If the working tree is dirty, stop at the end of Phase 3.** Report, judge, list the gaps, and ask
before touching anything. Uncommitted work is not there to be built on top of: mixing his edits with
this skill's makes every commit below more than one logical unit and makes the whole round hard to
undo. `rules/process.md` wants a restore point before a change like this, and a clean tree is it.

## Phase 3 · Judge each criterion independently

Not a self-assessment. The context that just wrote the report is the weakest available judge of it,
because it repeats its own intention, which is the same failure Phase 1 exists to prevent.

So fan out per `~/.claude/references/parallelization.md`: one verdict pass per criterion (or per small
group of related ones), each given the criterion text and the repo but NOT the session narrative, each
told to default to NOT MET and to change its mind only by pointing at the code that makes the criterion
true. A criterion nobody can evidence is not met, whatever the session remembers.

Every criterion comes back with one verdict, provisional until Phase 4 puts a test behind it:

| Verdict | Means | Carries |
|---|---|---|
| Met | The code does it | `file:line` |
| Partly met | Some of it does | what is missing, precisely |
| Not met | Nothing does it | where it should have been |
| Deliberately dropped | Decided against | who decided, and when |
| Superseded | Another decision replaced it | what replaced it |
| Undecidable from code | Needs a run, a service, or Simon | what would settle it, for Phase 4 to try |

Then run it the other way: **code on this branch that no criterion asked for.** List it with evidence.
Scope creep is a finding here, not a note for later.

## Phase 4 · Prove each verdict with a test

A `file:line` is a reading of the code, and a reading is all Phase 3 can produce without running
anything. This phase replaces it with evidence: a test per criterion, derived from the criterion and
from the journeys Phase 1 wrote, written here, run here, committed here.

**The Phase 2 gate applies unchanged: no baseline, no tests.**

**Prepare the environment, then record the ground state.** The test command, where tests live, which
runner, the test accounts and the one-time setup are all stated in the project: its `CLAUDE.md`, its
gitignored `CLAUDE.local.md`, and any playbook, in that order, per `references/testing-strategy.md`.
Running last is not evidence anyone already prepared the tree; a fresh worktree usually has not been,
and its failures are not a baseline. Prepare it, then run the suite untouched and write down every test
already failing and the skipped count. "Fix until green" is impossible if the base is red, and that
count is what proves later that no gate got weaker.

Met, Partly met and Not met each get a test. Deliberately dropped and Superseded never do, because
testing a dropped part builds it back. Where `/sk:ship-review` Step 5 already wrote one that covers a
criterion, run that and cite it: it enumerates by toggle pathway before the PR, this phase enumerates
by acceptance criterion after the work, and the overlap is real.

How each one is built:

- **The criteria supply the tests, the journeys supply the cases.** For each criterion take the
  numbered user and system steps it touches, every early stop in Block 2 part 3, and the scenario
  matrix in `references/testing-strategy.md`. An early stop asserts its reason code; "the guard
  correctly did nothing" is unprovable any other way. Name each test after its criterion and assert
  the artifact rather than the interaction, per `references/contracts-and-outcomes.md`.
- **Write the assertion from the criterion's words, before reading the implementation.** A test
  written from the diff tests what was built instead of what was agreed. Fan out per
  `references/parallelization.md`: one writer per criterion or small group, each denied the session
  narrative, exactly as Phase 3.
- **Prove it discriminates.** Put the implementing files back to base
  (`git checkout <base> -- <files>`), run that test alone, watch it fail, restore. If that breaks the
  build, neutralize instead: flip the new flag off, or stub the new function to its old return. If
  neither is practical, assert a value only the change can produce and say so in one line. A test
  nobody could make fail is marked **not discriminated**: it can confirm a verdict, never upgrade one.
- **Cheapest rung that can decide it:** offline, then integration against seeded local services, then
  live and browser. Escalate only when the rung below cannot decide the criterion, in one stated line.
  One browser pass walks the journey once and collects several criteria on the way; one boot per
  criterion is how twenty criteria become an hour.
- **A browser and a dev server are authorized here and nowhere else in this skill**, by the standing
  exception in `rules/process.md`, because this is the last check before hand-back. Boot per
  `references/dev-server-hygiene.md` and prove the server is yours before believing a log line;
  `/sk:test-eyeball` owns driving real Chrome, invoked scoped to drive and report, because its fix
  loop is Phase 5's job. Prod stays read-only under `rules/connectors.md`, and a committed test still
  spends nothing: it joins the default suite, which `references/testing-strategy.md` requires to
  trigger zero billable calls.

Then reconcile. The test outranks the reading:

| Phase 3 read | Test | Verdict |
|---|---|---|
| Met | passes | Met, evidenced. Cite the test |
| Met | fails | **Contradicted.** The reading was wrong, and it leads the hand-back |
| Not met, Partly met | fails | Confirmed. A gap for Phase 5 |
| Not met, Partly met | passes | Suspect the test before the verdict |

**A Met verdict with no passing test drops to Not met.** "The code looks right" is exactly what Phase
3 already produced. The asymmetry is deliberate: a failing test is near irrefutable, a passing one is
worth exactly its discrimination, so a green test never upgrades a verdict on its own. **Contradicted
invalidates the batch it came from** — re-judge the other criteria that verdict pass covered, because
one misreading rarely travels alone.

Rules for this phase:

- **It writes tests, fixtures, seeds and test config. Nothing else.** A test that cannot run for want
  of a seam (a missing export, no test id) is a Phase 5 finding with the exact edit named, not licence
  to make it here. A phase that can edit the code under test can make its own test pass, and then the
  loop only ever confirms itself. `git diff --stat` after every delegated batch shows test paths only.
- **A green test commits alone, a red test commits with its fix.** Passing and discriminating earns
  its own `test(<scope>): <criterion>` commit. Red, or unrunnable for want of a seam, is held
  uncommitted until Phase 5 lands it in the same commit as the fix. Never commit a red suite: it
  breaks bisect and CI for every commit in between.
- **Never weaken a gate to get green.** No threshold lowered, no `skip` or `only`, no ignore-list
  entry, no baseline rewritten, no retry added, no assertion loosened to fit what the code happens to
  do. Prove it rather than claim it: the skipped count is not above the ground state, and the diff
  touches no runner config, lint config, ignore list or baseline. A policy that genuinely has to move
  is a line in the questions block.
- **A flaky test is evidence for nothing.** Run it three times; if they disagree, do not commit it and
  send the criterion back to Undecidable with the flake named. A retry or a longer timeout is
  gate-weakening under another name.
- **Undecidable from code now has a much higher bar.** With a dev server, seeded state and a browser
  in scope it means only: Simon's judgement, a credential or platform nobody here has, a billable call
  the suite must not make, or real elapsed time with no collapse gate. Anything else is a test not yet
  written.
- **Never install test infrastructure.** Tests go where the project already puts them, in the runner
  it already uses. A new framework or directory convention is scope creep, and only a repo whose own
  docs and tree say nothing about testing is a question for Simon rather than a thing to install.

## Phase 5 · Close the gaps

Fix, in this order, each as its own commit with a conventional subject:

1. **Contradicted criteria.** The code was believed to do this and a test says it does not. It is the
   most wrong thing on the list, so it goes first.
2. **Criteria that are not met or partly met.** This is the point of the phase. The red test Phase 4
   held goes in the same commit as the fix, and the commit waits until it is green.
3. **Journey defects the report flagged** — a silent early stop with no user-visible outcome, a missing
   empty, loading or error state, a dead end. `references/user-journey-review.md` has the standard.
4. **Scope creep.** Every item gets an ACTION, not a note: remove it in its own commit, or keep it and
   write the criterion back into the plan doc or ticket so the baseline genuinely covers it. The one
   exception is taking away something a user can already reach in production — that is a soft-archive
   decision under `rules/engineering-standards.md`, so it gets one line asking him.

Rules for this phase:

- **Stay inside what was validated.** Closing a gap is not licence to build the next idea. Anything
  genuinely new is one line at the end, flagged as out of scope.
- **Run the project's build and tests before each commit**, Phase 4's tests included, and say what was
  run. A fix that does not turn its own test green is not a fix, and one that reds another criterion's
  test is a new gap. The browser belongs to Phase 4, which holds the standing authorization; this
  phase does not open one to check its own work, and Phase 6 re-runs the live rung anyway.
- **Branch first if HEAD is on the default branch.** Never commit straight to `master` or `main`.
- **Delegate the edits and verify them on disk**, per `references/parallelization.md`. A subagent's
  self-report is not evidence that a file changed.

## Phase 6 · Re-derive, re-run, judge again

Go back to Phase 1 and rebuild both journeys FROM THE CODE. Never from what Phase 5 said it did: a
loop that trusts its own fix report only ever confirms itself. Then re-run the FULL suite, not only
the tests you touched, because a fix that broke a neighbour shows up nowhere else. Then re-run Phases
3 and 4 against the same criteria and reconcile again.

Green means no failure outside Phase 4's ground-state list and no rise in the skipped count. A
pre-existing failure is not this run's job and is reported by name, with one exception: one sitting on
a criterion under judgement blocks that criterion, so it becomes a gap like any other. You cannot
evidence a verdict through a test that was already red.

Repeat until it comes back with nothing actionable. Four stop conditions that are not done:

- **The same finding survives two consecutive rounds.** The loop is not converging. Stop, and say
  where it stands and what you tried.
- **Everything left needs a decision only Simon can make.** Stop and name each one.
- **A test's result flips between rounds on code that did not change.** It is evidence for neither
  verdict. Stop, name it, and leave its criterion Undecidable.
- **A failure outside the ground-state list survives a fix round.** The run has broken something it
  does not understand. Stop and name the test and the commit.

## Phase 7 · Hand it back

- **Contradicted criteria first, if there are any.** The reading said Met and the test said no. It is
  the most useful thing this skill produces, so it never gets buried.
- The final user journey, system journey and mismatches, from the last round.
- The criteria table with its verdicts and the test behind each one, its rung, and how it was shown to
  fail without the change, so "it matches the plan" is checkable rather than claimed. A criterion with
  no test says why on the same line.
- What was fixed this run, one line each with its commit.
- **What was already red before this run started**, so a pre-existing failure is never mistaken for
  something this work broke.
- What is left, and why: a decision he owes, a blocker, or something out of scope.
- **Reconcile the ledger and promote it out**, because the worktree is disposable and it dies there.
  Append one verdict per recorded ask, tagged with its source, via
  `~/.claude/hooks/intent-ledger.sh note reconcile <scratch.md>`. Then put the reconciliation and the
  plan-vs-sources delta where each part belongs: each source's verdicts on its own ticket, anything
  cross-cutting on the primary (the ticket the branch is named for, else the PR title prefix, else
  the first source) with the rest linked, and a ticket with no verdicts gets no comment. With no
  tickets it goes in the PR body — fetch, edit, verify non-empty, then update, never reconstruct, or
  screenshots added through the GitHub UI are destroyed. Link only tickets this work delivered, since
  Linear syncs a linked ticket's status from the PR. **Never promote the verbatim asks.**
- **The questions**, in one consolidated block, per `rules/communication.md`. Each one answerable in a
  line, naming the decision and carrying the option you would take, so a "yes" is a complete answer.
  An ask that was never ratified and never built belongs HERE as a proposal, never in Phase 5's fix
  list. If there are none, leave the section out rather than manufacturing one.

## Rules

- **It is a report, not a narration.** Never walk the diff file by file, never recap what you did in
  the session, never celebrate. `rules/copy-quality.md` governs the writing: lead with the answer, cut
  anything that restates a heading or a neighbour, and check the other way too for the missing Five W
  that leaves him guessing.
- **Density over length.** If a section can be cut without costing him a decision, cut it. If a
  section leaves him unable to act, it is missing something and length is not the problem.
- **Read-only until the criteria are judged.** Phases 1 to 3 change nothing. Phase 4 writes tests and
  only tests. Phase 5 is the only phase that edits product code, and only against a criterion or a
  finding written down first. A judge that can edit the thing it is judging is not a judge.
- **No baseline, no edits, no tests.** The gate in Phase 2 is what separates closing a real gap from
  inventing work, and a test invented the same way is that failure with a green tick on it. It is the
  one rule here with no exception.

The work to report on and check (branch, ticket, or plan file): $ARGUMENTS
