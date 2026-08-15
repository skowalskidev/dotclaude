---
name: work-does-this-make-sense-to-build
description: Work out whether a proposed piece of work should be built at all, before any of it is. Takes a ticket, a feature request, a plan or a rough idea; reasons from first principles to the outcome it is really for; splits it into separately-decidable parts; and gives each part an evidence-backed verdict — build, build-but-changed, refuted, already-done, defer, or a decision only Simon can make. Researches to REFUTE rather than to agree: checks the codebase, real production data, the premises the ticket assumes about systems in other repos, and primary sources, so a part whose premise is factually wrong dies with the evidence attached instead of getting implemented. Output is a TLDR he can take into a conversation or act on straight away. Proposes only; never starts building. Use for "does this make sense to build", "does this ticket make sense", "is this worth building", "should we build this", "is this the right approach", or before scheduling a pre-existing ticket. Judges whether to build; /sk:ship-review judges work that already exists.
argument-hint: "the ticket id, the idea, or a paste of the request"
---

# Does this make sense to build?

The failure this exists to prevent: a ticket gets implemented because it was written down, and
nobody checked whether its premise was true. Tickets arrive as SOLUTIONS to problems that are often
stale, already solved, or misdiagnosed, and a diligent engineer building exactly what was asked is
the most expensive way to find that out.

So the job is not to plan the work. It is to decide whether the work should happen, part by part, on
evidence, and hand back an answer Simon can either act on or take into a conversation with the person
who wrote it.

**Not the same job as a founder-mode brainstorm.** `[gstack] /office-hours` advertises a similar
trigger and is a Socratic pass on a product idea that does not exist yet: it asks questions, it does
not go and check. This one is adversarial and empirical, against an existing proposal and a real
codebase. When both look like they fit, the tell is whether there is something to check: a ticket,
a repo, or production data means this skill.

## The bar — cuts both ways

**Do not manufacture objections.** A skill that always finds something wrong is exactly as useless as
one that always agrees, and it is worse, because it trains him to ignore it. A ticket that holds up
gets a three-line "build it, here is why" and nothing more. Say plainly when a premise checked out.

**Do not agree by default either.** The model's pull is toward finding reasons the written thing is
good. Every step below is built to fight that: assumptions are stated as claims that could be false,
and the research goes looking for the evidence that would kill them.

**A verdict without evidence does not ship.** Every REFUTED and every BUILD carries what you actually
checked. "This seems unnecessary" is not a finding.

## Step 1 · Get the real ask, whole

Read the source, not a summary of it. A Linear ticket: fetch it with the Linear MCP, including the
comments and the acceptance criteria, because the comments are usually where the real intent and the
objections already live. A pasted request or a spoken idea: take it as given and quote the part you
are judging so he can see you read it right.

If it is genuinely too vague to evaluate (no outcome, no user, no trigger), say so and ask the one
question that would make it decidable. Do not guess and then evaluate your own guess.

## Step 2 · Recover the outcome from the solution — the first-principles move

A ticket almost always names a mechanism ("add a toggle", "store a flag", "send a second reminder").
That mechanism is one candidate answer to a question nobody wrote down. Recover the question:

- **Who** hits this, **when**, and what happens to them today?
- **What outcome** is actually wanted? Keep asking "so that what?" until the answer stops being about
  the software and starts being about a person or a number.
- **What would have to be TRUE** for this mechanism to be the right way to get that outcome?

Then hold the outcome fixed and ask the question the ticket's author could not: what else gets this
outcome? Include the boring ones. A default changed, a line of copy, a guard that makes the bad state
impossible, and doing nothing are all candidates, and one of them is often better than the ticket.

## Step 3 · Split it into separately-decidable parts

Most tickets are several proposals in a coat. Split until each part could be shipped, dropped, or
reshaped on its own, and name each one. Parts get INDEPENDENT verdicts — killing part 2 while
building parts 1 and 3 is the normal, most useful outcome, and it is invisible if the ticket is
judged as one lump.

## Step 4 · Write each part's load-bearing assumptions as claims that could be false

For each part, list what must be true for it to be worth building, phrased so it could be checked and
found wrong. "Users hit this" is not checkable. "This state occurs in production" is.

Then, for each claim, write **what evidence would refute it** BEFORE going to look. Deciding the
refutation test in advance is what stops the research turning into a hunt for supporting quotes.

## Step 5 · Go and get the evidence

Read `~/.claude/references/research.md` for the source order and how to discount a staked source. On
top of that, in this order, because the cheap sources kill the most tickets:

1. **The codebase.** Does it already exist? Is the case already guarded upstream so it cannot occur?
   Is there a config or flag that already does it? What did the last person who touched this write in
   the commit message about why?
2. **Real data, read-only.** The claim "this happens" is settled by a count, not by an opinion. Get
   the denominator too: "3 occurrences across 40,000" refutes just as hard as zero, and "0 across 12"
   proves nothing. Prod is read-only by default under `rules/connectors.md` — counts and aggregations
   before document dumps, ids and counts in the report, never PII.
