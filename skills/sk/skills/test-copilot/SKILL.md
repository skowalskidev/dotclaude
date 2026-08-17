---
name: test-copilot
description: Test a feature WITH Simon rather than for him. Claude exhausts every machine-checkable thing first (build, types, tests, seeded states, its own browser pass), instruments the code with reason-coded logs and a correlation id BEFORE starting, then boots and identity-verifies its own dev server and paces Simon through the real user journey ONE step at a time while watching the logs live — so his eyes catch the UX gaps automated tests structurally cannot see, and Claude diagnoses each from the logs and fixes it. Use for "co-pilot test this", "let's test this together", "walk me through testing X", "my tests pass but the app is broken", or before shipping anything a human will click through.
argument-hint: "[what to test, e.g. 'the review queue' or 'this branch']"
---

# Co-pilot testing

**Why this exists:** the suite goes green and the app is still broken. Not subtly — a button
that isn't there, a screen you can reach but can't act from, a required field with no input, an
order that makes no sense. Assertions only check what someone thought to assert, so they cannot
notice a step is *missing*: nothing missing has a test. Unit tests never render; integration
tests run headless; e2e scripts a known-good happy path by construction. The defect classes
that survive all three are exactly the ones Nielsen's heuristics name — visibility of status,
error prevention, recognition over recall, error recovery.

So Claude does everything a machine can, then gets out of the way and drives Simon through the
real journey while watching the logs. Simon supplies judgement. Claude supplies instrumentation,
correlation, and the fix.

**Don't duplicate the neighbours:**
- `/sk:test-eyeball` — Claude drives the browser itself. No human needed.
- `/sk:ship-review` Step 6 — Claude *reasons* over a flow and reports gaps. No live session.
- **This skill** — Simon drives the UI, Claude watches the server. Human judgement is the point.

Read, don't restate: `~/.claude/references/user-journey-review.md` (what to look for at each step
while he drives: dead ends, the three states, the wait, when a lock needs a reason),
`~/.claude/references/testing-strategy.md` (gates, seeding, reason-coded logging, failure classes
automation can't catch), `~/.claude/references/dev-server-hygiene.md` (port preflight, identity
handshake, teardown), `~/.claude/references/browser-debugging.md`.

---

## Phase 0 — Scope it. Ask FIRST.

Use **AskUserQuestion**, pre-filling from `git diff` and session context so the inferred answer
is the recommended option:

1. **What are we testing?** — this session's work · this branch vs base · a named existing
   feature · a whole end-to-end flow.
2. **Goal?** — verify new work before shipping · audit an existing feature and improve it ·
   hunt a specific bug Simon already hit.
3. **How deep?** — happy path · happy path + edges · adversarial (empty, huge, unicode,
   double-click, back button, refresh mid-flow, expired state).
4. **Anything to bypass?** — a wait or delay, a paid action, an external service, an email/SMS
   step, a scheduled job.

If he already said all this, don't ask. State your reading in one line and move.

Write a one-line **charter** before starting: *explore \<area\>, using \<setup\>, to discover
\<information\>* — and say what is explicitly NOT covered. Scope stated up front prevents the
session wandering the whole app.

---

## Phase 1 — Instrument BEFORE testing, never during

### 1.1 Read the project's playbook first
Project-specific how-to (commands, test accounts, password-free login, dry-run modes, seed
recipes) lives IN the project — `docs/testing-playbook.md`, `CLAUDE.md`, gitignored
`CLAUDE.local.md`. Read before improvising. Fix any wrong step empirically and update the
playbook at the end.

### 1.2 Enumerate the surfaces
`git diff` vs base, or read the feature. List every route, screen, state and control in scope.
That list is the plan's spine; anything off it is out of scope — say so rather than wandering.

### 1.3 Add the logging that makes the session diagnosable
Claude cannot see Simon's screen. **The log stream is Claude's only sensor.** Per
`testing-strategy.md`, before the session starts:

