# Planning and tracking

Reference catalog for how to plan work and track it to completion. Pulled in by skills and CLAUDE.md on demand.

## Plan first, tickets second, code last
- Before implementing anything, produce the complete plan first — with all implementation details — in the tracker, then implement.
- Alongside the detailed plan, always give a top-view, human-readable game plan in a few short numbered steps (1. 2. 3.).
- Keep the plan that connects all the pieces together in one main ticket; spin the work off into subtasks.
- At the top of every plan and every ticket, open with the user AND system journey (current trajectory) described in the next section, before any detail.
- Every ticket the plan names is a full clickable link (the Linear issue URL, e.g. `https://linear.app/<org>/issue/<ID>/...`), never a bare id, so each stays checkable from the plan.
- Consolidate every question — clarifications, decisions, confirmations — into ONE section directly below the TLDR; never scatter questions through the plan body or bury them mid-detail.
- Ensure no context loss across tickets — tickets must not become incompatible with each other when merged. Each ticket carries the context of how it relates to the rest.
- Order follow-up tickets by priority; each must include testing instructions, how it relates to the rest, and exactly what part of the app breaks if it doesn't work.
- If work is blocked on an unreliable or non-developer contributor (no published branch, or their work is wrong), take it over: cancel/supersede their ticket with a comment linking the new ticket that solves it, and fold the work into the plan.

## Open every plan with the user AND system journey (current trajectory)

The first thing in any plan is TWO journeys, one above the other, ABOVE the technical detail: the
**user journey** (what the user does and sees) and the **system journey** (what the machine does, in
order, including where it stops early). A ticket or PR body opens with them too.

Both reflect the plan's CURRENT TRAJECTORY — what it would do if built now, applying every confirmed
decision AND the recommended default for each still-open question — labelled as such, so the reader
sees where it is heading, not only what is locked. Keep both in sync on EVERY change: a decision that
resolves, or a default that shifts, updates the journeys at the top in the SAME edit. They are DERIVED
from the resolved plan, so they never drift from it (`rules/engineering-standards.md` § single-source-of-truth).

The format is owned by `~/.claude/references/tldr-report-formats.md` § Block 1 (user) + Block 2
(system), including the cross-check between them — read it there, don't restate it. It is what makes a
proposal judgeable before it is built: a plan described in components reads as fine right up until
someone tries to use it.

## Re-check the plan against the original source material, twice

Requirements leak out of a plan quietly. Across three revisions an acceptance criterion nobody
explicitly dropped is simply no longer in the document, and the plan still reads complete.

- **Keep the source material to hand for the whole task** — the tickets as written, and the original
  request. Not a summary of them; re-read the originals.
- **Read the WHOLE ticket, not just its description field** — the description AND every comment (the
  top-level discussion AND the inline/anchored comments, which carry a `quotedText` snippet of the text
  they annotate) AND its attachments and linked docs. Decisions, corrections, scope changes and revised
  acceptance criteria routinely land in the comments, not the description, so a description-only read
  schedules stale or already-answered work (e.g. a ticket surveyed by its description alone reads as
  unbuilt when a comment already handed it off or narrowed it). TEST: a per-ticket verdict whose
  evidence traces only to the description, never to a comment or attachment, has not read the ticket.
- **Before proposing any plan, go through it against every source item** and account for each one:
  carried in, deliberately dropped (say who decided that and when), or superseded. Anything with no
  verdict is a dropped requirement, not an omission.
- **Run that check again after every revision.** Revisions are where things fall out, and the later
  the revision the less anyone remembers what the original asked for.

## Check every decided rule against the goal it serves

A criterion can be met and still work against the reason the ticket exists. Judged one by one, a rule
from a review round passes; judged against the goal, it undoes it.

- **DO state the business goal in one line at the top of the plan**, in the asker's words ("always
  encourage people to buy the paid plan"), not in the ticket's mechanism.
- **DO write one sentence beside every rule decided during the work** (a review round, a design call, a
  scope cut): how it serves that goal. DON'T accept "criterion met" as that sentence.
- **DO put a rule that reduces the goal in the question block, before it is built.** It does not wait
  for a reviewer to notice.
