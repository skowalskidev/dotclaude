---
name: ship-merge-batch
description: Merge several approved PRs into the default branch at once instead of one by one, so they pass CI once and deploy once, with their migrations applied together in number order. Uses the repo's merge queue when one is enabled; otherwise builds one batch PR that merge-commits each PR head, waits for one green run, merges once, watches the one deploy, runs the post-deploy smokes, and confirms every original PR shows merged. Never merges a PR Simon did not name. Use for "merge these all at once", "bundle the PRs and deploy once", "batch merge these PRs", "stop merging each PR one by one", or when every merge puts the other open PRs behind main.
---

# Merge a batch of PRs once, deploy once

The method, the mechanism order and the settings options live in
`references/git-pr-deploy.md` § Merging several PRs at once. Read it first; this skill orders the run.

## Steps

1. **Fix the set.** List the PR numbers Simon named in chat. A PR he did not name stays out, even if
   it is green. Record his yes per PR in the living plan.
2. **Read the repo, change nothing.** The default-branch ruleset (`gh api repos/<o>/<r>/rulesets`,
   then each id), `mergeQueue` over GraphQL, `allowed_merge_methods`, and the deploy workflow's
   triggers and concurrency group. A wanted settings change goes to Simon as a decision.
3. **Gate each PR.** Not a draft, `mergeable` is `MERGEABLE`, every check in `statusCheckRollup` on
   the head sha is SUCCESS or SKIPPED. Drop a failing PR from the set and say which and why.
4. **Check numbered files** across the set, the base and every other open PR; renumber on the
   original branch, per the reference.
5. **Batch** through the merge queue or the batch PR, per the reference's order. Open the batch PR
   through `/sk:ship-pr`.
6. **Merge once.** Prefix the one `gh pr merge` with `CLAUDE_ALLOW_PR_MERGE=1`, only after step 1's
   yes covers every PR in the batch and the batch run is green. `hooks/git-commit-guard.py` blocks it
   otherwise.
7. **Watch the one deploy** to completion and run each PR's post-deploy smoke from its Deploy TLDR.
8. **Report**: the batch PR, the merge sha, the one deploy run and its duration, the migrations it
   applied, each original PR's state, each smoke result, and any PR dropped from the set.

## Rules

- One batch, one default-branch push. A second push mid-batch means start the count again.
- A red PR leaves the batch; it is never fixed on the batch branch.
- Apply `rules/spend-approval.md` to any smoke that costs money.

TEST: every merged PR traces to Simon's yes naming it, the report names exactly one deploy run, and
each original PR reads MERGED or carries the stated reason it does not.
