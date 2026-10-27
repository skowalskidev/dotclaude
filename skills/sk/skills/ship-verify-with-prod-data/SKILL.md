---
name: ship-verify-with-prod-data
description: Verify production compatibility before shipping changes to data figures or runtime admission, rate limits, request validation, authorization and retention migrations whose eligibility depends on stored data or usage, even with no displayed figure. Read prod read-only, cover current legitimate cohorts, replay actual client payloads locally and report measured headroom and unknown telemetry. Use for "verify against prod data", "check it works for all accounts with real data", "make sure this will not regress on production", "look at recent data from all accounts", "does this add up across accounts", "check runtime limits against legitimate production usage", "verify request validation accepts actual client payloads", or "check authorization after retention migration". Scope conclusions to verified evidence; preserve production write and spend approvals.
argument-hint: "[optional: the surface / route / account list to verify]"
---

# Verify production compatibility before shipping

DO verify changed figures and runtime eligibility against real production evidence. Apply the shared
procedure below; fixtures alone do not establish compatibility with current legitimate users.

It composes, and does not restate:
- **`~/.claude/rules/connectors.md`** — the read-only prod path, the auth-gate protocol, the
  work/personal boundary. Prod is READ-ONLY; a prod WRITE needs Simon's per-write go-ahead.
- **`/sk:ship-screenshot-changes`** — the capture + PR post (Phase 6 hands off to it).
- **`/sk:ship-report-and-ensure-correct-user-system-journey`** — the acceptance-criteria verdicts this
  feeds a real-data verdict into.

## Phase 1 · Decide whether it applies

Read `~/.claude/references/testing-strategy.md` sections **Production compatibility gates**,
**Production source fidelity** and **Prepare derived state before capture**.
Apply the compatibility procedure for every changed data figure or runtime eligibility decision.
For runtime gates with no figures, use that procedure through hand-back; the figure/recompute phases
below apply only to data surfaces. Record N/A only with the traced absence of a stored-data or usage
dependency, never because no figure is displayed.
TEST: admission, validation, authorization and retention changes receive an applicability verdict.

## Phase 2 · Enumerate EVERY account the surface serves — from the SSOT list

**DO find the authoritative list of every account/tenant/owner/entity the surface covers, and verify
them ALL; report unknown or excluded accounts explicitly.** Get the list from the surface's own
enumeration source (the same list the writer iterates), never a hand-picked account.
**DON'T verify a single account (yours) and call it correct** — the account you know is the one least
likely to expose the shape that breaks.
**DO rank the set by RECENT activity** (last-updated, recent recoveries/rows) and cover every account
with recent data first, so the accounts that matter are checked, not just the loudest.
TEST: the count of accounts checked equals the count in the surface's enumeration source (or you name
which you skipped and why, e.g. zero recent data). e.g. a sweep that enumerated only one billing rail
left every account on the other rail unverified and reading `$0`.

## Phase 3 · Read prod read-only and RECOMPUTE the surface per account

Apply the shared source-read and preview-data procedures named in Phase 1.
Recompute each figure under the NEW code for every account selected above. When several figures must
agree, derive each independently and verify they resolve to one source/predicate and the same value.
Use saved export files for large reads so transcript truncation cannot change the arithmetic.
TEST: for each checked account, the figures reconcile (or you have a named discrepancy carried to
Phase 4). e.g. a hero total, a members count and a funnel's last stage all reduce to the same
net-recovered cohort count.

**DO date-stamp every record a finding rests on, and reason from the RECENT/live cohort — not from
whatever the query surfaced first.** An oldest-first or unordered scan can overrepresent historical
shapes; inspect current dependencies before treating them as legacy residue. Order
by recency (or bucket the population by created/updated date) and check whether the RECENT cohort
reproduces the discrepancy or still depends on the historical records before classifying it.
TEST: every finding records available created/updated dates and missing-date gaps, and states its
current cohort or dependency. (the fix for flagging ~10 months-stale records as a live edge when every
recent record was classified correctly.)

## Phase 4 · Classify each discrepancy — code bug vs deploy/data-skew vs legacy residue

**DO decide, for every discrepancy, whether it is a CODE bug or a DEPLOY/DATA-SKEW** — the fixes are
opposite. A code bug: the new logic computes the wrong thing on well-formed data → fix the code at the
root. A skew: prod data lacks a field or shape the new code reads because the WRITER hasn't been
redeployed/re-run yet → not a code defect, a recompute dependency.
**DON'T introduce an infra/DB/schema change until you've confirmed one is actually needed** — verify
the field is genuinely absent on real docs (not just unread), and that the new writer will populate it
on its next run, before writing a migration. Changing data is hard to reverse; changing code isn't.
**DO label a discrepancy LEGACY RESIDUE only after proving no current legitimate journey depends on
those stale/superseded records.** Apply the shared compatibility procedure when retention has removed
fields or records that a new gate requires. Age alone cannot clear a regression. Use UNKNOWN when the
necessary activity or dependency evidence is missing; carry it as an unverified gap.
TEST: each discrepancy is bug / skew / legacy / unknown with dated evidence; a legacy verdict proves
no current dependency, and a migration is proposed only after confirming the missing source fields.

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

Report the checked population and window, figures or gates exercised, discrepancies and unknowns.
Apply the shared compatibility procedure's separate code, activation and live-proof verdicts. Carry
deploy/backfill dependencies into the PR's Deploy-TLDR (`/sk:ship-pr`).