- TEST: every decided rule carries a how-it-serves line, and a rule with no line, or a line that says
  it reduces the goal, has a question against it (the fix for a review-round rule that hid an upgrade
  prompt, built and judged met, when the ticket's purpose was to encourage upgrades).

## A pre-existing ticket is a claim about the past — verify it against today's code

An older ticket, spec or plan was written against the codebase as it stood then. Some of it has since
been built, some has been made irrelevant by other work, and some was always wrong.

- **Read the real code for each one before scheduling it**, and give a verdict per ticket: still
  needed as written · partly done (say which part) · already solved elsewhere · obsolete.
- **DO re-verify an existing PR or ticket against today's base AND today's production data,
  unprompted, before any more work on it:** when a session resumes it, the base moved since its last
  push, or a deploy landed in its area. Read the problem's production signal read-only over a recent
  window since the last deploy (the refusal, error or empty result it fixes, counted with its
  denominator; `/sk:ship-verify-with-prod-data` owns the reads), and say whether real users reach the
  state or only tests and seeded data do. Then give the verdict above per part, list what the PR still
  adds over the current base, and cut any part the base now delivers from the PR in the same batch.
  DON'T keep building, re-shooting or shipping a PR before this verdict exists. TEST: every resumed PR
  or ticket has a dated verdict with the production count it rests on, and the PR holds no part the
  base already delivers (the fix for a PR Simon had to ask four times whether it was still needed after
  main moved).
- **Say what changed** that makes an obsolete one obsolete. A verdict with no evidence is a guess,
  and the guess is what reintroduces work someone already deleted.
- **Check work already underway before scheduling it.** `git fetch`, then search every branch and
  worktree for the ticket id (`git log --all --oneline --grep=<ID>`, `git worktree list`) and the
  ticket's own comments, and list the migration, ADR and other sequence numbers those branches
  already hold. Record the overlapping branch, or "none found", in the plan before assigning files,
  and take the next free number. TEST: the plan names each overlapping branch, and no two open
  branches hold the same sequence number. (The fix for two branches claiming one migration
  number.)
- **When several tickets block each other, order them from the verified state**, not from the
  dependency links as filed — a link written months ago can point at a ticket that no longer has
  anything to do.

## Scope a feature across every surface it touches

A feature is not done when the mechanism works. When planning one, enumerate all of its surfaces up
front, because the ones that get forgotten are always the same ones:

- **The mechanism** — the backend, the integration, the logic.
- **Discoverability** — how does anyone learn it exists? A capability nobody knows about was not
  shipped. This usually means the marketing surface: the landing page, the changelog, the pricing table.
- **In-product guidance** — where does a user who wants it go, and what walks them through it? Place it
  where users already look rather than inventing a new home for it.
- **Guardrails** — anything that spends money or acts on a user's behalf confirms with them first, and
  shows them what it is about to do while they can still change it.
- **The docs** — the agent-facing ones included, per the project-documentation rule in `rules/process.md`.

Decide these at planning time. Retrofitting discoverability onto a shipped feature is how a good
feature stays unused.

## Capture the inputs the code cannot show you — ask now, and make each ticket ask too

Why front-load (moved from `rules/process.md`): assume Simon may hand the session over and walk away.

A plan built only from the repo misses everything that lives in another system: edge/CDN rules and
cache/routing/firewall config, design-tool screens (mockups, prototypes) and their export settings, a
third-party service console (billing, telephony, auth, analytics), an infra or observability dashboard,
a DNS record. None of it is in the diff, so a plan derived from code alone ships with those to-dos
silently missing.

- **DO list every out-of-code surface the work touches, then ask Simon for each BEFORE writing the
  plan** — one questions block, the exact thing named ("the edge cache rules for the app's domain",
  "the design-tool frame for the new wizard step"), never "the relevant config". This is
  `rules/process.md` § "Front-load everything you need from me" applied to out-of-code STATE, not just
  auth. TEST: every external system the feature reads or writes has its config in hand OR a named ask
  against it before the plan is proposed.
- **DO make each ticket name the inputs its implementer must obtain before starting** — mockup/design
  references, that out-of-code config, a sample payload — so the downstream agent asks Simon for them
  instead of guessing. A ticket that needs a mockup and does not say so produces a confidently wrong build.
  For a visible change, name the design source's absolute path, board ids and measured spec path,
  restate no board value in ticket prose, and apply `references/workflow-loops.md` § Build from a
  supplied design source.
- **DO list the prerequisites of any check you propose BEFORE you estimate it.** Read from the code and
  the provider what it needs (credentials, catalog objects, settings, accounts), confirm each exists, and
  give the time estimate only after, naming what is missing. DON'T send Simon to fetch one input for a
  check whose other prerequisites are unverified. TEST: a proposed check that needs something from him
  lists each prerequisite as found or missing before any estimate (the fix for a "15-minute" payment
  sandbox check proposed twice while the catalog objects it reads did not exist in the account).

- **Front-load what is PREDICTABLE from the task** (moved from `rules/process.md` § Front-load). This
  does not forbid interrupting Simon later: if something unexpected turns up, or a new fork appears
  where guessing wrong would waste the work, ask then; he is not always away. It forbids stalling
  mid-run on a blocker foreseeable at the start.

## Before building, the ticket is a complete, decision-resolved spec — the builder cannot ask

The thing that builds a ticket is increasingly NOT the session that planned it: a Claude Code cloud
session, a parallel `/sk:work-hyperspeed` part, a teammate, or you three days later. None of them can
ask a follow-up mid-build, so every fork left open becomes a confident wrong choice and every
requirement left only in chat becomes a missed point.

- **DO resolve every decision the build depends on BEFORE it starts, and write the resolution INTO the
  ticket** — the option chosen and a one-line why, not the open question. A fork recorded as "TBD", or
  left in the chat log, is one the builder picks blind.
- **DO make the ticket carry every requirement and acceptance criterion the build must satisfy**, so a
  builder reading only the ticket misses nothing. Run § "Re-check the plan against the original source
  material" and § "Scope a feature across every surface it touches" against the TICKET, not just the plan.
- **The full plan narrative stays in chat / `.context/`, never auto-posted as a ticket comment.** What
  goes INTO the ticket is the resolved decisions, the acceptance criteria, and the context linking it to
  the other tickets — with Simon's sign-off, and only what he actually stated or approved, never invented
  detail. His approval on the plan is what licenses writing it into a work ticket.
- TEST: hand a cold build session ONLY the ticket and it can build without one follow-up — every fork
  has a recorded verdict (option + why) and every requirement is present. A ticket with an open decision
  is not ready to build.

## Track every ask to completion — never drop items

Owned by **`~/.claude/rules/process.md` § "Track every task to completion"**, which is always-on and
so already loaded. Not restated here — two copies of a completion rule is how one of them ends up
saying "done" while the other still has open items.

The only thing this file adds: WHERE that durable artifact lives, and how it survives worktree
teardown. The intent-ledger hook already logs every prompt verbatim to `.context/intent-ledger.md`.
Durability tiers, most durable first: the ticket/tracker outlives everything; the worktree's
`.context/` survives a restart but dies with the worktree, so promote the decisions and human input to
the ticket before teardown (§ Promotion before teardown below). The survives-a-restart guarantee and
the no-`/tmp` rule are process.md's, above.

## Asked-for work ends built

Owned by `rules/process.md` § "Run to completion". This section holds the detail.

DO read the verb Simon used before choosing the deliverable. "Do", "build", "fix", "ship", "the queued
tasks" and "for each of the queued tasks, use skill X" ask for the work done; the skills he names are
the method, never the scope.
DO run a named evaluation skill (`/sk:work-does-this-make-sense-to-build`, `/sk:plan-research`,
`/sk:ship-verify-with-prod-data`, a plan) as one stage of each item, then carry each BUILD or
BUILD-CHANGED part on through `/sk:work-full-detailed-workflow` to its done state in the same run: a
pushed, ready PR for code, a landed commit for config, the applied change for anything else.
DO dispatch independent items in parallel (`references/parallelization.md` § Parallelize across tasks
AND stages); DON'T serialize them into "one at a time, later" or hand back a queue for Simon to start.
DON'T end the turn on a table of verdicts or plans. A REFUTED, ALREADY-DONE or DEFER verdict closes its
item with the evidence; a DECIDE verdict waits on Simon while every other item keeps building.
NUMBER: an item may be listed as not done at hand-back only with one named Simon-only blocker: a
decision, a credential, a production write or a paid call.
TEST: every item Simon asked to have done is, at hand-back, done or blocked by a named Simon-only step;
a verdict alone is never a completed item (the fix for a batch of asked-for follow-ups handed back as
verdicts and plans).

## Close the session

Owned by `rules/communication.md` § Close the session. Detail:

- **Finished** means every ask in the ledger/plan has a verdict, no agent, watcher or process of this
  session is running, no lease or port is held, the worktree is clean and pushed, and the session holds
  nothing Simon still needs it for. The line is false while any of these is open:
  - a CI run, background agent or job this session started, including CI on a head it just pushed;
  - an open PR or branch this session produced that still needs Simon's merge or deploy;
  - a promised follow-up: a deploy smoke, a reply to a reporter, or a decision awaiting his answer
    that blocks shipped value.
  - a runtime clause still `open` on the live acceptance list (§ Runtime asks).
- **Unresolved findings block the line too.** Before it, list every item the session found or created
  that is unresolved: a ticket it created or adopted not Done or Canceled, a defect it found and neither
  fixed nor ticketed, a residual risk or follow-up check it promised. One row each: link, status, one
  line on what it is, and a disposition: **worked now** in this session, **deferred** with Simon's own
  words quoted, or **owned** by a named person who was told (message sent). Filing a ticket starts
  tracking and is never a disposition. Build the list from the plan, the ledger notes and the tickets
  the session's tool calls created (every `issueCreate`), not from memory. With any row lacking a
  disposition, work it now or end with `Action needed` naming the deferral Simon must give. e.g. three
  Backlog tickets and one un-ticketed button defect under "everything here is done" would have been
  buried among hundreds of tickets. (the fix for a session that gave the archive line with three
  self-created Backlog tickets and an unticketed defect.)
- **When the only remaining step is Simon's own merge or deploy, end with the merge list and no
  archive line:** each PR to merge, in order, and that this session holds the post-deploy smoke and
  follow-ups. e.g. two open PRs with CI running on the last push end "Merge [#A](url), then [#B](url); I run the
  smoke and reply to the reporter after deploy", never the archive line. (the fix for a session that
  said the line with CI running and two PRs awaiting merge, then had to be asked what to merge.)
