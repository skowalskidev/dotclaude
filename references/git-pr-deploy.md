# Git, PRs, integration, and deploy tracking

Reference catalog entry — load on demand. Source harness: `full-detailed-workflow`.

## ALWAYS write the commit message to a file. No exceptions, no length threshold.

`git commit -F <file>`, with the file written by the Write tool first. Never `-m`, never a heredoc,
regardless of how short the message looks.

The shell interprets both `-m "…"` and a heredoc body: backticks run as command substitution, `$VAR`
expands, braces and unmatched quotes break the parse. It fails SILENTLY — the commit succeeds with
the content missing, and you only notice on `git log`.

**This is a recidivism rule, not a style preference.** It happened twice, the rule was written, and
then it happened a THIRD time in the same session — on a message that felt too short to bother with,
which contained one backticked word. Every instance needed an `--amend`, and an amend after a push
needs `--force-with-lease`.

The trap is "this message is short enough to inline". There is no such message. Write the file.

## The shape of the message

`~/.claude/.githooks/commit-msg` enforces the subject line in the config repo and rejects anything
that fails it. Everywhere else the same standard applies without a hook to catch you.

**Subject:** `<type>(<scope>): <imperative description>`

- Types: `feat` `fix` `docs` `chore` `refactor` `test` `perf` `build` `ci` `style` `revert`.
- Scope is the area, lower-case: `rules`, `skills`, `connectors/firebase`, `api-routes`. Optional,
  but include it whenever the repo has more than one obvious area.
- Imperative and lower-case after the colon: "make ui-conventions load", not "Made" or "Makes".
- No trailing period. Under 72 characters, so `git log --oneline` stays scannable.
- `!` before the colon for a breaking change.

**Body: say WHY, because the diff already says what.** A body that narrates the change is dead
weight; `git show` does it better and never goes stale. Write the body to answer what the diff
cannot:

- What was wrong, and how it actually presented. "The gate armed and could never be disarmed" beats
  "fixed the gate".
- Why this fix and not the obvious alternative. This is the line that saves the next person from
  re-litigating a decision you already thought through.
- What it cost or what it does not cover. A known gap recorded here is a gap; the same gap unrecorded
  is a trap.
- Anything load-bearing that is invisible in the diff: a version floor, an ordering constraint, a
  platform bug you are working around, the issue number that documents it.

**A commit is one logical unit.** If the body needs "and also", it is two commits. This is what makes
`git log` navigable later: a bisect lands on one intent, and a revert takes one thing with it.

## Git, PRs, integration

- **I own PR and remote operations — never do or raise them unprompted (the trigger is in
  `rules/process.md`).** After the local commit, STOP. Do NOT push, open a PR, flip a PR ready/draft,
  request or add reviewers, add/remove labels, edit a PR body, comment on a PR, or merge — UNLESS I ask
  for that exact op, or a skill whose defined flow performs PR ops is running (e.g. `/sk:ship-pr`,
  `/sk:ship-screenshot-changes`, `/sk:ship-resolve-pr-comments`, `/sk:ship-full-detailed-workflow`),
  which I authorized by invoking it. And DON'T talk about PRs to me — no ready-flip prompts,
  held-for-you PR next-steps, or reviewer nudges — unless I ask about the PR; I run PR ops on my own
  cadence or tell you to. Merge is separately gated below (never without an explicit ask). This gates
  only the PR/remote layer; the local commit-when-done authorization is unchanged. TEST: a hand-back
  reports what was built and stops, carrying no PR next-step, ready-flip prompt, or reviewer ask I
  didn't request.
- Read the project's CLAUDE.md AND CLAUDE.local.md and relevant plan docs at the start of the task — the
  local file carries machine-local setup, test accounts and secrets-by-reference the committed one omits.
- Merge/rebase the latest default branch in before working, and re-evaluate the plan against what changed (e.g., redesigns that must now be used).
- Resolve all merge conflicts by merging the default branch into the feature/base branch before merging the PR.
- Fix all PR review comments: fix the code, reply inline, and resolve the threads.
- **Keep the ticket, branch, and PR in lockstep — the routine is `references/ticket-lifecycle.md`.**
  Set the ticket In Progress on start, name the branch from the ticket code + title slug (auto-links it),
  match the PR title to the ticket title, put the ticket link in the PR body, and link only the tickets
  the PR delivers. That reference owns the routine; apply it on any task that carries a ticket.
- When adopting someone else's branch: check whether it reinvents logic that already exists; run full review tooling on it and fix all findings with no loose ends; verify none of it breaks existing behavior; compare it against the reference implementation for missing parts (tests, error handling, logging) and add them.
- Build and run with the project's documented commands to verify before declaring done.
- When finished: fix everything with no loose ends, commit, then tear down all processes and clean up the environment for other testing. Open/flip a PR only when I ask or a `sk:ship-*` skill does it (see the PR-ops rule at the top of this section).

## Merging to the default branch — a general instruction is never a yes for a specific merge

**DO get the user's explicit yes for THIS PR before `gh pr merge` or any push to the remote default
branch.** A general "merge everything", "proceed", or "continue" authorizes the direction, never the
specific irreversible merge. `hooks/git-commit-guard.py` hard-blocks `gh pr merge` and default-branch
pushes; clear it with `CLAUDE_ALLOW_PR_MERGE=1` (or `CLAUDE_ALLOW_MAIN_COMMIT=1` for a push) only once
the user has confirmed that exact merge.
**DON'T admin-override a required review, and DON'T merge for the user when handing them the PR is the
safer move.** The fix for the incident where 8 PRs (two on red CI) went into remote master off "merge
everything, no loose ends."

