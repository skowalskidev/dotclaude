# Config repo — keep ~/.claude in sync

## My ~/.claude config is a git repo — keep it in sync (source of truth)

My whole Claude setup lives in `~/.claude`, which is a git repo mirrored to your **private** GitHub
config repo. That repo is the **single source of truth**: any uncommitted change in
`~/.claude` means it's out of sync, and `git -C ~/.claude status` is the litmus test.

- **After you change ANYTHING TRACKED under `~/.claude`** — this global `CLAUDE.md`, a hook, an `sk`
  skill, `settings.json`, the guard allowlist, anything — **offer to commit + push it** so the repo stays
  current. Use the **`/sk:claude-config-sync`** skill (it reviews the diff, secret-scans, commits, pushes).
  **Not `work/` or `skills/sk-work`** — untracked, so a sync offer there yields an empty diff.
- **When the STRUCTURE changes — update the companion/manifest docs in the SAME change** so they never
  go stale: a new/renamed/removed rule, hook, skill, `bin/` script, `connectors/` manifest, or tooling dep
  means updating `README.md` (the inventory table + `Agent setup` + `Secrets to recreate`), `AGENTS.md` if
  affected, the `CLAUDE.md` index line, and `dotfiles/Brewfile` for a new dependency. `README.md` is the
  reproduce-on-a-new-machine manifest; a stale one silently breaks setup. This is part of "done" for a
  structural change — and if a change misses it, the `self-healing-config` rule catches it (ask-first).
- A **SessionStart hook** (`hooks/config-status.sh`) surfaces uncommitted config at the start of each
  session; when you see that note, proactively offer to sync. There is deliberately **no background
  daemon** — syncing is on-demand / event-driven.
- **NEVER commit a secret** to this repo (keys, tokens, `.env`, credentials, private keys). An allowlist
  `.gitignore` + a `gitleaks` pre-commit gate back this up, but read the diff yourself; if unsure, ask.
- Keep config **only** in `~/.claude` so the repo captures everything — don't scatter my setup elsewhere;
  if something belongs in my Claude config, it goes under `~/.claude` so `git status` catches it.
- **Route EVERY `~/.claude` change through `/sk:claude-config-update` — mandatory, whenever Simon asks
  for a config change, "create a new skill" included, unprompted.** It fits the structure (thin
  `CLAUDE.md` index, one concern per `rules/*.md`, deep how-to in `references/*.md`, enforcement in
  `hooks/`, engine in `bin/`, flows in `skills/`), previews, gates on his yes, and keeps the
  contracts/routing tests in step. **`hooks/config-edit-guard.py` enforces it**: it hard-blocks an
  Edit/Write to a tracked config file unless that flow authorized it. Runtime state (`projects/`,
  `logs/`) is never gated, so memory writes work; the hook's message carries the one-off override.
