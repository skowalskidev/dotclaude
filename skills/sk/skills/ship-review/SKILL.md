---
name: ship-review
description: Unified pre-PR review — multi-model code review (gstack Claude + Codex everywhere; WORK adds pal Gemini + GPT-5, PERSONAL adds a pal-free personal-key Gemini pass; work/personal aware) plus a user-journey pass that walks the whole flow through in order as a first-time user, so a diff that reads fine but leaves a dead end, a missing empty/loading/error state, or a step nobody can reach is caught before it ships. Use for "code review", "review my changes", "walk the whole flow", "walk through this as a user", "pre-ship UX pass". Judges work that EXISTS; whether it should be built at all is /sk:work-does-this-make-sense-to-build.
argument-hint: [optional focus, e.g. "the billing changes" or "journey" to run the journey pass alone]
---

Run Simon's unified pre-PR review: combine the gstack review with the pal multi-model review, walk
the change as a real user, and STRICTLY respect work/personal resource isolation.

**Running the journey pass alone.** Steps 1–5 are the multi-model code review; Step 6 is the
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

### If WORK (your work org) — WORK resources only
1. **gstack**: invoke the gstack `/review` skill (Claude staff-engineer pass + its Codex adversarial pass, which now runs on the WORK OpenAI key via the `~/.codex-work` home — billed to your work org, not personal ChatGPT).
   - **Best Claude here = your session model.** pal has no Anthropic provider, so the Claude reviewer is whatever model this Claude Code session runs on — there is no way to pin it from the skill. Run `/review-all` on the strongest coding Claude: **Fable 5** or **Opus 4.8** (2026-07 SWE-bench Verified leaders — 95.0% / 88.6%). Don't run a review pass on a Haiku/small session.
   - The Codex adversarial pass uses `~/.codex-work`'s configured model — keep it on the current best OpenAI coding model (`gpt-5.6-sol`) to match the pal reviewer.
2. **pal multi-model**: call the pal `codereview` tool on the diff vs the merge-base **with the two strongest LIVE coding models** (work keys), critical/high severity. As of 2026-07-27: OpenAI **`gpt-5.6-sol`** (OpenAI's "best coding model yet", GA 2026-07-09) + Google **`gemini-3.1-pro-preview`** (Gemini 3.1 Pro) — both added to pal's registry 2026-07-27; `gemini-2.5-pro` is the known-live Gemini fallback.
   - **pal's registry gates model NAMES; the API key does not.** pal rejects any model absent from its `conf/<provider>_models.json` even though the raw key can call it. To add one: add an entry to `~/dev/tools/pal-mcp-server/conf/openai_models.json` (or the provider file) **and restart pal** (the registry loads at import — a running pal won't see the edit). Until pal restarts, call the new model directly via the work key: `curl https://api.openai.com/v1/chat/completions` with the key read inline from `~/dev/tools/pal-mcp-server/.env` (never printed), `reasoning_effort: high`, and **omit `max_completion_tokens` (or set it to the model's max)** — a low cap is spent on reasoning first and returns empty content with `finish_reason: length`.
   - **A registered name can still be DEAD — verify it's LIVE.** pal listed `gemini-3-pro-preview` but Google had retired it (404 NOT_FOUND). Probe any new model with a 1-token call before relying on it; keep `gemini-2.5-pro` as the known-live Google fallback.
   - **Gemini id note:** `gemini-3-pro-preview` was RETIRED (404); the live best is `gemini-3.1-pro-preview`. `work-resource-guard.sh` ALLOWS a direct `generativelanguage.googleapis.com` probe **when the key comes from `pal-mcp-server/.env`** (work key) — so to check for a newer Gemini, list live ids with `.../v1beta/models?pageSize=1000`, verify one with a 1-token `:generateContent` call, then register it in `conf/gemini_models.json` + restart pal.
   - **Keep current:** re-check `pal listmodels` + the vendors' newest GA model and bump when a stronger live model appears.
3. **adversarial**: call the pal `challenge` tool on your top 1–2 findings to confirm they're real (not false positives).
Do NOT use the personal ChatGPT/Codex CLI here.

### If PERSONAL — PERSONAL resources only
1. **gstack**: invoke the gstack `/review` skill (Claude pass).
2. **Gemini (pal-free, personal key)**: run the command below. It reads your personal key from `~/.config/personal-keys.env` **inline** — the key never becomes an ambient shell env var, so the WORK `pal` server can never pick it up. Present the output under a `GEMINI SAYS (personal key):` header. If the key is empty or the file is missing, skip this step and say so.
   ```bash
   PERSONAL_ENV="$HOME/.config/personal-keys.env"
   GKEY="$(grep -E '^GEMINI_API_KEY=.+' "$PERSONAL_ENV" 2>/dev/null | head -1 | cut -d= -f2- | tr -d '[:space:]')"
   if [ -n "$GKEY" ]; then
     BASE=$(git merge-base origin/master HEAD 2>/dev/null || git merge-base origin/main HEAD 2>/dev/null || echo HEAD~1)
     REQ=$(mktemp); RESP=$(mktemp)
     git diff "$BASE"...HEAD | jq -Rs --arg pre "You are a staff engineer doing a pre-PR code review. Report only CRITICAL and HIGH severity correctness, security, data-safety, and concurrency bugs in this diff. Be terse: severity, file:line, problem, one-line fix. If nothing critical, say so.\n\nDIFF:\n" '{contents:[{parts:[{text:($pre + .)}]}]}' > "$REQ"
     # Live-verified Gemini 3.1 Pro on the public API (gemini-3-pro-preview is RETIRED → 404). Bump when a newer pro is live-verified.
     curl -s "https://generativelanguage.googleapis.com/v1beta/models/gemini-3.1-pro-preview:generateContent" \
       -H "x-goog-api-key: $GKEY" -H "Content-Type: application/json" -d @"$REQ" > "$RESP"
     jq -r '.candidates[0].content.parts[0].text // ("Gemini error: " + (.error.message // "no response"))' "$RESP"
     rm -f "$REQ" "$RESP"; unset GKEY
   else
     echo "No personal Gemini key in ~/.config/personal-keys.env — skipping Gemini reviewer."
   fi
   ```
3. **adversarial**: invoke gstack `/codex challenge` (personal ChatGPT login — allowed here).
Do NOT call pal — it holds WORK keys and is blocked in personal repos by policy.

## Step 3 — Synthesize one report
Merge all reviewers into a single DEDUPLICATED, severity-ranked report (CRITICAL / HIGH / MEDIUM / LOW).
For each finding, tag which reviewer(s) raised it (e.g. "gstack+gemini agree", "gpt-5 only").
Prefer findings multiple models agree on. End with a clear SHIP / DON'T-SHIP verdict and the top 3 must-fix items.

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