**DO verify CI is genuinely GREEN on the exact head commit before any merge** — read the actual
per-check conclusions (`gh pr view <n> --json statusCheckRollup`): every required check SUCCESS, none
FAILURE/PENDING/incomplete.
**DON'T trust a truncated summary.** A `SKIPPED:3,SUCC…` glance hid a `test-unit-serverless FAILURE`
and the red PR merged; a merge on red CI breaks the default branch for everyone.

**DO re-verify the ASSEMBLED result when several PRs touching the same file merge together.** Each
PR's own CI is green against its base, not against the others: a textual auto-merge can duplicate a
symbol (two PRs each adding the same `const` or object key → a TS "cannot redeclare"/TS1117 that fails
the whole build), and no individual PR's CI catches it.

**DO treat "merge into main"/"land"/"propagate"/"integrate" as a LOCAL merge, and read the MAIN
CHECKOUT's actual main before integrating — not the worktree's `origin/main`.** A worktree's
`origin/main` (and the SessionStart freshness hook's "N behind main" comparison) can be stale while the
main checkout's LOCAL main is far ahead with unpushed work.
**DON'T "fast-forward" origin/main from a worktree to land work.** It only fast-forwards the STALE
remote ref, silently diverging origin from the real integration point and forcing a conflicting
`git pull` on the user (the fix for a worktree that pushed its branch to origin/main while the main
checkout held 53 unpushed commits of other work — the pull then hit merge conflicts). Merge locally and
hand back; push only on an explicit "push" for that action. TEST: after an integration task the only ref
that moved is a local branch; origin is untouched unless the user said "push".

**DO integrate a branch by MERGING it — a merge commit that keeps the branch tip as an ancestor of the
target — so `git branch --merged` and `git merge-base --is-ancestor <branch> main` later PROVE it landed.**
The user wants to SEE, unambiguously, that a branch was merged in.
**DON'T rebase, squash, or re-implement a branch's work into the target when the source branch will
outlive the merge.** Those rewrite patch-ids, so `git cherry` reads all `+` and the source branch shows as
UNMERGED even though its work is in — the exact ambiguity that made two finished feature branches look like
unmerged work at cleanup time. If a squash/rebase is genuinely wanted, delete the source branch in the SAME
step so no ref is left behind claiming to be unmerged.

## Deleting a merged branch safely — the gate is the seatbelt, not `-d`

`git branch -d` decides "merged?" against the CURRENT HEAD (or the branch's upstream), NOT against the
default branch. So in a stale worktree — HEAD sitting behind `master` — `-d` REFUSES a branch that is
already merged to `origin/master`, and the refusal reads exactly like a real "unmerged." Observed: a
252-commit-behind worktree refused six branches whose tips WERE `origin/master`; the branches were
genuine merged leftovers and `-d` could not clear them.

**First, confirm with the user — always.** Removing a branch or worktree is destructive and not cleanly
reversible, so present the exact list you propose to remove and get an explicit yes; never delete
unprompted. The gate below proves a deletion is SAFE; the user still decides WHETHER to make it, and may
veto any item. The cleanup flows that use this rule carry it as their confirm step —
`/sk:meta-cleanup-worktrees` (Step 4) and `/sk:work-hyperspeed` (Step 6).

Then prove the merge yourself, and force:

1. **Gate on the default branch, not HEAD.** `git merge-base --is-ancestor <branch> origin/<default>`
   (exit 0 = every commit on the branch is already in the default branch), OR — for a squash/rebase
   merge, which is not an ancestor — `gh pr view <branch> --json state -q .state` is `MERGED`. Resolve
   `<default>` with `git symbolic-ref --short refs/remotes/origin/HEAD`.
2. **If the gate passed only via gh `MERGED` (not ancestry), also prove nothing local-only.** A squash
   or rebase merge puts a REWRITTEN commit into the default branch, so the branch's own tip is not
   contained in it — and if that tip carries commits added AFTER the merge, `gh MERGED` is still true
   while those commits live nowhere else. So when ancestry failed, additionally require the tip fully
   pushed: `git rev-list --count <upstream>..<branch>` is `0` (or `origin/<default>..<branch>` if there
   is no upstream). If commits remain, do NOT `-D` — they are unmerged work the PR state hid.
3. **Only once a gate above holds, delete with `git branch -D <branch>`.** The gate is the seatbelt, so
   `-D` here is safe and correct, and it is the only form that works from a stale worktree. `-d` is not
   a safety upgrade over this; it is an unreliable HEAD-relative check that produces false negatives.
4. **Never `-D` a branch no gate passed.** Without the ancestry (or gh-`MERGED`-plus-pushed) proof, `-D`
   really can drop unmerged commits — the proof is what makes it safe, not the flag.

## Deployment tracking

- Keep a running list of everything that must be applied at deploy time — prod configs, indexes, rules, functions, env vars — so nothing is missed when shipping.

## Shipping is not done until the deploy is verified

A merge is a request to deploy, not a deployment. After merging and pushing, **watch the autodeploy
through to a running state and prove the thing works in the deployed environment**, then loop:

1. Merge, push, and watch the pipeline to completion. A green pipeline is not proof; it means the
   artifact built.
2. Exercise the actual change against the deployed environment. Hit the endpoint, load the page,
   check the logs for the error rate after traffic arrives.
3. When something is wrong or merely not as expected, diagnose the cause, fix it, and go back to 1.
4. Stop when a full pass comes back clean with nothing outstanding.

The loop exists because the interesting failures only appear here: environment variables that are not
set, a runtime that differs from local, a build step that drops an asset, a permission that was never
granted. None of them can fail locally. If a loose end is left, say which one plainly rather than
reporting the deploy as done.
