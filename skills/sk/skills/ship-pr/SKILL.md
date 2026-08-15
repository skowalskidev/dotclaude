---
name: ship-pr
description: Simon's PR-authoring standard — every PR body STARTS with a human-readable Deploy TLDR (imperative, do-only numbered steps covering cross-repo order, build prerequisites, deploy commands, and the post-deploy smoke). Apply whenever creating a PR or finalizing one for review, in any repo.
argument-hint: [optional PR number or "draft body" context]
---

# Simon's PR standard — Deploy TLDR first

Whenever you create a PR, or finalize/flip one to ready-for-review, the body must START
with a deployment TLDR, before any template sections.

## The Deploy TLDR block

- Heading: `## 🚀 Deploy TLDR`, as the very first content of the PR body.
- Human-readable numbered steps in the imperative mood.
- **Only what to DO.** Never what not to do — no warnings, no prohibitions, no rollback
  caveats in this block. If a hazard genuinely must be recorded, it goes in Dev Notes,
  not the TLDR.
- Cover, in this order, only the items the diff actually needs:
  1. Cross-repo merges/deploys and their order, linking companion PRs
     (e.g. "Merge and deploy your-work-org/some-service#NN first").
  2. Build prerequisites (codebase example: `cd packages/sdk && yarn build` before any
     API deploy when the SDK changed).
  3. The exact deploy command per changed artifact (codebase examples:
     `yarn fb:deploy:prod` when apps/serverless changed;
     `firebase deploy --only firestore` when indexes/rules changed;
     the app box `./update` (awb) for API + portal).
  4. Config/env/index/migration steps the diff introduced, as concrete commands. **Audit the
     diff for a CROSS-ACCOUNT data migration** — a collection or field the change consolidates,
     renames, or stops reading — and give it its own step with the strict order (migrate FIRST,
     deploy the code SECOND) and the blast radius named. The new code reads only the new shape, so
     every EXISTING account breaks until the backfill runs; and a shared-code reader (one call
     site several features go through) makes the reach WIDER than the feature that introduced it,
     not narrower — say which accounts and which features. TEST: grep the diff for an added
     `scripts/backfill-*` (or other migration) and for a deleted reader of an old collection;
     each must have a TLDR step ordered before the code deploy. (The fix for a knowledge-base
     consolidation whose backfill was missing from the TLDR, and whose company-name resolver runs
     on every recovery trigger, not only the new one.)
  5. A short post-deploy smoke: what to run or click, and the observable signal that
     confirms success (a log line, a UI state, a document field).
- Keep it to roughly 8 steps or fewer. The test: someone can deploy correctly from this
  block alone, without reading the rest of the PR.

## User journey TLDR, then System journey

Straight after the Deploy TLDR, every PR carries a **User journey** section and then a **System
journey** section. Both shapes are owned by `~/.claude/references/tldr-report-formats.md` (Blocks 1
and 2) — read them there rather than reinventing the format, and run its cross-check so the PR states
any mismatch between the two rather than leaving a reviewer to notice it.

A reviewer should be able to judge whether the feature makes sense for a real person from the user
journey alone, and whether the mechanism holds up from the system journey alone, without reading the
diff. `/sk:ship-report-and-ensure-correct-user-system-journey` builds the same two blocks for chat, so a PR and the report tell one story.

## Existing accounts — how the deploy affects them (human TLDR)

Any PR that changes behavior for existing accounts/users must include a short, human-readable
**Existing accounts** section (right after the Deploy TLDR) that answers, plainly, how they're
affected on deploy:
- **Activation model** — does the change apply automatically to every existing account on
  deploy, or must each account activate it, opt in, or re-open and re-save a setting for it to
  take effect? State which, in one line.
- **Interacting settings** — enumerate the settings/toggles that gate or change this behavior
  (codebase example: an annual-offer on/off switch, the offer-percentage) and whether existing
  accounts already sit in the state that makes the new behavior correct. Flag any that were
  missed or that a merchant must set before the change does what's intended.
- Who sees the change and WHEN — be honest about no-op accounts (nothing to see until they do X).

## The rest of the body

- Follow the repo's PULL_REQUEST_TEMPLATE.md and its committed CLAUDE.md GitHub rules
  (ticket-prefixed title from the Linear ticket, reviewer, labels, assignee).
- When adding the TLDR to an EXISTING PR: fetch the current body first, verify it is
  non-empty, prepend programmatically, and write back — preserving every existing
  section exactly.
