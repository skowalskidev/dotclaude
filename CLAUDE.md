# Simon's Claude Setup — index

This file is deliberately thin. My instructions are split for SRP/DRY and to keep per-turn context lean:

- **Always-on behavioral rules** → `~/.claude/rules/*.md` (auto-loaded every session, same priority as this file). One concern per file:
  - `security.md` — provenance-gated actions (rogue-skill / prompt-injection guard), MCP/CLI credential safety, the two Firebase/cloud accounts.
  - `communication.md` — response format: consolidate questions at the END, answer in TLDR style (direct first, nuance on demand).
  - `copy-quality.md` — how anything a human reads must be written: never AI-sounding (banned words/phrases/patterns, the em-dash rule), and TL;DR + actionable, checked both ways for redundant clutter and for missing info (Five Ws).
  - `process.md` — how I work: front-load what you need from me at session start, plan + sign-off, verify before retrying, track every task to completion (a mid-run message is queued, never an interrupt; the worktree's intent ledger is the checklist), commit-when-done, don't auto-verify frontend and hand me the new UI's inputs to type myself, worktree discipline, claim ports in the shared registry, clean up processes/scratch/workspaces, project-doc rule, test/QA machine-local secrets.
  - `engineering-standards.md` — latest-stable versions, mainstream tool choice, single-source-of-truth (DRY/SRP), harden-without-breaking, legacy policy, soft-archive-not-delete.
  - `ui-conventions.md` — button order, and minimalist interfaces: default to a label, cut the number of text blocks. Always-on with a scope line at the top, because `paths:` frontmatter is silently ignored at user level and this file consequently never loaded; see the comment in it before re-scoping.
  - `skills-workflow.md` — the skill-listing repo-prefix rule, how my `sk`/`sk-work` skills are organised, when to use my own vs other repos' skills.
  - `config-repo.md` — `~/.claude` is a git repo (this config repo); keep it in sync via `/sk:claude-config-sync`.
  - `connectors.md` — connector/credential system: the auth-gate protocol (ask first with numbered steps, then wait), work/personal boundary, prod read-only + gated writes, and the per-project manifest convention (`~/.claude/connectors/<project>.json`).
  - `self-healing-config.md` — when a config-rooted problem is diagnosed and resolved mid-session, propose a durable fix and ask to fold it in (event-driven, never a cron).

- **Deep, task-only how-tos** → `~/.claude/references/*.md` (on-demand, zero context cost until read):
  - `research.md` · `contracts-and-outcomes.md` · `planning-and-tracking.md` · `parallelization.md` · `testing-strategy.md` · `dev-server-hygiene.md` · `code-best-practices.md` · `git-pr-deploy.md` · `api-empirical-iteration.md` · `browser-debugging.md` · `connectors-setup.md` · `skill-stack.md` · `user-journey-review.md` · `tldr-report-formats.md`
  - `config-writing-standard.md` — how every line of this config is written: DO-led, banned hedge words, the DEFAULT/NUMBER/TEST rule, the mission format. Enforced by `hooks/config-contract.test.py`.
  - `research.md` is read at the START of every workflow run, not on demand like the rest — the opening research pass is step 1 of `/sk:work-full-detailed-workflow`, so Simon never has to ask for it separately.
  - `skill-stack.md` is the one to read at the START of a task: it maps a task shape to the right skill and to the third-party skills that stack on it, so I never have to remember which to use. `hooks/task-intake.sh` points you there on every new task and BLOCKS Agent/Task/Workflow until I've confirmed the proposal.
  - The `sk` skills (esp. `/sk:work-full-detailed-workflow`) point at these same catalogs, so a rule has ONE home.

- **Project-specific** instructions live in each project's own `CLAUDE.md` / `CLAUDE.local.md` (and its `docs/`), never here.

## Where a new lesson goes
- Always-on behavioral rule → the matching `rules/*.md`.
- Deep task-only how-to → the matching `references/*.md` (skills already point to it).
- Project-specific → that project's `CLAUDE.md` (team) or `CLAUDE.local.md` (personal).
- Route it with `/sk:claude-config-update`, which knows this layout (named to stay distinct from Claude Code's built-in `/update-config`, which edits `settings.json` hooks/permissions rather than instructions).