- **After merge and deploy, production is proven live** before the archive line: the deploy run for
  the merge sha passed, prod serves the new build, and the changed behaviour passed its read-only
  smoke (`references/git-pr-deploy.md` § Shipping is not done until the deploy is verified).
  The hand-back lists each Deploy TLDR step as ran with its check result, rolled back, or held with
  Simon's quoted keep-off or a Simon-only blocker (§ A merge word runs the Deploy TLDR), never a new ask.
- **Time-only checks**: what only time, a real customer or a future event can confirm is no loose end:
  drop it, or use one short "will show up naturally" clause.
- **Outstanding work** (process.md "name all outstanding work", living-plan, the Stop-hook reconcile)
  means work the ask requires or a blocker with evidence. A check only time or a real customer can
  confirm is not outstanding. This never weakens CI, tests, the reachable walkthrough, security review
  or the ship landing gate, and never lets a requested feature go unbuilt.
- **Not stop signals** (moved from process.md "Run to completion"): **a clean verification** (green
  tests mean the batch is safe to build on, not that the job is over) and **a long turn** (length is
  not a stopping condition, nor is "a good place to pause"). The stop is the ask's outcome delivered and
  verified to a reasonable level, never an invented check.
- **A checkpoint is not a stop** (moved from process.md "Run to completion"): the recurring failure
  is a checkpoint reached, a summary worth writing, and the summary becoming the end of the turn.
  Verification generates new work, and stopping after the first fix round is how a "done" lands with
  known loose ends.
