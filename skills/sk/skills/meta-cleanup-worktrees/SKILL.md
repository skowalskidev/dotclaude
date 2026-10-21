---
name: meta-cleanup-worktrees
description: Safely clean up DONE git worktrees, their Conductor folders, plan dashboards, and branches for this repo. Remove only proven finished, clean, idle workspaces; preserve current/main checkouts. Retire a finished task-owned current local ref separately while preserving its workspace. Reuse existing cleanup authorization, list exact candidates and confirm only uncovered actions. For disk cleanup, measure the whole requested root and prune verified inactive generated caches without deleting source or branches. Block removal with another live session, uncommitted changes or unpreserved unique work; unmerged drafts require authorized reviewed retirement and recovery. Offer merged remote counterparts separately within remote-write authority, limited to owned branches. Use for "delete Conductor archives", "free disk space in Conductor", "clean up archived Conductor caches", "clean up Conductor folders", "clean up merged worktrees", "remove done worktrees and branches", "delete finished dashboards", "tidy up my worktrees", "delete merged branches", "which sessions can I archive", or /sk:meta-cleanup-worktrees.
argument-hint: "[optional repo path; defaults to the current repo]"
---

# Clean up DONE worktrees and branches — safely

Sweep the worktrees and branches for THIS repo that are provably finished, clean and idle.
Remove ordinary worktrees and request Conductor archives through the app. Verify the matching folders
are gone before calling whole-workspace cleanup complete. For disk-space requests, use cache pruning
below as a separate operation. NEVER remove source or branches still being worked on.
DO list exact candidates before deleting, reuse recorded authorization and confirm only uncovered actions.

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

Default branch/worktree cleanup to this repo only: every worktree `git worktree list` reports for it,
wherever it lives. Don't hardcode a root: this machine keeps worktrees under `<repo>/.claude/worktrees/`, other setups under
`~/conductor/workspaces/<project>/*`, and filtering to one prefix silently no-ops the whole run on the
other layout. The safety is the EXCLUSIONS plus the gate, never a path prefix: never the main checkout,
never the current worktree, never a detached-HEAD worktree. Expand to other repositories only on an
explicit cross-repository request; an explicit whole-root disk cleanup covers all projects beneath that
root. Read the bundled Conductor skill at
`/Applications/Conductor.app/Contents/Resources/conductor-skill/skills/conductor/SKILL.md` before
handling Conductor workspaces. Only the user controls local managed workspaces through the app;
there is no local workspace CLI/API. Never mutate its database or bypass its archive flow.
Preserve main clones and shared application state; never recursively delete `~/conductor` or infer
permission to delete an archive from its archived status. Distinguish these operations:

- **Task-owned ref-only closure:** apply `references/git-pr-deploy.md` § Task-owned ref-only closure
  in any repository. This narrow current-branch exception preserves the current workspace;
  whole-workspace exclusions and Conductor's app archive flow remain in force.
- **Workspace/branch lifecycle:** follow Steps 1–6 and the full merged/clean gate; app-managed
  workspace archiving remains user-controlled through Conductor.
- **Disk/cache pruning:** first measure the WHOLE requested root with `du -sk`, then each top-level
  category, including `workspaces`, `archived-contexts`, `repos` and other children. Inventory the
  largest paths in every category; an archives-only or workspaces-only sweep is incomplete for a root
  request. Use the cache gate below, then Steps 4–6 only for its confirmed cache paths; do not fetch,
  delete refs, prune worktree metadata or remove workspace folders during a cache-only pass.
- **Explicit archive deletion:** “delete archives” authorizes removal of archived filesystem contents,
  including old source, materials and evidence, without another permission request or merge/reproducibility
  proof. Resolve the exact canonical archive root from the request/context; retain every keep-list path.
  Record paths and `du -sk` sizes, prove they are archives rather than active managed workspaces, and
  require no active users, cwd users or open files using the cache gate's activity check. Never traverse
  symlinks outside that scope. Recheck scope, keep-list, links and activity immediately before deletion;
  unresolved scope/activity → BLOCK. Preserve app databases/chat metadata outside the requested archive
  root and active workspace lifecycle. Follow Steps 4–6 for these authorized paths, skipping lifecycle
  operations and cache reproducibility checks; verify absence or name retained exceptions.

### Cache gate for ordinary disk-space or archive-cache cleanup

Treat that request as authorization to dispose of verified inactive generated contents within its
scope, including archive directories; do not request permission again for already authorized caches.
Keep the exact keep-list above all candidates. Preserve unique source, materials, designs, attachments,
secrets and chat/app metadata by default; explicit archive deletion uses its separate scope above. Never equate an ignored path with a cache.

