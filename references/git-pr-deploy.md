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

**DO chain a commit after its checks with `&&`: `npm test && npm run build && git commit -F msg.txt`.**
**DON'T join them with `;` or a newline in one command.** `;` runs the commit when a check fails, and
the red commit then needs an `--amend` (the fix for a commit that landed with a failing config test).
TEST: no `git commit` in a command is reachable after a failed check.

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

DO apply `rules/self-healing-config.md` for the explicit standing authorization covering Simon's own
config repairs. The project-repository restrictions below do not cancel that scoped authorization.

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
- Apply `references/project-instructions.md` before project docs. When allowed, read the project's CLAUDE.md AND CLAUDE.local.md and relevant plan docs at the start of the task — the
  local file carries machine-local setup, test accounts and secrets-by-reference the committed one omits.
- Merge/rebase the latest default branch in before working, and re-evaluate the plan against what changed (e.g., redesigns that must now be used).
- Resolve all merge conflicts by merging the default branch into the feature/base branch before merging the PR.
- Fix all PR review comments: fix the code, reply inline, and resolve the threads.
- **Keep the ticket, branch, and PR in lockstep — the routine is `references/ticket-lifecycle.md`.**
  Set the ticket In Progress on start, name the branch from the ticket code + title slug (auto-links it),
  match the PR title to the ticket title, put the ticket link in the PR body, and link only the tickets
  the PR delivers. That reference owns the routine; apply it on any task that carries a ticket.
- When adopting someone else's branch: check whether it reinvents logic that already exists; run full review tooling on it and fix all findings with no loose ends; verify none of it breaks existing behavior; compare it against the reference implementation for missing parts (tests, error handling, logging) and add them.
- Build and run with allowed project commands; when project instructions are ignored, derive them from source, executable config and CI.
- When finished: fix everything with no loose ends, commit, then tear down all processes and clean up the environment for other testing. Open/flip a PR only when I ask or a `sk:ship-*` skill does it (see the PR-ops rule at the top of this section).

**DO check open PRs before claiming a sequential number** — a migration file number, an ADR number, a
numbered manifest entry. Run `gh pr list --state open --limit 500 --json number,files` and look for the same number
in the same directory; when another open PR already adds it, take the next free one. DON'T pick the
number from the default branch alone (the fix for two open PRs both adding migration 197). TEST: no
two open PRs add the same numbered file.

## After a push, and after merging the base in

Applies once a push is authorized (Simon asked, or a `sk:ship-*` flow that pushes is running).

**DO read the PR's merge state and the CI runs for the pushed commit after every push:**
`gh pr view <n> --json mergeable,mergeStateStatus` and `gh run list --commit <sha>`. Expect
`MERGEABLE` and one run for that sha within 5 minutes. DON'T read "no checks" as a quiet state: a
PR that conflicts with its base starts no run. Do the same within 1 minute of any state change that
should start CI (marking a PR ready): confirm a run for the head commit is `in_progress`, and cancel
(`gh run cancel <id>`) an older run it is queued behind. TEST: each push records the merge state and a run
id for its sha, or the named reason there is none (the fix for CI that never started for an hour because
the PR conflicted with main, and for required checks left at "waiting for status" for ten minutes behind
a superseded run).

**DO run the repo's own ordering and migration checks before pushing a merge of the base** (the CI gate
list from `references/testing-strategy.md` § Defects first; e.g. a rule that a new migration is numbered
above every migration on the base). TEST: the first CI run after a base merge fails on no gate that has
a local command.

**DO finish four steps after merging the base, before the next commit:**
1. Reinstall dependencies with the project's lockfile command.
2. Re-download the test browsers and pinned binaries (a base dependency bump can change the browser a
   test tool needs).
3. After any migration rename, compare the local stack's applied migrations with the files by name and
   number, and state which files are applied (a stale record of the old name hides a base migration
   that took its number).
4. Read `git status` for tracked files a tool rewrote, and revert or explain each.
TEST: the hand-back names the install, the browser download, the applied-migration comparison and the
`git status` result.

## Merging to the default branch — a general instruction is never a yes for a specific merge