- **Follow-ups**: at most 2, optional, one line, only if they change a decision or fix an evidenced
  problem; otherwise do it now if cheap and in scope, or drop it. The archive line is never withheld
  for an optional follow-up (an open item from the list above is not optional).

## Shared observable dashboard

DO compose `references/workflow-loops.md` for the plan’s status projection and execution mode.
Keep it current after each substantive transition. TEST: the dashboard revision matches the plan.

## Every flow writes into the ONE living plan — including verify, test, review, merge and ship

DO route EVERY flow's output back into the single living plan (`.context/<slug>-plan.md`), not only the
build's: a test matrix's per-feature verdicts, a review's findings, a merge's conflict decisions and a
ship-report's per-ask verdicts all land IN the plan as they are produced. WHY: the plan is the ONE report
Claude reads at the start of the next turn and updates, so a verdict left only in a transcript, a
workflow's return value, or a side file is one the next turn cannot see — and the work drifts off its
rail. This is `rules/living-plan.md`'s always-on rule applied to the flows that only VERIFY, not just the
ones that build; a verify/test/review flow is a substantive flow, so it reads the plan first and
reconciles its findings into it exactly as a build does.
TEST: after any test/review/ship pass, the plan holds each verdict and finding it produced, none
stranded in a transcript or a workflow result.

