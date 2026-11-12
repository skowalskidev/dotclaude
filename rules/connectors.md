# Connectors & credentials

How Claude uses external connectors in work and personal projects. Schema, route kinds and recipes:
`references/connectors-setup.md`. The registry is local data, one root per boundary (`connectorRoots`
in `identity.local.json`), never in `~/.claude`.

For Codex setup and diagnostics, apply `references/agent-hosts.md`.
TEST: identify the host, credential home and registry project before diagnosing unavailable tools.

## Resolve the routes FIRST, then fall back on your own

Before any work that REACHES a service (auth, login, screenshots, a DB or cloud read/write, an API, a
message, a real backend), **DO run `python3 ~/.claude/bin/connector_registry.py resolve <capability>`**
in the repo (e.g. `slack.send`, `supabase.read`, `twilio`) and read `references/connectors-setup.md`
(plus `browser-debugging.md` for login/screenshots). Use a listed route, never an improvised cloud-CLI
or boot recipe (it produces a bogus auth gate).
**DO try the routes in the printed order and record every outcome:** `connector_registry.py record
<provider> <route> ok|fail --reason "<what failed>"`. On a failure, take the next route in the same turn
without asking. A BLOCKED route (another Claude login, an on-demand write path) and an open
circuit (failed within 24 h) come last, after every other route failed.
**DON'T ask Simon to reconnect, log in or pick a host while an unblocked route is untried.** A route in
the registry carries his standing authorization to use it (the fix for asking to reconnect Slack while a
recorded OpenAI Slack route worked). `serves` only ranks a route: a route declared for another project
of the same boundary is still tried, after the ones that serve this project.
**Delegating it? Put the resolver output, route record and reference IN the subagent's prompt**
(catalog § Resolve, try, record).
TEST: every service step traces to a resolved route, every attempt has a recorded outcome, and an
auth question names each route tried and its failure.

**DO complete these three capability checks for the route you are on before reporting it failed:**
1. Discover current host tools and connected apps/plugins, native MCP status and installed/enabled state.
2. Read the route record in the registry roots, host credential home and fallbacks; verify the intended
   identity and environment through existing evidence or one bounded read-only check per candidate path.
3. Verify the exact requested action with tool schemas or CLI version/help and current official
   support. Use an authorized capable path within the same credential and write boundaries.
Apply the catalog's Capability diagnosis section. A fallback never authorizes bypassing a policy
denial, installing a connector or moving credentials.

DO scope results to host, profile and action. A signed-out test browser does not invalidate a working
CLI or connector. Keep installed, exposed, authenticated and action-capable separate.
TEST: an auth question names the missing action and checked paths; zero authorized capable routes
remain untried.

## The auth-gate protocol (after every route, ask once and wait)

DO enter this gate only after the checks above establish an action ONLY Simon can do on every
remaining route: authentication, consent, a required install/restart or a gated write. Surface the
exact missing action at first need:

1. **Detect early** at session start and first need. Treat precheck warnings as evidence about their
   recorded host/path, then complete capability checks before labeling the task blocked.
2. **Ask once for the human-only step**, with the routes tried and the exact remaining blocker. Stop
   dependent work; keep independent authorized work moving. Never work around a confirmed policy denial.
3. **Give numbered, copy-pasteable steps** from the route's `auth.steps`, adapted through the host
   reference. For an unlisted account connector, verify the active host's official instructions.
   Never invent login steps or ask to reconnect working access.
4. **Wait, leaving open what he needs.** No credential copying, guessing, or repeated auth prompts.
5. **Resume the blocked task first** once I reply "done" / "restarted" / an explicit write-confirmation,
   and record the route's new outcome.

## Work / personal boundary

Work = the repo's `git origin` matches your work org (workOrgMatch in your identity overlay). Never cross
resources. The resolver returns only the session boundary's root; a fallback never leaves it.
- **Credentials:** keep each in its home from `references/connectors-setup.md` § Secret homes (work
  runtime secrets via AWS `dogfood()`, never a hand-added worktree `.env`; others `chmod 600` outside
  every repo at the route's `secret.path`, or Supabase Vault via a pointer). **Use both, falling back
  between them, via `connector_registry.py run`** (catalog § Hybrid secrets).
- **Model APIs go through `pal` only,** inside its boundary and with Simon's per-call yes; DON'T call
  OpenAI or Gemini from the shell. Detail and TEST: `references/connectors-setup.md` § Model-API keys.
- **Never** commit a secret, and never write one into `~/.claude` (a pushed git repo). The
  `work-resource-guard.sh` hook enforces the boundary on MCP tools (data-driven from the registry) and
  Bash; if it blocks something I need, tell me plainly (per `security.md`).
- **Keep personal config and keys OUT of team repos and never commit them:** `engineering-standards.md`
  § "Personal / meta tooling is not a project artifact" and `references/connectors-setup.md` § Personal
  files stay OUT of team repos.

## Prod / live safety (never write unless I ask for that specific write)

Prod is READ-ONLY by default, whatever a route's key could do (catalog § Prod-write pathway). Never
attempt a prod/live write unless I explicitly ask for that exact change. When a task needs one, surface
it up front: the write pathway is SEPARATE — enabled on demand, confirmed per write, torn down after.
No prod data is touched until both happen. A fallback route inherits the same gate: a gated send or
write still needs its per-message or per-write yes on every route.

## Registry convention (one loader, one file per provider)

Keep connector detail only in the registry roots, read them only through `bin/connector_registry.py`,
and set them up or repair them with `/sk:setup-connectors`.
