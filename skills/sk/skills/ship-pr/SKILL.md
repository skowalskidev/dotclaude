---
name: ship-pr
description: Simon's PR-authoring standard — every PR body STARTS with a before/after TLDR and a Do line, then a human-readable Deploy TLDR (imperative, do-only numbered steps covering cross-repo order, build prerequisites, deploy commands, and the post-deploy smoke). Apply whenever creating a PR or finalizing one for review, in any repo.
argument-hint: [optional PR number or "draft body" context]
---

# Simon's PR standard — TLDR, then Deploy TLDR

Whenever you create a PR, or finalize/flip one to ready-for-review, the body must START
with `## TLDR` (shape and TEST: `~/.claude/references/tldr-report-formats.md` § Before/after TLDR),
then the deployment TLDR, before any template sections.

## The Deploy TLDR block

- Heading: `## 🚀 Deploy TLDR`, as the first content after `## TLDR`.
- Human-readable numbered steps in the imperative mood.
- **Only what to DO.** Never what not to do — no warnings or prohibitions in this block. If a
  hazard genuinely must be recorded, it goes in Dev Notes, not the TLDR.
- **DO give every step that changes production four parts:** its order number, a `Check:` line
  (the precondition and its expected result, e.g. "the provider shows the registration approved"),
  a `Smoke:` line (the post-step check and its expected result, read-only, run on production after deploy per `references/git-pr-deploy.md` § Prod check after every production deploy), and a `Rollback:` line (the command
  or setting that restores the prior state). Rollback is an action to run, not a caveat. A step with
  no safe rollback says so on its `Rollback:` line. The content comes from
  `~/.claude/references/git-pr-deploy.md` § Deploy safety. TEST: every merge, deploy, migration
  and traffic-moving step carries all four parts.
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
- DO give every body section a visible `##` or `###` heading, named as in `SECTIONS` in
  `~/.claude/bin/pr-landing-gate.py` (the one home of the names), plus any other the repo's template
  adds. Run that checker on the fetched PR after every body write. DON'T wrap any section, table, image or
  video in a collapsed `<details>`, and convert one you find while editing the body; a reviewer reads
  a closed block as missing (the fix for screenshots that sat in a closed block and read as missing).
  TEST: the fetched PR `body_html` holds zero collapsed `<details>`: every `<details>` carries the
  `open` attribute (GitHub's own wrapper around an attached video is one).
- When adding either TLDR to an EXISTING PR: fetch the current body first, verify it is
  non-empty, prepend programmatically, and write back — preserving every existing
  section exactly.

## Rewrite the body when the PR changes

**DO rewrite every section in `SECTIONS` from the current diff, and re-shoot every screenshot,
journey clip and verification run against the current base, in the same push batch, unprompted,
whenever the PR's behaviour or base moves after its body was written:** requested changes land, a
base merge changes code the PR touches, a migration is renumbered, or scope moves. Re-derive each
section from `git diff <base>...<head>` and the code at the head, never from the old body. Re-shoot
under `references/screenshot-review.md` § Refresh after the follow-up batch.
**DON'T patch the few lines you remember changing.** Every untouched section is a current claim
about superseded code, and the reviewer cannot tell which lines are still true.
**DO keep the write safe; the rewrite covers OUR sections' content, never a blind overwrite:**
1. Fetch the body; STOP on an empty or suspiciously short fetch.
2. Keep exactly every section whose heading is outside `SECTIONS` and the repo template, and every
   line a reviewer added (`gh api graphql` on `pullRequest.userContentEdits` lists each editor).
3. Replace each of our sections in place by heading, then write the body.
4. Re-fetch, confirm every `SECTIONS` heading is present, and run `pr-landing-gate.py` again before
   recording the gate.
TEST: after the push, the Test matrix heading names the head sha (`## Test matrix (head <sha>)`),
every AFTER capture records that sha and every BEFORE the current base, zero sections describe
superseded behaviour, every reviewer-added line survives, and the gate ran on the re-fetched body
(the fix for a PR patched line by line across five rounds of requested changes and two base merges,
until a full rewrite and fresh screenshots had to be asked for).
