# TLDR report formats — the block shapes a human reads to judge work

On-demand catalog. Sole owner of the SHAPE of the human-readable blocks that describe a piece of
work: what the user goes through, what the system does, what changed on this branch, and, when the change
is near money, what it does to a payment path, plus the shape of a message to someone else or one an
automation posts. Read it when writing a plan, a ticket, a PR body, an end report, or a message a
teammate will read.

**Boundary.** This file owns the SHAPE — which parts, in what order, and the test each block has to
pass. `rules/copy-quality.md` owns the WRITING: lead with the answer, the Five Ws completeness check,
the both-ways check for redundant clutter and missing information, no AI-sounding copy, no em dashes.
`rules/communication.md` owns where questions go and the shape of a message to a person (§ Answer
first). Don't restate either here.

Consumers: `/sk:ship-report-and-ensure-correct-user-system-journey` (every block), `/sk:ship-pr` (the before/after TLDR, user journey and system journey in the PR body),
`/sk:work-full-detailed-workflow` and `references/planning-and-tracking.md` (Block 1 AND Block 2 open every
plan, reflecting its current trajectory), `/sk:work-does-this-make-sense-to-build` (Part verdicts), the before/after producers listed in § Before/after unit. One owner, so a format fixed once is fixed everywhere.

## Human-facing messages

The rule, number and TEST live in `rules/communication.md` § Answer first. This section holds its
example and the WHYs moved out of `rules/` to keep the always-on budget.

DO copy this shape for a chat reply, Slack/DM, PR comment or message sent for Simon:

```
Action needed: approve the migration in [PR #812](https://github.com/org/repo/pull/812)
- Search results now cached 6 h, so a repeat search makes no API call
- Dates past the provider's 330-day horizon skip the call
- Migration 705 adds one nullable column; nothing else touches prod

Your call
1. Approve `db/705_add_cache_column.sql` in [PR #812](https://github.com/org/repo/pull/812)
```

WHY, one per rule:
- Line 1 action verdict (a status-only reply under `No action needed` while a click-through or merge word waited sat idle until he asked "are you stuck?"): Simon reads the first line and decides; the reader acts on line one or the
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

## Answer the prompt

The rule and TEST live in `rules/communication.md` § Answer first. This section holds the shape, the
pre-send check and the WHY.

DO answer, in the final message of every turn that answers a Simon prompt, each question and point
that prompt made, in his order, one bullet each, right after line 1 and before any status bullet:
- a question: `Yes: <why>` or `No: <why>`, or the direct answer;
- a claim he asked you to check ("correct me if I'm wrong", "is it", "should we"): `You're right: <why>`
  or `Correction: <what is true>`;
- a point he made with no question: one line saying what you did with it.

The same holds for the reply that delivers background work the prompt started, and for questions he
sent mid-run (text between tool calls is collapsed, so only the final message counts). Status, PR
heads and the end block follow the answers.

```
Action needed: say merge for [PR #812](https://github.com/org/repo/pull/812)
- No: a returning buyer never restarts the quiz; Back now reopens checkout
- You're right: anyone who reaches the paywall can pay; the extra gate is gone
- [PR #812](https://github.com/org/repo/pull/812) is green and its preview serves the new build

Your call
1. Say merge for [PR #812](https://github.com/org/repo/pull/812)
Merge list: [#812](https://github.com/org/repo/pull/812)
```

**DO end the final reply to a check ask** ("ensure everything works", "see if X happened", "is it ok")
**with one bold verdict line, at most 20 words: `**Yay, all good:** <evidence>` or `**Nay: <what is
broken>.** <next step>`.** Keep the body above it TLDR: at most 3 one-line bullets. Put an unchecked
scope inside the verdict ("Yay for web; iPhone not walked"), never as a hedge bullet that withholds it.
TEST: the last line of a check ask's final reply starts with `**Yay` or `**Nay` (the fix for a
post-merge check whose hand-back spread "yes for web", "not checked" and status over 4 bullets, so
Simon had to ask "all good or not, yay or nay").

