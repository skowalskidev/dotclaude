---
name: ship-check-merge-readiness
description: Check that a PR (and its stack + every open PR it needs/influences) will merge onto CURRENT master and work together as one assembled end state — rebase onto up-to-date master, close every in-scope gap so it lands harmoniously, and for anything owned by ANOTHER PR/person, keep it in that owner's scope (a ticket + a comment + an explicit BLOCKING line in this PR's Deploy TLDR) rather than doing it unilaterally. Use for "is this ready to merge", "make these land together with master", "check merge readiness", "assemble the open PRs", "is it ready to ship to prod as-is", or before flipping a stacked PR to ready.
---

# Check merge readiness — assemble onto current master, own only your scope

The failure this prevents: a PR that is green in isolation but does not compose. It branched
off an old master, a sibling PR merged the engine it depends on, and once both land they
disagree — or it silently needs a change in someone else's PR that nobody tracked. "My tests
pass" is not "the assembled system works."

The end state you are checking for: **every open or draft PR involved, once merged onto today's
master, works together — nothing missing, nothing double-owned, and every cross-owner gap is tracked
and flagged as blocking.**

## Step 1 — Establish the real current state (never trust the branch in isolation)

- `git fetch origin` and resolve **current** master (`git rev-parse origin/master`). The PR's
  own merge-base is usually stale; that staleness is the whole problem.
- List the PR, its stack (base chain), and **every open OR DRAFT PR it needs, depends on, or
  influences** — the ones that touch the same subsystem, the same hot files, or a contract it
  consumes. A draft sibling still lands and can conflict, so it counts in the assembled end state
  (`gh pr list` includes drafts). Plus read the PR's own "Coordination"/"depends on" notes and the ticket.
- For each, record: merged-or-open, what it changed, and whether it is on master yet.

## Step 2 — Draft the PR, then rebase onto up-to-date master, resolve for correctness

- **Draft it before you touch it.** The moment you start reshaping a PR — rebasing, editing the
  body, re-implementing onto master — convert it (and every PR in the stack you will touch) to
  **draft**: `gh pr ready --undo <number>`. A PR mid-assembly is NOT open for review; drafting makes
  that unmistakable and stops a reviewer approving a half-updated diff. It goes back to ready only in
  Step 5, once the assembly holds and every blocking dependency is tracked. If it was already draft,
  leave it and note so.