Prove each candidate is an untracked, reproducible generated directory from its contents/metadata and
project configuration: e.g. Xcode DerivedData with matching plist metadata, dependency installs with
retained manifests/lockfiles, `.next` outputs, or old test-result bundles whose needed evidence is
already retained. A basename alone is insufficient. Use generator metadata or saved ownership evidence
when archive Git metadata is absent; unresolved ownership, reproducibility or unique-data questions → BLOCK that candidate.
Record canonical root/path, owning project/archive, evidence, size and action; reject links escaping
scope and never traverse them. Require no active workspace users, cwd users or open files beneath the
candidate: filter one `lsof -nP` snapshot by exact path boundaries, never `lsof +D`; incomplete visibility
→ BLOCK. Recheck identity, keep-list, links, data classification and activity immediately before deletion.

An idle unmerged or dirty workspace may pass this cache gate: preserve its source, branch and dirty
files, remove ONLY the proven generated paths. Whole-folder merge/clean gates do not govern cache-only
pruning. Keep current-workspace caches excluded; touch main-clone caches only when the explicit request
includes that context and this same gate passes. Report unresolved or active cache paths as retained.
TEST: an unmerged workspace's disposable cache can be reclaimed while its source and branch remain;
an archive's unique design file remains even when a generated sibling directory is removed.

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