**DON'T** end a long run on status alone, and DON'T re-answer an older prompt whose questions an
earlier message already answered.
Pre-send check: list every `?` and every "should we", "is it", "correct me" or "am I wrong" in the
triggering prompt and in each message he sent during the turn; each has its answer bullet above the
first status bullet. A missing one goes in before sending. TEST (moved from `rules/process.md`): the
last message answers every question asked during the turn.
WHY: across a long turn the work's status crowds out the question that started it; Simon then sees a
wall of status and has to ask again (the fix for a session whose closing messages reported PR status
and never answered "should we just let people on the paywall pay?").
Backstop: the `hooks/intent-ledger.sh` stop reconciliation reason repeats this rule at the end of a
work turn. It does not detect a missing answer: whether a line answers a question needs judgement, and
a second Stop block would add the very wall of text this rule removes.

## App build line

The pointer lives in `rules/communication.md` § Answer first. This section holds the rule, shape and
TEST.

**DO state whether a new native app build is needed on every hand-back that names a PR or change for
Simon to merge or deploy, in a repo that ships a native app** (a top-level `ios/` or `android/`
directory, or a native shell that loads hosted web pages). Put it in the `Action needed` line or in
the numbered step that names the merge, one line per PR, as one of:
- `No app build needed: <why>`, e.g. every changed file is hosted web, so installed builds load it on
  the next page load;
- `Needs an app build: <which parts wait for it>`, naming what users get at deploy and what waits for
  the store release.

**DO derive it from the PR's changed files and its `Waits for the new build:` line**
(`references/git-pr-deploy.md` § Deploy safety check 4), and copy the PR's Deploy TLDR app build line
word for word.
**DON'T write one verdict for a set of PRs whose verdicts differ, and DON'T leave it for Simon to ask.**

```
Action needed (2): say merge for [PR #812](https://github.com/org/repo/pull/812), then retarget [PR #813](https://github.com/org/repo/pull/813) and say merge
- [PR #812](https://github.com/org/repo/pull/812) No app build needed: only hosted web files change; installed builds load them on next open
- [PR #813](https://github.com/org/repo/pull/813) Needs an app build: the new paywall header waits for 1.5.0; the price fix is live at deploy
```