- **A correlation id per request**, echoed in a response header, on every log line for that
  request. Use W3C Trace Context (`traceparent`) if the project already emits it, else a plain
  `x-request-id`. This is what ties "Simon clicked" to "this exact server trace" instead of
  guessing by timestamp proximity.
- **`[feature:phase]` tags plus a lifecycle state word** so one feature greps out of a noisy log.
- **A machine-readable reason on every skip, guard and rejection.** Half of any good matrix is
  "the guard correctly did nothing", which is otherwise unprovable.
- **Log the boundaries**: request in, external call out (target, duration, status), every write,
  every branch that can short-circuit.
- **Get the browser console into the same stream.** Next.js ≥16.2 has stable
  `logging.browserToTerminal` (plus `logging.fetches.fullUrl`, `logging.incomingRequests`) which
  forwards client `console.*` into the server terminal with file and line. Turn these on for the
  session and off after. Without it, client-side errors — where a lot of these defects live —
  are invisible to Claude. If the framework has no equivalent, use the browser MCP's console and
  network readers instead, and say which you're relying on.

### 1.4 Build the gates you need
Full detail in `testing-strategy.md`. The two that matter most here:

- **Collapse time**, and remember a time-collapse switch is **inseparable from an allowlist** —
  fast-forwarding in a shared environment wakes every stale record and can fire real side
  effects at abandoned data.
- **Force state directly** rather than walking a twelve-step flow to reach it.

Say plainly which gates you added, how they're production-locked, and add them to the teardown
checklist immediately so they can't be left on.

### 1.5 Get to a known state
Reset or seed so the run starts somewhere Simon recognises. Cover **empty** (first-run),
**populated** (normal) and **the edge state that usually breaks**. Prefer an idempotent seed
script over hand-clicking; record the recipe.

**Seed up to the new UI, never through it.** Seed the backend prerequisites the new screens cannot
create themselves, and stop there. Every input the change ADDS is Simon's to type, one step at a
time in Phase 4 — a field he never filled is a field neither of you has verified, and "I seeded it
and it worked" is exactly the report that precedes him finding the flow makes no sense. Pre-fill
only what is off the path being tested (a login, an unrelated account setting).

---

## Phase 2 — Claude's solo pass. Exhaust the machine first.

Earn the ask (`rules/communication.md`): a machine-catchable defect never reaches him. Run and **fix**:

- build, typecheck, lint, unit + integration tests
- every route renders: status, no error boundary, expected landmark present
- **the three states AI forgets, on every surface: EMPTY, LOADING, ERROR** — verify each exists
- every control has a working handler; every disabled control states why
- every stated prerequisite is reachable from where the user is told to do it
- if a debug browser is available, do an `/sk:test-eyeball`-style pass first

Loop until clean. Simon's session must start on a build that already passes every machine check.

**Then produce the table that IS his task list:**

| Cannot be automated | Why | What Simon must do |
|---|---|---|

Naming the missing capability turns each gap into a backlog item, and forces you to maximise the
automated slice before asking for hands. Never fake a blocked path with a network mock — assert
the largest verifiable slice (e.g. the buttons render) and hand over only the irreducible
remainder.

Report the solo pass as a short list of what you checked and fixed. Don't narrate commands.

---

## Phase 3 — Write the plan to a file, then never paste it whole again

An ordered step list in a working file (project-local gitignored, or the session scratchpad).
Three columns, non-negotiable: **setup Claude performs · action Simon performs · evidence Claude
will look for**. Writing it first forces you to discover the state-forcing recipes *before* Simon
is sitting there waiting.

The file holds progress and observations. Chat gets one step at a time.

---

## Phase 4 — The co-pilot session

### 4.1 Boot the server yourself — and prove it's yours
Follow `dev-server-hygiene.md`. Port preflight, then an **identity handshake** before trusting a
single log line: something answering on the port is not the same as your server being up, and an
agent reading a stale process's logs will confidently report on code that isn't running. That
failure mode invalidates this entire skill, so do not skip it.

