---
name: claude-config-sync
description: Commit + push changes to Simon's ~/.claude config repo (his config source of truth — a public GitHub repo) SAFELY. Review the diff, NEVER commit secrets, write a conventional commit, push, confirm in sync. Use whenever ~/.claude has uncommitted config changes (the SessionStart hook flags them), right after editing any config under ~/.claude (CLAUDE.md, a hook, an sk/sk-work skill, settings.json), or when Simon says "sync my config" / "commit my config".
allowed-tools:
  - Bash(git -C ~/.claude *)
---

# Sync Simon's Claude config repo

## Resolve the checkout

DO resolve `sync_root` to the owned config-update worktree for this task, or `~/.claude` when the
owned change is already there. Verify its common Git directory matches `~/.claude` and inspect its
origin before staging. Read status, the full diff and recent commits from that same checkout.
Never stage the live checkout while the task's changes are in a worktree.

`~/.claude` is a git repo and Simon's **single source of truth** for his Claude setup, mirrored to a
**public** GitHub repo. An uncommitted change there = out of sync. This
skill commits + pushes those changes safely.

## Absolute rules
- **NEVER commit a secret.** Not an API key, token, private key, password, `.env`, `*.credentials*`,
  service-account JSON, cookie, or anything that authenticates. Two automated gates exist (the allowlist
  `.gitignore` + a `gitleaks`/grep pre-commit hook), but they are a backstop, not a licence to stop
  looking — **read the diff yourself.** If anything looks secret-like, or you're unsure, **STOP and ask
  Simon** rather than commit it.
- **The remote is PUBLIC: a push publishes.** Besides secrets, STOP on any real account, org name,
  project name or email in the diff. Those belong in the untracked overlay (`identity.local.json`,
  `connectors/*.json`, `work/`), and tracked text stays generic ("your work org").
- **Authority:** apply `rules/self-healing-config.md`. Its standing scope authorizes validated own-config
  repairs through commit, merge, push, activation and cleanup; do not request those approvals again.
  Never force-push, rewrite published history or use this authorization for another repository.
- **Scope:** only Simon's own config (CLAUDE.md, hooks/, settings.json, contracts/, skills/sk,
  references/ (shared on-demand catalogs), rules/ (if present), dotfiles/, README/AGENTS, .githooks/).
  Never add third-party skills or runtime data — the allowlist `.gitignore` handles this; don't fight it.
  **`skills/sk-work` and `work/` are deliberately untracked** (job-specific, see README). They will
  never appear in a diff; if they ever do, something force-added them and that is a bug to report,
  not a change to commit.

## Steps
1. **See what changed:** inspect `git -C "$sync_root" status -sb` and the full owned diff.
   Account for every changed file and exclude unrelated WIP.
2. **Eyeball for secrets** in the diff (see the rules above). This step reads the REAL diff, not the
   summary — `--stat` shows names and line counts, never content, so it cannot clear a file of
   secrets. If clean, continue; if not, stop and ask.
3. **Stage only the reviewed owned paths:** `git -C "$sync_root" add -- <paths>`.
   Review the staged diff and run the secret scanner before committing.
4. **Commit with the message in a FILE, never `-m`:** write it with the Write tool, then
   `git -C "$sync_root" commit -F <file>`. The shell interprets `-m` and heredocs (a backtick runs, a
   `$VAR` expands) and it fails SILENTLY, which is why `~/.claude/references/git-pr-deploy.md` makes
   `-F` absolute at any length. That catalog also owns the subject and body shape — read it there
   rather than composing a message from scratch. Two hooks gate the result: `.githooks/commit-msg`
   rejects a non-conforming subject, and the pre-commit hook runs `gitleaks` (or the grep fallback)
   and **blocks on any secret**. If either blocks, surface the reason to Simon and fix it; never
   bypass with `--no-verify`, which skips the secret gate too.
5. **Land:** follow the worktree flow below for a config-update branch. For an already integrated
   live change, push its verified destination without changing another branch by assumption.
6. **Confirm in sync:** verify the landed branch and `origin/main` have zero commits on either side,
   then activate and clean up as below. Preserve the live checkout's branch name and unrelated WIP.

**A branch from a worktree:** inspect the full `origin/main..<branch>` diff, its evidence and owner.
For a validated repair within standing scope, fetch and merge current `origin/main` into that branch,
resolve conflicts only within the owned change and re-run affected checks on the final state. Commit
with `-F` if needed, secret-scan, then `git push origin <branch>:main`.
A non-fast-forward rejection means another session landed: fetch, reconcile and validate again;
never force-push. Verify `git rev-list --left-right --count origin/main...<branch>` returns `0 0`.

DO activate in `~/.claude` only with a clean tracked tree and no merge/rebase in progress. Preserve its
branch: fast-forward to `origin/main` when possible; otherwise merge it without discarding unrelated
commits. On a conflict, preserve all work and record the exact activation blocker. Re-read current
rules and verify the changed files are present in the live checkout before claiming active.

DO remove the owned temporary worktree and its merged local branch after the commit is on
`origin/main` and activation is verified. If this task published its temporary branch, delete that
owned remote ref after verifying its tip is on main. Check Git registration and disk absence. Keep only
intentional report artifacts; never delete another session's workspace or unmerged unique work.
A pending branch is resumed against evidence and ownership, not blindly landed because it exists.
TEST: a completed sync has a remote commit, verified live files and no owned temporary worktree;
a blocked sync names its exact blocker without another generic commit/merge question.

## Notes
- Manual one-shot equivalent: `bash ~/.claude/dotfiles/sync-config.sh` (stages, secret-scans, commits with
  a timestamp message, pushes). Prefer a descriptive commit via the steps above for real changes; the
  script is the catch-all.
- If `gitleaks` flags a genuine false positive (e.g. a detection pattern in a scanner file), add a narrow
  allowlist to a repo `.gitleaks.toml` rather than disabling the gate.
- If a secret was *already* committed, don't just delete it — tell Simon; it needs history rewrite +
  rotation of the exposed credential.