TEST: every hand-back naming a mergeable PR in such a repo holds a `No app build needed` or `Needs an
app build` line per PR, matching that PR's Deploy TLDR (the fix for a merge ask on a web change to a
hosted app screen that never said whether its sibling PR's native part needed a build).

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
Hey, [PR #812](https://github.com/org/repo/pull/812) (search cache) is ready for your review.
- Adds one nullable column; nothing else touches prod
- Needs your yes before Monday's deploy
```

DO show a draft for Simon as the message alone in one quote block, under a chat reply that itself
follows § Human-facing messages. Both stay TLDR: the draft at most 5 lines, the reply around it with
no commentary restating the draft.

DO open a reply to someone's report or question with the verdict on line 1 when no ask exists
(`rules/communication.md` § Answer first): "All ok, nothing was broken." or "You're right, it was
broken; fix is in PR X." Detail below it only where it changes their action; no investigation
narrative (the fix for a reply that opened with "Checked it, and the fallback worked for all 5.").

DO lead with the action when a reply to a teammate's proposal carries a decision: line 1 is what to do,
with its numbers; then the rule for what comes next; then the one-line why; the acknowledgement ("your
inputs check out") goes last. End on the suggestion, never a question, and name whose figure each is
("your table", "my query"), never a bare "ours". TEST: no line before the action thanks, agrees or
confirms (the fix for an ads-scoreboard reply that opened "Agreed on your table" and closed "Can we use
the after-costs query?").

DO measure a draft for someone else when you write it, before you show it to Simon for approval,
and again before sending it by any route the hook cannot see (a `codex-app` run, `gh pr comment`,
`gh api .../replies`); an approved draft over the cap otherwise goes out with words he never saw:
`python3 ~/.claude/hooks/outbound-message-guard.py --check <draft-file>`. Expect `ok` and exit 0;
exit 1 prints the counts. Cut the draft; DON'T split it into several messages.
`hooks/outbound-message-guard.py` denies a Slack or Gmail send, reply, forward or draft over the cap.
When Simon's own message asked for the length ("send the team the full write-up"), write his words
into `.context/long-message-ok` in the working directory; the guard allows the next send only and
deletes the file.
WHY: a teammate reads the notification preview and the first lines; a long message from Simon reads
as a long instruction from him.
TEST: every message to someone else has at most 5 lines and 100 words, with an ask or verdict on line 1, or traces to a
`.context/long-message-ok` quoting Simon's request for length.

## Data table

The pointer lives in `rules/communication.md` § Answer first. This section owns the shape of any table
that goes to Slack, a chat or an email, and of any figures table shown to Simon.

DO render a table sent to Slack, a chat or an email as a friendly table IMAGE, never a markdown table
(Slack does not render one). Build it as HTML, screenshot it to PNG with headless Chrome for Testing
(binary: `~/.claude/bin/test-browser.sh path`), and use the dataviz skill's palette and status rules.
The image holds two tables:
1. WHAT CHANGED: before and after per row, the changed cells highlighted, plus a text label ("Cut",
   "Up", "Same") beside the highlight. Never color alone.
2. THE EVIDENCE: the figures that justify the change, the deciding rows highlighted, the best value per
   group in bold.
Under them, one footer line: the date window, the source, and what is excluded (test devices, a
named offer). Keep the width near 880 px so a phone shows it without zooming.
DO view the rendered PNG yourself and fix clipping before use, then show Simon the image and the
message text for preview before sending; the message text carries the ask on line 1 per § Message for
someone else, and the image carries the numbers.

DO keep ONE table per question. Name every money column by its source (card sales, a named offer,
refunds), and give a buyer column for every source the revenue counts, plus an "All buyers" column
drawn from the same sources as the revenue. Reconcile each row before sending: re-derive one revenue
and one buyer cell by hand from the raw rows.
TEST: no row shows 0 buyers with revenue above 0 unless a column names that revenue's source, and no
rate column contradicts a count column in the same row (the fix for a readout whose "bought 0" row
carried revenue from an offer the buyer column left out, which a reader caught twice).

## Automated message

The rule and TEST live in `rules/copy-quality.md`. This section holds the shape for a message a bot,
alert or scheduled job posts. DO copy it; the `[text](url)` links carry every id:

```
Checkout errors up 4x in the last hour

Card payments fail with a timeout since 14:05. Web only; the iPhone app is fine.

1. [Open the failing function's logs](https://logs.example.test/fn/checkout?window=1h)
2. [Roll back the 13:58 deploy](https://ci.example.test/runs/123/rollback)
```

Thread reply: cause, raw evidence (queries, API responses, sample rows), and anything else the
person reads only after deciding to act.

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

## Before/after unit

The one owner of how any BEFORE/AFTER is shown: a proposal or decision card
(`/sk:work-ask-reply-in-full-before-after-artifact`, `bin/decision-artifact.py`), a mockup plan part
(`/sk:ship-mockup-before-after`), a PR evidence pair (`/sk:ship-screenshot-changes`,
`references/screenshot-review.md` § PR evidence template), a plan delta and a row of § Before/after
TLDR. Each consumer points here and restates none of it.

**DO make each unit show ONE proposed change, titled with that change in 2-6 words** (e.g. "Outside
workouts count for streaks").
**DON'T title a unit with an option label or a bare topic** ("Streaks", "Ship as built", "Suggest to
<person>", "Option B", "Keep current"): the reader cannot tell what Accept takes.

**DO show, visible without expanding, in this order:**
1. A one-line context TLDR: what changes, who sees it, the consequence.
2. On a decision card, one line each: `Accept:` what ships or happens, `Decline:` what stays.
3. BEFORE, the exact current state, and AFTER, the exact state once accepted.

DO show BEFORE and AFTER as real screenshots when the change touches a visible surface; a not-built
AFTER is a labelled Preview rendered from the real app code or screenshot. Otherwise write
them as concrete text with real values, e.g. `Streak day: plan workout + calorie goal` →
`Streak day: plan workout OR a 20+ min outside workout, + calorie goal`.
DO put context the TLDR cannot hold in one collapsed Details, and add none when the TLDR covers it.
**DON'T split one decision into mirror units** (keep vs change, ship vs defer, suggest vs build as
is): one unit, and its Accept/Decline control decides it. Two genuinely different changes are two
units, each with its own BEFORE and AFTER.
DO give a PR evidence pair a context line above its image (what changed, why it matters), a BEFORE
caption saying what happens on the base and an AFTER caption saying the result, never the same text.

NUMBER: 1 change per unit; title 2-6 words; TLDR at most 25 words; Accept and Decline one line each.
TEST: reading one unit alone, a reviewer names what changes and what Accept does; every unit carries
a TLDR, a BEFORE and an AFTER; zero titles are option labels; zero pairs of units are the same
decision. The card builder refuses a feedback card that breaks this, and `bin/pr-evidence.py` refuses
a blank or identical caption pair (the fix for a decision board whose first two cards,
"Streaks: suggest to <person>" and "Streaks: ship as built", each held one sentence and no
before/after).

## Before/after TLDR

**DO open every PR body with `## TLDR`, above `## 🚀 Deploy TLDR`, holding exactly two parts:**
1. A `| Change (biggest impact first) | Before | After | Why |` table, one numbered row per
   behaviour a user or the system shows or does differently against the CURRENT base (a behaviour
   the base already delivers is no row). Order rows by impact: people or money affected first, using
   the real production count where one is known (e.g. "10 people in 10 days, none bought"). Write
   each cell as a person would say it: the screen, the words they see, what they can do, no code
   names. The changed value is **bold**; a neighbour a reader might assume moved reads `unchanged`.
   `Why` is last: the one-line reason the new behaviour is right.
2. One line starting `**Do:**`, after a blank line (GitHub folds an unseparated line into the
   table): the reader's action (merge, review a named file, decide a named question) plus the one
   fact that makes it safe or risky.

**DON'T add a prose paragraph, an intro line, or a row restating a section below.** NUMBER: each
cell at most 25 words; above 15 rows, fold the lowest-impact ones into one last `Smaller fixes` row.
WHY: Simon opens a PR and decides from this block alone; every section below is detail on demand.

**DO print the same table, unprompted, in the chat hand-back of every PR or change,** straight after
line 1 (`rules/communication.md` § Answer first), re-derived from the final head: the table is
not a bullet and does not count against the 5-bullet cap. **DON'T wait for "give me the before and
after".** TEST: every hand-back naming a PR or a finished change carries the table, and its rows match
the PR's `## TLDR` (the fix for a 14-row change table Simon had to ask for by name).

```
| Change (biggest impact first) | Before | After | Why |
|---|---|---|---|
| 1. Paid-plan searches (server cap) | 50 a week; 30 members hit it last month | **200 a month** | Members on long trips ran out mid-week |
| 2. Counter resets | every Monday | **on the account's start day** | One period per member, matching the bill |
| 3. Free plan | 5 a week | unchanged | Out of scope |

**Do:** merge. The migration applies itself; no current member is refused.
```

TEST: the fetched PR body's first heading is `## TLDR`, it holds a table whose header names Before,
After and Why in that order, and a `**Do:**` line, and nothing else before `## 🚀 Deploy TLDR`.
`bin/pr-landing-gate.py` checks this and owns the heading names.

## Part verdicts

**DO hand back, and post under `## Part verdicts` in the PR body, one row per separately-decidable
part `/sk:work-does-this-make-sense-to-build` named, re-derived on the final head of every Standard or
Deep build, adopt or rebuild; a Light one (`references/testing-strategy.md` § Size the checks to the
change) posts no table and convenes no judges:**

```
| Part | Verdict | Mainstream practice | Regression evidence | Claude judge | OpenAI judge |
|---|---|---|---|---|---|
| 1. Retry failed sync calls | BUILD: 4% of calls fail once, then succeed | Capped backoff with jitter ([AWS](https://aws.amazon.com/blogs/architecture/exponential-backoff-and-jitter/)) | 3 changed files, base and head suites PASS | agrees | agrees; caps total wait |
```

- **Verdict:** the skill's verdict plus the one fact that decided it.
- **Mainstream practice:** the widest-adopted approach to the same problem, one primary-source link
  (`rules/engineering-standards.md` § Choose mainstream, widely-adopted tools); a part that departs
  from it names why. A part with no outside analogue links the repo file whose convention it follows.
- **Regression evidence:** the part's rows from `references/testing-strategy.md` § Regression check;
  `pending` only before the build.
- **One judge column per provider** (`references/research.md` § Independent judges), each holding that
  judge's own position.

NUMBER: one row per part, each cell at most 20 words. TEST: every Standard or Deep build, adopt or
rebuild hand-back and PR body carries the table with a link in every Mainstream practice cell and a position in every
judge cell; `bin/pr-landing-gate.py` fails a posted section missing its columns or a link.

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

## Background-event turns

A task notification, an expiring monitor and a Stop-hook feedback turn start a turn Simon did not write.
When it brings no new outcome, decision or ask, the reply is empty or one line naming the new fact. The
full block returns on his next message, a changed ask, or a real outcome (verdict, merge, failure). The
pending ask stays in the plan and ledger, and the last message after his own turn carries it. A Stop-hook
reconcile turn records the ledger note and sends no restatement. TEST: two assistant messages with no
Simon message between never carry the same `Your call` block (the fix for 7 copies of one merge ask sent
on idle agent pings and monitor expiries).

## Moved from `rules/communication.md` § Answer first

Send this session's impact on another session's work to that session (`rules/process.md` § Tell the
live session your change affects), never onto Simon's action list.

Things that wait on Simon: a test, a merge word, a decision, a login, a reply. Origin of the
no-repeat TEST: 7 repeats of one block on idle notifications.

## Answer-first TEST (moved from `rules/communication.md`)

Two assistant messages with no Simon message between never carry the same block; line 1 is
`Action needed: …` or `No action needed`; a body naming a pending item on Simon ("say merge", "your
retest", "your call", "after your") under `No action needed` fails; each pending ask is a numbered
step; at most 5 one-line bullets and 5 steps of at most 20 words; a message for someone else has at
most 5 lines, line 1 an ask or verdict; each `?`, "should we" or "correct me" in the prompt is
answered above any status; a check ask's final reply ends with a `**Yay`/`**Nay` line; in a
native-app repo each merge or deploy ask holds its app build line (§ App build line). Every `Action needed` item, follow-up and status bullet traces to this
session's own ledger or work, unless Simon asked about the other session (the fix for a session TLDR
that listed two other sessions' PR conflicts as Simon's actions).

## Close-session TEST (moved from `rules/communication.md`)

A finished session's last message has the archive line, at most 2 optional follow-ups, and no
"the next X will confirm", "worth watching" or "keep an eye on" item. No line, or the line with work
running, an unmerged session PR or an item unverdicted, fails; so does "merged" reported as done
with no prod evidence.

Open-items TEST: the message before the archive line lists every ticket the session created or
adopted that is not Done or Canceled, every found defect neither fixed nor ticketed and every promised
check, each with link, status, one line and a disposition (worked now, Simon's quoted deferral, or a
named owner told). A ticket filed with no disposition, an item missing from the list, or the line
above any such row fails. Filing a ticket alone is not a disposition. Not enforced by the Stop hook: the ledger records prompts and notes, not the
tool calls that create tickets, so a ledger scan would miss them.

Also moved from the close-session rule: stop once CI is green, deployed and a smoke on what can be
reached passed; ask no new question at hand-back unless only Simon can decide it and it blocks the
outcome. The five writing rules govern content and apply equally to subagent prompts.

## Loose term (moved from `rules/communication.md`)

Use the standard term from then on unless he keeps his. DON'T adopt his term silently and raise the
standard one only when he asks. Method: `references/code-best-practices.md` § Use the industry's
name. TEST: the reply naming the term precedes the first artifact.

## Links

Every PR, issue, ticket, Slack thread, CI run or doc a message to Simon mentions is a markdown link
with its full URL, e.g. `[#123](https://github.com/org/repo/pull/123)`, in bullets, steps and the end
block, on every mention. He cannot click a bare "#123" or "POI-123", so either one fails. Resolve the URL (`gh pr view
--json url`, the ticket's own link) before sending; if none exists, say so in place of the id.
A `Merge list:` line follows the same rule: `Merge list: [#812](https://github.com/org/repo/pull/812),
[#813](https://github.com/org/repo/pull/813)`; `hooks/git-commit-guard.py` still reads each `#N` from the label.
TEST: grep the message for `#\d+` and ticket-id patterns outside a link; any hit fails (the fix for a
status message that named six PRs and tickets as bare ids).
Backstop: `hooks/bare-reference-guard.py` blocks Stop once when the final message holds a bare `#NN`,
`owner/repo#N` or ticket key outside a link, code span or URL, and names the origin's link form
(the fix for hand-backs ending on "Merge list: #1297, #1497" until Simon asked for the links).
`python3 ~/.claude/hooks/bare-reference-guard.py --check <draft-file>` measures a draft; expect `ok`.

## Pasted example (moved from `rules/communication.md`)

**DO read a concrete prompt or example Simon pastes as an illustration of the intent, and act on the
rule behind it — not the example's specifics.**
**DON'T build the example verbatim, and DON'T ask him to confirm its specifics.**
TEST: a reply that treats a value from his example as a literal requirement, or asks him to confirm
one, broke the rule.
