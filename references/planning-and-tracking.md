# Planning and tracking

Reference catalog for how to plan work and track it to completion. Pulled in by skills and CLAUDE.md on demand.

## Plan first, tickets second, code last
- Before implementing anything, produce the complete plan first — with all implementation details — in the tracker, then implement.
- Alongside the detailed plan, always give a top-view, human-readable game plan in a few short numbered steps (1. 2. 3.).
- Keep the plan that connects all the pieces together in one main ticket; spin the work off into subtasks.
- At the top of every plan and every ticket, open with the user-journey TLDR described in the next section, before any detail.
- Consolidate every question — clarifications, decisions, confirmations — into ONE section directly below the TLDR; never scatter questions through the plan body or bury them mid-detail.
- Ensure no context loss across tickets — tickets must not become incompatible with each other when merged. Each ticket carries the context of how it relates to the rest.
- Order follow-up tickets by priority; each must include testing instructions, how it relates to the rest, and exactly what part of the app breaks if it doesn't work.
- If work is blocked on an unreliable or non-developer contributor (no published branch, or their work is wrong), take it over: cancel/supersede their ticket with a comment linking the new ticket that solves it, and fold the work into the plan.

## Open every plan with the user-journey TLDR

The first thing in any plan, ticket or PR body is the user-journey block: what the user does and
sees, from the moment the feature becomes reachable to the moment they get the result. It goes ABOVE
the technical detail, always, not only when it is asked for.

The format is owned by `~/.claude/references/tldr-report-formats.md` § "Block 1 · User journey" —
read it there. It is what makes a proposal judgeable before it is built: a plan described in
components reads as fine right up until someone tries to use it.

## Re-check the plan against the original source material, twice

Requirements leak out of a plan quietly. Across three revisions an acceptance criterion nobody
explicitly dropped is simply no longer in the document, and the plan still reads complete.

- **Keep the source material to hand for the whole task** — the tickets as written, and the original
  request. Not a summary of them; re-read the originals.
- **Before proposing any plan, go through it against every source item** and account for each one:
  carried in, deliberately dropped (say who decided that and when), or superseded. Anything with no
  verdict is a dropped requirement, not an omission.
- **Run that check again after every revision.** Revisions are where things fall out, and the later
  the revision the less anyone remembers what the original asked for.

## A pre-existing ticket is a claim about the past — verify it against today's code

An older ticket, spec or plan was written against the codebase as it stood then. Some of it has since
been built, some has been made irrelevant by other work, and some was always wrong.

- **Read the real code for each one before scheduling it**, and give a verdict per ticket: still
  needed as written · partly done (say which part) · already solved elsewhere · obsolete.
- **Say what changed** that makes an obsolete one obsolete. A verdict with no evidence is a guess,
  and the guess is what reintroduces work someone already deleted.
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

## The intent ledger — the record of what was asked, and whether it got built

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
- `reconcile` — at hand-back, on substantive or multi-step work. One verdict per recorded ask, in
  ledger order, each tagged with its source, so a skipped ask reads as a gap rather than an absence
  and no single source can fall out unnoticed.

**Ratified or it is not a baseline.** The hook writes the file in every worktree from the first
prompt, so its existence proves nothing and a bare prompt log is not a baseline. A verbatim ask is
what was WANTED; a baseline is what was AGREED. An unratified ask carries his words and reads as
authority, which is exactly why it may never become a criterion, a test, or a gap to close. It is
material for the reconciliation and, if still undone, a proposal in the questions block.

**Two shortfalls, two different homes.** An ask that was ratified and not built is a Not-met
criterion and is closed the way any gap is, by
`/sk:ship-report-and-ensure-correct-user-system-journey`. An ask that never reached the ledger, or a
ledger nothing consulted, is a config fault: propose the durable fix and ask, per
`rules/self-healing-config.md`. Never route the first into a config change or the second into code.

**Promotion before teardown.** The worktree is disposable and the ledger dies with it by design, so
what only it holds is promoted out first: the reconciliation and the plan-vs-sources delta go to the
tickets in `sources` (each source's verdicts on its own ticket, anything cross-cutting on the primary
with the rest linked), or to the PR body when there are no tickets, with anything still open filed as
a follow-up. **The verbatim prompts are never promoted.** They may carry pasted credentials, and the
session transcript already holds them outside the worktree, so copying them into a pushed artifact
adds a leak path and no information.

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
