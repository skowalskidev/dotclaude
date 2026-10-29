# Config repo — keep ~/.claude in sync

## My ~/.claude config is a git repo — keep it in sync (source of truth)

This config lives in `~/.claude`, a git repo mirrored to your **public** GitHub repo.
Keep this single source of truth synced; verify both working-tree state and branch completion.

- **DO finish tracked config changes through `/sk:claude-config-sync`** under the standing authority
  in `rules/self-healing-config.md`. Do not leave a verified repair waiting for a commit question.
  Its land check (`bin/config-land-check.py`) lets the push to main through with no confirmation.
  **Not `work/` or `skills/sk-work`** (untracked; the diff would be empty).
- **When the STRUCTURE changes — update the companion/manifest docs in the SAME change** so they never
  go stale: a new/renamed/removed rule, hook, skill, `bin/` script, `connectors/` manifest, or tooling dep
  means updating `README.md` (the inventory table + `Agent setup` + `Secrets to recreate`), `AGENTS.md` if
  affected, the `CLAUDE.md` index line, and `dotfiles/Brewfile` for a new dependency. `README.md` is the
  reproduce-on-a-new-machine manifest; a stale one silently breaks setup. This is part of "done" for a
  structural change — and if a change misses it, the `self-healing-config` rule catches it.
- A **SessionStart hook** (`hooks/config-status.sh`) surfaces uncommitted config at the start of each
  session; reconcile ownership and resume authorized repairs. No background daemon: syncing is event-driven.
- **The remote is PUBLIC. NEVER commit a secret (keys, tokens, `.env`, credentials) or a real account,
  org, project or email**; those stay in the untracked overlay. The allowlist `.gitignore` + `gitleaks`
  gate cover secrets only, so read the diff yourself; if unsure, ask.
- Keep config **only** in `~/.claude` so the repo captures everything; anything that belongs in my
  Claude config goes under `~/.claude` so `git status` catches it.
- **Route EVERY `~/.claude` change through `/sk:claude-config-update` — mandatory, whenever Simon asks
  for a config change, "create a new skill" included, unprompted.** It fits the structure (thin
  `CLAUDE.md` index, one concern per `rules/*.md`, deep how-to in `references/*.md`, enforcement in
  `hooks/`, engine in `bin/`, flows in `skills/`), checks authorization, and keeps the
  contracts/routing tests in step. Use the native Skill tool when present, otherwise read and follow
  its canonical `SKILL.md`. This is the routing and review workflow, not a second approval lock.
  Existing explicit or standing authorization covers the edit; no sentinel or tool-call receipt is
  required. Native approvals and the secret, credential, worktree and git guards remain in force.

## Return to main after completed work

DO finish config work with clean, synced main and zero finished local/origin branches.
Keep GitHub's `delete_branch_on_merge` enabled. Apply `references/git-pr-deploy.md` § Config
repository completion at session start and hand-back.
TEST: only main or evidenced active/protected/blocked refs remain.
