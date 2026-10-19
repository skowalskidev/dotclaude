---
name: meta-cleanup-worktrees
description: Safely clean up DONE git worktrees, their Conductor folders, plan dashboards, and branches for this repo — remove only the ones that are provably finished (merged into master, clean, idle, and never the current or main checkout) and tell you which Conductor/Claude sessions you can archive. It lists and CONFIRMS before it deletes anything, stops only a dashboard viewer whose runtime receipt proves it belongs to that worktree, never force-deletes, and BLOCKS any worktree with another live session, uncommitted changes, unpushed commits, or an open/unmerged PR. It also OFFERS (opt-in) to delete the merged remote counterparts of the branches it removes — your OWN branches only, by tip author. Reuses bin/port-registry.sh + bin/kill-orphan-workers.sh for live-session detection and points to rules/process.md + references/dev-server-hygiene.md for the teardown rules. Use for "clean up Conductor folders", "clean up merged worktrees", "remove done worktrees and branches", "delete finished dashboards", "tidy up my worktrees", "delete merged branches", "which sessions can I archive", or /sk:meta-cleanup-worktrees.
argument-hint: "[optional repo path; defaults to the current repo]"
---

# Clean up DONE worktrees and branches — safely

Sweep the worktrees and branches for THIS repo that are provably finished — merged, clean, and idle —
remove ordinary worktrees and request Conductor archives through the app. Verify the matching folders
are gone before calling their cleanup complete. NEVER touch anything still being worked on.
Conservative by construction: it LISTS and CONFIRMS before deleting, and never force-deletes.

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

This repo only — every worktree `git worktree list` reports for it, wherever it lives. Don't hardcode a
root: this machine keeps worktrees under `<repo>/.claude/worktrees/`, other setups under
`~/conductor/workspaces/<project>/*`, and filtering to one prefix silently no-ops the whole run on the
other layout. The safety is the EXCLUSIONS plus the gate, never a path prefix: never the main checkout,
never the current worktree, never a detached-HEAD worktree. Expand to other repositories only on an
explicit cross-repository request. Read the bundled Conductor skill at
`/Applications/Conductor.app/Contents/Resources/conductor-skill/skills/conductor/SKILL.md` before
handling Conductor workspaces. Only the user controls local managed workspaces through the app;
there is no local workspace CLI/API. Never mutate its database or bypass its archive flow.
Keep `~/conductor/repos` main clones, `archived-contexts`, chat history and shared application state
out of deletion scope; never recursively delete `~/conductor`.

## Step 1 — refresh the merge state (one network read)

Resolve the default branch (`git symbolic-ref --short refs/remotes/origin/HEAD`, usually `origin/master`)
and `git fetch --prune origin <default>`. Without this a just-merged branch can look unmerged, or a
just-deleted remote branch can linger in the listing.

## Step 2 — enumerate candidates

`git worktree list --porcelain` — it lists every worktree wherever it lives, so derive candidates from
it directly, never by filtering to a hardcoded path prefix (that filter is what no-ops the run on a
`.claude/worktrees/` layout). HARD-EXCLUDE:

- the MAIN checkout: `dirname "$(git rev-parse --git-common-dir)"`
- the CURRENT worktree: `git rev-parse --show-toplevel`
- any detached-HEAD worktree (no branch to reason about)

Inventory the filesystem independently of Git: enumerate `~/conductor/workspaces` and every configured
alternate workspace root, plus the parents of this repo's listed worktrees. Read configured locations
from Conductor user settings; record absent or unreadable roots. Do not stop at a discovered common
parent: directories can survive after all worktree metadata AND branch refs disappear.

Join each directory to this repo using its canonical Git common directory and origin, then its branch
and HEAD, or a previously saved inventory carrying that evidence. Record canonical path, repository,
branch, HEAD, managed/archive status, alias links and `du -sk` size BEFORE deleting any refs or metadata.
Do not infer ownership from project-folder names, city names, or a same-named branch in another repo.
Retain every unresolved mapping with its reason. Inspect only metadata and paths; never print copied
credentials or `.env` contents. Keep the inventory outside any directory proposed for removal.

Canonicalize roots and candidate paths without traversing symlinks outside the authorized scope.
Inventory alias links separately, deduplicate targets, and never count their target sizes twice.
Only remove a confirmed owned alias as a link after its target's cleanup decision; retain unknown links.
TEST: a directory missing from both Git listings and local heads still receives a mapped or blocked row.

