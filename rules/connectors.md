# Connectors & credentials

Always-on rule for how Claude uses external connectors (Firebase, Linear, Stripe, Twilio, AWS, pal,
etc.) across my work and personal projects. Complements `security.md` (provenance/credential safety)
and `config-repo.md`. Deep how-to + the manifest schema live in `references/connectors-setup.md`; each
project's connectors are declared in `~/.claude/connectors/<project>.json`.

## Discover the provisioned path FIRST

Before any work that REACHES a project service — auth, login, screenshots, seed/read/write a DB or
cloud, hit an API, boot against a real backend — read `~/.claude/connectors/<project>.json` +
`references/connectors-setup.md` (and `browser-debugging.md` for login/screenshots) and use the
provisioned path, never an improvised cloud-CLI or boot recipe (it's what produces a bogus auth gate).
**Delegating it? Carry the connector + `auth.steps` + reference INTO the subagent's prompt** — it won't
read the manifest unless told, so it improvises (the fix for: a boot+screenshot agent handed an
"emulator-first" guess when the `firebase` MCP + the repo's e2e sign-in bridge were provisioned). TEST:
before any such step, here or in a subagent prompt, the manifest + reference were read and the path
traces to them.

## The auth-gate protocol (ask me FIRST, then wait)

When a task needs any action ONLY I can do — authenticate, start a service, install a tool, restart the
session/app, or use a capability the connector withholds by default (e.g. a prod/Firestore write) — do
NOT grind around it or bury it at the end. Instead:

1. **Detect early** — at session start (the precheck hook flags already-expired connectors) and at the
   first point of need. A missing/blocked connector is surfaced as obviously as any hard blocker.
2. **Stop and ask FIRST**, before starting the task and before any workaround.
3. **Give numbered, copy-pasteable, right-sized steps** — no lecture. Use the exact `auth.steps` from
   this project's manifest for that connector; never invent them. e.g. "1. Run `stripe login
   --project-name=work-prod`  2. Confirm 'configured for your work org'  3. Reply done."
4. **Wait.** No degrading, guessing, or grinding. Only genuinely UNRELATED parallel work may continue.
5. **Resume the blocked task first** once I reply "done" / "restarted" / an explicit write-confirmation.

Distinguish the failure so the fix is right:
- **Needs authentication** (expired/absent OAuth) → I run `/mcp` and re-authenticate. Only I can; a
  hook/agent cannot refresh it, so don't try.
- **Down / unreachable** (a local server is off) → start the service; this is NOT an auth problem.
- **Not loaded yet** (a just-provisioned MCP server loads next session) → tell me up front to restart,
  then reply "restarted"; don't try and fail.
- **Blocked by design** (a prod write via a read-only connector) → see prod safety below.

## Work / personal boundary

Work = the repo's `git origin` matches your work org (workOrgMatch in your identity overlay). Never cross resources:
- **Work credentials:** AWS Secrets Manager (via `apps/api` `dogfood()` at startup) is the source of
  truth for runtime secrets (Twilio, Stripe, SendGrid, …) — do NOT hand-add them to a per-worktree
  `.env`. Anything AWS does not serve is a machine-local file under `~/.config/**`, outside every repo.
- **Personal credentials:** machine-local, gitignored (`.env`, or the platform's own store).
- **There is no secret-manager vault in this setup, and adding one is not the default answer.** The
  provider's own IAM is the source of truth: a key is minted on demand from a connector's `auth.steps`,
  kept `chmod 600` under `~/.config/**`, and regenerated rather than mirrored into a vault. So when a
  plaintext secret turns up on disk, the fix is scope and file mode (least-privilege key, `600`, outside
  the repo, rotate if it was exposed) — never "move it into 1Password". Propose a vault only if I ask.
- **Never** commit a secret, and never write a secret into `~/.claude` (it is a pushed git repo). The
  `work-resource-guard.sh` hook enforces the boundary on MCP tools (data-driven from the manifests) and
  on Bash; if it blocks something I actually need, tell me plainly (per `security.md`).
- **Keep personal / project-local config OUT of team repos.** The general rule, including which local
  ignore layer to use when a personal file genuinely must sit inside a repo, is owned by
  `engineering-standards.md` § "Personal / meta tooling is not a project artifact". What is specific to
  connectors: the detail lives in `~/.claude/connectors/*.json` and the keys in `~/.config/**`, both
  outside every project repo, so in practice there is nothing personal to ignore in a team repo at all.
- **And never COMMIT them, not just ignore them.** Defense-in-depth (git commands stay unblocked so
  normal `git add` always works): `~/.gitignore_global` ignores the personal/secret patterns
  (`*serviceAccountKey*.json`, `.firebase/`, `.env.op`) so `git add .` / `git add -A` never stages them; gitleaks/
  pre-commit scans content on commit (the `~/.claude` repo gates with gitleaks; team repos rely on their
  own secret scanning/CI); and I never force-add a secret past `.gitignore`.

## Prod / live safety (never write unless I ask for that specific write)

Prod is READ-ONLY by default (`firebase-prod` uses an IAM viewer key; Stripe production uses a
restricted read-only key). Never attempt a prod/live write unless I explicitly ask for that exact
change. When a task needs one, surface it up front and give the steps: the write pathway is SEPARATE,
enabled on demand, confirmed per write, and torn down after — `/sk:setup-connectors enable-prod-write
<platform>`, then I confirm the exact change. No prod data is touched until both happen.

## Manifest convention (one generic engine, per-project specs)

The engine is generic and lives in `~/.claude` (`bin/connectors-provision.sh`,
`hooks/session-connectors.sh`, `hooks/work-resource-guard.sh`, `/sk:setup-connectors`). Each project's
connectors — which servers/CLIs it uses, their env (dev/prod/sandbox/production), boundary, read/write
policy, and `auth.steps` — live ONLY in `~/.claude/connectors/<project>.json`. To set up or repair a
project's connectors, run `/sk:setup-connectors`; to add one, `/sk:setup-connectors add`. Onboarding a
new project = drop in a new `<project>.json`. Don't hard-code connector detail anywhere else.
