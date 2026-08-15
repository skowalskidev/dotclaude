# TLDR report formats — the block shapes a human reads to judge work

On-demand catalog. Sole owner of the SHAPE of the three human-readable blocks that describe a piece of
work: what the user goes through, what the system does, and what changed on this branch. Read it when
writing a plan, a ticket, a PR body, or an end report.

**Boundary.** This file owns the SHAPE — which parts, in what order, and the test each block has to
pass. `rules/copy-quality.md` owns the WRITING: lead with the answer, the Five Ws completeness check,
the both-ways check for redundant clutter and missing information, no AI-sounding copy, no em dashes.
`rules/communication.md` owns where questions go. Don't restate either here.

Consumers: `/sk:ship-report-and-ensure-correct-user-system-journey` (all three), `/sk:ship-pr` (user journey and system journey in the PR body),
`/sk:work-full-detailed-workflow` and `references/planning-and-tracking.md` (the user journey opens every
plan). One owner, so a format fixed once is fixed everywhere.

## The glance test — what all three blocks must pass

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
