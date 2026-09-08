---
name: ship-review
description: Unified pre-PR review using independent subscription-backed code review passes and a user-journey pass. Preserve the selected Full Claude or Full Astra setup; never use API-billed reviewers. Find dead ends, missing states and unreachable steps before shipping. Use for "code review", "review my changes", "walk the whole flow", "walk through this as a user", "pre-ship UX pass". Judges work that EXISTS; whether it should be built at all is /sk:work-does-this-make-sense-to-build.
argument-hint: [optional focus, e.g. "the billing changes" or "journey" to run the journey pass alone]
---

Run Simon's unified pre-PR review: combine independent subscription-backed passes, walk
the change as a real user, and STRICTLY respect work/personal resource isolation.

**Running the journey pass alone.** Steps 1–5 are the code review; Step 6 is the
user-journey pass. When the ask is only "walk this as a user" (no code review wanted), run Step 6 on
its own and say that is what you did — don't spend the model passes to get there.

## Step 1 — Detect context (required)
- Repo origin: !`git remote get-url origin 2>/dev/null || echo "(no git remote)"`
- Diff scope: !`base=$(git merge-base origin/master HEAD 2>/dev/null || git merge-base origin/main HEAD 2>/dev/null || echo HEAD~1); git diff --stat "$base"...HEAD 2>/dev/null | tail -1`

Rule: if the origin matches your work org (workOrgMatch in your identity overlay) → **WORK** repo. Otherwise → **PERSONAL** repo.
Before reviewing, state in one line the detected context and exactly which reviewers/resources you will use.

## Step 2 — Run the reviewers for that context

**Cover the WHOLE diff — every changed file, not a risk-weighted subset.** Feed the reviewers the
entire diff from Step 1, tests and UI and docs included. When it is too large for one model call,
PARTITION it so every file is covered by some reviewer (fan out across parallel passes — `/sk:work-superspeed`
slices each owning a share of the files is one clean cut), never sample down to the "high-risk" files
and read the rest by hand or not at all. TEST: the file set handed to the reviewers equals the diff's
file list; state "reviewed N of N changed files" in the report, and treat any changed file no reviewer
saw as a coverage gap and a finding. (The failure this prevents: sending only the backend/money source
files of a large diff to the models while the UI, tests and docs go unreviewed.)

### Subscription reviewers, in either project boundary

Read `references/parallelization.md` and preserve the workflow's selected setup. Codex billing follows
`references/agent-hosts.md`; the same existing ChatGPT subscription serves work and personal reviews.
Project databases, cloud accounts and other service credentials still follow Step 1's boundary.

1. Run a fresh correctness/security pass over the complete diff using the selected subscription model.
   Full Astra uses `~/.claude/bin/codex-launch.py -m gpt-6-astra --sandbox read-only review --base <base-ref>`.
   Full Claude uses fresh Claude reviewers on the existing subscription, with model tiers from the
   saved workflow. Check the active authentication method before starting a headless Claude reviewer.
2. Run a separate fresh adversarial pass on the first pass's top findings using the same setup.
   For Astra, use `~/.claude/bin/codex-launch.py -p "<findings and diff review brief>" --sandbox read-only`.
   Verify every finding against the source before accepting it.
3. If subscription authentication, quota or the selected model is unavailable, stop and report it.
   Never switch to API keys, pal or direct paid model APIs. Reviews have no API-billing exception.

## Step 3 — Synthesize one report
Merge all reviewers into a single DEDUPLICATED, severity-ranked report (CRITICAL / HIGH / MEDIUM / LOW).
For each finding, tag which review pass raised or confirmed it (correctness, security, adversarial).
Prioritize independently confirmed findings. End with a clear SHIP / DON'T-SHIP verdict and the top 3 must-fix items.

## Step 4 — Verify findings against REAL production data, then fix

Reviewer findings are hypotheses, not facts — models routinely assert chains that don't hold in
the real system (wrong campaign types, dead code paths, shapes that never occur). Before fixing
anything from Step 3, verify each finding empirically:

