# Simon's Claude config (`~/.claude`)

Version-controlled subset of `~/.claude`: my global instructions, hooks, guards, and my own
skills. The **files here are the source of truth** and `git log` is the change history — there's no
hand-maintained list to go stale.

Made by Simon. Fork it and make it yours.

## Make it yours (quickstart)

1. Clone it to `~/.claude`: `git clone https://github.com/skowalskidev/dotclaude.git ~/.claude` (or clone elsewhere and point Claude Code at it).
2. Install the tools: `brew bundle --file dotfiles/Brewfile` (gitleaks, jq).
3. Run `bash dotfiles/bootstrap.sh`. It wires the safe parts (dotfile symlinks, hook bits, the secret-scan gate), scaffolds `identity.local.json` from the template, then prints a checklist of anything left to do and **fails loud until it is all done**. Re-run it until it says `Ready`.
4. Edit `identity.local.json` with your own accounts: the git-origin substring that marks a WORK repo, your work and personal emails, and your work and personal cloud projects. Untracked, so it is never pushed; it drives the work/personal guard and the boundary context injected each session.
5. Set up connectors per project with `/sk:setup-connectors` (or copy `connectors/example.json.example` to `connectors/<project>.json`). Schema and steps in `references/connectors-setup.md`.

Your accounts live only in the untracked overlay files (`identity.local.json`, `connectors/*.json`), so nothing personal is ever committed. The full step-by-step an agent can run is in [§ Agent setup](#-agent-setup-run-in-order); `bootstrap.sh` automates its mechanical parts and tells you what is left.

> ## 🤖 For an AI agent
> **These are setup instructions written for you to execute.** If the user points you at this repo and asks
> you to set up their Claude config on a machine, follow **[§ Agent setup](#-agent-setup-run-in-order)**
> below, in order. The steps are **idempotent** — safe to run again on a machine that's already set up.
>
> **Hard rules (do not break):**
> - **Never commit a secret.** An allowlist `.gitignore` + a `*.key|pem|p12|pfx|env|token|credentials|id_rsa`
>   belt guard against it — but still scan staged content before any push.
> - **Stop and ask the user** for anything under [§ Secrets to recreate](#secrets-to-recreate-ask-the-user--never-fabricate).
>   **Never invent, guess, or fabricate** a credential, token, key, UID, or path.
> - Only ever push to this config repo (your own account).
> - This repo tracks **only your own** config. Do not add third-party skills or runtime data (see
>   [§ Not tracked](#not-tracked-and-why)).

## Inventory (what's tracked)

| Path | What |
|---|---|
| `CLAUDE.md` | Thin **index** for all projects — points at `rules/` + `references/` and the project-boundary rule; the actual rules live in `rules/` |
| `rules/` | **Always-on** behavioral rules (auto-loaded every session, one concern per file): `security`, `communication`, `copy-quality`, `process`, `engineering-standards`, `ui-conventions` (always-on; `paths:` scoping is ignored at user level), `skills-workflow`, `config-repo`, `connectors`, `self-healing-config` |
| `references/` | **On-demand** deep how-to catalogs (zero context cost until read; shared by `CLAUDE.md` + the `sk` skills): `research` (read at the start of every workflow run, not on demand), `contracts-and-outcomes`, `planning-and-tracking`, `parallelization`, `testing-strategy`, `dev-server-hygiene`, `code-best-practices`, `git-pr-deploy`, `api-empirical-iteration`, `browser-debugging`, `connectors-setup`, `skill-stack`, `user-journey-review`, `tldr-report-formats` |
| `settings.json` | Hook wiring + `permissions.deny` (DENY-only, no `ask` tier, so nothing prompts) |
| `hooks/intent-ledger.sh` | UserPromptSubmit + Stop — appends every ask verbatim to the worktree's `.context/intent-ledger.md`, and blocks the finish when a ratified plan has no reconciliation. The only hook that writes into a project, so its refusals are the contract; redirects out of the tracked tree inside `~/.claude`. Kill switch: `CLAUDE_INTENT_LEDGER=off` |
| `hooks/task-intake.sh` | UserPromptSubmit + PreToolUse + PostToolUse — proposes the skills for a new task, and DENIES Agent/Task/Workflow until you confirm |
| `hooks/config-contract.test.py` | The config's own acceptance criteria: plain-English outcomes, each backed by a check, with a coverage ratchet |
| `contracts/config_contracts.py` | What every config part is FOR and what must stay true about it. Enforced both ways by the contract test: a part with no entry fails, an entry naming a missing file fails |
| `contracts/routing_scenarios.py` | Which part should fire for a given request, in Simon's own words, plus deterministic hook-matcher cases. Catches the silent failure where a skill never triggers because its description speaks the wrong language. Zero model calls |
| `contracts/skill_naming.py` | The `<group>-<what-it-does>` prefixes skills are named by, so typing a group narrows the slash menu instead of scrolling all 16. The suite fails on a skill matching no group; the principle behind it is in `references/code-best-practices.md` |
| `hooks/retro-trigger-log.sh` | SessionEnd hook — appends one JSON line of guard-denial counts to `~/.claude/logs/`. Detects and reports only; `/sk:claude-config-self-development-research` reads it for class-level findings |
| `bin/install-third-party-skills.sh` | Clones the third-party skill packs `references/skill-stack.md` stacks on |
| `hooks/work-resource-guard.sh` | PreToolUse work/personal isolation guard — Bash + data-driven `mcp__.*` connector boundary (from `connectors/`) + Firebase prod write-guard. Also denies a CLI left unpinned when its own default profile belongs to the other boundary |
| `hooks/work-resource-guard.test.py` | Its both-directions suite, driven through the hook's real stdin contract. The 9 must-NOT-fire cases pin that a name in prose is never a block |
| `hooks/crown-jewel-read-guard.py` | PreToolUse Bash guard — denies a file-READING verb pointed at a crown-jewel secret, closing the Bash hole the `Read` deny rules cannot reach. Asks about the verb, not the command text |
| `hooks/crown-jewel-read-guard.test.py` | Its both-directions suite. The 12 must-NOT-fire cases include all four false positives that retired the old guard |
| `hooks/config-edit-guard.py` | PreToolUse Edit/Write guard — hard-blocks an edit to a tracked `~/.claude` config file unless `/sk:claude-config-update` set the `.config-edit-authorized` sentinel. Makes that skill the only path to change config; runtime state and memory writes stay open. Override: `CLAUDE_CONFIG_EDIT=1` |
| `hooks/git-commit-guard.py` | PreToolUse Bash guard — blocks a commit/push on `main`/`master` (config repo exempt) and a `git commit` with `-m`/heredoc (the `-F`-only rule). Overrides: `CLAUDE_ALLOW_MAIN_COMMIT=1`, `CLAUDE_ALLOW_COMMIT_M=1` |
| `hooks/background-process-guard.py` | PreToolUse Bash guard — blocks installing a persistent process (crontab install, `launchctl load`, `systemctl enable`, LaunchAgents/Daemons writes). Override: `CLAUDE_ALLOW_DAEMON=1` |
| `hooks/browser-launch-guard.py` | PreToolUse guard on `mcp__chrome-devtools__*` — blocks the page-launch tools (`new_page`, `navigate_page`) so a frontend change is not auto-verified in the browser without asking. Override: `CLAUDE_ALLOW_BROWSER=1` |
| `hooks/session-connectors.sh` | SessionStart hook — read-only connector precheck: flags a connector needing re-auth, notes any manifest server not set up. Does NOT provision; that is `/sk:setup-connectors` |
| `bin/connectors-provision.sh` | Generic connector engine — reads `connectors/<project>.json`, registers local-scope MCP servers, reports missing key files. Fetches no secrets |
| `connectors/` | Per-project connector manifests (`<project>.json`): which connectors each project uses, boundary, env, read/write policy, CLI profile, auth steps. No secrets — only paths |
| `skills/sk/` | My personal (`/sk:*`) skill plugin. **`skills/sk-work/` is NOT tracked** — see [§ Not tracked](#not-tracked-and-why) |
| `dotfiles/zsh-work-codex.zsh` | The live `~/.zsh-work-codex.zsh` (symlinked here) — work/personal `CODEX_HOME` switch |
| `dotfiles/gitignore_global` | The live `~/.gitignore_global` (symlinked here), git's `core.excludesFile` — personal/secret patterns plus `.context/`, so the agent scratch dir is ignored in every repo without touching any committed `.gitignore` |
| `hooks/config-status.sh` | SessionStart hook — flags uncommitted config so Claude offers to sync |
| `hooks/worktree-freshness.sh` | SessionStart hook — warns once when this worktree's branch is 10+ commits behind main, so stale-base work is caught before it starts rather than at merge. Detects and reports only |
| `hooks/orphan-worker-sweep.sh` | SessionStart hook — reports (never kills) orphaned framework dev-tool worker processes machine-wide (PID 1 parent + interpreter/dev-tool match + cwd inside a git checkout). Detection delegates to `bin/kill-orphan-workers.sh --list` |
| `bin/kill-orphan-workers.sh` | Clears the orphans `hooks/orphan-worker-sweep.sh` reports — kills the whole process family (not just the parent, which only reparents its children), re-scans for survivors, escalates to `-9`, verifies. `--dry-run` / `--list` / no-arg |
| `hooks/port-registry-sweep.sh` | SessionStart hook — reconciles the shared port registry and reports (never kills) who holds which local dev port. Silent when nothing is claimed |
| `bin/port-registry.sh` | Machine-wide port coordination between sessions that can't see each other: `claim` / `release` / `check` / `list [--tsv]` / `wait` / `reconcile` / `reap`. Exit 3 = held by another live session, 4 = a listener nobody claimed, 5 = a lane whose workspace is gone but whose server still listens. A lane survives with no listener while a live Claude session works in that workspace. Writes `~/.claude/port-registry.md` (untracked). Protocol in `references/dev-server-hygiene.md` |
| `bin/port-slot.sh` | Gives a worktree its own LANE of dev ports (slot 0-9, `base + N*10`) so several sessions run stacks at once. Claims lazily, sweeps eagerly, kills only a server whose worktree was deleted, records each run to `logs/isolate-runs.jsonl` (self-trimming). Base ports discovered, never hardcoded. Driven by `/sk:work-isolate-environment` |
| `.githooks/pre-commit` + `dotfiles/secret-scan.sh` | Secret gate (gitleaks + grep fallback) — blocks any commit staging a secret |
| `.githooks/commit-msg` | Conventional-commit gate — rejects a non-conforming subject line. The written standard lives in `references/git-pr-deploy.md`; this makes it bite in this repo |
| `dotfiles/sync-config.sh` | On-demand commit + push of config changes (used by `/sk:claude-config-sync`) |
| `dotfiles/Brewfile` | Reproducible CLI deps (gitleaks, jq) — `brew bundle` |
| `skills/sk/skills/claude-config-sync/` | The `/sk:claude-config-sync` skill — safe commit + push of this repo |
| `skills/sk/skills/setup-connectors/` | The `/sk:setup-connectors` skill — guided connector setup + doctor + migration audit (no arg does all three) |
| `skills/sk/skills/claude-config-self-development-research/` | The `/sk:claude-config-self-development-research` skill — quarterly research pass over the config, the skills, the packs and the CLI deps against primary sources; proposes, never applies |
| `bin/superspeed-dispatch.sh` | Engine for `/sk:work-superspeed` — fans a task out across real parallel `claude -p` sessions from a `slices.json` spec (exclusive file ownership per slice), sets `CLAUDE_INTAKE_GATE=off` on each, verifies every slice on disk rather than by exit code (`anthropics/claude-code#74761`), and logs timings, tokens and status per slice |
| `bin/superspeed-dispatch.test.sh` | Regression test for the dispatcher, with `claude` stubbed so it spends nothing. Asserts the one failure no other signal catches: that the run EXITS once its slices do. A bare `wait` also waits on the concurrency sampler it kills afterwards, which deadlocks a run whose slices all succeeded. Also asserts the sampler stops, the per-slice completion lines and parallel summary are printed, and each slice writes its own status so a killed run still holds the truth |
| `bin/superspeed-analyse.py` | Turns one superspeed run directory into waste metrics and actions: idle capacity, slice imbalance, cache read/write ratio, achieved concurrency, ownership leaks, duplicated reads, reconcile rework, dead slices, fan-out-worth-it, plus the log's own `INSTRUMENTATION GAPS`. Writes `analysis.json` |
| `bin/dotclaude-redact.py` | The one need-to-know minimization layer for config metrics — scrubs secrets + PII and drops file/code/command content before any event is stored or committed. Fail-closed; pure functions |
| `bin/dotclaude-log.py` | The one shared writer for config metrics — minimizes, boundary-scopes, appends to a local outbox first, then batch-flushes to the `dotclaude-metrics` Firestore project. Never blocks or fails a session; no-ops to the outbox when no project is configured |
| `bin/config-metrics-record.py` | SessionEnd recorder — parses the ended session's transcript into minimized per-part events (prompt/tool_call/hook_deny/error) and writes them via the shared writer. Work-boundary sessions contribute the signal but no request text |
| `bin/config-metrics.py` | The self-analysis engine — scores every config part two-axis (reachable × used) from the store, classifies dead/underused/erroring/instrumentation-gap/new/safety/stub, writes `aggregates/*`, and renders a terminal scoreboard + `--html` console. Parts list comes only from `contracts/config_contracts.py` |
| `hooks/config-metrics-log.sh` | SessionEnd hook — hands the transcript to `bin/config-metrics-record.py` under the metrics venv (else system python3). Detects and records only; never proposes, prompts, or edits |
| `contracts/part_criticality.py` | Tags the parts whose low usage is expected — safety/compliance (warranted-dormant) and deliberate stubs (planned) — so the metrics self-analysis never flags them as defects |
| `references/dotclaude-metrics-setup.md` | Generic, placeholder-only setup for your own `dotclaude-metrics` Firebase project (create project, least-privilege key, venv, locked rules). Public-template-safe |
| `skills/sk/skills/claude-config-metrics-self-analysis/` | The `/sk:claude-config-metrics-self-analysis` skill — reads the metrics store, scores every part, and proposes a trigger FIX so a dead/underused part gets used (never a removal by default). Proposes only |
| `skills/sk/skills/work-superspeed/` | The `/sk:work-superspeed` skill — cut a task into 3-5 exclusively-owned slices, dispatch them as parallel sessions, reconcile warm in the orchestrator, then analyse the run. Measured 2026-08-06: beat in-session subagents in all 4 configs and all 14 reps, by a fixed ~33s |
| `skills/sk/skills/claude-config-self-optimize-analysis-after-run/` | The `/sk:claude-config-self-optimize-analysis-after-run` skill — reads one run's logs and proposes the specific partition and instrumentation changes for the next run; proposes, never applies |
| `skills/sk/skills/ship-mockup-before-after/` | The `/sk:ship-mockup-before-after` skill — builds a dev-only before/after preview of a planned change inside the project using its OWN components (never hand-written HTML, never a rebuilt screen), cites the validated plan behind each difference, and is deleted when the work lands. Any repo |
| `skills/sk/skills/work-preview-on-phone/` | The `/sk:work-preview-on-phone` skill — puts a running dev server on your phone over Tailscale Serve (tailnet-private, never Funnel), binds the server to loopback first so the LAN cannot reach it, clears the silent cross-origin allowlist trap, and mints a dev-only API credential rather than widening production's. Any repo |
| `skills/sk/skills/work-isolate-environment/` | The `/sk:work-isolate-environment` skill — wires a project so this session's dev stack runs on its own lane of ports (`bin/port-slot.sh` allocates, this decides the per-project knobs). Any repo, personal or work, containerised or host-run |
| `skills/sk/skills/meta-report-standup-weekly/` | The `/sk:meta-report-standup-weekly` skill — the spoken Monday standup script, sourced from git + `gh` + Linear over a window rather than from you. Collapses commits into outcomes and refuses to call a draft PR shipped |

## 🤖 Agent setup (run in order)

### Preconditions — check first, install what's missing
- **macOS** with Xcode Command Line Tools (`xcode-select -p`), so `/usr/bin/python3`, `git` exist.
- **GitHub CLI** `gh` installed and authenticated **as your personal account** — verify: `gh auth status`
  (must show your account). If not authenticated, tell the user to run `gh auth login` — do not proceed.
- **Node** via `nvm` if you'll build anything. Per `rules/engineering-standards.md` that means the
  current Active LTS, and a project's own `.nvmrc` always wins over any version named here — run
  `nvm install && nvm use` inside the repo. As of Aug 2026 the Active LTS lines are 22 and 24
  (20 is EOL; 26 becomes LTS in Oct 2026). Do not pin a number in this file — it goes stale, and
  `hooks/config-contract.test.py` fails the build when it names an EOL runtime.
- **Username:** `settings.json` hook commands use absolute `$HOME/...` paths. If your `settings.json`
  still carries a hardcoded home dir, repoint the paths at your own `$HOME`: `sed -i '' "s#/Users/<olduser>#$HOME#g" ~/.claude/settings.json`.

### Steps
1. **Clone the repo into `~/.claude`.**
   - If `~/.claude` does **not** exist yet (Claude Code never run): `git clone https://github.com/skowalskidev/dotclaude.git ~/.claude`
   - If `~/.claude` **already exists** (Claude Code created defaults): this overwrites config files — **back up first and confirm with the user before running:**
     ```bash
     cp -R ~/.claude ~/.claude.bak-$(date +%Y%m%d)   # backup
     cd ~/.claude && git init && git remote add origin https://github.com/skowalskidev/dotclaude.git
     git fetch origin && git checkout -f main         # ASK THE USER — overwrites tracked config files
     ```
   - Then run `bash ~/.claude/dotfiles/bootstrap.sh`: it does steps 2–4 and 6 below (the safe, idempotent parts) and prints a fail-loud checklist of the rest. The steps below are what it automates, plus the human-judgment parts (secrets, shell edits) it leaves to you.
2. **Symlink + wire the shell snippet.**
   ```bash
   ln -sf ~/.claude/dotfiles/zsh-work-codex.zsh ~/.zsh-work-codex.zsh
   ln -sf ~/.claude/dotfiles/gitignore_global ~/.gitignore_global
   git config --global core.excludesFile ~/.gitignore_global
   ```
   Ensure this exact line is present in **both** `~/.zprofile` and `~/.zshrc` (append if missing — ask the user before editing their shell files):
   ```bash
   [ -f "$HOME/.zsh-work-codex.zsh" ] && source "$HOME/.zsh-work-codex.zsh"
   ```
3. **Make the hooks executable** (git preserves the bit, but ensure it): `chmod +x ~/.claude/hooks/*.py ~/.claude/hooks/*.sh ~/.claude/.githooks/*` — the `.githooks` ones too, or a non-executable `commit-msg` silently no-ops while reading as enforcement.
4. **Install tooling + enable the secret-scan gate** (see [§ Staying in sync](#staying-in-sync-no-daemon)):
   ```bash
   brew bundle --file ~/.claude/dotfiles/Brewfile     # gitleaks, jq
   git -C ~/.claude config core.hooksPath .githooks    # secret gate + conventional-commit gate
   ```
   The SessionStart sync-reminder hook is already wired in `settings.json` (no separate install). There is
   **no background daemon** — syncing is on-demand via the `/sk:claude-config-sync` skill.
5. **Install the third-party skill packs** (intentionally NOT tracked here — they're other people's
   repos, ~1.6 GB, and reinstallable):
   ```bash
   ~/.claude/bin/install-third-party-skills.sh
   ```
   It clones `gstack`, `impeccable` and `agency-agents` and prints the two `/plugin marketplace add`
   commands for Anthropic's own skills and the official plugin marketplace, which Claude Code
   installs itself. `--check` reports without changing anything. The URLs live in that script, so
   setup no longer stalls on a question the user has to answer. `references/skill-stack.md` says which
   pack is stacked on for which task shape, and records the adoption number each had to clear.
6. **Add the per-worktree lane state to the global git excludes.** `~/.gitignore_global` is machine-local
   and deliberately not tracked here, so this line does not survive a rebuild on its own. Without it,
   `bin/port-slot.sh` leaves an untracked `.claude-slot.json` visible in every repo it runs in, including
   work repos teammates can see:
   ```bash
   git config --global core.excludesFile "$HOME/.gitignore_global"   # already set on this machine
   grep -q '\*\*/.claude-slot.json' ~/.gitignore_global || printf '\n**/.claude-slot.json\n' >> ~/.gitignore_global
   ```
   Global rather than per-repo on purpose: one line covers every repo, personal and work, with no
   per-repo setup and nothing in anyone's committed `.gitignore`.
7. **Secrets — see the next section. Stop and ask the user; do not fabricate.**
8. **Verify (idempotent checks — all should pass):**
   ```bash
   /usr/bin/python3 ~/.claude/hooks/config-contract.test.py  # every criterion passes
   readlink ~/.zsh-work-codex.zsh                            # -> $HOME/.claude/dotfiles/zsh-work-codex.zsh
   git -C ~/.claude status --short                           # clean working tree
   ```
   `config-contract.test.py` is the one that matters: it re-checks the other two, the hook wiring,
   the JSON validity, the secret gate and the doc claims. Neither suite states a pass COUNT here —
   a hardcoded count drifts, and a stale one teaches the next agent to accept a wrong number.

### Secrets to recreate (ask the user — never fabricate)
These live **outside** this repo and are **not** committed. Prompt the user for each; never invent one.
- `~/.codex-work/` — WORK Codex home (apikey auth). Recreate: `CODEX_HOME=~/.codex-work codex login`, or set a work `OPENAI_API_KEY` with `auth_mode=apikey`.
- `~/.claude.json` — Claude Code's main config (MCP servers, OAuth). Reconfigure MCP servers with `claude mcp`.
- The `pal` MCP server's `.env` (work OpenAI/Gemini keys) — separate repo, ask the user.
- Firebase / service-account keys — referenced by path in `CLAUDE.md`; ask the user to place them.
- Connector credentials (work), set up per project by **`/sk:setup-connectors`** (see `rules/connectors.md` + `references/connectors-setup.md`). All live OUTSIDE this repo. Each connector's manifest carries the exact recreate steps in its `auth.steps`; those are the source of truth, not this list:
  - `~/.config/gcloud-work/` — the WORK gcloud config home. Keeping it separate from the default `~/.config/gcloud` (personal) is what stops the work account and its ADC leaking into personal projects. Recreate with the steps in your work connector manifest (`connectors/example.json.example` shows the shape; `references/connectors-setup.md` documents it).
  - `~/.config/firebase-mcp/work-dev/`, `~/.config/firebase-mcp/work-prod/` — stub project dirs. `firebase mcp` has no `--project` flag, so the project and the account both come from the dir (`.firebaserc` + the configstore's per-directory entries). Pinning them there is what stops a worktree drifting the target.
  - `~/.config/firebase-keys/work-prod-readonly.json` — read-only (IAM viewer) prod key. Regenerated on demand with `gcloud`; GCP IAM is the source of truth, so there is no secret store to restore from. Steps are in the `firebase-prod` entry.
  - Stripe CLI profiles in `~/.config/stripe/config.toml` (`stripe login --project-name=work-sandbox|work-prod`, plus a personal profile per that project's manifest). Note `work-prod` grants FULL live keys — nothing mechanical makes it read-only. `[default]` is a work profile, so personal repos must always pin `--project-name=`; the guard enforces it.
  - **There is no secret store.** Every credential above is minted on demand from its connector's `auth.steps` and kept `chmod 600` outside this repo. Nothing to restore from a vault, and nothing to recreate here beyond running those steps.

### Agent boundaries
- **Do without asking:** read files, run `config-contract.test.py`, `git status`/`log`, `readlink` checks.
- **Ask the user first:** `git push`, package installs, `chmod` outside `hooks/`, editing `~/.zprofile`/`~/.zshrc`, the overwrite in step 1 (Case B), anything that creates or reads a credential.
- **Never:** commit a secret; fabricate a credential/token/key/URL; add third-party skills or runtime data to this repo.

## Staying in sync (no daemon)

The GitHub repo is the single source of truth. Syncing is **event-driven / on-demand — there is no
background daemon** (deliberately, to avoid idle CPU):

- **One source of truth locally:** `~/.claude` *is* the git working tree, so every config file lives in
  exactly one place. The one file that used to live outside (`~/.zsh-work-codex.zsh`) is a **symlink**
  into `dotfiles/`. So `git -C ~/.claude status` is the whole litmus test — anything uncommitted or
  unpushed = out of sync.
- **Reminder at session start:** the `hooks/config-status.sh` SessionStart hook runs one local
  `git status` and reports uncommitted, unpushed AND unpulled changes, so Claude offers to sync. It
  also kicks off a detached `git fetch` at most once every 4 hours, purely to keep `@{upstream}`
  fresh across machines. That fetch never blocks session start and is not a background process.
- **The sync itself:** the **`/sk:claude-config-sync`** skill (reviews the diff, secret-scans, writes a
  conventional commit, pushes) — or the one-shot script `bash ~/.claude/dotfiles/sync-config.sh`.
- **Two secret gates, both blocking:** the allowlist `.gitignore` + a **`gitleaks`** pre-commit hook
  (`.githooks/pre-commit` → `dotfiles/secret-scan.sh`, with a credential-format grep fallback when
  gitleaks isn't installed). Install gitleaks via `brew bundle --file dotfiles/Brewfile`.

## Not tracked (and why)
- **Secrets/credentials** and **runtime data** (`projects/`, by far the largest, holding conversations + auto-memory; `tasks/`,
  `sessions/`, `telemetry/`, `shell-snapshots/`, `logs/`, `cache/`, `backups/`, `plans/`, `history.jsonl`,
  `config.json`, …) — excluded by the allowlist `.gitignore`.
- **Third-party skills** (`skills/gstack`, `impeccable`, `agency-agents`) — reinstallable, each its own
  git repo (~1.6 GB total), plus the `skills/*` symlinks into `.agents/`.
  Two stale gstack copies were removed on 2026-08-04, reclaiming 1.7 GB: `gstack.bak` (same HEAD as
  `gstack`, byte-identical once its dereferenced symlinks were compared) and `.gstack-backup` (an older
  HEAD, but one reachable from `origin/main`, so re-clonable rather than unique). Keep it that way: a
  snapshot of a public repo is not a backup, it is a copy of something upstream already has.
- **Plugins** (`plugins/`) — marketplace clones, reinstallable.
- **Work skills** (`work/sk-work/`, reached via the symlink `skills/sk-work`) — job-specific, so
  they stay out of a repo that is otherwise portable across machines and jobs. Untracked by OMISSION
  from the allowlist rather than by an ignore rule: `/skills/*` and the top-level `/*` already cover
  both paths, so nothing had to be added and `git add -A` cannot stage them.
  **⚠️ This directory is unversioned and backed up by nothing.** A bad edit or an `rm` is
  unrecoverable. A work skill's own SETUP doc may capture a one-time provisioning that nobody will
  reconstruct from memory, so copy it somewhere before touching it. It is also outside the repo's
  secret scanning, which is only acceptable because it is never pushed.
  Consequence for this README: the repo is Simon's config source of truth for everything **portable**,
  not literally everything under `~/.claude`.
- **`~/.claude/port-registry.md`** — which local dev port each session holds. Machine-local runtime
  state by definition (ports are a property of this machine, not of the config), so the repo carries
  the path and the protocol while the contents stay out. Already excluded by the allowlist, since a
  new top-level file is ignored unless it is opted in.
- **`~/.claude/logs/isolate-runs.jsonl`** — one line per `bin/port-slot.sh` run, so the next run in a
  worktree is better aimed than the last. Machine-local, self-trimming to 200 lines, and excluded by the
  allowlist. Reading it is step 6 of `/sk:work-isolate-environment`.
- **`<worktree>/.claude-slot.json`** — the lane and discovered port map for ONE worktree, deliberately
  living inside that worktree so deleting it deletes the state. Ignored through `~/.gitignore_global`
  (`**/.claude-slot.json`) rather than any repo's committed `.gitignore`, so one line covers every repo,
  personal and work, and teammates never see it. Not part of this repo.

## Security posture

See `rules/security.md`. The provenance rule there is the primary control; the mechanical layer is
`permissions.deny` in `settings.json` (Read on credential paths, Edit/Write on the key directories),
enforced by the harness with no model vote.

The `hooks/security-guard.py` pattern guard was RETIRED on 2026-08-04 after falsely blocking four
ordinary commands in one session — it matched on a command's TEXT, so naming a sensitive path was
indistinguishable from reading one. It and its 81-case suite are recoverable from git history, but
should not be restored: that defect is structural, not a matter of narrower patterns.

`hooks/crown-jewel-read-guard.py` replaced it the same day, covering the one thing the retirement
actually left open — a secret read out through **Bash**, which path matchers cannot see. It denies
only when a file-READING verb (`cat`, `head`, `xxd`, `base64`, `cp`, …) is pointed at a crown jewel,
so the four historical false positives all pass: `grep` on `settings.json` is not a jewel path,
`cat .npmrc` is not a jewel, `git commit -m "...~/.gnupg..."` has no reading verb, and `nvm use` has
neither. Each is a named test case. Run `python3 hooks/crown-jewel-read-guard.test.py`.

It stops the literal read, not obfuscation or an interpreter opening the file, and it deliberately
still allows passing a credential PATH to a tool (`GOOGLE_APPLICATION_CREDENTIALS=… node x.mjs`).
`rules/security.md` states the full posture, including what remains uncovered.


## Path scoping — why no rule here uses `paths:` frontmatter

`paths:` globs work in a project's `.claude/rules/`, but are **silently ignored at user level** in
`~/.claude/rules/` — reported twice (anthropics/claude-code #21858 Jan 2026, #57722 May 2026),
neither closed with a stated fix.

`rules/ui-conventions.md` carried them until 2026-08-04, which meant it never loaded at all. The
scoping failed open in the wrong direction: the UI rules reached Claude on exactly zero UI tasks,
and nothing surfaced it, because a rule that does not load looks identical to a rule that is being
followed.

Always-on costs ~1.5KB a session. That is the cheaper failure. The project-level pattern in
a personal project (a nested `CLAUDE.md` importing the same rule) is the fix when scoping is genuinely
needed; at user level there is no equivalent, so those rules just load, each with a scope line at
the top telling Claude when to skip it.

## Changing the config
When your Claude config changes (this `CLAUDE.md`, a hook, an `sk` skill, `settings.json`),
commit it here: `git -C ~/.claude add -A && git -C ~/.claude commit -m "..."`. Never commit a secret — the
allowlist `.gitignore` + belt guard it; scan staged content before pushing.