## Make long work resumable after a quota/usage cut-off — commit stages, resume from them

DO commit every finished-and-verified STAGE of a long multi-stage task as its own green,
self-contained checkpoint (one logical unit per commit), and keep a durable STAGE-CHECKLIST in the
worktree's `.context/` — the plan, the restore point, one line per stage marked done as it lands.
WHY: a usage/quota limit can end the session mid-run; a committed stage plus a durable tracker means
the cut-off costs one stage, not the run. This is the resilience reason behind commit-when-done and
phased-execution (`rules/process.md`), stated here as the concrete artifact — not a second copy of
those rules.

DO, when Simon says "complete the interrupted task" after a reset, reconstruct where you left off
from `git log` + the `.context/` stage-checklist + the working tree BEFORE doing anything, and
continue from the first unfinished stage — never redo a committed one (process.md § phased-execution's
resume rule).

TEST: at any point mid-run, the last finished stage is a commit AND the `.context/` checklist names
it, so a fresh session resumes from git alone with no lost stage.

## The intent ledger — the record of what was asked, and whether it got built

WHY: a gate proves the code runs. A summary proves you can describe it. Neither proves point four of
a five-point ask was built.

`hooks/intent-ledger.sh` appends every prompt verbatim to `.context/intent-ledger.md` at the worktree
root, under a lock, and announces `INTENT LEDGER ACTIVE` once per session. **No announcement means no
ledger for this worktree: do not create one by hand.** It refuses where writing would be unsafe (a
path that is git-tracked, or one that is not git-ignored) and says so once with the exact fix, so a
silent ledger is never mistaken for an empty one. Inside `~/.claude` it redirects out of the tracked
tree rather than refusing, because that repo is pushed and its allowlist `.gitignore` makes
`check-ignore` useless as a guard there.

**Four sections are yours. Append them with `intent-ledger.sh note <kind> <scratch.md>`, never with
Edit or Write.** The hook is the sole writer, so a whole-file rewrite from a second chat in the same
Conductor workspace cannot delete an ask appended since it read the file.

- `sources` — every source this work is judged against, each as a **link**, written at the start and
  appended to whenever another is named. A ticket goes in as its full URL, so all of them stay
  checkable later and none is picked over the others. With no ticket the entry is `prompt-derived`
  with the timestamp of the ask it came from. This is what makes the no-ticket and the many-ticket
  cases one mechanism rather than two special cases.
- `plan` — the approach at sign-off, and specifically its DELTA from those sources, in this file's
  vocabulary from § "Re-check the plan against the original source material": carried in ·
  deliberately dropped (who decided, and when) · superseded. **It carries a ratification line** naming
  what approved it and when. A plan derived from a prompt says so, and the approval ratifies it.
- `pivot` — one entry per redirection, written when it lands and not later. A pivot reconstructed at
  the end always agrees with what got built, which is exactly what makes it useless as a check on
  what got built. Record what caused it, what it replaced, and which source it changes.
