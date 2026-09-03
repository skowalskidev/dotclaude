# Connectors & credentials — the system (engine + per-project manifests)

Deep, on-demand how-to. The always-on behavioral rule is `rules/connectors.md`; this file is the
technical spec the engine derives from. Read it when setting up connectors, adding one, or debugging
the provisioner/guard.

## Shape (DRY/SRP)

- **Generic engine, once, in `~/.claude`:** `bin/connectors-provision.sh`, `hooks/session-connectors.sh`,
  `hooks/work-resource-guard.sh`, the `/sk:setup-connectors` skill, and `rules/connectors.md`. None of
  these hard-code a project.
- **Per-project manifest:** `~/.claude/connectors/<project>.json` — one file per project, the ONLY place
  project detail lives. The engine picks the manifest whose `match` hits the current git origin.
- **Secrets never live here.** Manifests carry only paths. Real secrets live in AWS Secrets Manager
  (work runtime) or machine-local files under `~/.config/**`, outside every repo.
- **No vault, by design.** The engine fetches nothing. A key is minted on demand from its connector's
  own `auth.steps`, kept `chmod 600`, and regenerated when needed — the provider's IAM is the source of
  truth, so there is no second copy to rotate, sync or leak. Don't propose adding a secret manager.

Application-agnostic: works under the official Claude app, the CLI, and Conductor. The only harness-
specific glue is an optional Conductor `scripts.setup` in a WORK repo's machine-local
`.conductor/settings.local.toml` that calls the provisioner at workspace creation.

## Manifest schema (`connectors/<project>.json`, plain JSON — no comments, jq-parseable)

```json
{
  "project": "codebase",
  "boundary": "work",
  "match": ["YourOrg/codebase", "your-org/codebase", "conductor/workspaces/codebase"],
  "connectors": [ { "...": "see connector record" } ]
}
```