Then tail the log with a live filter for errors, warnings and correlation ids. Earning the ask
(`rules/communication.md`) is what makes this phase exist: reading the log is the job.

### 4.2 The pacing contract — the part that must not be got wrong

Pace Simon per `references/human-pacing.md` — overview once, one action per message, a progress count,
say what you're watching, signal the hand-off, wait, never re-print a step. It owns those rules and is
shared with hyperspeed; read it there. The browser-journey shape they take here:

> **Step 4 of 12 · Review queue**
>
> **Do:** open `http://localhost:3000/campaigns/abc123/review`
> **Expect:** first card shows a business name, an editable email field, Approve enabled
> **Then:** press `a`
>
> *Watching:* `PATCH /api/prospects/*` and the browser console.

### 4.3 After each step
- **Works** → log it, advance. One line.
- **Problem** → do NOT start fixing. First: pull the correlated log lines and quote the relevant
  ones; say what they show, or say plainly that the server saw nothing (itself a finding); read
  back the persisted state, because the UI can look right while the write is wrong; record the
  observation with a severity. Then ask only for what you genuinely can't infer.
  **Fix a blocker before proceeding** — otherwise you collect nine failures with one root cause
  and the last six steps were never really tested. Log non-blockers and keep moving.

### 4.4 Ask the questions a machine can't
At each step, alongside the mechanical check, run the **cognitive walkthrough** questions
(Wharton, Rieman, Lewis & Polson, 1994) — they are purpose-built for first-use success and map
exactly onto this loop:

1. Would the user be trying to achieve the right thing here?
2. Would they notice the correct action is available?
3. Would they connect that action with the result they want? (Or is the label jargon?)
4. Once they do it, do they see that progress was made?

A "no" to any of these is a **failure story** — a written hypothesis of why a first-time user
gets stuck at this step, not a checkbox. Ask Simon for this explicitly rather than hoping he
volunteers it; it is the entire reason a human is in the loop.

---

## Phase 5 — Triage, fix, re-verify

Record every observation with: step, expected, actual, correlated log excerpt, environment, and
severity. An unexplained deviation in timing or behaviour must be **explained, not waved away**.

**Severity** (technical impact) and **priority** (urgency) are separate fields — a cosmetic bug
on the demo path can be low-severity and high-priority.

- **S1 Blocker** — cannot continue, no workaround
- **S2 Critical** — major function broken, workaround exists
- **S3 Major** — misbehaves, app still usable
- **S4 Minor** — confusing or wrong, low impact
- **S5 Trivial** — cosmetic

For each fix: make it, add or extend a test that fails without it, re-run the machine checks,
then have Simon re-do **just that one step**. **Fix the class, not the instance** (`process.md`) —
one missing empty state means checking every sibling surface. Keep looping until a full pass
comes back clean; one round of fixes is not the end.

---

## Phase 6 — Close out

- **Write what you learned into the project's playbook** — seed recipe, the gates and how to
  enable them, login recipe, surfaces worth walking, any "this always breaks" note. A solved
  testing problem must end up documented.
- **Teardown checklist, enumerated and reported**: turn the verbose logging back down, **turn
  every test gate OFF and clear any allowlist**, remove scratch data, kill every process you
  started and verify by checking the port (not by trusting the kill), sweep orphaned workers.
  Leaving a time-collapse flag on in a shared environment is a live incident waiting to happen.
- **Commit** one logical commit per fix, per the standing commit rule.
- **Report a results matrix**: step, result, evidence, severity — plus what was fixed, what
  remains, and the exact steps for anything still open.
- If you update a human-edited document, fetch it, edit it with a targeted replace, and verify
  existing content survived. Never reconstruct one from scratch; if the read looks suspiciously
  short or empty, STOP and say so.

---

## The two ways this skill fails

1. **Wasting Simon's time on machine-checkable things.** If a step could have been a test, it
   should have been a test. Phase 2 exists to prevent this.
2. **Word vomit.** A step he has to re-read is a step that slows the session. One action, the
   literal target, the expected result, the progress count. Nothing else.
