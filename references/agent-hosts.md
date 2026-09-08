# Native agent hosts

Keep rules, references, skills, identity and project connector manifests under `~/.claude`.
Use `bin/agent_runtime.py` for the Codex adapter; use `settings.json` for shared hook commands.
Keep account credentials in each host's own store. Never copy OAuth tokens between hosts or profiles.

## Instructions and skills

Run `python3 ~/.claude/bin/agent_runtime.py install` once. Add `--conductor` to configure its executable.
It links the same
`dotfiles/codex-AGENTS.md` into both `~/.codex/AGENTS.md` and `~/.codex-work/AGENTS.md`.
Review an existing AGENTS.md before using `install --replace`; replacement archives it once.
Keep `AGENTS.override.md` absent unless an intentional temporary override is required.
Bootstrap retains the existing `~/.agents/skills` links to the canonical skill directories.

The native entrypoint explicitly loads `CLAUDE.md` and `rules/*.md`. The SessionStart adapter
also reads them from disk, so new rule files need no copied index or generated instruction bundle.
Follow the host's higher-priority instructions when a shared rule names another host's tools.

## Launch and refresh

`bin/codex_print.py` supplies the launcher's local `codex -p` print mode using the same native runtime and
credential routing. It does not replace the interactive host or change its model configuration.
For Full Claude/Full Astra workflow selection and child-model policy, read
`references/parallelization.md` § Choose and preserve the agent setup.

Put `-p` or `--print` first for the local print extension; use `--profile` for native profile
selection. Other invocations, including `exec`, `mcp` and Conductor's `app-server`, pass through.

Launch with `~/.claude/bin/codex-launch.py`, or `codex` after sourcing the shell snippet.
In Conductor, set `codex_executable_path` in `~/.conductor/settings.toml` to that absolute path.
Keep model selection, provider configuration and authentication in native Codex configuration.
The adapter never replaces built-in model instructions or edits credential files.

Each launch resolves `--cd`, then `CONDUCTOR_WORKSPACE_PATH`, then the current directory;
matches the git origin to one manifest; and passes current MCP definitions and hook dispatcher
definitions to the real executable through native `-c` arguments. No projection is written to disk.
An ownership receipt under the chosen home's `.agent-runtime/` stores server names only; it disables
removed entries so an obsolete native registration cannot silently become active again.
Use `AGENT_CODEX_BIN` for an explicit executable override. Otherwise the launcher selects the
newest installed stable Codex under `CONDUCTOR_AGENT_BINARIES_DIR`, or the macOS default
`~/Library/Application Support/com.conductor.app/agent-binaries` when that variable is absent,
before searching PATH. Non-executable files, prereleases and the launcher itself are skipped.
TEST: `~/.claude/bin/codex-launch.py --version` reports the selected binary without changing authentication.

Use `identity.local.json` to select the credential home: work origin -> `~/.codex-work`,
other origins -> `~/.codex`. The session hook rejects a different manifest or boundary inside a running
process. Start a separate process when switching projects. Keep an explicitly chosen model/provider intact.

Restart the Codex process after changing connector definitions or hook event registrations.
An already-running app-server retains its startup configuration; a new thread in that process
does not reload MCP servers. Restart Conductor when its server process remains alive.
Existing hook commands are read from `settings.json` on each event, and rule contents on SessionStart.
For immediate instruction updates in an existing conversation, explicitly re-read the changed rules.
TEST: change a fixture rule/hook/connector once; the next read/event/launch observes it with no copy step.

## Hooks

Review native definitions in `/hooks` in the selected Codex profile before relying on enforcement.
Do not use `--dangerously-bypass-hook-trust` as a default. The native instruction file remains active
when hooks have not been trusted. A changed definition can require another native review.

The dispatcher reads the shared event wiring, preserves block/ask decisions, maps native shell and
agent tools, and extracts every apply_patch source/destination for the shared edit guards.
Its own native context replaces Claude's connector precheck, whose auth cache describes Claude only.
SessionEnd transcript metrics remain Claude-only until their parsers accept Codex's transcript format;
do not claim parity for those metrics. The adapter does not copy Claude permission/sandbox settings.

## Connectors and authentication

Read `references/connectors-setup.md`. The manifest's service/CLI/secret metadata stays authoritative.
Only supported stdio/HTTP MCP records become native Codex MCP settings; non-MCP records stay metadata.
On-demand and opposite-boundary connector records remain disabled. Unsupported fields fail with a
named validation error instead of silently dropping settings. Literal HTTP auth headers are rejected.

Run `python3 ~/.claude/bin/agent_runtime.py doctor --cwd <workspace>` for metadata-only diagnostics.
Run the launcher with `mcp list` to check native status, then `mcp login <name>` when OAuth is missing.
Authenticate to the project account in the browser; the manifest's Claude `/mcp` steps are not Codex UI.
Never report a connector authenticated merely because it is declared or registered.

## Verification

Run `python3 bin/agent_runtime.test.py` and `python3 hooks/config-contract.test.py` from the config root.
Keep tests inside temporary homes with fake executables; do not spend model calls or contact cloud services.
Verify a fresh Conductor session names the selected manifest and applies shared instructions before tools.
Keep the native runtime's trust/auth steps explicit in the hand-back when human interaction remains.

## Upstream references

- https://learn.chatgpt.com/docs/agent-configuration/agents-md
- https://learn.chatgpt.com/docs/build-skills
- https://learn.chatgpt.com/docs/hooks
- https://learn.chatgpt.com/docs/extend/mcp?surface=cli
- https://code.claude.com/docs/en/memory
- https://www.conductor.build/docs/reference/mcp
- https://www.conductor.build/docs/troubleshooting/issues

Verified 2026-09-08 with Codex CLI 0.142.5. Use Python 3.11+ for the adapter's TOML round-trip tests.
