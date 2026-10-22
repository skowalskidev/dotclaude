---
name: meta-report-standup-weekly
description: Write the short spoken weekly standup report Simon reads aloud. Gathers the full weekly window mechanically from git commits, GitHub PRs and Linear tickets, collapses them into outcomes, and emits punchy This week or Last week / Today / Next bullets. Use for "standup report", "write my standup", "monday morning standup", "what did I do last week", or the weekly summary of work done.
argument-hint: [optional window, e.g. "since Friday" or "2026-08-03..2026-08-10"]
---

# Standup report — spoken, punchy, mechanically sourced

The output is a **script to read out loud in about 45 seconds**, not a document. If a line sounds
written, it is wrong.

Two failure modes this skill exists to prevent, in order of how often they happen:

1. **Asking Simon what he did.** Everything is in git, `gh` and Linear. Asking wastes the one thing
   he is short of on a Monday morning.
2. **Reading out commits.** Eighty commits become twelve bullets. Nobody in the room wants the log.

## 1. Fix the window, and say what you fixed it to

Take today's date from the session context. Never shell out for it.

- **DO default to a weekly window in the session's timezone:** on Monday, use the previous
  Monday 00:00 through now; Tuesday through Sunday, use this week's Monday 00:00 through now.
- **DO honor an explicit window** ("since Friday", "last week", a date range) instead. "Last week"
  means the previous calendar week, Monday 00:00 to this Monday 00:00, excluding the end boundary.
- **DO state the exact date range in one line before the report.** Keep the same start and end
  across git, GitHub and Linear; retrieve every page needed to cover it.
- **DON'T shorten a weekly report to the previous working day.** For example, a Thursday default
  includes Monday through Thursday, not just Wednesday and Thursday.
  TEST: Monday covers the preceding week; every other day starts this Monday; an explicit range wins.

## 2. Gather from three sources, in parallel, never from him

Run all three in one batch. Each is cheap and they do not depend on each other.

**Commits.** Simon runs several Conductor worktrees off one object store, so `--all` from any
worktree sees every branch he touched:

```bash
git log --all --author="$(git config user.email)" --since=<start> \
  --date=short --pretty='%ad %h %s'
```

Resolve the author from `git config user.email`, falling back to `user.name` or the GitHub
username. **An empty result almost always means the author filter missed, not that he did
nothing** — verify against `git log --all --since=<start> --pretty='%an' | sort -u` before
believing a quiet week.

**Pull requests.** State and merge date are what separate "shipped" from "in flight":

```bash
gh pr list --repo <owner/repo> --author @me --state all --limit 40 \
  --json number,title,state,createdAt,mergedAt,isDraft,headRefName,updatedAt \
  --jq '.[] | select(.updatedAt > "<start>")'
```

**Linear.** `list_issues` for issues assigned to him and updated in the window. Use it for ticket
**titles and statuses**, so a bullet can say what the work was for instead of quoting an ID.

If a source comes back empty or unauthenticated, say so in one line. A silently dropped source
reads as "nothing happened there".

## 3. Collapse commits into outcomes

This step is the whole value of the skill.

- **Group by PR or ticket first.** Then ask each group one question: *what can a customer or a
  colleague now do that they could not before?* That answer is the bullet.
- **One bullet per outcome, never per commit.** The feature commit, its refactor, its tests, its
  docs and the formatting pass are one bullet or they are nothing.
- **Drop entirely:** merges, formatting, static-analysis cleanups, test-only and docs-only commits,
  and internal refactors with no visible effect.
- **Keep a bug fix only if someone in the room would care.** "Stopped double-texting customers" is
  a bullet. "Fixed a null check" is not.

## 4. Write it in this shape, always

Three headings, in this order. Only the date-range line precedes them; no closing summary.

**This week** (use **Last week** for the Monday default or an explicit previous week, and the date
range for other windows) — outcomes only, and honestly tagged. Say "shipped" or "merged" only when
the PR has a non-null `mergedAt` inside the reporting window. Draft work belongs under Today or Next.

**Today** — the ticket you are on, then the two or three concrete things already done this morning.

**Next** — the single next step, then blockers, or the words "no blockers" said out loud. Silence
about blockers reads as hiding one.

Voice rules, all of them load-bearing:

- **One breath per bullet.** Roughly twelve words. If it needs a "and then", split it in two.
- **Lead with the verb and the outcome.** "Recovery texts now work both ways" beats "Implemented
  inbound SMS handling".
- **Plain nouns a non-engineer understands.** No class names, no file paths, no ticket IDs unless
  the team genuinely speaks in them.
- **`rules/copy-quality.md` applies in full.** No em dashes, none of the banned vocabulary. Written
  phrasing is audible.
- **Fifteen bullets is the ceiling.** Past that it stops being a standup.

## 5. Check it before handing it over

- Every "shipped" traces to a merged PR. A draft is not a ship.
- Nothing in the report that no commit, PR or ticket backs.
- Blockers stated, or explicitly none.
- **Stale draft PRs are not read out.** Open and untouched for over a week is parked, not progress.
  Offer them as one separate line he can use if someone asks.

## What this skill does not do

- It does not post anywhere. It hands back a script.
- It does not judge the work. `/sk:ship-report-and-ensure-correct-user-system-journey` reports one
  change against its plan; this reports a person's week to a room.