- Rebase the stack onto current master (`--update-refs` for a stack). Tag restore points first;
  a half-finished rebase is the worst mid-state. When a later fix lands on a BASE branch, restacking
  the branches above it is clean if the edits sit on different lines — verify the rebase kept BOTH
  intents (the base fix and each upper branch's own changes).
- Resolve every conflict for **behaviour**, not just to make it apply: when your change and a
  merged sibling touched the same function, keep BOTH intents (e.g. your guard + their assert),
  never pick one side blindly.
- After the rebase the code has changed — **re-verify any earlier finding/verdict against the
  post-rebase code.** A verdict cited against the old tree can name a commit that is not even on
  this branch.
- **Review the ENTIRE assembled diff, exhaustively — every changed file against current master, not
  a sample and not only the files that conflicted.** Take the full `git diff origin/master...HEAD`
  (the whole set, every hunk) and read it the way `/sk:ship-review` reads a change, because the
  failure this skill exists to catch hides in the files that did NOT conflict: a rebase can drop a
  hunk, leave a file half-migrated, strip an import only a re-implemented sibling still needed, or
  keep a call site pointed at a symbol another PR renamed — and none of that surfaces if you only
  re-read the conflict set. A green audit over a sampled or conflict-only diff is precisely the
  incomplete pass `/sk:ship-review` had to be corrected for; do not reproduce it here. For a large
  diff, fan out per `references/parallelization.md` (a reviewer per subsystem or file group) so
  "exhaustive" scales instead of being quietly narrowed to what one pass had time for.

## Step 3 — Split every gap by OWNERSHIP

For each thing needed for the assembled end state to work, decide who owns it:

- **In THIS PR's scope** → make the change here so it assembles. Do it.
- **Owned by another PR / another person** → do NOT complete it unilaterally. Keep it in the
  owner's scope:
  1. **File a ticket** for the missing part, assigned to the owner, `blocks` this PR, in the
     same project. State the gap precisely, verified against real code, with what the owner
     must provide (the contract/signal), and what THIS PR still owns.
  2. **Comment** on the PR/thread, @-mention the owner, link the ticket, state the alignment
     decision and the ownership split.
  3. **Flag it BLOCKING in this PR's Deploy TLDR** — an unmissable line naming the blocking
     ticket, what breaks if it is relied on before the dependency lands, and the safe interim
     behaviour. Edit the body safely: fetch it, insert programmatically, assert the body grew
     and every existing section survived, then write back. Never reconstruct a PR body.

  TEST: a reader of the Deploy TLDR alone knows this PR cannot fully function until ticket X
  lands, and X is assigned to its owner, not silently carried here.

## Step 4 — Make the deploy order the assembly

Rewrite the Deploy TLDR so someone can land the whole set correctly from it alone: the merge
order of the stack + sibling PRs, the cross-repo/companion order, build prerequisites, the
per-artifact deploy command, index-before-functions, and the blocking dependencies from Step 3.
Follow `/sk:ship-pr` for the block's shape.

**State merge-in-isolation safety explicitly, per PR — this is the point of the whole skill.** The
deploy order alone is not enough: whoever merges ONE PR needs to know, from its Deploy TLDR alone,
whether doing so is safe. For each PR in the set the TLDR must say plainly one of:

- **Safe to merge alone** — it stands up in isolation, nothing else has to land with it.
- **Must merge with / after #N** — name the sibling(s) and the order, AND say **what breaks if it
  merges by itself**: a runtime error, a half-migrated schema, a feature that silently no-ops, a
  call site pointed at a symbol only a sibling PR adds, an index that must precede the functions
  that query it, a contract one side ships and the other consumes.

The failure this exists to prevent: a PR merges green in isolation, and only in production does it
emerge that a sibling PR was supposed to land too, or first, or that this one alone left the system
worse than before. If merging THIS PR by itself is detrimental in ANY way, that is a BLOCKING line
at the top of the TLDR, never a footnote — and if the missing piece is owned by another PR, it is
already a Step 3 cross-owner ticket + blocking flag, so the two stay consistent.

TEST: a reader who merges only this PR, reading only its Deploy TLDR, cannot be surprised in
production — either it was genuinely safe alone, or the TLDR told them exactly what else had to
land, in what order, and what would have broken otherwise.

## Step 5 — Prove the assembly, then hand back

- Build + all suites + the repo's static gate on the rebased tip. Re-run the journey/verify pass
  if the PR carries one; a rebase can re-introduce a defect a sibling already fixed.
- Confirm the exhaustive full-diff review from Step 2 actually covered EVERY changed file, and where
  the project has a full-repo static scan (not only a diff-scoped/new-only gate) run THAT too — the
  new-only gate's blind spot is exactly the orphaned or half-migrated file a rebase leaves in a diff
  it never touched, which is the defect class this skill exists to prevent.
- Report: is-it-ready per PR, the assembled deploy order, every cross-owner ticket filed with its
  blocking flag, and anything still open that only the human can settle. Flip to ready only when
  the assembly holds and every blocking dependency is tracked.
- **Three execution traps quietly break the proof — check each.** (1) A PR stacked on a non-default
  branch has its heavy CI jobs SKIPPED (only the PR targeting the default branch runs the full suite);
  skipped ≠ passed, so verify the stacked branches LOCALLY (build + suites + static gate). (2) A gate
  fix can INTRODUCE a new finding — extracting a helper to cut complexity creates a duplication finding,
  a test's alias-path mock string trips an unlisted-dependency check — so re-run the static gate after
  EACH fix and iterate to clean, one fix is not the end. (3) A pre-push hook can fail on an unrelated
  missing local tool (a linter binary nobody installed) and block every push; run the one gate that
  matters manually, push `--no-verify`, and flag the environment gap.

## Step 6 — Drive every open thread to a decisive ship-ready verdict

The assembly holding is not the end; resolving every open review thread and stating whether it
actually ships is. This is where a run rots into turn-after-turn scope questions when there is no
framework — so there is one.

**Resolve EVERY open review thread — never hand the human a list to chase.** For each:

1. **Verify the claim against the CURRENT code, never the plan or a prior verdict.** Saved-plan
   labels and even sub-agent verdicts are wrong often enough to bite: on the run that wrote this step
   two "refuted" comments were real bugs (a missing composite index that fails a query at runtime; a
   tax-inclusive money basis). Read the code the comment points at before trusting any label on it.
   Independent threads → fan out one verify agent per thread (`references/parallelization.md`); that
   parallelism is what makes an exhaustive re-verify affordable.
2. **Classify on the bar, act on it, never leave it an open "your call":**
   - **fix-here** — a real practical gap, or a serious-if-rare money/data bug, AND the fix is small +
     safe. Do it, re-run the gate (a fix can introduce a NEW finding — see Step 5), commit.
   - **refute** — not a real gap (cosmetic, dormant, or already handled on the branch). Reply with the
     CODE reasoning (file:line, the actual logic), resolve.
   - **follow-up** — real but LATENT (does not break the common path in today's prod) or a multi-site
     change unsafe to rush. File a ticket with the precise fix + why-deferred, reply with the link,
     resolve.

**Then state ONE ship-ready verdict and stop.** Split the two halves a bare "yes/no" collapses:
- **Code** — complete, green, every thread resolved; or exactly what is not.
- **Deploy** — the HUMAN-only steps no code can do and that silently break it if skipped: the stack
  merge order, a manual provider/dashboard/config step that leaves the feature INERT when missed (e.g.
  a webhook the collector depends on), index-before-functions — plus the known caveats (a blocking
  cross-owner ticket, the latent follow-ups). Simon's target end state is "ship-to-prod-as-is": say
  plainly the code is done and give the exact deploy sequence + the human steps.

**Do NOT re-litigate scope with the human turn after turn.** The bar above IS the decision — apply it
and present the verdict once. Flip-flopping a recommendation, or repeatedly asking "do X or defer?",
is the failure this step replaces. TEST: the human never has to ask "so is it ready to ship as-is?" —
the verdict already answered it.

## Rules

- **Own your scope, track the rest.** The point is not to do everyone's work — it is to leave
  nothing untracked. A cross-owner gap with no ticket + no blocking flag is the defect this skill
  exists to prevent.
- **Safe to run concurrently, one run per branch.** When several ship-check runs execute at once
  (Simon runs `/sk:ship-full-detailed-workflow` across many branches), each OWNS ONLY ITS OWN branch —
  never edit, rebase, commit to, or push a sibling branch. A fix that belongs to another PR is a
  ticket + a comment + a BLOCKING TLDR line on THAT PR, never a commit on its branch. That is what
  lets N runs coexist without clobbering each other.
- **A ship-check run itself triggers self-healing** (`rules/self-healing-config.md`): fold any new
  pitfall this run surfaced back into this skill via `/sk:claude-config-update` before handing back.
- **Read the other side's real code**, not the types on this side, before asserting a contract
  holds or a dependency is satisfied (`rules/process.md` cross-repo rule).
- **Never weaken to get green** — no skipped gate, no baseline rewrite, no "we'll fix it after
  merge" without a filed blocking ticket.
