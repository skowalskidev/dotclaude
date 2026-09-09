---
name: ship-verify-with-prod-data
description: Before shipping a change to a data-facing surface — a dashboard, a report, a total, a count, a funnel, a chart, any figure whose job is to reflect stored data correctly — prove it renders correctly and will NOT regress against REAL production data, across EVERY prod account with recent data, not one. Reads prod READ-ONLY through the provisioned path, enumerates every account/tenant/entity the surface serves, recomputes what each figure would show under the new code, and confirms they cross-verify to one source. Distinguishes a real code bug from a deploy/data-skew (prod written by the old code), supplies a backfill or recompute the user runs on prod, and proves that backfill first on a seedable dev account. Use for "verify against prod data", "check it works for all accounts with real data", "make sure this won't regress on production", "look at recent data from all accounts", "does this add up across accounts", or before screenshotting a data surface. Reconciling three cards to one cohort is the SSOT check; capturing the screens is /sk:ship-screenshot-changes.
argument-hint: "[optional: the surface / route / account list to verify]"
---

# Verify a data surface against real production data — for ALL accounts, before shipping

A green test suite proves the code runs on fixtures. It does not prove the numbers are right on the
real data every account actually has. A money/data surface can pass every test and still read `$0`,
double-count, or disagree with itself on a live account whose data shape the fixtures never had. This
skill closes that gap: read prod read-only, recompute what the surface WOULD show for every account
with recent data, and confirm it reconciles before the change ships.

It composes, and does not restate:
- **`~/.claude/rules/connectors.md`** — the read-only prod path, the auth-gate protocol, the
  work/personal boundary. Prod is READ-ONLY; a prod WRITE needs Simon's per-write go-ahead.
- **`/sk:ship-screenshot-changes`** — the capture + PR post (Phase 6 hands off to it).
- **`/sk:ship-report-and-ensure-correct-user-system-journey`** — the acceptance-criteria verdicts this
  feeds a real-data verdict into.

## Phase 1 · Decide whether it applies

**DO run this when the diff changes how a surface READS, derives, reconciles, or enumerates stored
data** — a displayed total/count/rate, a funnel, a chart, a cross-surface reconciliation, or the list
of entities a sweep/report covers.
**DON'T run it for a pure-logic change with no data-shaped output** (a refactor, a copy tweak, a new
pure function with unit tests). Say it doesn't apply and stop.
TEST: name the exact figure(s) on the surface whose correctness depends on real per-account data. If
you can't, the skill doesn't apply.

## Phase 2 · Enumerate EVERY account the surface serves — from the SSOT list

**DO find the authoritative list of every account/tenant/owner/entity the surface covers, and verify
them ALL — a regression is only provable across the whole set, and "works for one" hides "broke the
other rail".** Get the list from the surface's own enumeration source (the same list the writer
iterates), never a hand-picked account.
**DON'T verify a single account (yours) and call it correct** — the account you know is the one least
likely to expose the shape that breaks.
**DO rank the set by RECENT activity** (last-updated, recent recoveries/rows) and cover every account
with recent data first, so the accounts that matter are checked, not just the loudest.
TEST: the count of accounts checked equals the count in the surface's enumeration source (or you name
which you skipped and why, e.g. zero recent data). e.g. a sweep that enumerated only one billing rail
left every account on the other rail unverified and reading `$0`.

## Phase 3 · Read prod read-only and RECOMPUTE the surface per account

Read `~/.claude/references/testing-strategy.md`, sections **Production source fidelity** and
**Prepare derived state before capture**, for the shared source-read and preview-data procedure.
Recompute each figure under the NEW code for every account selected above. When several figures must
agree, derive each independently and verify they resolve to one source/predicate and the same value.
Use saved export files for large reads so transcript truncation cannot change the arithmetic.
TEST: for each checked account, the figures reconcile (or you have a named discrepancy carried to
Phase 4). e.g. a hero total, a members count and a funnel's last stage all reduce to the same
net-recovered cohort count.

## Phase 4 · Classify each discrepancy — code bug vs deploy/data-skew

**DO decide, for every discrepancy, whether it is a CODE bug or a DEPLOY/DATA-SKEW** — the fixes are
opposite. A code bug: the new logic computes the wrong thing on well-formed data → fix the code at the
root. A skew: prod data lacks a field or shape the new code reads because the WRITER hasn't been
redeployed/re-run yet → not a code defect, a recompute dependency.
**DON'T introduce an infra/DB/schema change until you've confirmed one is actually needed** — verify
the field is genuinely absent on real docs (not just unread), and that the new writer will populate it
on its next run, before writing a migration. Changing data is hard to reverse; changing code isn't.
TEST: each discrepancy is labelled bug-or-skew with the evidence (the real doc that proves it), and a
schema/migration is proposed only after the field's absence on prod is confirmed.

## Phase 5 · Supply the backfill/recompute — the USER runs it on prod

**DO hand Simon the exact backfill or recompute command to run on prod, and the deploy order** — when
a skew needs the data rewritten, supply the script (the same one the scheduled writer uses, run
on-demand), not a description of it.
**DON'T run a prod write yourself** (`rules/connectors.md`: prod is read-only; a write needs his
per-write go-ahead).
**DO prove the backfill FIRST on a seedable dev account** — run the identical script against dev for a
representative account, then re-read (Phase 3) and confirm the surface now reconciles. A backfill
verified only in prose is unverified.
TEST: the dev account's surface reconciles after the dev recompute, and the prod steps are copy-paste
with a stated order (writer deploy → recompute → readers).

## Phase 6 · Before screenshots — name the data mode

Apply the shared **Prepare derived state before capture** procedure named above, then hand off to
`/sk:ship-screenshot-changes`. Confirm the captured figures match the named data mode; require a
verified recompute for post-refresh claims and report persisted-source deployment skew explicitly.

## Hand back

Report per account: the figures, whether they reconciled, and every discrepancy with its bug/skew
verdict. Lead with the one line that matters — "reconciles for all N accounts" or "account X regresses
because …". Carry the deploy/backfill dependency into the PR's Deploy-TLDR (`/sk:ship-pr`).
