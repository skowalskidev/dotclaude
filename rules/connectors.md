# Connectors & credentials

Always-on rule for how Claude uses external connectors (Firebase, Linear, Stripe, Twilio, AWS, pal, …)
across my work and personal projects. Complements `security.md` and `config-repo.md`. Deep how-to + the
manifest schema live in `references/connectors-setup.md`; each project's connectors are declared in
`~/.claude/connectors/<project>.json`.

## Discover the provisioned path FIRST

Before any work that REACHES a project service — auth, login, screenshots, seed/read/write a DB or
cloud, hit an API, boot against a real backend — read `~/.claude/connectors/<project>.json` +
`references/connectors-setup.md` (and `browser-debugging.md` for login/screenshots) and use the
provisioned path, never an improvised cloud-CLI or boot recipe (it produces a bogus auth gate).
**Delegating it? Carry the connector + `auth.steps` + reference INTO the subagent's prompt** — it won't
read the manifest unless told, so it improvises (the fix for a boot+screenshot agent that guessed
"emulator-first" when the `firebase` MCP + the repo's e2e sign-in bridge were provisioned). TEST: before
any such step, here or in a subagent prompt, the manifest + reference were read and the path traces to them.

**DO check the FALLBACK before reporting a project capability unavailable — an MCP failing to connect is
not a missing capability.** ToolSearch finding none of a stdio MCP's tools means the SERVER didn't load,
not that the service is down. Read the fallback from the manifest, the project's `CLAUDE.md`, and its
`CLAUDE.local.md`, then drive the same endpoint another way — an SDK + credential, a CLI, or a library
(e.g. firebase MCP down → `firebase-admin` + the work ADC; chrome-devtools MCP down → Playwright over
CDP on the debug port). TEST: no capability is called unavailable until those sources were read and the
fallback tried.

## The auth-gate protocol (ask me FIRST, then wait)

When a task needs an action ONLY I can do — authenticate, start a service, install a tool, restart the
session/app, or use a capability the connector withholds (e.g. a prod/Firestore write) — do NOT grind
around it or bury it at the end. Instead:

1. **Detect early** — at session start (the precheck hook flags already-expired connectors) and at the
   first point of need. A missing/blocked connector is surfaced as obviously as any hard blocker.
2. **Stop and ask FIRST**, before starting the task and before any workaround.
3. **Give numbered, copy-pasteable, right-sized steps** — no lecture. Use the exact `auth.steps` from
   this project's manifest; never invent them. e.g. "1. Run `stripe login --project-name=work-prod`
   2. Confirm 'configured for your work org'  3. Reply done."
4. **Wait.** No degrading, guessing, or grinding. Only genuinely UNRELATED parallel work may continue.
5. **Resume the blocked task first** once I reply "done" / "restarted" / an explicit write-confirmation.

Distinguish the failure so the fix is right:
- **Needs authentication** (expired/absent OAuth) → I run `/mcp` and re-authenticate. Only I can — a
  hook/agent can't refresh it.
- **Down / unreachable** (a local server is off) → start the service; this is NOT an auth problem.
- **Not loaded yet** (a just-provisioned MCP server loads next session) → tell me up front to restart,
  then reply "restarted".
- **Blocked by design** (a prod write via a read-only connector) → see prod safety below.

## Work / personal boundary

Work = the repo's `git origin` matches your work org (workOrgMatch in your identity overlay). Never cross resources:
- **Work credentials:** AWS Secrets Manager (via `apps/api` `dogfood()` at startup) is the source of
  truth for runtime secrets (Twilio, Stripe, SendGrid, …) — do NOT hand-add them to a per-worktree
  `.env`. Anything AWS does not serve is a machine-local file under `~/.config/**`, outside every repo.
- **Personal credentials:** machine-local, gitignored (`.env`, or the platform's own store).
- **No secret-manager vault here, and adding one is not the default.** The provider's own IAM is the
  source of truth: a key is minted on demand from a connector's `auth.steps`, kept `chmod 600` under
  `~/.config/**`, regenerated not mirrored into a vault. A plaintext secret on disk → fix scope + file
  mode (least-privilege key, `600`, outside the repo, rotate if exposed), never "move it into 1Password".
  Propose a vault only if I ask.
- **Never** commit a secret, and never write one into `~/.claude` (a pushed git repo). The
  `work-resource-guard.sh` hook enforces the boundary on MCP tools (data-driven from the manifests) and
  Bash; if it blocks something I need, tell me plainly (per `security.md`).
- **Keep personal / project-local config OUT of team repos** — rule owned by `engineering-standards.md`
  § "Personal / meta tooling is not a project artifact"; connector detail lives in
  `~/.claude/connectors/*.json` and keys in `~/.config/**`, both outside every repo.
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

The engine is generic and lives in `~/.claude` (`bin/connectors-provision.sh`,
`hooks/session-connectors.sh`, `hooks/work-resource-guard.sh`, `/sk:setup-connectors`). Each project's
connectors — servers/CLIs, their env, boundary, read/write policy, `auth.steps` — live ONLY in
`~/.claude/connectors/<project>.json`. Run `/sk:setup-connectors` to set up or repair them, `add` for a
new one; onboarding a project = drop in a new `<project>.json`. Don't hard-code connector detail elsewhere.
