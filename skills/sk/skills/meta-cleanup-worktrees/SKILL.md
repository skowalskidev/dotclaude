---
name: meta-cleanup-worktrees
description: Safely clean up DONE git worktrees and branches for this repo — remove only the ones that are provably finished (merged into master, clean, idle, and never the current or main checkout) and tell you which Conductor/Claude sessions you can archive. It lists and CONFIRMS before it deletes anything, never force-deletes, and BLOCKS any worktree with a live session, uncommitted changes, unpushed commits, or an open/unmerged PR. Reuses bin/port-registry.sh + bin/kill-orphan-workers.sh for live-session detection and points to rules/process.md + references/dev-server-hygiene.md for the teardown rules. Use for "clean up merged worktrees", "remove done worktrees and branches", "tidy up my worktrees", "delete merged branches", "which sessions can I archive", or /sk:meta-cleanup-worktrees.
argument-hint: "[optional repo path; defaults to the current repo]"
---

# Clean up DONE worktrees and branches — safely

Sweep the worktrees and branches for THIS repo that are provably finished — merged, clean, and idle —
remove them, and name the Conductor sessions for Simon to archive. NEVER touch anything still being
worked on. Conservative by construction: it LISTS and CONFIRMS before deleting, and never force-deletes.

## Reuse, don't reimplement