Also enumerate `.context/*-dashboard.runtime.json` inside each candidate. Treat a receipt as owned only
when its `plan` and `output` resolve inside that worktree, the plan exists, and `ps -p <pid> -o command=`
names `workflow-dashboard.py serve`; resolve the command's plan argument against the PID's cwd and require
it to equal the receipt's plan. A missing/dead receipt is stale runtime metadata;
a live receipt that fails any ownership check is an unknown process and BLOCKS cleanup.

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

Join EVERY branch-only candidate to the filesystem inventory before calling its workspace gone.
A matching residual directory remains a workspace cleanup item even if Git reports no worktree.
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
4. **Idle:** no process except a verified dashboard viewer is cwd'd in the worktree —
   `lsof -nP -d cwd | grep -F <path>` (NEVER `lsof +D`, which recurses the whole tree and hangs).
   A verified viewer is removable-after-confirmation and appears in the candidate table with its PID;
   a live `claude`/`node` session or unverified viewer → BLOCK. An idle `zsh` sitting in it → removable
   but WARN (removing it orphans that shell's cwd). Cross-check with `bin/port-registry.sh reap`.
5. **Protected paths/refs:** exclude current, main, default, detached HEAD and the explicit keep-list.
6. **Owned and disposable:** require Step 2's repository/branch identity proof and no unique user
   data in EVERY workspace proposed for removal, including ordinary Git worktrees and app archives.
   Keep the tracked-file clean/merge checks; also inventory untracked AND ignored paths and classify
   each as reproducible output or safely preserved user data. A clean Git status alone is insufficient.
   Inspect metadata/paths without exposing credential contents. Copied secrets, local databases and
   unknown ignored files are not disposable caches; unresolved data safety → BLOCK.
   For orphan or interrupted-deletion directories, compare tracked files to the saved merged HEAD.
   Missing metadata or refs requires equivalent saved proof of identity, merge state and data safety;
   inability to establish any of them → BLOCK. Idleness and root membership alone never pass.

A PR that is CLOSED-but-not-merged is NOT merged → BLOCK. A merged branch with NO worktree is a 🌱
branch-only candidate (Step 2 enumerates these): the merge gate applies, plus — if it passed only via
gh `MERGED`, not ancestry — the pushed check from `references/git-pr-deploy.md` §, since there is no
worktree to read local-only commits from. Delete its ref only after the inventory and gate; do not
claim disk cleanup while a matching directory remains.

## Step 4 — present and CONFIRM (never delete unprompted)

Show a table, grouped: ✅ removable · ⏳ app archive required · ⛔ blocked (with the exact reason) ·
🌱 branch-only. Include repository, branch/HEAD, exact path, aliases, before-size and planned action. Then use
AskUserQuestion and act ONLY on Simon's yes.

For each removable worktree, list its canonical `.context/*-dashboard.html` files and any verified
viewer PID under `Dashboard cleanup`. The worktree confirmation covers deleting those disposable files
with the worktree and stopping those exact viewers; it never covers a mismatched or unrecorded process.

**Honor an explicit keep-list.** When Simon names branches or worktrees to keep, HARD-EXCLUDE them from
every removable group before presenting — above the gate, even for ones the gate would already block.

**Offer the merged remote counterparts as their OWN opt-in question — do NOT stay silent.** For every
✅/🌱 local orphan being removed whose `origin/<branch>` is ALSO ancestor-merged into `origin/<default>`
(`git rev-list --count origin/<default>..origin/<branch>` is `0`), list those remotes and ASK whether to
delete them too. It is a separate shared-remote write, so it defaults to no — but SURFACE it in the same
gate, never omit it and make Simon ask.

**Only the user's OWN remote branches.** A shared remote holds teammates' branches, so before offering a
remote confirm its tip author is Simon's: `git log -1 --format='%ae %an' origin/<branch>` matches his git
author (the `skowalskidev` GitHub identity / a `simon@` email). NEVER offer or delete a remote branch
someone else authored, even when it is the counterpart of a local orphan Simon is removing.

## Step 5 — remove, safely (only after yes)

For each confirmed candidate, recheck identity, branch/HEAD, path/link targets, keep-list, cleanliness,
local-only commits, tracked/untracked/ignored data safety and idleness immediately before destruction. Changed evidence → BLOCK and refresh
its inventory; an earlier yes never covers a different path or newly created work.

- For each verified dashboard viewer listed at the gate, run
  `python3 "$HOME/.claude/bin/workflow-dashboard.py" stop <plan> --expect-pid <pid>`. The helper re-runs
  the receipt/worktree/output/command checks, sends `TERM` only to that confirmed PID, waits up to 5
  seconds and verifies it exited. If ownership changed or it survives, BLOCK that worktree instead of
  widening the kill. Re-run the idle check after the viewer exits.

For a Conductor-managed workspace, ask Simon to archive its exact workspace name and canonical path
in the Conductor app. Leave it pending until he does, then verify the disk result. Do not run
`git worktree remove` or `rm` on it, even when idle. Preserve Conductor's archive/history state.
An archive script runs before archiving and handles resources outside the workspace; do not add a
script to delete its own workspace. Sources: [workflow](https://www.conductor.build/docs/concepts/workflow)
and [scripts](https://www.conductor.build/docs/reference/scripts).

For each confirmed-removable ordinary worktree or proven abandoned filesystem residue:

- For a registered non-Conductor worktree, use `git worktree remove <path>` without `--force`.
  Allow minutes for `node_modules` deletion; monitor completion rather than impose a short timeout.
  If interrupted, retain the saved inventory and recheck the gate. A `prunable` entry is not permission
  to delete: preserve identity evidence before pruning, and classify any remaining directory below.
- For an unregistered directory, first prove it is abandoned filesystem residue, not still managed by
  Conductor. Unknown management status → BLOCK. Apply the full identity, merge, data and idle gates,
  then get an EXTRA confirmation naming that exact canonical path before manual recursive removal.
  Never replace failed `git worktree remove` with root-prefix/idle-only `rm -rf`.

For each confirmed branch, including a branch-only orphan or a branch left after app archiving:

- Delete the branch with `git branch -D <branch>`, but ONLY after Step 3 #1's merge gate passed. Do NOT
  reach for `git branch -d` as the "safe" form here: its merged test is against the CURRENT HEAD, so a
  stale worktree (HEAD behind the default branch) makes it REFUSE a branch genuinely merged to
  `origin/<default>` — a false negative that leaves the leftover uncleaned. The Step 3 gate (ancestor of
  `origin/<default>` OR gh `MERGED`) is the real seatbelt; `references/git-pr-deploy.md` § "Deleting a
  merged branch safely" owns this rule. Never `-D` a branch that did not pass the gate.
- Remote branch, only if extra-confirmed AND its tip author is Simon's (Step 4's `%ae %an` check):
  `git push origin --delete <branch> …` (batch them in one push). Never a branch someone else authored.

The normal worktree removal deletes its `.context` directory, including the plan, canonical dashboard,
mockups, evidence and runtime receipt. Never preserve a second dashboard archive during cleanup; promote
the durable decisions and verdicts first through `references/planning-and-tracking.md`.

Then once, at the end: `git worktree prune -v`, only after preserving the mapping evidence.
Verify `git worktree list` AND every exact inventory path. A completed workspace cleanup requires the
whole matching tree, including `node_modules`, build caches and listed dashboards, to be absent;
verify owned aliases are absent as links and stopped viewer PIDs remain gone. Verify removed local
refs with `git show-ref --verify --quiet refs/heads/<branch>` returning nonzero.

## Step 6 — report verified disk cleanup and pending archives

Repeat `du -sk` for surviving inventory paths and workspace roots; record absent paths as zero with
an explicit absence check. Report before/after KiB, completed paths, retained paths with reasons,
and exact workspace names/paths still awaiting app archive. Do not credit ref deletion as reclaimed
workspace storage, or an archive request as completed disk cleanup. Name managed workspaces from
verified inventory evidence; aliases are hints, never ownership proof. For a true branch-only cleanup
with no matching directory, report branch removal and zero workspace storage reclaimed.
TEST: every proposed path has a verified absent result or a named pending/blocked reason.

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
repo-wide remote purge (a shared remote is hundreds of others' branches)** · **keep-list Simon names is
hard-excluded ABOVE the gate** · **the merged-remote-counterpart offer is SURFACED in the gate, never
left for Simon to ask** · **a remote counterpart authored by a TEAMMATE is never offered or deleted —
only Simon's own, by `%ae %an` tip author** · **orphan and interrupted-deletion directories require
saved identity, merge and data-safety proof plus exact-path extra confirmation; idle/root alone is
insufficient** · **Conductor-managed workspaces stay pending until Simon archives them in the app
and disk verification passes** · **a dashboard viewer is exempt from the idle block only after its
receipt, plan path, output path and process command all match that worktree; stop it after confirmation,
then re-run the idle gate** · `lsof +D` hangs (use `-d cwd`) · stale/duplicate aliases require a proven
target mapping; never follow them outside scope.
