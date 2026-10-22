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
  (work runtime) or machine-local files outside every repo, at each connector's `secret.path`:
  `~/.config/**`, or an org key directory (a shared `.env` plus one `<project>.env` per project, each
  repo's `.env` a symlink to its project file).
- **No vault, by design.** The engine fetches nothing. A key is minted on demand from its connector's
  own `auth.steps`, kept `chmod 600`, and regenerated when needed — the provider's IAM is the source of
  truth, so there is no second copy to rotate, sync or leak. Don't propose adding a secret manager.

Use `references/agent-hosts.md` for native Codex configuration. Both hosts consume these manifests;
Claude uses native local registration, while the Codex launcher reads the current definitions before
starting the process. Codex has no manually maintained mirror of a manifest. The native adapter's
ownership receipt stores server names only, so deleted entries cannot fall back to old registrations.
Keep host-specific authentication separate. A Conductor workspace does not merge the hosts' MCP stores.

## Manifest schema (`connectors/<project>.json`, plain JSON — no comments, jq-parseable)

```json
{
  "project": "codebase",
  "boundary": "work",
  "ignoreProjectInstructions": false,
  "match": ["YourOrg/codebase", "your-org/codebase", "conductor/workspaces/codebase"],
  "connectors": [ { "...": "see connector record" } ]
}
```

- `project` — label.
- `boundary` — `work` | `personal`. Default for connectors that omit their own.
- `ignoreProjectInstructions` — optional boolean on a selected non-shared project manifest, default `false`. `true` activates `references/project-instructions.md`; shared manifests cannot set it. This does not change connector or credential policy.
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
- `mcp` — for `mcp-*` kinds, the canonical transport object (stdio: command/args/env;
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
1. **provision** — make it available (Claude mcp-*: `claude mcp add-json -s local`; Codex: native launch-time projection; api/cli/env/claude-connector: no-op).
2. **readiness** — is it usable now? (mcp-*: registered + not needs-auth; cli: logged-in profile; api/env: key/secret present; claude-connector: `account` — loaded from claude.ai settings, so present whenever the session has it).
3. **auth-steps** — the numbered fix (from `auth.steps`), which is also how the key gets created.
4. **boundary-guard** — deny in the wrong boundary; deny writes when `readOnly`/`gated` (handled data-driven in the guard).
5. **secret-location** — where the key lives (for `permissions.deny` + the readiness check).

To add a NEW kind: add its case to the `provision`/`readiness` switch in `bin/connectors-provision.sh`
and (if it exposes tools) to the guard. The manifest, skill, and auth-gate need no change.

## Capability diagnosis

DO search the active host's tool and app/plugin catalog by name AND description. A catalog entry,
manifest or enabled flag proves neither installation nor exposed tools. Use native status to resolve
that distinction; missing tools alone prove neither an auth failure nor an outage.

DO reuse matching live capability evidence; otherwise run one bounded read-only check per authorized
candidate path. Check tool schemas and CLI version/help for the requested action. When a feature is
missing, check current official docs/releases before calling it unsupported (e.g. an older CLI can
read a private resource but lack its attachment command). Reads never prove upload/write support.

DO classify the failure before selecting a remedy:
- Verified expired/absent OAuth on the required path: request that host's login flow, not another
  host's `/mcp` command.
- Down/unreachable local service: start it within existing authority; this is not an auth problem.
- Tools absent from this session: check native status and authorized alternatives; request a restart
  only when the required path demonstrably needs it.
- Missing action in the schema or installed CLI: check official version support; login adds no command.
- Policy denial or read-only connector: preserve the existing write gate across every path.
TEST: each blocker names its host/profile, exact action, checked paths and evidence; an unverified
tool listing or blank browser never becomes a service-wide auth diagnosis.

## Official account connectors and completion messages

DO start with the official connector offered by the active host. For Slack, use Claude's
Customize > Connectors > Slack, or ChatGPT's Apps/Plugins > Slack > Connect. Select the intended
work workspace during OAuth. Check current vendor instructions if the controls differ.
DON'T create a custom Slack app, request a Client ID, install a local MCP server, or copy tokens
between hosts when the official connector supplies the requested action.
Sources: [Claude connectors](https://support.claude.com/en/articles/11176164-use-connectors-to-extend-claude-s-capabilities)
and [Slack in ChatGPT](https://help.openai.com/en/articles/12525822-using-slack-in-chatgpt), checked 2026-10-20.

DO distinguish three states: installed, tools exposed in this session, and verified action. Discover
the tools again after Simon connects. If installation is confirmed but tools are absent, use the
host's new-chat entry (ChatGPT: **Try in chat**) and check there. Report a missing tool separately
from an OAuth failure. Verify each host independently; ChatGPT success does not prove native Codex
access, and Claude credentials do not authenticate an OpenAI session.

DO keep shared work connector metadata in one matching shared manifest, with `boundary: work` and
`gated: true`; remove a project duplicate when moving it. Use `claude-connector` only for the Claude
account route. Record another host's observed status without inventing an MCP registration or a new
adapter kind. Keep real workspace/user IDs and proof links in the ignored overlay, never this catalog.

DO confirm the live workspace, signed-in identity and recipient/channel before sending. Resolve an
ambiguous display name before any write. A requested setup test authorizes one self-DM; return its
permalink and record the result. Accept Simon's screenshot or receipt as evidence without sending a
second test. Label evidence from another host accurately.

DO treat "when this work is done, message <recipient> with <purpose>" as authorization for that one
completion message. Carry the request in the existing plan, finish and verify the work, write a short
factual update with the relevant result/link, send once, and return the Slack permalink. Explicit
wording supplied by Simon stays unchanged; otherwise summarize the completed task. Ask only for a
missing or ambiguous recipient, completion condition or required access; do not re-ask permission for
the same authorized message. If Simon asks only for a draft, show it and wait. General connector setup
does not authorize automatic future notifications.

DO apply `rules/communication.md` and `rules/copy-quality.md` to every outgoing message.
Use those existing TL;DR and actionable-copy standards; do not define separate Slack writing rules.

DO obey runtime approvals and existing write gates. If a send times out or returns an uncertain
result, check the target conversation before retrying; never duplicate a message on assumption.
If tools or access are missing, retain the message task and provide the exact connection step.
TEST: every send traces to Simon's request, the intended workspace and recipient, verified task
completion when applicable, and one delivery receipt or an explicit unresolved outcome.

## Model-API keys (`pal`)

DEFAULT: workers and reviews run on the Claude or Codex subscription. The one API route is the `pal` MCP,
with a key of the repo's own boundary and Simon's per-call yes (`rules/spend-approval.md`). Codex's own
inference never takes an API key (`bin/agent_runtime.py`); Codex reaches `pal` the way Claude does, as an
MCP server inside its boundary. Shell calls to api.openai.com or generativelanguage.googleapis.com
are denied in every repo, whatever key file they name.

DO declare `pal` as ONE record in `connectors/work-shared.json` (`boundary: work`, `kind: mcp-stdio` with its
`mcp` command, `secret.path` `~/dev/tools/pal-mcp-server/.env`, which holds one work Gemini key). Claude
loads `pal` from user scope in `~/.claude.json`; the Codex launch registers it from this record, enabled
only when the session's boundary equals the record's. `hooks/work-resource-guard.sh` passes `mcp__pal__*` only when exactly
one `pal` record exists across `connectors/*.json` and its boundary equals the repo's. Undeclared, declared
twice, no `jq` and an unreadable manifest all deny.
TEST: `mcp__pal__version` passes in a work repo and is denied in a personal repo; `connectors-provision.sh
--host codex --check` lists `pal mcp-stdio` in a work repo and no `pal` in a personal one.

## Secret homes (never committed, never in `~/.claude`)

| Class | Home |
| --- | --- |
| Work runtime secrets (Twilio, Stripe, SendGrid, …) | AWS Secrets Manager via `apps/api` `dogfood()` (already working) |
| Firebase prod read-only SA key (work) | `~/.config/firebase-keys/your-project-readonly.json`, chmod 600 — minted from `auth.steps` |
| Firebase prod WRITE SA key (work, ephemeral) | `~/.config/firebase-keys/your-project-write.json` — created for one confirmed write, removed after |
| Firebase Admin SDK key (personal project) | `~/dev/secrets/firebase-keys/*.json`, chmod 600, dir 700 |
| Stripe CLI profiles | `~/.config/stripe/config.toml` — `work-sandbox`, `work-prod`, `personal` |
| Personal API keys (incl. `LINEAR_API_KEY`) | `~/.config/personal-keys.env`, chmod 600 |
| Per-project runtime keys (personal) | that project's gitignored `.env.local`, chmod 600, symlinked into worktrees |

Claude may read `~/.config/firebase-keys/**` and the other credential paths — the read-blockers were
removed as theatre (`rules/security.md`), since a secret here is reachable by design. The control is
never surfacing a secret VALUE into the chat: load a key into the firebase process or pass its path to
a tool, never `cat`/`echo` it into the transcript, a message, or a commit.

**Rotate rather than relocate.** When a key turns up somewhere it shouldn't be, the fix is: tighten the
mode, move it to the file its connector's `secret.path` names, and mint a fresh one from
`auth.steps` because the old one was exposed. Do not propose importing it into a vault.

**Personal files stay OUT of team repos.** Everything above lives outside every project repo (in
`~/.claude` or `~/.config`), so no personal connector artifact lands in a team repo and no project's
committed `.gitignore` is ever touched. If some tool genuinely forces a personal file to sit inside a
project repo, ignore it in a NON-committed local layer teammates never see — `.git/info/exclude` (that
repo only) or the global `core.excludesFile` (`~/.gitignore_global`, all repos) — never in the shared
`.gitignore`. (Simon already has `core.excludesFile = ~/.gitignore_global` configured.)

## Shared manifests (`"shared": true`) — one connector, layered across every matching project

A manifest with `"shared": true` (e.g. `connectors/personal-shared.json`) declares connectors used by
MORE than one project under a single `match` (a path or origin substring), instead of copying the same
connector record into every project manifest that needs it.

- **Layers UNDER the project manifest, never instead of it.** `bin/connectors-provision.sh` resolves
  the project manifest by first-match as before (shared manifests are excluded from that loop), then
  separately collects every `shared:true` manifest whose `match` also hits this repo — and applies
  BOTH. A project connector always wins on a `name` clash.
- **`--check` and provisioning include shared connectors automatically**; `--manifest --shared DIR`
  prints just the matching shared manifest paths. `hooks/work-resource-guard.sh` reads shared manifests
  the same way, so the work/personal boundary and the `gated`/`readOnly` write-guard cover a shared
  connector exactly like a project one.
- **Codex gets the same connectors.** `bin/agent_runtime.py` layers matching shared manifests under
  the project manifest for a Codex launch, project connector first on a `name` clash, and leaves out
  a shared manifest whose `boundary` differs from the session's. TEST: `connectors-provision.sh
  --host codex --check` in a repo that matches both lists the project's connectors and the shared ones.
- **Still never carries a secret value** — same `secret.path` declaration as any other connector.

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

### A schema change in production (a migration)

DEFAULT: the project's own pipeline applies a migration that merged through a reviewed PR, with the
database credentials held as CI secrets. No agent and no laptop holds a production write credential for
it. Vendors document this as the route (e.g. Supabase, read 2026-10-06: "we recommend using a CI/CD
pipeline to deploy new migrations with GitHub Actions rather than deploying from your local machine").

DO find which of three routes the project has, in this order, and use the first that exists:
1. **Pipeline.** The merge applies it. Verify afterwards, read-only.
2. **By hand.** The project documents manual migrations and has no pipeline: Simon runs the file in the
   vendor's console, you prepare it and verify read-only. Propose a ticket for route 1.
3. **Agent-run, the exception.** Only on Simon's own yes naming that migration in this conversation.
   Record the route first as an `enabledOnDemand`, `gated` connector. Then do all five: save the
   definition of every object the file replaces; run the file inside a block that always rolls back
   and read the new answers out of it; apply the exact committed file (its hash equals the repo's
   manifest line); verify through the app's own read path; leave no credential or script behind.
DON'T record a route-3 mechanism as the project's normal way, and DON'T reach for an admin API or a
token that is on disk because it would work. (the fix for a migration applied through a vendor's beta
query endpoint with a broad token, because no route was recorded.)
TEST: a production schema change traces to a merged PR and a pipeline run, or to Simon's hands, or to
his yes for that file with a saved restore copy and a rolled-back dry run before it.

## Production log reads: one tested query per connector

**DO keep one tested log query per production connector kind in the table below** (kind, command,
query dialect, date last run), and re-run it the first time a session needs logs, before the incident
needs it. A documented endpoint can be removed and its replacement can use another dialect.
**DO switch to the provider's own record of the event after 2 failed log reads** (a payment provider's
session list, a database's rows, a deploy history). DON'T try a third query shape.
TEST: a session whose log read failed twice has read a provider record before any further log attempt
(the fix for several minutes lost on a removed log endpoint, then a replacement in another SQL dialect,
when database and payment-provider reads already held the cause).

| Kind | Command | Dialect | Last run |
|---|---|---|---|
| Supabase Management API logs | `curl --fail --silent --show-error --get "https://api.supabase.com/v1/projects/$PROJECT_REF/analytics/endpoints/logs" --header "Authorization: Bearer $SUPABASE_ACCESS_TOKEN" --data-urlencode "sql=select source, count() events, countIf(toInt32OrZero(log_attributes['response.status_code']) between 500 and 599) server_errors, min(timestamp) first_event, max(timestamp) last_event from logs where source in ('edge_logs','function_edge_logs','function_logs') group by source limit 10" --data-urlencode "iso_timestamp_start=$START_UTC" --data-urlencode "iso_timestamp_end=$END_UTC"` | ClickHouse; `server_errors` counts HTTP 5xx for `edge_logs` and `function_edge_logs`, not runtime errors in `function_logs`. | 2026-10-20; 20-minute UTC window, all 3 sources returned. |

## Known verification items (confirm during first live run)

- Same-named server at local vs project scope: local should win; confirm no conflict.
- Firebase MCP honoring `GOOGLE_APPLICATION_CREDENTIALS` for firestore/rtdb tools (else the write-guard + rule are the floor).
- Whether provisioner-added servers load same-session or next-session (if next, the hook advises restart up front).
- Exact `claude mcp add-json` flag form and local-scope project keying on this Claude Code version.
- Non-interactive Stripe active-account/profile check for the guard.