- The RULES live in `rules/process.md` §§ "Git worktree discipline" + "Clean up after yourself" (never
  disturb the main-checkout WIP; tear the worktree down WITH its merged branch in the same step; verify
  cleanup against on-disk storage, not just `git worktree list`) and `references/dev-server-hygiene.md`
  (never kill another session's server; storage-vs-listing reconcile). Read them there; do not restate.
- For live-worktree detection REUSE `bin/port-registry.sh reap` (exit 5 = workspace gone but its server
  still listens) and `bin/kill-orphan-workers.sh` (`family_is_serving`). Do not reimplement them.
- This GENERALISES `/sk:work-hyperspeed` Step 6 (delete the merged branch local+remote; name the sessions
  Simon must archive) from hyperspeed's own `hs/<run>/*` branches to any merged worktree/branch.

## Scope

This repo only. Conductor worktrees under `~/conductor/workspaces/<project>/*`. Never the main checkout,
never the current worktree, never a detached-HEAD or non-Conductor worktree.

## Step 1 — refresh the merge state (one network read)

Resolve the default branch (`git symbolic-ref --short refs/remotes/origin/HEAD`, usually `origin/master`)
and `git fetch --prune origin <default>`. Without this a just-merged branch can look unmerged, or a
just-deleted remote branch can linger in the listing.

## Step 2 — enumerate candidates

`git worktree list --porcelain`. Keep only paths under `~/conductor/workspaces/<project>/`. HARD-EXCLUDE:

- the MAIN checkout: `dirname "$(git rev-parse --git-common-dir)"`
- the CURRENT worktree: `git rev-parse --show-toplevel`
- any detached-HEAD worktree (no branch to reason about)
- anything outside the Conductor workspaces dir

Then `ls` the workspaces parent dir on disk and reconcile against the listing — git stops listing a
worktree once its metadata is pruned while the checkout still sits on disk (`dev-server-hygiene.md`).

**Also enumerate BRANCH-ONLY orphans — merged local branches whose worktree is already gone.** This is
the most common leftover: Conductor (or a `git worktree remove`) reaps the workspace but leaves the
branch behind, so it never appears in `git worktree list` and a run that enumerates only worktrees never
sees it. That is exactly how a batch of merged part-branches accumulates unseen. List the local heads
that have NO worktree, and explicitly drop the default branch — `comm` does NOT exclude it on its own (it
drops out only when checked out somewhere, and the main checkout may sit on a feature branch, which would
otherwise offer local `master` for deletion):

```bash
DEF=$(git symbolic-ref --short refs/remotes/origin/HEAD | sed 's#^origin/##')   # e.g. master
comm -23 <(git for-each-ref --format='%(refname:short)' refs/heads | sort) \
         <(git worktree list --porcelain | awk '/^branch /{sub("refs/heads/","",$2); print $2}' | sort) \
  | grep -vxF "$DEF"      # never the default; the current branch is already dropped (it has this worktree)
```

Each that PASSES the merge gate (Step 3 #1) is a 🌱 branch-only candidate. It STILL has a local-only
question when the gate passed ONLY via gh `MERGED` (a squash/rebase tip can carry post-merge commits that
are in no default branch) — apply `references/git-pr-deploy.md` §'s pushed check before `-D`. One that
FAILS the gate is left untouched and unlisted: it is a live branch someone may resume, not a leftover.

**A REMOTE part branch is the OWNING run's job, not a repo-wide purge.** A hyperspeed part that pushed
then had its workspace archived leaves a branch on origin — but hyperspeed Step 6 deletes that remote by
the name it recorded (even for an aborted run, from its status dir). Do NOT enumerate every
remote-head-with-no-local here and offer it: on a shared team remote that is HUNDREDS of other people's
branches (measured), and deleting one is a destructive shared-remote write against work you don't own.
meta-cleanup only ever deletes the REMOTE COUNTERPART of a LOCAL orphan it is already removing, and only
as Step 4's separate extra-confirmed step.

## Step 3 — the SAFE gate (ALL must hold, or BLOCK with a printed reason)

A worktree is removable only if EVERY check passes:

1. **Merged:** `git rev-list --count origin/<default>..<branch>` is `0` (ancestor-merged) **OR**
   `gh pr view <branch> --json state -q .state` is `MERGED`. The OR is load-bearing: a squash- or
   rebase-merged branch is NOT an ancestor of master, so `rev-list` wrongly calls it unmerged; the gh
   `MERGED` state is the truth for those.
2. **Clean:** `git -C <wt> status --porcelain` is empty.
3. **Nothing local-only:** if the branch has an upstream, `git -C <wt> rev-list --count @{upstream}..HEAD`
   is `0`; if it has NO upstream (never pushed), fall back to
   `git -C <wt> rev-list --count origin/<default>..HEAD` is `0`.
4. **Idle:** no process is cwd'd in the worktree — `lsof -nP -d cwd | grep -F <path>` (NEVER `lsof +D`,
   which recurses the whole tree and hangs). A live `claude`/`node` session → BLOCK. An idle `zsh`
   sitting in it → removable but WARN (removing it orphans that shell's cwd). Cross-check with
   `bin/port-registry.sh reap`.
5. **Not the current worktree, not the main checkout.**

A PR that is CLOSED-but-not-merged is NOT merged → BLOCK. A merged branch with NO worktree is a 🌱
branch-only candidate (Step 2 enumerates these): the merge gate applies, plus — if it passed only via
gh `MERGED`, not ancestry — the pushed check from `references/git-pr-deploy.md` §, since there is no
worktree to read local-only commits from. Then `git branch -D`; no worktree to remove.

## Step 4 — present and CONFIRM (never delete unprompted)

Show a table, grouped: ✅ removable · ⛔ blocked (with the exact reason) · 🌱 branch-only. Then use
AskUserQuestion and act ONLY on Simon's yes. Deleting the REMOTE counterpart of a ✅/🌱 local orphan being
removed is a SEPARATE, extra-confirmed step — it is a shared-remote write — and is OFF by default.

## Step 5 — remove, safely (only after yes)

For each confirmed-removable worktree:

- `git worktree remove <path>` — NEVER `--force`. Its refusal on a dirty or locked tree is the seatbelt.
- For a dir that is ON DISK but git NO LONGER tracks (Step 2's reconcile caught it; `git worktree remove`
  errors "is not a working tree"): confirm it is idle (`lsof -nP -d cwd | grep -F <path>`, Step 3 #4) and
  under `~/conductor/workspaces/<project>/`, then `rm -rf <path>` — only after an explicit EXTRA confirm,
  since git cannot manage it. This is the directory half of an archived workspace that left both a branch
  and its on-disk tree.
- Delete the branch with `git branch -D <branch>`, but ONLY after Step 3 #1's merge gate passed. Do NOT
  reach for `git branch -d` as the "safe" form here: its merged test is against the CURRENT HEAD, so a
  stale worktree (HEAD behind the default branch) makes it REFUSE a branch genuinely merged to
  `origin/<default>` — a false negative that leaves the leftover uncleaned. The Step 3 gate (ancestor of
  `origin/<default>` OR gh `MERGED`) is the real seatbelt; `references/git-pr-deploy.md` § "Deleting a
  merged branch safely" owns this rule. Never `-D` a branch that did not pass the gate.
- Remote branch, only if extra-confirmed: `git push origin --delete <branch>`.

Then once, at the end: `git worktree prune -v` (reclaims the removed entries + any `fallow-*` scratch
worktrees git has already orphaned). VERIFY against disk: `ls` the workspaces dir AND `git worktree list`
must both agree the removed ones are gone (storage-vs-listing).

## Step 6 — name the sessions for Simon to archive

The skill cannot touch the Conductor/Claude UI. For each removed worktree, report:
`Archive Conductor workspace <codename> (alias <friendly-name>)`.

- `<codename>` = the last path segment of the worktree (the reliable key).
- `<friendly-name>` = reverse-lookup the `~/conductor/workspaces/<project>/*` symlinks for one whose
  target is `<codename>`. A codename may carry several or stale aliases — the codename is authoritative,
  the alias is a readable hint. Verify the symlink's target codename still had a worktree. Simon archives
  them from the Conductor app.

## The gotchas this skill must never trip

Squash/rebase merge (OR-in gh `MERGED`) · no-upstream branch (fall back to `origin/<default>`) · the
current worktree and main checkout (hard-excluded) · merged-but-running (block on a live session) ·
merged-but-idle-shell (warn) · dirty tree (never `--force`) · detached HEAD (skip branch logic) · PR
closed-not-merged (block) · **branch-only orphan whose worktree is already archived (Step 2 enumerates
merged heads-with-no-worktree, or it is never seen — the usual leftover)** · **`git branch -d` is
HEAD-relative, so a stale worktree makes it refuse a genuinely-merged branch (gate on `origin/<default>`
ancestry, then `-D`)** · **local `master` enumerated when the main checkout sits on a feature branch
(filter `$DEF` out of the branch-only `comm`, never rely on it being checked out)** · **gh-`MERGED` alone
does not prove containment — a squash/rebase tip carrying post-merge commits needs the pushed check
before `-D`** · **a remote part branch is the owning run's job (hyperspeed Step 6, by recorded name) —
meta-cleanup deletes only the remote COUNTERPART of a local orphan it removes, extra-confirmed, never a
repo-wide remote purge (a shared remote is hundreds of others' branches)** · **on-disk dir git no longer
tracks — `git worktree remove` errors; idle-check then `rm -rf`, extra-confirmed** · `lsof +D` hangs (use
`-d cwd`) · stale/duplicate session symlinks (verify the target codename still has a worktree).
