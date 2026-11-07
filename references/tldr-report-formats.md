# TLDR report formats — the block shapes a human reads to judge work

On-demand catalog. Sole owner of the SHAPE of the human-readable blocks that describe a piece of
work: what the user goes through, what the system does, what changed on this branch, and, when the change
is near money, what it does to a payment path, plus the shape of a message to someone else. Read it
when writing a plan, a ticket, a PR body, an end report, or a message a teammate will read.

**Boundary.** This file owns the SHAPE — which parts, in what order, and the test each block has to
pass. `rules/copy-quality.md` owns the WRITING: lead with the answer, the Five Ws completeness check,
the both-ways check for redundant clutter and missing information, no AI-sounding copy, no em dashes.
`rules/communication.md` owns where questions go and the shape of a message to a person (§ Answer
first). Don't restate either here.

Consumers: `/sk:ship-report-and-ensure-correct-user-system-journey` (every block), `/sk:ship-pr` (the before/after TLDR, user journey and system journey in the PR body),
`/sk:work-full-detailed-workflow` and `references/planning-and-tracking.md` (Block 1 AND Block 2 open every
plan, reflecting its current trajectory). One owner, so a format fixed once is fixed everywhere.

## Human-facing messages

The rule, number and TEST live in `rules/communication.md` § Answer first. This section holds its
example and the WHYs moved out of `rules/` to keep the always-on budget.

DO copy this shape for a chat reply, Slack/DM, PR comment or message sent for Simon:

```
Action needed: approve the migration in PR #812
- Search results now cached 6 h, so a repeat search makes no API call
- Dates past the provider's 330-day horizon skip the call
- Migration 705 adds one nullable column; nothing else touches prod

Your call
1. Approve `db/705_add_cache_column.sql` in PR #812
```

WHY, one per rule:
- Line 1 action verdict: Simon reads the first line and decides; the reader acts on line one or the
  reply failed. Nuance he did not ask for buries the line he needed.
- No prose paragraph: reams of prose are not thoroughness; they bury the one line the reader needed.
- One end question block (clarification, decision, confirmation, "want me to also…"): a question
  mid-answer stops him reading the answer.
- Subagent prompts follow the writing rules: a vague delegation returns vague work, and the subagent
  cannot ask a follow-up.
- A pasted example is not a spec: asking him to confirm its specifics spends the one-question-block
  channel on detail he never meant as a spec. He shows the SHAPE of what he wants; a number, name or
  step inside it is illustration, not a requirement.
- The caps hold per message, not per part: a reply answering three questions that gives each part its
  own bullets and step block reaches 9 bullets, which is how replies kept growing.
- State the expected result: "Run X" with no outcome can only be obeyed, never checked, so neither
  of you can tell it went wrong.
- Close the session without invented checks: a time-only "the next X will confirm" item blocks
  archiving for nothing.
- The five writing rules live in `rules/communication.md`; `copilot-testing` and `parallelization.md`
  point there and do not restate them.

## Message for someone else

The rule and its number live in `rules/communication.md` § Answer first. This section holds the shape,
the pre-send check and the override. It covers every message read by anyone but Simon: a Slack/DM or
email to a teammate, a PR or ticket comment, and a draft Simon sends as himself.

DO write it as:
1. Line 1: the ask or the fact the reader needs, naming the real thing (PR number, screen, date).
2. At most 4 more lines, each one fact, link or step the reader acts on.

**DON'T** open with a greeting run-up or context the reader already has, add the `Action needed`
line (that shape is for Simon), recap, or close with "let me know if you have questions". Offer
detail in one clause ("details on request") only when it exists.
NUMBER: at most 5 non-blank lines and 100 words, a one-line greeting and a short sign-off excluded.

```
Hey, PR #812 (search cache) is ready for your review.
- Adds one nullable column; nothing else touches prod
- Needs your yes before Monday's deploy
```

DO show a draft for Simon as the message alone in one quote block, under a chat reply that itself
follows § Human-facing messages. Both stay TLDR: the draft at most 5 lines, the reply around it with
no commentary restating the draft.

DO measure a draft before sending it by any route the hook cannot see (a `codex-app` run,
`gh pr comment`, `gh api .../replies`):
`python3 ~/.claude/hooks/outbound-message-guard.py --check <draft-file>`. Expect `ok` and exit 0;
exit 1 prints the counts. Cut the draft; DON'T split it into several messages.
`hooks/outbound-message-guard.py` denies a Slack or Gmail send, reply, forward or draft over the cap.
When Simon's own message asked for the length ("send the team the full write-up"), write his words
into `.context/long-message-ok` in the working directory; the guard allows the next send only and
deletes the file.
WHY: a teammate reads the notification preview and the first lines; a long message from Simon reads
as a long instruction from him.
TEST: every message to someone else has at most 5 lines and 100 words, or traces to a
`.context/long-message-ok` quoting Simon's request for length.

## The glance test — what every block must pass

Simon reads these while switching between several things at once, so a block that needs a run-up has
failed. Each one has to answer, at a glance: what is this about, what is happening, what does it do.

- **Name real things.** The actual screen, button, message, route, collection, field, flag, command.
  Never "the relevant page" or "the appropriate handler". A generic noun is what makes a report
  unusable at a glance, because it forces a lookup.
- **One line per step.** If a step needs a paragraph, it is two steps or it is detail that belongs
  outside the block.
- **No rediscovery.** Never assume the reader remembers the context. Say what the thing is before
  saying what happened to it.
- **Actionable, not narrated.** Every block ends in something the reader can do: approve it, ask a
  named question, or request a specific change.

## Before/after TLDR