- `reconcile` — at hand-back, on substantive or multi-step work. One verdict per clause of each
  recorded ask, in ledger order, each tagged with its source, so a skipped clause reads as a gap rather
  than an absence and no single source can fall out unnoticed. `/sk:ship-report-and-ensure-correct-user-system-journey`
  writes it at the end of any substantial ask (`rules/process.md` § Prove every point): it walks the user
  journey and the system journey, judges both against the criteria the plan validated, writes a test
  per verdict, and reconciles the worktree's `.context/intent-ledger.md` ask by ask.

**Record authorization separately from capture.** A direct instruction authorizes its stated scope;
record that source in the plan without asking for the same permission again. A brainstorm, quoted
example or unapproved proposal stays recorded with its decision pending. The mere existence of a
ledger or skeleton does not approve implementation. Apply the shared Continuous request reconciliation
protocol above to both, so pending decisions cannot erase authorized work.

The finish hook requires a reconciliation after the newest ask, plan or pivot, including sessions
without a formal ratified-plan entry. It checks freshness, not whether the agent
fulfilled each ask. Its stop feedback is bounded to once per unchanged ledger snapshot and respects
`stop_hook_active`; remaining work must still be reported honestly.

**Ship gate.** `hooks/intent-ledger.sh push` (PostToolUse) records each successful `git push` of a
non-default branch from a repo other than `~/.claude`. After `/sk:ship-full-detailed-workflow` runs on
the pushed head, record it with `intent-ledger.sh gate <branch> <sha|HEAD> PASS|BLOCKED|N/A [light|standard|deep] [reason]`
(BLOCKED, N/A and a light or standard PASS need a reason; a standard or deep BLOCKED reason
holds `All stages ran` or `Not run: <stage>, <stage>`, a standard or deep PASS holds `All stages ran`
and no `Not run:` list; tiers: `references/testing-strategy.md`
§ Size the checks to the change). Every PASS names its tier and needs a stage receipt on the gated
sha for each stage that tier requires: `intent-ledger.sh skill` (PostToolUse on the Skill tool, a
typed `/sk:<stage>` prompt, or a Codex read of the stage's SKILL.md) records one for the HEAD of
the checkout the work runs in (the payload cwd; a subagent's, whose cwd resets, is the checkout its
last Bash `cd`/`git -C` named), and `intent-ledger.sh stages <tier> HEAD` prints `All stages ran` or the `Not run:` list. The
hook's stage list is the one home of which stages each tier requires. Stop blocks once per set of
open pushes, naming each tier's missing stages; a newer head re-opens it. A light or standard
receipt carries to a later head across a Light-sized delta of the PR's own commits, and an N/A
quoting Simon's recorded waiver covers the branch's later non-Deep-path heads
(`references/testing-strategy.md` § Follow-up pushes and waivers).
This is what backs `rules/process.md` § Prove every point: Stop blocks once per pushed non-default
branch head until `hooks/intent-ledger.sh gate <branch> <sha|HEAD> PASS|BLOCKED|N/A [tier] [reason]`
records the result (the fix for two PRs handed back unreviewed; the harness then found a dropped
consent event and a no-op column revoke).

**Two shortfalls, two different homes.** A raw-ask clause, or a ratified criterion, that was not
built is a Not-met criterion and is closed the way any gap is, by
`/sk:ship-report-and-ensure-correct-user-system-journey`. An ask that never reached the ledger, or a
ledger nothing consulted, is a config fault: repair it under
`rules/self-healing-config.md`. Never route the first into a config change or the second into code.

**Promotion before teardown.** The worktree is disposable and the ledger dies with it by design, so
what only it holds is promoted out first: the reconciliation and the plan-vs-sources delta go to the
tickets in `sources` (each source's verdicts on its own ticket, anything cross-cutting on the primary
with the rest linked), or to the PR body when there are no tickets, with anything still open filed as
a follow-up. **The verbatim prompts are never promoted.** They may carry pasted credentials, and the
session transcript already holds them outside the worktree, so copying them into a pushed artifact
adds a leak path and no information.

## Gap sweep before the first push

**DO, before the first push of a build, adopt or rebuild (a push to an adopted PR's existing branch
included), list every acceptance criterion of every ticket in `sources` (fetched whole, comments
included, plus the stated scope of the PR being adopted or rebuilt) and every clause of every raw ask,
one row per target the clause names (§ Every named part on every named target),
and mark each MET or GAP against `git diff <base>...HEAD`.** Build each in-scope GAP before that push;
route only another owner's item through `/sk:ship-check-merge-readiness`'s cross-owner discipline.
Repeat the sweep for an ask that lands after the first push, before the next one.
**DON'T leave the sweep to `/sk:ship-report-and-ensure-correct-user-system-journey` at the end:** that
pass proves the criteria with tests; this one keeps a gap from reaching the PR.
NUMBER: one verdict per criterion and per clause; zero GAP rows unbuilt or unrouted at the push.
TEST: the plan holds the sweep's verdicts, timestamped before the first push record (the fix for ticket
criteria a rebuilt PR left out, found only by the late ship report and then asked for by Simon).

