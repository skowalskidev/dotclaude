# Connectors & credentials

Always-on rule for how Claude uses external connectors (Firebase, Linear, Stripe, Twilio, AWS, pal, …)
across my work and personal projects. Complements `security.md` and `config-repo.md`. Deep how-to + the
manifest schema live in `references/connectors-setup.md`; each project's connectors are declared in
`~/.claude/connectors/<project>.json`.

For Codex setup and diagnostics, apply `references/agent-hosts.md`.
TEST: identify the host, credential home and manifest before diagnosing unavailable tools.

## Discover the provisioned path FIRST

Before any work that REACHES a project service — auth, login, screenshots, seed/read/write a DB or
cloud, hit an API, boot against a real backend — read `~/.claude/connectors/<project>.json` +
`references/connectors-setup.md` (and `browser-debugging.md` for login/screenshots) and use the
provisioned path, never an improvised cloud-CLI or boot recipe (it produces a bogus auth gate).
**Delegating it? Carry the connector + `auth.steps` + reference INTO the subagent's prompt** — it won't
read the manifest unless told, so it improvises (the fix for a boot+screenshot agent that guessed
"emulator-first" when the `firebase` MCP + the repo's e2e sign-in bridge were provisioned). TEST: before
any such step, here or in a subagent prompt, the manifest + reference were read and the path traces to them.

**DO complete these three capability checks before asking for auth or reporting access unavailable:**
1. Discover current host tools and connected apps/plugins, native MCP status and installed/enabled state.
2. Read project and shared manifests, host credential home and fallbacks; verify the intended identity
   and environment through existing evidence or one bounded read-only check per candidate path.
3. Verify the exact requested action with tool schemas or CLI version/help and current official
   support. Use an authorized capable path within the same credential and write boundaries.
Apply the catalog's Capability diagnosis section. A fallback never authorizes bypassing a policy
denial, installing a connector or moving credentials.

DO scope results to host, profile and action. A signed-out test browser does not invalidate a working
CLI or connector. Keep installed, exposed, authenticated and action-capable separate.
TEST: an auth question names the missing action and checked paths; zero authorized capable paths
remain unchecked.

## The auth-gate protocol (after capability checks, ask once and wait)

DO enter this gate only after the checks above establish an action ONLY Simon can do: authentication,
consent, a required install/restart or a gated write. Surface the exact missing action at first need:

1. **Detect early** at session start and first need. Treat precheck warnings as evidence about their
   recorded host/path, then complete capability checks before labeling the task blocked.
2. **Ask once for the human-only step**, with the checked paths and exact remaining blocker. Stop
   dependent work; keep independent authorized work moving. Never work around a confirmed policy denial.
3. **Give numbered, copy-pasteable steps** from the manifest's `auth.steps`, adapted through the host
   reference. For an unlisted account connector, verify the active host's official instructions.
   Never invent login steps or ask to reconnect working access.
4. **Wait, leaving open what he needs.** No credential copying, guessing, or repeated auth prompts.
5. **Resume the blocked task first** once I reply "done" / "restarted" / an explicit write-confirmation.

## Work / personal boundary

Work = the repo's `git origin` matches your work org (workOrgMatch in your identity overlay). Never cross resources:
- **Work credentials:** AWS Secrets Manager (via `apps/api` `dogfood()` at startup) is the source of
  truth for runtime secrets (Twilio, Stripe, SendGrid, …) — do NOT hand-add them to a per-worktree
  `.env`. Anything else is a `chmod 600` file outside every repo, at its manifest's `secret.path`.
- **Personal credentials:** machine-local, gitignored (`.env`, or the platform's own store).
- **No secret-manager vault here, and adding one is not the default.** The provider's own IAM is the
  source of truth: a key is minted on demand from a connector's `auth.steps`, kept `chmod 600` at
  its `secret.path`, regenerated not mirrored into a vault. A plaintext secret on disk → fix scope + file
  mode (least-privilege key, `600`, outside the repo, rotate if exposed), never "move it into 1Password".
  Propose a vault only if I ask.
- **Model APIs go through `pal` only.** DO make an API-billed model call only through the `pal` MCP, with
  a key from the repo's own boundary (pal holds a work key, so work repos only) and Simon's per-call yes
  (`rules/spend-approval.md`). DON'T call OpenAI or Gemini from the shell; the guard denies it in every
  repo. Subscription workers and reviews stay the default. TEST: `mcp__pal__*` in a personal repo, or a
  shell model-API call anywhere, is denied.
- **Never** commit a secret, and never write one into `~/.claude` (a pushed git repo). The
  `work-resource-guard.sh` hook enforces the boundary on MCP tools (data-driven from the manifests) and
  Bash; if it blocks something I need, tell me plainly (per `security.md`).
- **Keep personal / project-local config OUT of team repos** — rule owned by `engineering-standards.md`
  § "Personal / meta tooling is not a project artifact"; connector detail lives in
  `~/.claude/connectors/*.json` and keys at each `secret.path`, both outside every repo.
- **And never COMMIT them, not just ignore them** (git commands stay unblocked, so `git add` works):
  `~/.gitignore_global` ignores the secret patterns (`*serviceAccountKey*.json`, `.firebase/`, `.env.op`)
  so `git add -A` never stages them; gitleaks/pre-commit scans content on commit (the `~/.claude` repo
  gates with gitleaks; team repos rely on their own CI); and I never force-add a secret past `.gitignore`.

## Prod / live safety (never write unless I ask for that specific write)

Prod is READ-ONLY by default (`firebase-prod` uses an IAM viewer key; Stripe production a restricted
read-only key). Never attempt a prod/live write unless I explicitly ask for that exact change. When a
task needs one, surface it up front: the write pathway is SEPARATE — enabled on demand, confirmed per
write, torn down after (`/sk:setup-connectors enable-prod-write <platform>`, then I confirm the exact
change). No prod data is touched until both happen.

## Manifest convention (one generic engine, per-project specs)

Keep project detail only in `connectors/<project>.json`; use the shared engines and
`/sk:setup-connectors` for setup or repair. Follow the manifest schema in the reference above.