**DO enumerate every BRANCH-ONLY local head, including unresolved unique work.** This is
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
Each that PASSES the merge gate (Step 3 #1) is a 🌱 branch-only candidate. A missing upstream does
not block independently proven merged work; PR status alone never proves the current tip merged.
DO list every candidate that fails the gate as retained with its tip, unique-commit count, owner or unknown ownership, reason and next action. Never hide unmerged branches from the
inventory or infer that they are disposable from age or naming.

DO resolve unique work when Simon explicitly authorizes needed merges. Inspect the full unique diff,
current default branch, ownership and existing decisions; review and run required checks before
landing a still-needed change through the repository's shipping workflow. A cleanup request alone
never authorizes merging. Keep conflicts, unknown ownership, failed checks and missing authority as
specific blockers with a retry action. Do not merge obsolete code solely to make a branch deletable.

DO retire a superseded unmerged draft only with recorded authority covering that draft, a fresh review
of its entire unique diff against the kept implementation, and zero unexplained still-needed changes.
Preserve its recoverable commits and necessary evidence outside deletion targets before removing refs;
verify that recovery can be read back from a Git bundle or retained reachable ref. A bare SHA or reflog
is not durable recovery. Keep bundles outside tracked trees with mode `600`; never publish recovery
history or add a tag without separate authorization. A prior report or a "superseded" name is evidence to inspect,
never deletion authority. An explicit repository cleanup covers reviewed candidates in that scope;
reuse that authorization instead of asking again for each branch. Resolve actual ownership, needed-work
or scope uncertainty before removal.

DO preserve backup/recovery refs by default. Within an authorized cleanup, migrate a redundant recovery
ref to a private external bundle only after preserving its exact tip and all reachable history,
restoring it into a temporary local repository, and verifying the restored tip and object integrity.
Record the bundle location outside deletion targets, then remove only the redundant local ref.
An explicit keep-list still wins; this recovery migration never authorizes publishing history.
TEST: a requested repo sweep accounts for every local head; a task-end pass covers only its owned
refs. Every unique branch is reviewed for an authorized merge, verified retirement or recovery migration, or retained with
an exact reason and next action.

**A REMOTE part branch is the OWNING run's job, not a repo-wide purge.** A hyperspeed part that pushed
then had its workspace archived leaves a branch on origin — but hyperspeed Step 6 deletes that remote by
the name it recorded (even for an aborted run, from its status dir). Do NOT enumerate every
remote-head-with-no-local here and offer it: on a shared team remote that is HUNDREDS of other people's
branches (measured), and deleting one is a destructive shared-remote write against work you don't own.
meta-cleanup only ever deletes the REMOTE COUNTERPART of a LOCAL orphan it is already removing, and only
as Step 4's separate extra-confirmed step.

## Step 3 — the SAFE gate (ALL must hold, or BLOCK with a printed reason)

For whole-worktree or ordinary branch removal, EVERY check must pass. Scope's task-owned ref-only
closure and cache-only pruning use their separate gates:

1. **Disposition:** apply the shared catalog's § Deleting a merged branch safely to the exact tip:
   ancestry, verified merged-PR-head containment or full content proof. Unmerged exceptions are Step 2's authorized,
   reviewed superseded draft or verified recovery migration; record that proof separately from merge
   evidence. Never describe it as merged.
2. **Clean:** `git -C <wt> status --porcelain` is empty.
3. **Nothing unpreserved:** require the disposition proof to cover the entire current tip, including
   any post-merge commits; being pushed alone does not prove they merged. For an authorized superseded draft or recovery migration,
   require its verified recovery to cover every local-only commit instead; an unpushed commit must
   never disappear with the ref.
4. **Idle:** no process except a verified dashboard viewer is cwd'd in the worktree —
   `lsof -nP -d cwd | grep -F <path>` (NEVER `lsof +D`, which recurses the whole tree and hangs).
   A verified viewer is removable-after-confirmation and appears in the candidate table with its PID;
   a live `claude`/`node` session or unverified viewer → BLOCK. An idle `zsh` sitting in it → removable
   but WARN (removing it orphans that shell's cwd). Cross-check with `bin/port-registry.sh reap`.
5. **Protected paths/refs:** exclude current, main, default, detached HEAD, backup/recovery refs and
   the explicit keep-list from whole-workspace removal. Scope's task-owned ref-only closure is the
   sole exception for the current local branch, never another session's attached ref.
   Step 2 permits only a verified migration of a redundant recovery ref within
   authorized cleanup scope; it never overrides the keep-list.
6. **Owned and disposable:** require Step 2's repository/branch identity proof and no unique user
   data in EVERY workspace proposed for removal, including ordinary Git worktrees and app archives.
   Keep the tracked-file clean/disposition checks; also inventory untracked AND ignored paths and classify
   each as reproducible output or safely preserved user data. A clean Git status alone is insufficient.
   Inspect metadata/paths without exposing credential contents. Copied secrets, local databases and
   unknown ignored files are not disposable caches; unresolved data safety → BLOCK.
   For orphan or interrupted-deletion directories, compare tracked files to the saved merged HEAD.
   Missing metadata or refs requires equivalent saved proof of identity, disposition and data safety;
   inability to establish any of them → BLOCK. Idleness and root membership alone never pass.

A PR that is CLOSED-but-not-merged is NOT merged. Retain it unless the separate authorized supersession
proof passes; its closed status alone never authorizes removal. A merged branch with NO worktree is a 🌱
branch-only candidate (Step 2 enumerates these): apply the same entire-tip proof without needing a
worktree or surviving upstream. Delete its ref only after the inventory and gate; do not
claim disk cleanup while a matching directory remains.

## Step 4 — present and resolve authorization

Show a table, grouped: ✅ removable · ⏳ app archive required · ⛔ blocked (with the exact reason) ·
🌱 branch-only. Include repository, branch/HEAD, exact path, aliases, before-size and planned action. Then use
AskUserQuestion for actions not already authorized and act ONLY within Simon's confirmed scope.
For cache-only pruning, list exact generated paths and their evidence separately from whole worktrees.

For each removable worktree, list its canonical `.context/*-dashboard.html` files and any verified
viewer PID under `Dashboard cleanup`. The worktree confirmation covers deleting those disposable files
with the worktree and stopping those exact viewers; it never covers a mismatched or unrecorded process.

**Honor an explicit keep-list.** When Simon names branches or worktrees to keep, HARD-EXCLUDE them from
every removable group before presenting — above the gate, even for ones the gate would already block.

**Offer the merged remote counterparts as their OWN opt-in question when not already authorized.**
For every ✅/🌱 local orphan being removed, record whether its remote counterpart exists. Apply Step 3's
merge proof to that remote tip independently, then list eligible owned remotes. Reuse an existing
explicit remote-deletion instruction; otherwise ASK before this separate shared-remote write.
Default uncovered remote deletion to no, but surface its disposition in the same inventory.

**Only the user's OWN remote branches.** A shared remote holds teammates' branches, so before offering a
remote confirm its live proven tip author is Simon's: `git log -1 --format='%ae %an' <proven-tip>` matches his git
author (the `skowalskidev` GitHub identity / a `simon@` email). NEVER offer or delete a remote branch
someone else authored, even when it is the counterpart of a local orphan Simon is removing.

## Step 5 — remove, safely (only after yes)

For confirmed cache or explicitly authorized archive paths, re-run the corresponding Scope gate,
delete only those paths and skip workspace/branch lifecycle operations below. For whole-worktree candidates, recheck identity,
branch/HEAD, path/link targets, keep-list, cleanliness,
local-only commits, tracked/untracked/ignored data safety and idleness immediately before destruction. Changed evidence → BLOCK and refresh
its inventory; an earlier yes never covers a different path or newly created work.

- For each verified dashboard viewer listed at the gate, run
  `python3 "$HOME/.claude/bin/workflow-dashboard.py" stop <plan> --expect-pid <pid>`. The helper re-runs
  the receipt/worktree/output/command checks, sends `TERM` only to that confirmed PID, waits up to 5
  seconds and verifies it exited. If ownership changed or it survives, BLOCK that worktree instead of
  widening the kill. Re-run the idle check after the viewer exits.

For a Conductor-managed workspace, ask Simon to archive its exact workspace name and canonical path
in the Conductor app. Leave it pending until he does, then verify the disk result. Do not run
`git worktree remove` or `rm` on the workspace itself, even when idle. Preserve Conductor's archive/history state.
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

- Delete the branch with `git branch -D <branch>`, but ONLY after Step 3 #1's disposition gate passed. Do NOT
  reach for `git branch -d` as the "safe" form here: its merged test is against the CURRENT HEAD, so a
  stale worktree (HEAD behind the default branch) makes it REFUSE a branch genuinely merged to
  `origin/<default>`. Step 3's entire-tip proof is the seatbelt. For an authorized superseded draft or recovery migration, use its separately recorded
  retirement and recovery proof, never a fabricated merge result. Never `-D` without the gate.
- Remote branch, only within explicit remote-deletion authority AND its tip author is Simon's (Step 4's `%ae %an` check):
  use the shared catalog's live-tip proof and expected-tip deletion condition. Never delete from a
  stale remote-tracking ref or touch a branch someone else authored.

The normal worktree removal deletes its `.context` directory, including the plan, canonical dashboard,
mockups, evidence and runtime receipt. Never preserve a second dashboard archive during cleanup; promote
the durable decisions and verdicts first through `references/planning-and-tracking.md`.

After workspace/branch lifecycle cleanup only: `git worktree prune -v`, only after preserving the mapping evidence.
Verify `git worktree list` AND every exact inventory path. A completed whole-workspace cleanup requires the
whole matching tree, including `node_modules`, build caches and listed dashboards, to be absent;
verify owned aliases are absent as links and stopped viewer PIDs remain gone. Verify removed local
refs with `git show-ref --verify --quiet refs/heads/<branch>` returning nonzero.

## Step 6 — report verified disk cleanup and pending archives

DO reconcile the before/after inventory of local refs, their remote counterparts and worktrees with
every planned action. For repo cleanup include all local heads; for task closure include only refs
created or adopted by that task. Record a separate disposition for each local ref, remote counterpart
(including already absent) and workspace, plus each retained main/default, active, recovery or blocked
item's reason and next action. Verify local absence directly, including branch-only leftovers;
remote auto-deletion never proves a local ref disappeared. Keep pending app archives separate.
TEST: zero inventory rows lack a disposition; neither clean status nor remote deletion alone proves
cleanup complete.

Repeat `du -sk` for the requested root, every measured category and surviving candidate paths;
record removed paths as zero with an explicit absence check. Report actual before/after KiB for root
and categories, removed paths, retained paths with reasons, and exact workspace names/paths awaiting
app archive. Do not credit ref deletion as reclaimed
workspace storage, or an archive request as completed disk cleanup. Name managed workspaces from
verified inventory evidence; aliases are hints, never ownership proof. For a true branch-only cleanup
with no matching directory, report branch removal and zero workspace storage reclaimed.
For cache-only pruning, verify only cache paths are absent and source/branches remain. Branch-only
ref counts never satisfy a disk-space request. TEST: every candidate has a verified result or reason;
the report accounts for the whole requested root, not just workspace listings. After archive deletion,
re-evaluate remaining large categories within the original cleanup scope and report the next safe
reclamation candidates or their blocking reasons.

## The gotchas this skill must never trip

Squash/rebase merge (verify merged PR head and reachable merge commit) · no-upstream branch (use
entire-tip proof) · current/main workspace preserved (task-owned ref-only closure is separate) ·
merged-but-running (block on another live session) ·
merged-but-idle-shell (warn) · dirty tree (never `--force`) · detached HEAD (skip branch logic) · PR
closed-not-merged (never merge proof) · **branch-only orphan whose worktree is already archived (Step 2 enumerates
all heads-with-no-worktree, including unresolved unique work)** · **`git branch -d` is
HEAD-relative, so a stale worktree makes it refuse a genuinely-merged branch (gate on `origin/<default>`
ancestry, then `-D`)** · **local `master` enumerated when the main checkout sits on a feature branch
(filter `$DEF` out of the branch-only `comm`, never rely on it being checked out)** · **gh-`MERGED` or
being fully pushed alone never proves post-merge commits disposable** · **a remote part branch is the owning run's job (hyperspeed Step 6, by recorded name) —
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
