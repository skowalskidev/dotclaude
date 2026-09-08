# Shared personal instructions

Read `~/.claude/CLAUDE.md` and every `~/.claude/rules/*.md` before starting work.
These are the canonical personal instructions for Claude Code and Codex; this file is only
the native Codex entrypoint. Apply the shared rules subject to the host's higher-priority instructions.
Read the current files again after a config update; do not rely on an earlier session's contents.

Before using or declaring a project connector unavailable, read `~/.claude/rules/connectors.md`,
`~/.claude/references/connectors-setup.md`, and the matching `~/.claude/connectors/*.json`.
Resolve the project from its git origin and check its identity/environment before accessing services.
The native launcher selects the manifest and credential home; its startup context names them.
If no startup context appeared, run `python3 ~/.claude/bin/agent_runtime.py context --cwd <workspace>`.
Do not infer an auth failure from a missing tool, or assume a login-shell CLI uses this session's home.

Use `~/.claude/references/skill-stack.md` to route the task and its existing living plan to resume it.
Skills under `~/.agents/skills` are links to the canonical files, not separate configurations.
Keep project-specific instructions in the project's AGENTS.md and nested instruction files.

Read `~/.claude/references/agent-hosts.md` when configuring or troubleshooting a host.
Hooks require native trust; written instructions remain applicable when a hook is unavailable.