1. **Verify with read-only calls to real prod data.** For each finding, identify its load-bearing
   factual claim (a doc shape exists, a config value is set, a code path fires, a cohort is
   non-empty) and test it against production:
   - WORK (your work org): prod Firestore via the REST API — `runQuery`/`runAggregationQuery` with
     `curl -H "Authorization: Bearer $(gcloud auth print-access-token --account=<your-work-email>)"`
     against `projects/<your-work-project>/...`. **Never** run `gcloud config set` / `firebase login:use` — the
     globally-active account may be the personal one; scope EVERY call with per-command
     `--account`/`--project` flags. Cloud Logging via the google-observability MCP where log
     evidence is needed. Get the exact collection names from the code (`Firestore.ts`
     `collections`), never guess.
   - PERSONAL: the project's own prod resources only (e.g. a personal project via its documented
     account) — never work-org data, and vice versa.
   - **READS ONLY.** No prod writes, backfills, or config flips without explicit approval.
     Aggregation counts before document dumps; `select` projections to keep payloads small; never
     dump PII into the transcript (ids and counts, not phone numbers/emails).
2. **Classify each finding** with the evidence attached:
   - **VERIFIED** — the claimed shape/chain exists in prod (cite the query + counts/doc ids).
   - **LATENT** — code-reachable but zero prod incidence (cite the denominators, e.g. "0 stuck
     docs across 370 misses"). Fix only when the fix is cheap, surgical, and matches product
     intent; say why.
   - **REFUTED** — prod contradicts the claim (e.g. the field is `null` not `false`, the campaign
     type breaks the chain). Do NOT fix; record the refuting evidence in the report so the
     finding doesn't resurface next review.
3. **Fix everything VERIFIED (and justified LATENT).** One logical fix per commit, each with a
   test that fails against the unfixed code (mutation-check when cheap); run the affected
   suites + scoped tsc before each commit. Pure product/ops decisions (semantics changes,
   new kill-switches, spec changes) are NOT auto-fixed — present them with the prod evidence
   and a recommendation instead.
4. **Close the loop.** Final report gains a per-finding verdict column
   (VERIFIED-FIXED @commit / LATENT-FIXED @commit / REFUTED + evidence / DECISION-NEEDED) and an
   updated SHIP verdict.

## Step 5 — Ensure every behavioral pathway has an E2E test, then exercise it

Reviewers read the diff; they don't run it. Before the SHIP verdict, confirm an end-to-end test
actually EXISTS for every pathway the change creates — not just the happy path, but each branch
produced by a setting or toggle that changes the feature's behavior (codebase example: an
annual-offer on/off switch, or a different offer percentage, altering a generated link). List the
interacting settings and their states; for each combination that changes the outcome: if an E2E
test already covers it, run it; if none exists, WRITE one (a test that fails without the change),
and drive the pathway live where that adds confidence. Absent E2E coverage is itself a finding to
fix before signing off — a branch with no test that no one exercised is not "reviewed."

## Step 6 — Walk it as a first-time user

Read **`~/.claude/references/user-journey-review.md`** and run its method against this change. That
catalog is the sole owner of the journey method; don't restate it here.

Run this pass whenever the change touches anything a person meets — a screen, a flow, a message, an
email or SMS, a CLI a human types. Skip it only for a change with no human-facing surface at all
(an internal refactor, a build script), and say you skipped it and why.

Why it is a separate step from everything above: the reviewers judge the diff, and a diff can be
correct in every line while the flow it produces has no empty state, no way back, or a step that
assumes setup the user was never offered. Those defects are invisible to a code reviewer and obvious
to the person using it.

Fold its findings into the same severity-ranked report, tagged `journey`, and let them count toward
the SHIP verdict — a dead end or a silent failure is a blocker, not a polish item.

Extra focus for this run (if any): $ARGUMENTS
