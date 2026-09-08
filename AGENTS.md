# AGENTS.md

Simon's personal Claude Code config (`~/.claude`), version-controlled in this config repo.

**To set up / reproduce this on a machine:** follow **[README.md](README.md) § "🤖 Agent setup"** —
execute the steps in order; they're idempotent.

**Hard rules for any agent working in this repo:**
- **Never commit a secret.** An allowlist `.gitignore` + a `*.key|pem|p12|pfx|env|token|credentials|id_rsa`
  belt guard it — still scan staged content before any push.
- **Stop and ask Simon** for anything under README.md § "Secrets to recreate". Never invent, guess, or
  fabricate a credential, token, key, UID, or URL.
- Only push to this config repo (Simon's own account).
- Track **only Simon's own** config. Do not add third-party skills (gstack / impeccable / agency-agents)
  or runtime data — they're excluded on purpose.
- When Simon's config changes, commit it here via the **`/sk:claude-config-sync`** skill (reviews the diff +
  secret-scans first), or `git -C ~/.claude add -A && git -C ~/.claude commit && git -C ~/.claude push`.
  A `gitleaks` pre-commit hook + the allowlist `.gitignore` block any staged secret. No background daemon.

## Native host adapters

Keep shared rules and hook wiring in their existing sources. Read `references/agent-hosts.md`
before changing native adapters. `bin/agent_runtime.py` projects connector metadata at Codex
launch and dispatches shared hooks; `dotfiles/codex-AGENTS.md` is the linked native entrypoint.
Run `python3 bin/agent_runtime.test.py` plus the config contract suite after adapter changes.
Never copy credentials between Claude, default Codex, and work Codex homes.

## Shared workflow dashboard

Read `ABOUT.md` for the user-facing overview and `references/workflow-loops.md` for the protocol.
Keep the thin entry skills `work-gauntlet-loop` and `work-ralph-loop` in the `sk` plugin.
Keep shared runtime in `bin/workflow-dashboard.*`; plan and mockup skills compose the same catalog.
Run `python3 hooks/config-contract.test.py` after changes; it includes the dashboard runtime tests.
Use the test-only intake state override in that suite so verification cannot clear live session gates.