- `project` — label.
- `boundary` — `work` | `personal`. Default for connectors that omit their own.
- `match` — array of substrings; the manifest is selected when ANY appears in the repo's `git remote
  get-url origin` (or, for path-based fallback, in the repo path). First matching manifest wins.

### Connector record

```json
{
  "name": "firebase-prod",
  "kind": "mcp-stdio",
  "env": "prod",
  "boundary": "work",
  "readOnly": true,
  "gated": true,
  "enabledOnDemand": false,
  "ephemeral": false,
  "mcp": { "type": "stdio", "command": "npx",
           "args": ["-y","firebase-tools","mcp","--dir","~/.config/firebase-mcp/your-project","--only","firestore,database"],
           "env": { "GOOGLE_APPLICATION_CREDENTIALS": "~/.config/firebase-keys/your-project-readonly.json" } },
  "secret": { "path": "~/.config/firebase-keys/your-project-readonly.json" },
  "auth": { "how": "read-only service-account key (IAM viewer), machine-local in ~/.config",
            "steps": ["CLOUDSDK_CONFIG=~/.config/gcloud-work gcloud iam service-accounts keys create ~/.config/firebase-keys/your-project-readonly.json --iam-account=<readonly-sa-email> && chmod 600 ~/.config/firebase-keys/your-project-readonly.json"] }
}
```

Fields:
- `name` — the MCP server name (becomes `mcp__<name>__*` tool prefix) or a CLI/label.
- `kind` — **OPEN string, adapter-backed** (not a closed enum). Shipped adapters: `mcp-http`,
  `mcp-stdio`, `cli`, `api` (a.k.a. `service-key`), `env` (runtime secret-manager, e.g. AWS dogfood),
  `claude-connector` (a claude.ai account-level connector — loaded from claude.ai connector settings in
  every session, NEVER registered by the engine; readiness is `account`, and the boundary guard matches
  on its live server-id `name`, e.g. `mcp__<id>__*`. Use when the connector is configured in claude.ai,
  not via `claude mcp add-json`; no `mcp` block, and no guard change is needed since the guard is already
  name/boundary-driven and kind-agnostic).
  A new type = one new adapter case in `bin/connectors-provision.sh` (+ `hooks/work-resource-guard.sh`
  only if it needs kind-specific guard logic); nothing else changes.
- `env` — variant: `dev`|`prod`|`sandbox`|`production`|… A platform may have several records (Firebase
  dev + prod; Stripe sandbox + production), all usable at once.
- `boundary` — `work`|`personal`; the guard enforces it. Defaults to the manifest `boundary`.
- `readOnly` — true = must not mutate (e.g. prod read). `gated` — writes require explicit per-write ok.
- `enabledOnDemand` — NOT provisioned by default; only enabled when required (e.g. a prod-write pathway).
- `ephemeral` — torn down after use (materialized key removed).
- `mcp` — for `mcp-*` kinds, the exact object passed to `claude mcp add-json` (stdio: command/args/env;
  http: type+url). `~` in `env` values and `args` is expanded to `$HOME` at provision time.
- `secret` — `{ path }`: where this connector's key file lives. A DECLARATION, not a fetch instruction.
  `--check` reports `key-present`/`key-missing` from it, provisioning warns when it is absent, and the
  key itself is created by hand from `auth.steps`. There is no `from` field and no vault to pull from.
- `cli` — `{ name, profile }` for `kind: cli`: the CLI binary and the named profile this project must
  use. The guard reads `profile` so a bare invocation that would fall through to the CLI's own default
  profile is denied by data rather than by a hardcoded name (this is what stops a bare `stripe` in a
  personal repo from silently hitting the work account).
- `auth` — `{ how, steps[] }`. `steps` are the exact numbered instructions the auth-gate relays to Simon.

## Adapters (the per-`kind` behaviors the engine calls)

Each `kind` implements the same five behaviors:
1. **provision** — make it available (mcp-*: `claude mcp add-json -s local`; api/cli/env/claude-connector: no-op).
2. **readiness** — is it usable now? (mcp-*: registered + not needs-auth; cli: logged-in profile; api/env: key/secret present; claude-connector: `account` — loaded from claude.ai settings, so present whenever the session has it).
3. **auth-steps** — the numbered fix (from `auth.steps`), which is also how the key gets created.
4. **boundary-guard** — deny in the wrong boundary; deny writes when `readOnly`/`gated` (handled data-driven in the guard).
5. **secret-location** — where the key lives (for `permissions.deny` + the readiness check).

To add a NEW kind: add its case to the `provision`/`readiness` switch in `bin/connectors-provision.sh`
and (if it exposes tools) to the guard. The manifest, skill, and auth-gate need no change.

## Secret homes (never committed, never in `~/.claude`)

| Class | Home |
| --- | --- |
| Work runtime secrets (Twilio, Stripe, SendGrid, …) | AWS Secrets Manager via `apps/api` `dogfood()` (already working) |
| Firebase prod read-only SA key (work) | `~/.config/firebase-keys/your-project-readonly.json`, chmod 600 — minted from `auth.steps` |
| Firebase prod WRITE SA key (work, ephemeral) | `~/.config/firebase-keys/your-project-write.json` — created for one confirmed write, removed after |
| Firebase Admin SDK key (personal project) | `~/dev/secrets/firebase-keys/*.json`, chmod 600, dir 700 |
| Stripe CLI profiles | `~/.config/stripe/config.toml` — `work-sandbox`, `work-prod`, `personal` |
| Personal API keys | `~/.config/personal-keys.env`, chmod 600 |
| Per-project runtime keys (personal) | that project's gitignored `.env.local`, chmod 600, symlinked into worktrees |

Claude may read `~/.config/firebase-keys/**` and the other credential paths — the read-blockers were
removed as theatre (`rules/security.md`), since a secret here is reachable by design. The control is
never surfacing a secret VALUE into the chat: load a key into the firebase process or pass its path to
a tool, never `cat`/`echo` it into the transcript, a message, or a commit.

**Rotate rather than relocate.** When a key turns up somewhere it shouldn't be, the fix is: tighten the
mode, move it under `~/.config/**` or the project's gitignored env file, and mint a fresh one from
`auth.steps` because the old one was exposed. Do not propose importing it into a vault.

**Personal files stay OUT of team repos.** Everything above lives outside every project repo (in
`~/.claude` or `~/.config`), so no personal connector artifact lands in a team repo and no project's
committed `.gitignore` is ever touched. If some tool genuinely forces a personal file to sit inside a
project repo, ignore it in a NON-committed local layer teammates never see — `.git/info/exclude` (that
repo only) or the global `core.excludesFile` (`~/.gitignore_global`, all repos) — never in the shared
`.gitignore`. (Simon already has `core.excludesFile = ~/.gitignore_global` configured.)

## Onboarding a new project

1. Drop a `~/.claude/connectors/<project>.json` with `match` (a git-origin substring) + its connectors.
2. Run `/sk:setup-connectors` in that project — it provisions. The SessionStart hook only reports; it never provisions.
3. Do any manual steps it reports red (create a read-only SA, `stripe login --project-name=…`, …).

## Prod-write pathway (separate, on-demand, confirmed, ephemeral)

Prod is read-only by default (`firebase-prod`, IAM viewer SA). A write goes through a SEPARATE
`firebase-prod-write` record (`readOnly:false, gated:true, enabledOnDemand:true, ephemeral:true`):
`/sk:setup-connectors enable-prod-write firebase` mints the write key from GCP IAM, Simon confirms the
exact write, the one write is made, then the pathway is disabled and the key is deleted both on disk
and in IAM. Same pattern for Stripe live.

## Known verification items (confirm during first live run)

- Same-named server at local vs project scope: local should win; confirm no conflict.
- Firebase MCP honoring `GOOGLE_APPLICATION_CREDENTIALS` for firestore/rtdb tools (else the write-guard + rule are the floor).
- Whether provisioner-added servers load same-session or next-session (if next, the hook advises restart up front).
- Exact `claude mcp add-json` flag form and local-scope project keying on this Claude Code version.
- Non-interactive Stripe active-account/profile check for the guard.