Outside the own-config exception above, **DO get the user's explicit yes for THIS PR before `gh pr merge` or any push to the remote default
branch.** A general "merge everything", "proceed", or "continue" authorizes the direction, never the
specific irreversible merge. `hooks/git-commit-guard.py` hard-blocks `gh pr merge` and default-branch
pushes; clear it with `CLAUDE_ALLOW_PR_MERGE=1` (or `CLAUDE_ALLOW_MAIN_COMMIT=1` for a push) only once
the user has confirmed that exact merge.
**DON'T treat a yes to an AskUserQuestion option or plan YOU authored as that confirmation, and DON'T
author an option that pushes/merges a remote default branch in the first place.** The confirmation must
be the user's OWN unprompted "push"/"merge" for THAT action; offering "push to main" as a pickable
option and clearing the override on the click is the same mistake wearing a consent sticker — the click
is your idea, not theirs. (the fix for a "merge to main" answered by clicking a self-authored "push to
main (deploys)" option, which then fast-forward-pushed origin/main and triggered a prod deploy.)
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
**DON'T rebase, squash, cherry-pick, or re-implement a branch's work into the target when the source
branch will outlive the merge.** Each one puts NEW commits on the target, so `git branch --merged` and
`--is-ancestor` both report the source branch as UNMERGED even though its work is in — the exact ambiguity that made two finished feature branches look like
unmerged work at cleanup time. If a squash, rebase or cherry-pick is genuinely wanted, run the deletion gate below on the source
branch and put its deletion to the user in the SAME hand-back, so no ref is left behind claiming to be
unmerged. Skip `cherry-pick -x` when picking from a private agent branch: git documents `-x` for
publicly visible branches only.
**DO use the merge method the repo's default branch already uses** (read its last 20 subjects: `(#NNN)`
on every one means squash). Where the repo squashes, squash, run the deletion gate below on the source
branch, and put its deletion to the user in the same hand-back. Squash fits a short-lived one-change
branch and breaks a branch that keeps going (GitHub and GitLab both document this), so commit nothing
more to a squashed branch. TEST: after a squash merge the hand-back names the leftover branch and its
gate result.

## Merging several PRs at once — one batch, one CI run, one deploy

Owned here; `/sk:ship-merge-batch` drives it. Applies when 2+ approved PRs wait on a default branch
that requires branches to be up to date (ruleset `strict_required_status_checks_policy: true`): each
merge puts every other PR behind, so N PRs cost N rounds of update + full CI + deploy.

**DO get Simon's own yes naming EACH PR in the set before batching it.** "Merge these all" names the
direction; the PR numbers he lists are the set. The merge guard above still applies to the one
`gh pr merge`.
**DON'T batch a PR whose `statusCheckRollup` is not all SUCCESS/SKIPPED on its current head, or a
draft.** GitHub marks a PR merged indirectly "even if branch protection rules on that pull request
were not satisfied" ([About pull request merges § Indirect merges](https://docs.github.com/en/pull-requests/collaborating-with-pull-requests/incorporating-changes-from-a-pull-request/about-pull-request-merges)),
so the per-PR green check is the only protection left. TEST: every batched PR has a recorded yes and
a green rollup on the head sha that went into the batch.