3. **Any connector that can corroborate**, when it is relevant to the claim: the billing provider for
   a revenue claim, the telephony or messaging provider for a delivery claim, logs and traces for a
   frequency or latency claim, the issue tracker for whether this was already decided. Same read-only
   rule, same work/personal boundary.
4. **The other side of a cross-repo contract.** When the premise depends on how a service in another
   repo behaves, READ THAT SERVICE'S SOURCE. Never infer its semantics from the types on this side —
   an assumption about what a remote endpoint does with an omitted field is a premise, not a fact,
   and it is a recurring source of tickets that describe a problem the other system does not have.
5. **Primary sources** for any claim about a third party's product, per `rules/process.md`. Check all
   of their surfaces before asserting they do not support something.

**Corroborate before you rely on it.** One source is a lead. A claim that decides a verdict needs a
second, independent confirmation, and a claim that flatters the conclusion you were drifting toward
needs it most.

## Step 6 · Run the checks that actually catch things

Most refutations are one of these. Go through them deliberately rather than waiting for one to occur
to you:

- **It already exists** — as a feature, a setting, or a workaround the users have already found.
- **Nobody is hitting it** — the state is reachable in code and has zero real incidence.
- **The premise is factually wrong** — the system does not behave the way the ticket says it does.
- **It treats a symptom** — the cause will keep producing more of these, and this fixes one.
- **A cheaper path gets most of it** — a default, a guard, a doc line, or deleting the affordance.
- **The cost lands where nobody looked** — a migration, an index, a new gate, a permanent on-call
  burden, or a thing it makes harder to change later.
- **It contradicts a decision already made** — and written down with reasons. Read the history before
  proposing something that reopens it; re-litigating a settled call wastes everyone's time.
- **The trigger cannot fire** — the condition is guarded upstream, or the config that would enable it
  is never set.
- **It is right but not now** — it depends on something that does not exist yet. That is DEFER, with
  the dependency named, not a refutation.

## Step 7 · Argue the other side before you commit to the verdict

Take the verdict you are about to give and make the strongest honest case against it. For a REFUTED,
argue for building it. For a BUILD, argue for dropping it. If the counter-case survives, the verdict
was not ready. Say in one line what the best counter-argument was and why it did not win, so he can
judge the reasoning rather than take the answer on trust.

## Step 8 · Verdicts, and the line between a fact and a decision

One per part:

- **BUILD** — the premise holds and this is the right shape. One line on why.
- **BUILD-CHANGED** — the outcome is real, the mechanism is not. Give the reshaped version concretely.
- **REFUTED** — a load-bearing premise is false. Cite the evidence that killed it, so the same ticket
  does not come back next quarter with the same premise.
- **ALREADY-DONE** — it exists. Point at where.
- **DEFER** — right, but blocked on a named dependency.
- **DECIDE** — the facts are settled and what is left is a judgement call: a product trade-off, a
  cost he is willing to bear, a customer promise. **Never refute a part on a decision.** Lay out the
  options, the evidence, and a recommendation, and hand him the call.

**No evidence found is not the same as refuted.** If a claim could not be checked, mark it UNVERIFIED,
say what would settle it and what it would cost to find out. Silence is not disproof.

## Step 9 · Report it as a TLDR he can act on

Follow `rules/copy-quality.md` and `rules/communication.md`: answer first, no preamble, no em dashes.

1. **One-line verdict** for the whole thing — build it, build part of it, or drop it.
2. **The table** — one row per part: part, verdict, the one fact that decided it.
3. **Per part, only where it earns space** — the claim that was load-bearing, the evidence with its
   source, and the reshaped proposal if the verdict was BUILD-CHANGED.
4. **What to say to the author** — two or three sentences he can paste into Linear or say out loud,
   written for the person who wrote the ticket rather than for a machine. This is the deliverable he
   asked for most often, so do not skip it.
5. **If he says go** — the first concrete step for whatever survived, one line. Not a plan.
   `/sk:work-full-detailed-workflow` owns the plan, and it starts once he has decided.

## Rules

- **Propose, never build.** No implementation, no scaffolding, no "I went ahead and started". The
  output of this skill is a decision, and the work begins only after he makes it.
- **Read-only everywhere.** No prod writes, no ticket edits, no status changes, no comments posted.
  Per `rules/process.md`, plans and analyses go in chat and are never auto-posted to a ticket.
- **Never widen the ask.** Judge what was proposed. Adjacent work you noticed goes in one line at the
  end, flagged as out of scope, not folded into the verdict.
- **Say when you were wrong to doubt it.** If the research confirmed the ticket's premise, lead with
  that. Conceding is what makes the refutations worth reading.
- This is the mechanism behind `references/planning-and-tracking.md`'s rule that a pre-existing
  ticket gets a verdict against today's real code before it is scheduled. Run it there.

The thing being judged (ticket id, idea, or paste): $ARGUMENTS