**DO open every PR body with `## TLDR`, above `## 🚀 Deploy TLDR`, holding exactly two parts:**
1. A `| | Before | After |` table, 3-5 rows, one per thing a user or the system sees or does
   differently. The row label names the real thing; each cell is a few words; the changed value is
   **bold**; a neighbour a reader might assume moved reads `unchanged`.
2. One line starting `**Do:**`, after a blank line (GitHub folds an unseparated line into the
   table): the reader's action (merge, review a named file, decide a named question) plus the one
   fact that makes it safe or risky.

**DON'T add a prose paragraph, an intro line, or a row restating a section below.** Under 60 words
total, table pipes excluded.
WHY: Simon opens a PR and decides from this block alone; every section below is detail on demand.

```
| | Before | After |
|---|---|---|
| Paid-plan searches (server cap) | 50 a week | **200 a month** |
| Counter resets | every Monday | **on the account's start day** |
| Free plan | 5 a week | unchanged |

**Do:** merge. The migration applies itself; no current member is refused.
```

TEST: the fetched PR body's first heading is `## TLDR`, it holds a Before/After table of 3-5 rows and
a `**Do:**` line, and nothing else before `## 🚀 Deploy TLDR`. `bin/pr-landing-gate.py` checks this
and owns the heading names.

## Block 1 · User journey

The short, human-readable walk of what the user actually does and sees, from the moment the feature
becomes reachable to the moment they get the result. It goes ABOVE the technical detail, always, not
only when it is asked for.

Four parts, in this order:

1. **The journey** — numbered steps in the user's terms. Each step says where they are, what they
   do, and what they see back. Name the real screen, button and message, never "the relevant page".
2. **What they experience while waiting** — a step that takes time is a step in the journey. Say
   what is on screen during it and how they learn it finished.
3. **How it works underneath** — two or three lines, only enough to make the journey believable.
4. **The assumptions this rests on** — everything that must already be true for the journey to
   happen at all: a setting already on, a plan tier, a webhook already firing, data already
   present, a person who has to act. List them plainly; each one is a thing that can be wrong.

This is what makes a proposal judgeable before it is built. A plan described in components reads
as fine right up until someone tries to use it; the same plan described as a journey shows the
missing step immediately. The assumptions list is the other half — a journey that only works
because of an untrue precondition is a journey that will not happen.

## Block 2 · System journey

The same work described as what the machine does, in the order it does it, still in plain language.
Its job is to make the mechanism judgeable by a human who is not going to read the diff, and to sit
next to Block 1 so the two can be compared.

Five parts:

1. **The trigger** — what starts it and where that lands first. A click, a webhook, a cron, a queue
   message, another service. Name the real entry point: the route, the function, the handler.
2. **The steps** — numbered, one line each, in execution order. Each says what runs, what it reads or
   writes, and what it hands to the next step. Name the real collection, endpoint, queue or flag.
3. **Where it can stop early** — every branch that ends the flow before the result: a guard, a gate, a
   permission check, a validation failure, a retry that gives up. For each one, say what the user sees
   when it stops there. This part carries most of the value, because a silent stop is invisible in
   Block 1 and obvious here.
4. **What it touches outside itself** — external calls that cost money, hit a rate limit, or depend on
   a service in another repo. Anything with a deploy order attached belongs here.
5. **What it leaves behind** — the state written when it finishes: the field set, the record created,
   what happens if the same trigger fires again.

**Then cross-check the two blocks, and report the mismatches.** Line the numbered user steps up
against the numbered system steps:

- A system step no user step covers means something happens that the user is never told about.
- A user step no system step covers means the journey promises something the mechanism does not do.
- An early stop from part 3 with no matching user-visible outcome is a silent failure.

List each mismatch as one line, and say plainly when there are none. This comparison is the whole
reason the two blocks sit together; a report that prints both and compares neither has skipped the
work.

## Block 3 · Changes on this branch

What is new relative to the base, for someone who has not been watching. Diff explicitly and name the
scope, so it is trustworthy rather than asserted: a branch against its base
(`git diff <base>...HEAD`, with the commit and file counts) or uncommitted work in progress
(`git status --short` plus `git diff HEAD`, said out loud as uncommitted). When both exist, report
them as two groups rather than one list.

- **One line first** — what this branch adds, in the terms of the person who asked for it.
- **A table, grouped by what it does for a person**, not by directory: what changed, where it lives,
  and what is now possible that was not before. Group by capability so one row is one idea.
- **New surfaces, called out separately** — a screen, a route, a setting, an env var, an index, a
  migration, a new dependency, a new permission. These are the rows that need an action from someone,
  so they never get buried in the table.
- **What did NOT change that someone might assume did** — the neighbouring feature left alone, the
  setting that still defaults the old way. One line each, only where the assumption is likely.

## Block 4 · Change near money

Only when the change touches or opens a payment path: a checkout, a paywall, a plan gate, a price or a
billing webhook. It goes beside Block 3 in every hand-back, unasked. DON'T wait for "do the paywalls need
testing?"; the diff already answers it.

1. **One line first:** `Payment files changed:` followed by the list from `git diff <base>...HEAD` over
   the payment code, or the word `none`. Write `none` out.
2. **A table, one row per entry that opens the paywall** (a screen, a button, a route, a limit that
   now reaches it, new or changed), with these columns: the entry, what happens after paying (the
   redirect, the webhook, the entitlement write, the screen they land on), and the one check it needs
   (a test-mode checkout, a replayed event, a named test).

3. **One row per account state that can reach a pay button**, with the server's precondition and the
   production press-to-session rate, per `references/testing-strategy.md` § Layering and coverage
   arguments.

TEST: a change that reaches a payment path hands back this line and table, and a row exists for every
entry the diff changed (the fix for a hand-back that left the paywall question for Simon to ask).