## Every named part on every named target

**DO grid the ask before building: each part it names against each target it names (surface,
platform, audience), one cell per pair, in the plan.** Every cell holds the part the ask named.
A recommended default fills only a choice the ask leaves open; a named part is never one.
**DON'T keep a target's existing piece as a "same baseline" or "parity later" default when the ask
names the new one,** however close the old piece looks or however much it saves.
**DO carry a part that cannot move as-is by keeping it and changing only the piece that cannot** (a
platform API, a payment rail, a screen size), and name that piece in its cell and in the hand-off.
NUMBER: zero cells holding a substitute, an omission or an unnamed change.

**DO walk the whole deliverable end to end on every target to its last stage yourself before handing
Simon any step, link or "ready", and tick each cell from what you saw on screen there.** A walk that
stops short of the last stage, covers one target, or reads the code is not the check. Each step of
the walk follows `references/testing-strategy.md` § Human-driven sessions.
TEST: at every hand-off each cell names the part the ask named and carries a seen-on-screen tick from
a walk on the current build that reached that target's last stage (the fix for an ask naming a new flow on two platforms, where the
second kept its old final screens as a default and three hand-offs each failed at a later stage).

## Runtime asks

Owned by `rules/process.md` § Prove every point. A runtime clause asks what a deployed system does when
it runs on its own: a bot, a scheduled job, a pipeline, an alert, an agent (e.g. "it merges its own
fixes", "no false alarms", "its posts stay short").

**DO mark a runtime clause Met only with evidence from a production run that started AFTER the change
deployed:** the run URL or log line, the artifact it wrote, the message it posted, the PR it opened or
merged. **DON'T count a merged PR, green CI, a passing test or a local replay:** each leaves it `open`.
**DO keep a live acceptance list in the plan, one row per runtime clause:** the clause, the deploy it
waits on (sha and run), the next production run, and `observed <evidence link>`, `open` or
`blocked <Simon-only reason>`. Copy each row into every reconcile note as one line holding
`runtime: observed`, `runtime: open` or `runtime: blocked`; `hooks/intent-ledger.sh stop` blocks once
per ledger snapshot while the newest reconcile holds a `runtime: open` line.
**DO re-check after each deploy and each scheduled run of that system, waiting event-driven:**
`gh run watch <id>`, or a `run_in_background` wait with a timeout that ends non-zero, until the run
finishes or its next scheduled slot passes. Read that run's output against every open row, fix what
failed at its owning source, deploy, and wait for the next run. Start a run by hand only through a
trigger the system already offers (e.g. `workflow_dispatch`) and only when the ask covers running it.
**DON'T poll in a tight loop, install a cron, or hand back "done" while a row is `open`.**
NUMBER: stop early only on one of 3 conditions, each named with its row, runs and next step: the same
failure in 2 consecutive production runs after a fix; a decision, credential, production write or paid
call only Simon gives; a result that flips between runs on unchanged code (a flake, both runs linked).
TEST: every runtime row reads `observed` with a run that started after its deploy finished, or
`blocked` with a Simon-only reason; zero `open` rows at a hand-back that says done (the fix for a
deployed bot whose auto-merge, PR-structure and no-false-alarm asks were marked done at merge, then
failed in its next production runs until Simon spotted it).

## Verify foundation pillars before building
- Identify the foundational assumptions the plan rests on (especially third-party platform capabilities) and do detailed research on each before building anything — building around a false assumption is the worst failure mode.
- Verify what's possible three ways: (1) the codebase itself — read the actual branches, git diffs, and source, never descriptions of them; (2) online — official docs plus how popular production products actually do it; (3) empirically — a small isolated spike (T0) against the real service before anything else.
- When docs contradict each other or observed behavior, the empirical spike is the tiebreaker.
- Plan a concrete fallback for every risky assumption in case the spike disproves it.
- For empirical verification, tell me which credentials/mode you need (test vs prod key, sandbox vs live) and prefer sandbox/test so verification can't pollute production.
- If an assumption can't be verified with a simple script (needs a second account/another platform/too complex), don't block: create a prioritized follow-up backlog ticket with an explanation — unless it's mission-critical, in which case flag exactly what you need from me now.
- Before designing, inspect real production data (via MCP/CLI on the prod project) to verify base assumptions and see realistic document shapes, data patterns, and volumes — including worst cases — and plan for high performance against those worst cases.
- **Screen production data for the bug BEFORE planning the fix, and let only fresh data count.** The codebase moves fast, so a document written before the relevant code last changed can show a shape the current path no longer produces. DO pull the most-recent documents for the collection, treat a pattern that only pre-change docs show as already-fixed, and corroborate every inconsistency you keep against a second independent signal (a sibling collection, the write path in code, a log line). TEST: each inconsistency carried into the plan appears in data written AFTER the code that writes it last changed, AND is confirmed by one independent source — never inferred from a single stale document.
- Document platform gotchas discovered during spikes (account constraints, mode restrictions, version quirks) in the plan/test plan so they aren't re-learned.

## Phased execution

Applies only when Simon asks for phases, spacing or a stop after each stage:

- **Plan the phases first** and show me the list before starting, so I can see the whole shape and
  confirm nothing is missing. Dividing the work does not mean discovering it as you go.
- **Stop at each phase boundary and wait.** Inside a phase, run-to-completion applies in full: a phase
  ends when its work is done and verified, not when there is something tidy to report.
- **Commit as you go**, one logical unit per commit, so a phase boundary is a clean resumable point.
- **On resume, work out where you left off before doing anything** — read the plan, the commits, and
  the working tree. Never restart work that is already done, and never assume the previous phase
  finished cleanly just because it ended.
- **Phasing is for pacing, never for scope.** Everything on the original list still gets done. If a
  phase reveals more work, it goes into a later phase, not into the bin.

## Checkpoint before a risky change

Before a change that touches **more than about three files** (a refactor, a rename sweep, a migration, a
dependency bump), make a restore point FIRST. `/rewind` covers main-session edits only: a backgrounded
forked skill (`context: fork`) edits outside the session's checkpoints, and nothing Bash writes is
checkpointed. For those, commit the good state or branch before starting.

## Fix the class of failure (moved from `rules/process.md`)

When Simon reports wrong output (a bad render, a wrong answer, a broken page), his example is evidence
of a general failure mode, not the scope of the fix. **Don't patch the instance.** Name the rule that
was violated, check whether it is a known class, and write the fix generically so it catches variants
he hasn't hit.

- **Write the rule, not the example.** "The brand mark landed on the building instead of the crew's
  vests" becomes "a stated placement is authoritative and overrides any default placement", never "put
  brand marks on vests."
- **Keep ONE concrete instance** (`e.g.` / "the fix for X") so the fix stays actionable; never let it
  become the condition.
- **Grep every test in the repo for the old key before claiming suites green after renaming a
  persisted or saved shape;** the feature's own suites are not the scope (the fix for a renamed saved
  answer key where five tests in two other directories still saved the old shape). TEST: the evidence
  names the repo-wide grep and its zero remaining hits.
- **Tell me which class you concluded and what you checked** to rule out a one-off, so I can judge
  whether the generalization went too far or not far enough.