**DO pick the mechanism in this order, reading the repo's settings, never changing them:**
1. **Merge queue**, when `gh api graphql -f query='{repository(owner:"O",name:"R"){mergeQueue(branch:"main"){id}}}'`
   returns non-null: `gh pr merge <n>` adds each PR to the queue and GitHub merges the group in one
   operation ([Managing a merge queue](https://docs.github.com/en/repositories/configuring-branches-and-merges-in-your-repository/configuring-pull-request-merges/managing-a-merge-queue)).
   It is available "in any public repository owned by an organization, or in private repositories
   owned by organizations using GitHub Enterprise Cloud" (same page), and every required check must
   also run `on: merge_group`, or the queue waits forever on that check.
2. **Batch PR** otherwise. It needs no settings change.

**DO build a batch PR this way:**
1. Check numbered files first: list every new migration or numbered manifest entry across the set.
   Numbers must be unique and above the base's newest, and no open PR outside the set may hold one.
   Renumber on the ORIGINAL PR's branch, push, and wait for it to go green again.
2. `git switch -c batch/<yyyy-mm-dd>-<slug> origin/<default>`, then for each PR in dependency order
   (stack bases first): `git fetch origin pull/<n>/head`, check the sha equals `headRefOid`, and
   `git merge --no-ff <sha>`. Resolve a conflict inside that merge commit only (two appended
   manifest lines: keep both).
3. Run the repo's local ordering and migration checks, push the batch branch, and open the batch PR
   with `/sk:ship-pr`: a title carrying every ticket id the repo's title check needs, "Batches #A,
   #B, #C" in the body, and one Deploy TLDR merging each PR's steps in order.
4. Wait for ONE green CI run on the batch head, then merge it with `--merge`. When the ruleset's
   `allowed_merge_methods` lacks `merge`, squash, then close each original with a comment linking
   the batch PR.
5. Watch the one deploy run for the merge sha and run each PR's post-deploy smoke
   (§ Shipping is not done until the deploy is verified).
6. Read `gh pr view <n> --json state,mergedAt` for each original PR and the ticket status per
   `references/ticket-lifecycle.md`.

**DON'T rebase, squash or amend a PR head on the batch branch, and DON'T squash-merge the batch PR.**
A merge commit keeps every PR head reachable from the base, which is what marks each original PR
merged (same Indirect merges section) and keeps `git revert -m 1 <that PR's merge commit>` able to
undo one PR alone. A squash leaves the originals open and loses that revert.
**DON'T fix a red PR inside the batch.** Drop it, rebuild the batch from the default branch without
it, and hand it back on its own branch.

**DO put a settings change to Simon as a decision, with both halves stated, never apply it:**
- **Loose required checks** (untick "Require branches to be up to date before merging",
  [Available rules for rulesets](https://docs.github.com/en/repositories/configuring-branches-and-merges-in-your-repository/managing-rulesets/available-rules-for-rulesets)):
  each PR merges without re-running CI, and back-to-back deploys coalesce because a newer pending run
  in a concurrency group cancels the older pending one ([Control the concurrency of workflows and jobs](https://docs.github.com/en/actions/writing-workflows/choosing-what-your-workflow-does/control-the-concurrency-of-workflows-and-jobs)).
  It needs the default-branch push run to re-validate the combined tree before deploying, and the
  migration-order check to run on push too, since a PR-time check sees only its own base.
- **Merge queue**: a plan that includes it, plus `merge_group` triggers on every required check.

TEST: one batch yields exactly one default-branch push, one deploy run, and every original PR in
state MERGED, or a named reason for each that is not.

## Config repository completion

DO apply `rules/config-repo.md` to Simon's own config repository only. This is standing authority
to finish reviewed, validated config work and retire its merged branches without another cleanup
question. Other repositories keep their existing remote-operation and confirmation rules.

DO inventory all local heads, origin heads and worktrees at session start and before hand-back.
Finish ready authorized work and remove its merged refs in the same task, including branch-only
leftovers. Review and validate pending dependency PRs before merging ready patch updates and
removing their branches. Do not merge merely to empty the branch list.

DO retain another session's active work, unique unreviewed changes, protected recovery and concrete
blockers with an owner, evidence and next action in the plan. Resume ready owned work at the next
task boundary. Never delete work to manufacture a main-only result or weaken required checks.
No daemon or blind automatic merge.

DO retire a finished task-owned config branch even when its workspace stays open: verify a clean
tree and the entire tip's containment in `origin/main`, detach at the unchanged commit, then delete
only the merged ref. Preserve all workspace files and Conductor's lifecycle. Create a fresh branch
from current `origin/main` before further edits; never detach another session's active checkout.

TEST: after fetching origin, `git for-each-ref refs/heads` and `git ls-remote --heads origin` show
only main or individually evidenced active/protected/blocked exceptions; live main has clean status
and `git rev-list --left-right --count main...origin/main` prints `0 0`. Verify every retired ref's
absence separately from any worktree removal.

## Deleting a merged branch safely — the gate is the seatbelt, not `-d`

`git branch -d` decides "merged?" against the CURRENT HEAD (or the branch's upstream), NOT against the
default branch. So in a stale worktree — HEAD sitting behind `master` — `-d` REFUSES a branch that is
already merged to `origin/master`, and the refusal reads exactly like a real "unmerged." Observed: a
252-commit-behind worktree refused six branches whose tips WERE `origin/master`; the branches were
genuine merged leftovers and `-d` could not clear them.

**First, resolve authority.** Own-config closure uses the standing authority above. For other
deletion requests, confirm with the user. Removing a branch or worktree is destructive and not cleanly
reversible, so present the exact list you propose to remove and get an explicit yes; never delete
unprompted. The gate below proves a deletion is SAFE; the user still decides WHETHER to make it, and may
veto any item. The cleanup flows that use this rule carry it as their confirm step —
`/sk:meta-cleanup-worktrees` (Step 4) and `/sk:work-hyperspeed` (Step 6).

Then prove the merge yourself, and force:

1. **Gate on the default branch, not HEAD.** `git merge-base --is-ancestor <branch> origin/<default>`
   (exit 0 = every commit on the branch is already in the default branch), OR — for a squash/rebase
   merge, which is not an ancestor — `gh pr view <branch> --json state -q .state` is `MERGED`, OR — for
   a branch with no PR whose commits were cherry-picked or re-applied — the content proof: `git cherry
   origin/<default> <branch>` prints no `+` line (git matches each commit by its diff, so a clean
   cherry-pick reads `-`), or, when a pick was edited or conflict-resolved,
   `git merge-tree --write-tree origin/<default> <branch>` exits 0 and prints `origin/<default>`'s own
   tree id (merging would change nothing). Resolve `<default>` with
   `git symbolic-ref --short refs/remotes/origin/HEAD`.
2. **If the gate passed only via gh `MERGED` (not ancestry), also prove nothing local-only.** A squash
   or rebase merge puts a REWRITTEN commit into the default branch, so the branch's own tip is not
   contained in it — and if that tip carries commits added AFTER the merge, `gh MERGED` is still true
   while those commits live nowhere else. So when ancestry failed, additionally require the tip fully
   pushed: `git rev-list --count <upstream>..<branch>` is `0` (or `origin/<default>..<branch>` if there
   is no upstream). If commits remain, do NOT `-D` — they are unmerged work the PR state hid.
3. **Only once a gate above holds, delete with `git branch -D <branch>`.** The gate is the seatbelt, so
   `-D` here is safe and correct, and it is the only form that works from a stale worktree. `-d` is not
   a safety upgrade over this; it is an unreliable HEAD-relative check that produces false negatives.
4. **Never `-D` a branch no gate passed.** Without the ancestry, gh-`MERGED`-plus-pushed, or content proof, `-D`
   really can drop unmerged commits — the proof is what makes it safe, not the flag.

## Deployment tracking

- Keep a running list of everything that must be applied at deploy time — prod configs, indexes, rules, functions, env vars — so nothing is missed when shipping.

## Release preflight before building or uploading

**DO read the provider's current publication state before the first release-only build, archive,
package or export in each release attempt.** Apply `rules/connectors.md` to resolve the provisioned
read path and account. Match the remote app/package and environment to the intended artifact, then
check version eligibility, release-channel state and the build/release identifier strategy.
Ordinary development builds and tests do not need this publication check.

**DO record one timestamped preflight result in the living plan:** source command or console URL,
account/team and app identity, remote version/channel states, chosen candidate and eligibility
evidence. Reuse a fresh provider response when it covers these constraints; label conclusions
derived from that response and current provider rules. Do not require a second API or credential
for evidence the supported release tool already supplies.

**DO either check consumed identifiers before manually choosing one, or use the provider's documented
automatic allocation.** For manual selection, inspect complete relevant results, including pagination
and processing uploads; empty or incomplete results do not prove availability. For automatic selection,
record the enabled mode and retain the actual assigned identifier from the export/upload receipt.
Do not report the archive's original build number as the uploaded number when the provider changed it.
A build number named in a ticket or plan is an example, not a reservation: before the archive starts, find
the highest identifier already uploaded (the store's API when a key is provisioned, else ask the user once)
and build the next one. TEST: the archive's identifier is above the highest uploaded one, read before the
build began (the fix for an archive built as "99" because a ticket said so, refused as a duplicate after ten
minutes of build time).

**DO check App Store Connect before a TestFlight/App Store archive:** match team, app record and
bundle ID; read approved and submitted marketing versions (including approved versions awaiting
release) and the candidate version's release-train state. Choose a version eligible for another
upload and apply the identifier strategy above. When approval or a closed train prevents more uploads,
advance the marketing version; increasing only the build number does not resolve that constraint.
For a new train, establish eligibility from the app's current state and Apple's current requirements;
absence of a train record alone proves neither eligibility nor failure.

Apple associates uploads by bundle ID and version and identifies each build by its build string.
Check [Upload builds](https://developer.apple.com/help/app-store-connect/manage-builds/upload-builds/),
[Create a new version](https://developer.apple.com/help/app-store-connect/update-your-app/create-a-new-version/)
and [View builds and metadata](https://developer.apple.com/help/app-store-connect/manage-builds/view-builds-and-metadata/)
for the current rules and available status evidence. Xcode's `manageAppVersionAndBuildNumber=true`
can manage the build number during distribution; confirm support with installed `xcodebuild -help`
and [Preparing your app for distribution](https://developer.apple.com/documentation/xcode/preparing-your-app-for-distribution).
This does not replace the marketing-version/train check. Keep project version numbers out of this catalog.

**DO recheck eligibility after a resume or candidate/target change and immediately before upload.**
Use current provider evidence or supported validation; query again when existing evidence no longer
covers the candidate. Compare the artifact's identity, marketing version and selected identifier
strategy with that evidence, then verify the actual identifier in the distribution receipt. Resolve
changed remote state before publishing; reuse an artifact only while its metadata remains eligible.

**DO stop release packaging/upload when required state is unavailable or ambiguous**, record the
exact missing evidence and use the connector's documented fallback or auth gate. Continue independent
local work. **DON'T infer eligibility from source metadata, old archives or a prior successful release,
or deliberately use a rejected upload as the discovery step.** This check grants no publication permission.

TEST: each release attempt has live-state evidence predating its first release-only build/archive
and an artifact/identifier-strategy match before upload; unknown version eligibility causes zero
release archives or uploads. Closed trains and wrong app/team are resolved before expensive work;
identifier collisions are prevented by live manual checks or documented automatic allocation.

## Shipping is not done until the deploy is verified

A merge is a request to deploy, not a deployment. After merging and pushing, **watch the autodeploy
through to a running state and prove the thing works in the deployed environment**, then loop:
Keep the same project-instruction policy active before consulting a deploy runbook in this loop.

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
