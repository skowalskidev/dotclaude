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

- Read the project's CLAUDE.md AND CLAUDE.local.md and relevant plan docs at the start of the task — the
  local file carries machine-local setup, test accounts and secrets-by-reference the committed one omits.
- Merge/rebase the latest default branch in before working, and re-evaluate the plan against what changed (e.g., redesigns that must now be used).
- Resolve all merge conflicts by merging the default branch into the feature/base branch before merging the PR.
- Fix all PR review comments: fix the code, reply inline, and resolve the threads.
- **Keep the issue tracker in lockstep with the branch.** On starting a ticket, assign it to Simon and
  set it In Progress; on opening the PR, link the PR and the ticket both ways so the tracker syncs the
  ticket's status from the PR; tick each acceptance criterion as its work is verified, not at the end.
  Link ONLY the tickets this PR actually delivers — a linked ticket's status flips with the PR, so an
  unrelated link wrongly moves that ticket.
- When adopting someone else's branch: check whether it reinvents logic that already exists; run full review tooling on it and fix all findings with no loose ends; verify none of it breaks existing behavior; compare it against the reference implementation for missing parts (tests, error handling, logging) and add them.
- Build and run with the project's documented commands to verify before declaring done.
- When finished: fix everything with no loose ends, create a draft PR, then tear down all processes and clean up the environment for other testing.

## Deleting a merged branch safely — the gate is the seatbelt, not `-d`

`git branch -d` decides "merged?" against the CURRENT HEAD (or the branch's upstream), NOT against the
default branch. So in a stale worktree — HEAD sitting behind `master` — `-d` REFUSES a branch that is
already merged to `origin/master`, and the refusal reads exactly like a real "unmerged." Observed: a
252-commit-behind worktree refused six branches whose tips WERE `origin/master`; the branches were
genuine merged leftovers and `-d` could not clear them. So prove the merge yourself, then force:

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
