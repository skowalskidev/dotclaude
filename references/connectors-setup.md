# Connectors & credentials — the system (engine + local connector registry)

Deep, on-demand how-to. The always-on behavioral rule is `rules/connectors.md`; this file is the
technical spec the engine derives from. Read it when resolving a route, setting up connectors, adding
one, or debugging the provisioner/guard.

## Shape (DRY/SRP)

- **Generic engine, once, in `~/.claude`:** `bin/connector_registry.py` (the ONE loader and the route
  resolver), `bin/connectors-provision.sh`, `hooks/session-connectors.sh`, `hooks/work-resource-guard.sh`,
  `bin/agent_runtime.py`, `bin/health-pulse.py`, the `/sk:setup-connectors` skill and
  `rules/connectors.md`. None of these hard-codes a project, and none parses a registry file itself.
- **Local registry, one root per boundary, outside every repo:** `connectorRoots.work` and
  `connectorRoots.personal` in `identity.local.json` (e.g. a `connectors/` folder in the work-projects
  folder beside the org key directory, and one in the personal-projects folder).
  `CLAUDE_CONNECTOR_ROOTS="work=/a,personal=/b"` overrides both for tests. `~/.claude/connectors/`
  holds only the public `*.example` templates.
- **Secrets never live in the registry.** Records carry only paths and names. Real secrets live in AWS
  Secrets Manager (work runtime), machine-local files outside every repo at each route's `secret.path`
  (`~/.config/**`, or an org key directory: a shared `.env` plus one `<project>.env` per project, each
  repo's `.env` a symlink to its project file), or the project's own Supabase Vault, reached through a
  vault pointer (§ Hybrid secrets).
- **No new secret manager.** `resolve` fetches nothing. A local key is minted on demand from its
  route's own `auth.steps`, kept `chmod 600`, and regenerated when needed. A key the project already
  keeps in its Supabase Vault is read in place through its pointer, never copied to disk. Don't propose
  adding another secret manager unless Simon asks. A plaintext secret on disk → fix scope + file mode
  (least-privilege key, `600`, outside the repo, rotate if exposed), never "move it into 1Password".

Use `references/agent-hosts.md` for native Codex configuration. Both hosts consume the same loader;
Claude uses native local registration, while the Codex launcher reads the current definitions before
starting the process. Codex has no manually maintained mirror of the registry. The native adapter's
ownership receipt stores server names only, so deleted entries cannot fall back to old registrations.
Keep host-specific authentication separate. A Conductor workspace does not merge the hosts' MCP stores.

## Why this layout (research, 2026-11-06)

- **Scoped layers matched by name, highest precedence wins:** Claude Code loads MCP servers from local,
  project and user scope and "connects to it once, using the definition from the highest-precedence
  source" ([Claude Code MCP docs](https://code.claude.com/docs/en/mcp)). Here a project route beats a
  shared-account route of the same `name`.
- **An ordered provider chain that stops at the first source that works:** "After valid credentials are
  found, the search is stopped" ([AWS SDK credential provider chain](https://docs.aws.amazon.com/sdkref/latest/guide/standardized-credentials.html));
  named, user-level configurations with one active at a time ([gcloud configurations](https://docs.cloud.google.com/sdk/docs/configurations)).
  The resolver is that chain, per capability.
- **Shared values in one place, referenced by projects:** Doppler references secrets "across configs and
  projects" ([Doppler secrets](https://docs.doppler.com/docs/secrets)); here a shared-account route is
  written once and ranks for every project of its boundary.
- **Record failures and stop retrying a failing route for a while:** the circuit breaker's closed, open
  and half-open states ([Azure circuit breaker pattern](https://learn.microsoft.com/en-us/azure/architecture/patterns/circuit-breaker)).
  Health lives in `health.json`, apart from the records, as Claude Code keeps its needs-auth cache apart
  from its config.
- **A pointer to an external store, never the value:** Kubernetes External Secrets names the store
  (`secretStoreRef`) and the remote key (`remoteRef.key`) and fetches the value at use
  ([ExternalSecret API](https://external-secrets.io/latest/api/externalsecret/)). A vault pointer is
  that shape: `store`, `via`, `project`, `name`.
- **Rejected:** a new secret manager (policy above); one monolithic registry file (every outcome
  rewrites every record, and concurrent sessions collide); per-project copies of a shared account (the
  four drifting copies of one Twilio key this replaced).

## Registry schema (plain JSON, jq-parseable, one root per boundary)

```
<root>/index.json             {"boundary": "work", "match": ["YourOrg/"]}
<root>/projects/<project>.json {"match": [...], "ignoreProjectInstructions": false, "monitor": {...}}
<root>/<provider>.json        {"provider", "capabilities", "scope", "routes": [route, ...]}
<root>/health.json            {"<provider>/<route id>": {"lastSuccess": {...}, "lastFailure": {...}}}
```

- `index.json` — `boundary` (`work` | `personal`, must equal its `connectorRoots` key) and `match`:
  git-origin or path substrings whose repos receive this root's shared-account routes. A route's
  boundary always equals its root's; a record that says otherwise is unreadable.
- `projects/<project>.json` — `match` (substrings of the git origin; the path is used only when there is
  no remote; two matching projects fail), optional boolean `ignoreProjectInstructions` (default
  `false`; `true` activates `references/project-instructions.md`, and it is rejected anywhere else),
  optional `monitor` (the daily health pulse's probes and project SQL, `references/production-monitoring.md`).
  The project's root decides its boundary; it must agree with the identity overlay.
- `<provider>.json` — one file per provider: `provider`, `capabilities` (e.g. `slack.send`,
  `supabase.read`), `scope` (default for its routes), `routes` in PREFERENCE order, optional `notes`.
- **Route** = a connector record (below) plus `id` (unique in the file), optional `capabilities`,
  `scope` (`shared-account`: one account any project of the boundary can use; `per-project`: a key for
  the projects in `serves`), `serves` (projects it is known to serve), optional `requires`
  (`{"claudeAccount": "<email or identity-overlay key>"}`) and optional `recipe` (the exact steps).
- **Provisioned set:** a per-project route is registered, guarded and launched for the projects in
  `serves`; a shared-account route for every repo of the root, or only for its `serves` list when it has
  one. Provisioning never adds a server somewhere new; the resolver still ranks every route.
- `health.json` — written only by `record`, `chmod 600`, under a lock with an atomic replace.

## Resolve, try, record

```
python3 ~/.claude/bin/connector_registry.py resolve slack.send            # ordered routes for this repo
python3 ~/.claude/bin/connector_registry.py record slack codex-app ok     # after a success
python3 ~/.claude/bin/connector_registry.py record slack claude-ai fail --reason "not loaded on this login"
python3 ~/.claude/bin/connector_registry.py list | roots | manifest | project <name>
```

The resolver returns only the session boundary's routes whose capabilities match the query (the
provider name, an exact capability, or a prefix such as `slack`), in this order:
1. Unblocked before BLOCKED: `requires.claudeAccount` differing from the CLI's signed-in account (read
   from `~/.claude.json` `oauthAccount`, never a token), or `enabledOnDemand`. Both are human steps.
2. A closed circuit before an open one: a route whose last failure is newer than its last success and
   under 24 h old is `open`; after 24 h it is `half-open` and ranks like an untested route.
3. Routes serving this project (shared-account, listed in `serves`, or with a recorded success here)
   before the rest of the boundary.
4. Proven (`ok`) before untested, then the file's declared preference, then the most recent success.
Within the same serving rank, local-key routes rank before vault pointers unless the provider's
`storeOrder` is `["vault", "local"]`.
Each route line ends with `key in <secret.path> as <secret.var>`, or for a vault pointer
`key in Supabase Vault <project> as "<name>" via <provider/route>; load: connector_registry.py run ...`
(`--json`: `secret: {store, path, var[]}` or `secret: {store, via, project, name, env}`). Load a key
without printing it, through `connector_registry.py run <provider> <route> -- <cmd>` (§ Hybrid secrets).
DO put the resolver output, the route record and this reference IN a delegated subagent's prompt (the
fix for a subagent that guessed "emulator-first" past a provisioned MCP and sign-in bridge).
DO record the outcome of every attempt, success and failure, with the failure reason. A record whose
reason names a human-only cause (another login, missing consent) keeps the next session from trying it
first. TEST: after a failed route, the next `resolve` in the same boundary lists it after every
untried route for 24 h.

### Migrating legacy manifests

`connector_registry.py migrate --from <dir of legacy manifests> [--write] [--provider-map JSON]` builds
both roots: a `shared: true` manifest becomes the root's `match` plus shared-account routes; a record
that reaches the same account from two or more projects (same name, kind, key path, profile, transport
and write policy) becomes ONE shared-account route listing them in `serves`, with differing `auth`
text kept under `auth.byProject`. `check-migration --from <dir>` exits 1 unless every legacy project
field and connector field is reachable through the loader with its original value.

### Connector record (the body of every route)

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
  `codex-app` (an app in the Codex ChatGPT login, reached from any chat through `codex exec`; carries
  `codexApp: {appId, tool}` and a `recipe`; never registered, readiness `codex-app`).
  A new type = one new adapter case in `bin/connectors-provision.sh` (+ `hooks/work-resource-guard.sh`
  only if it needs kind-specific guard logic); nothing else changes.
- `env` — variant: `dev`|`prod`|`sandbox`|`production`|… A platform may have several records (Firebase
  dev + prod; Stripe sandbox + production), all usable at once.
- `boundary` — filled in from the root; the guard enforces it. Omit it in a route.
- `readOnly` — true = must not mutate (e.g. prod read). `gated` — writes require explicit per-write ok.
- `enabledOnDemand` — NOT provisioned by default; only enabled when required (e.g. a prod-write pathway).
- `ephemeral` — torn down after use (materialized key removed).
- `mcp` — for `mcp-*` kinds, the canonical transport object (stdio: command/args/env;
  http: type+url). `~` in `env` values and `args` is expanded to `$HOME` at provision time.
- `secret` — hybrid, one of two stores (§ Hybrid secrets). **Local** (`store` omitted or `"local"`):
  `{ path, var }`, where this connector's key file lives and, for an env-style file, the variable name
  holding the key (`var`: one name, or a list when the route needs several, e.g. an SID and a secret).
  `var` is a NAME only; the loader rejects anything that is not a shell identifier. `--check` reports
  `key-present`/`key-missing` from it, provisioning warns when it is absent, and the key itself is
  created by hand from `auth.steps`. DO fill both on every route that reads a key file holding more than
  one variable. TEST: `resolve` prints `key in <path> as <VAR>` on that route's line. **Vault**:
  `{ "store": "vault", "via": "<provider>/<route>", "project": "<project ref>", "name": "<Vault secret
  name>", "env": "<VAR the consumer reads>" }`; `name` and `env` may be equal-length lists for a key
  that comes in parts (an account SID and a token). `--check` reports `vault-pointer`.
- `cli` — `{ name, profile }` for `kind: cli`: the CLI binary and the named profile this project must
  use. The guard reads `profile` so a bare invocation that would fall through to the CLI's own default
  profile is denied by data rather than by a hardcoded name (this is what stops a bare `stripe` in a
  personal repo from silently hitting the work account).
- `auth` — `{ how, steps[] }`. `steps` are the exact numbered instructions the auth-gate relays to Simon.
  A migrated shared-account route may carry `auth.byProject.<project>` with that project's own text.

## Adapters (the per-`kind` behaviors the engine calls)

Each `kind` implements the same five behaviors:
1. **provision** — make it available (Claude mcp-*: `claude mcp add-json -s local`; Codex: native launch-time projection; api/cli/env/claude-connector/codex-app: no-op).
2. **readiness** — is it usable now? (mcp-*: registered + not needs-auth; cli: logged-in profile; api/env: key/secret present; claude-connector: `account` — loaded from claude.ai settings for the signed-in account; codex-app: present in the Codex apps cache).
3. **auth-steps** — the numbered fix (from `auth.steps`), which is also how the key gets created.
4. **boundary-guard** — deny in the wrong boundary; deny writes when `readOnly`/`gated` (handled data-driven in the guard).
5. **secret-location** — where the key lives (for `permissions.deny` + the readiness check).

To add a NEW kind: add its case to the `provision`/`readiness` switch in `bin/connectors-provision.sh`
and (if it exposes tools) to the guard. The registry, skill, and auth-gate need no change.

## Capability diagnosis

DO search the active host's tool and app/plugin catalog by name AND description. A catalog entry,
registry route or enabled flag proves neither installation nor exposed tools. Use native status to resolve
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

DO treat every Claude account listed in the identity overlay (`workEmail` plus `workClaudeLogins`) as
a work account: a claude.ai connector on any of them is authorized for work tasks. claude.ai
connectors follow the CLI's signed-in account, so before calling one unavailable run `claude mcp list`
and read the overlay; to reach a connector held by another listed account, sign the CLI in as that
account (`/login`) or connect the same connector on the signed-in account. Record each account as its
own route with `requires.claudeAccount`, so the resolver marks the other login BLOCKED and runs the
next route instead of asking.
DON'T extend this to the personal account; the work/personal boundary stays as written.
TEST: an "unavailable" verdict on a claude.ai connector names the signed-in account, the overlay's
work accounts and the `claude mcp list` result.

DO keep a shared work account as ONE shared-account provider file in the work root, with `gated: true`
on every write route; remove a project duplicate when moving it. Use `claude-connector` only for a
Claude account route and `codex-app` for the Codex app route; never invent an MCP registration for
another host. Keep real workspace/user IDs, app ids and proof links in the registry, never this catalog.

DO confirm the live workspace, signed-in identity and recipient/channel before sending. Resolve an
ambiguous display name before any write: list every channel or user whose name contains the stem
Simon named (e.g. `engineer*`). DO wait for his pick when more than one matches, even if one matches
exactly; a preference recorded in the route's `recipientPreferences` settles it.
TEST: a send to a named channel cites the full match list, or the recorded preference it used.
A requested setup test authorizes one self-DM; return its permalink and record the result.
Accept Simon's screenshot or receipt as evidence without sending a second test. Label evidence from another host accurately.

DO treat "when this work is done, message <recipient> with <purpose>" as authorization for that one
completion message. Carry the request in the existing plan, finish and verify the work, write the
update to `references/tldr-report-formats.md` § Message for someone else, send once, and return the
Slack permalink. Explicit
wording supplied by Simon stays unchanged; otherwise summarize the completed task. Ask only for a
missing or ambiguous recipient, completion condition or required access; do not re-ask permission for
the same authorized message. If Simon asks only for a draft, show it and wait. General connector setup
does not authorize automatic future notifications.

DO run a `codex-app` route from a Claude chat when the resolver lists it first, through the exact
command in its `recipe`; the record holds the app id. Every `codex-app` run (verified 2026-11-05 and
2026-11-06 for a message and for a thread reply with a video upload):
1. Sets `-c 'apps.<app id>.default_tools_approval_mode="approve"'` for that run only. `codex exec` runs
   with approval policy `never`, so an app write fails with "MCP tool call requires approval, but
   approval policy is never" without it. `default_tools_approval_mode` is the documented per-app key
   (Codex config reference, `apps.<id>`: `auto | prompt | writes | approve`); a per-tool
   `apps.<id>.tools.<tool>.approval_mode` alone, and the `_<tool>` and `"<app>.<tool>"` spellings, did
   not clear the block. Never write `approve` to `~/.codex/config.toml`.
2. Passes `-C <dir>` and absolute file paths (exec otherwise runs in the repo directory and relative
   paths break), and `-s workspace-write -c sandbox_workspace_write.network_access=true` when the run
   uploads bytes with `curl`.
3. Measures the draft first: `python3 ~/.claude/hooks/outbound-message-guard.py --check <draft-file>`;
   expect `ok`, and cut the draft on exit 1. The PreToolUse guard does not see a `codex exec` prompt.
4. Verifies the workspace by display name OR URL subdomain (a workspace-list tool can return either)
   and the signed-in identity, checks the target conversation for an existing copy, sends exactly once,
   never retries, and returns the permalink. Check the conversation before any retry.
5. Sets `AGENT_ALLOW_CROSS_PROVIDER=1`, authorized for a resolver-ordered `codex-app` route by Simon's
   standing instruction (2026-11-06) as well as by a named-host ask (`references/agent-hosts.md`).
The per-message authorization above still gates every send, on every route.

DO apply `rules/communication.md` and `rules/copy-quality.md` to every outgoing message, before the
send call, on every route. Use those existing TL;DR and actionable-copy standards; do not define
separate Slack writing rules.

DO obey runtime approvals and existing write gates. If a send times out or returns an uncertain
result, check the target conversation before retrying; never duplicate a message on assumption.
If tools or access are missing, retain the message task and provide the exact connection step.
TEST: every send traces to Simon's request, the intended workspace and recipient, verified task
completion when applicable, and one delivery receipt or an explicit unresolved outcome.

## Model-API keys (`pal`)

DEFAULT: workers, reviews and the cross-provider judges of `references/research.md` § Independent
judges run on the Claude or Codex subscription; a subscription run is not a model-API call and not
billable (`rules/spend-approval.md`). The one API route is the `pal` MCP,
with a key of the repo's own boundary and Simon's per-call yes (`rules/spend-approval.md`). Codex's own
inference never takes an API key (`bin/agent_runtime.py`); Codex reaches `pal` the way Claude does, as an
MCP server inside its boundary. Shell calls to api.openai.com or generativelanguage.googleapis.com
are denied in every repo, whatever key file they name.

DON'T call OpenAI or Gemini from the shell; the guard denies it in every repo. A repo's own billable
test harness Simon asked to run uses the repo's path, not pal.

DO declare `pal` as ONE shared-account route in the work root's `pal.json` (`kind: mcp-stdio` with its
`mcp` command, `secret.path` `~/dev/tools/pal-mcp-server/.env`, which holds one work Gemini key). Claude
loads `pal` from user scope in `~/.claude.json`; the Codex launch registers it from this route, enabled
only when the session's boundary equals the route's. `hooks/work-resource-guard.sh` passes `mcp__pal__*` only when
`pal` is declared under exactly one boundary across both roots and it equals the repo's. Undeclared,
declared in both roots, no `jq` and an unreadable record all deny.
TEST: `mcp__pal__version` passes in a work repo and is denied in a personal repo, and so is a shell
model-API call anywhere; `connectors-provision.sh --host codex --check` lists `pal mcp-stdio` in a work
repo and no `pal` in a personal one.

## Hybrid secrets: local key files and Supabase Vault pointers

A project's Supabase Vault holds the production keys of the data sources and suppliers its functions
call (billing, subscriptions, ads, messaging, supplier APIs), so it reaches sources no local file holds.
DO declare each such key as its own route whose `secret` is a vault pointer, beside any local-key route
for the same provider, with a distinct `name` (e.g. `<provider>-vault`). `via` names the local-key route
that reads the vault (a management-API token route), `name` is the exact Vault secret name, trailing
spaces included, and `env` is the variable the consumer reads.
DO use both stores: try the routes in `resolve` order (local first by default), and on a failure
`record` it and take the vault pointer, or the local key, in the same turn.
DO read a key only through `python3 ~/.claude/bin/connector_registry.py run <provider> <route> -- <cmd>`:
it loads a local key from its file, or a vault value through the `via` route's token and the Supabase
management API query endpoint, into the child's environment only. The command reads `$<env>`.
DON'T print, log, write to disk or commit a value, and don't paste one into a command line; test
presence by length inside the child (`${#VAR}`). A Vault write or rotation is a prod write
(`rules/connectors.md` § Prod / live safety).
DO discover Vault secret NAMES only, through the vault route: `select name from vault.secrets`.
DON'T route a model-API key (OpenAI, Gemini, Anthropic, xAI) through a vault pointer; § Model-API keys
owns that path. Note in the root's `index.json` `notes` that the Vault holds the data sources' keys.
TEST: `resolve <provider>` lists both the local and the vault route with their key locations; the
`run` output and transcript carry no value.

## Secret homes (never committed, never in `~/.claude`)

DO keep work runtime secrets in AWS Secrets Manager, loaded by `apps/api` `dogfood()` at startup;
DON'T hand-add them to a per-worktree `.env`. Every other key is a `chmod 600` file outside every repo
at its route's `secret.path`; personal credentials are machine-local and gitignored (`.env`, or the
platform's own store).

| Class | Home |
| --- | --- |
| Work runtime secrets (Twilio, Stripe, SendGrid, …) | AWS Secrets Manager via `apps/api` `dogfood()` (already working) |
| Firebase prod read-only SA key (work) | `~/.config/firebase-keys/your-project-readonly.json`, chmod 600 — minted from `auth.steps` |
| Firebase prod WRITE SA key (work, ephemeral) | `~/.config/firebase-keys/your-project-write.json` — created for one confirmed write, removed after |
| Firebase Admin SDK key (personal project) | `~/dev/secrets/firebase-keys/*.json`, chmod 600, dir 700 |
| Stripe CLI profiles | `~/.config/stripe/config.toml` — `work-sandbox`, `work-prod`, `personal` |
| Personal API keys (incl. `LINEAR_API_KEY`) | `~/.config/personal-keys.env`, chmod 600 |
| Per-project runtime keys (personal) | that project's gitignored `.env.local`, chmod 600, symlinked into worktrees |
| Supplier and data-source production keys a project's functions use (work) | that project's Supabase Vault, read in place through a vault-pointer route |

Claude may read `~/.config/firebase-keys/**` and the other credential paths — the read-blockers were
removed as theatre (`rules/security.md`), since a secret here is reachable by design. The control is
never surfacing a secret VALUE into the chat: load a key into the firebase process or pass its path to
a tool, never `cat`/`echo` it into the transcript, a message, or a commit.

**Rotate rather than relocate.** When a key turns up somewhere it shouldn't be, the fix is: tighten the
mode, move it to the file its connector's `secret.path` names, and mint a fresh one from
`auth.steps` because the old one was exposed. Do not propose importing it into a vault.

**Test a copied secret, then store it.** DO give Simon one command whenever a step has him copy a
token or key from the terminal or clipboard into a secret store: read the clipboard into a shell
variable with whitespace stripped, print only its length and its fixed non-secret prefix, test it
with one cheap authenticated call using that variable, and pipe it into the store only if the test
succeeds. e.g. a CI subscription token:
`T="$(pbpaste | tr -d '[:space:]')"; echo "${#T} ${T:0:13}"; CLAUDE_CODE_OAUTH_TOKEN="$T" claude -p "Reply with ok" && printf %s "$T" | gh secret set NAME --repo OWNER/REPO; unset T`.
A multi-line secret (PEM key, JSON) passes the same test, then goes in from its file:
`gh secret set NAME --repo OWNER/REPO < <file>`.
DON'T hand him an interactive paste or an untested pipe: wrapped terminal lines add line breaks, and
stripping them glues any other clipboard text onto the token, so the stored secret fails auth on every run.
DO confirm with the first real run that consumes it before reporting the step done; read the error
text, since a failing action can hide it.
TEST: a secret handoff with no test-then-store step fails; so does a step reported done with no
real run behind it.

**Personal files stay OUT of team repos.** Everything above lives outside every project repo (in
`~/.claude`, `~/.config` or a registry root), so no personal connector artifact lands in a team repo and
no project's committed `.gitignore` is ever touched. If some tool genuinely forces a personal file to sit inside a
project repo, ignore it in a NON-committed local layer teammates never see — `.git/info/exclude` (that
repo only) or the global `core.excludesFile` (`~/.gitignore_global`, all repos) — never in the shared
`.gitignore`. (Simon already has `core.excludesFile = ~/.gitignore_global` configured, and Conductor's
`.conductor/settings.local.toml` is already handled this way via `.git/info/exclude`.)
DO commit the shared behavior and ignore the personal parts (settings, credentials), which teammates
never see. DO keep them uncommitted, not just ignored: `~/.gitignore_global` ignores the secret patterns
(`*serviceAccountKey*.json`, `.firebase/`, `.env.op`) so `git add -A` never stages them; gitleaks or
pre-commit scans content on commit (the `~/.claude` repo gates with gitleaks; team repos rely on their
own CI). DON'T commit or force-add a personal or secret file past `.gitignore`; git commands themselves stay unblocked.

## Scope: shared-account vs per-project

- **shared-account** — one account every project of the boundary can use (one Twilio account, one
  Linear workspace, one Slack workspace, `pal`). Written once in the root; the resolver ranks it as
  serving every project of that boundary, and it layers under each matched project's routes.
- **per-project** — a key that reaches one project's resource (a database service key, a project's
  Firebase service account). `serves` lists the projects; the resolver still returns it for another
  project of the same boundary, ranked after the routes that serve that project, and a recorded success
  for a project counts as serving it from then on.
- **Layering:** a project route wins a `name` clash over a shared-account one. `--check`, provisioning,
  `hooks/work-resource-guard.sh` and the Codex launch all read the same effective set from the loader,
  so the boundary and the `gated`/`readOnly` write guard cover a shared route exactly like a project
  one. TEST: `connectors-provision.sh --check` in a work repo lists its project routes, then the
  shared ones marked `(shared)`.
- **Still never carries a secret value** — same `secret.path` declaration as any other route.

## Onboarding a new project

1. Add `<root>/projects/<project>.json` with `match` (a git-origin substring), in the root of the
   project's boundary.
2. Add its routes: append to an existing `<provider>.json` (add the project to `serves`, or nothing
   for a shared-account route), or create one from `~/.claude/connectors/provider.json.example`.
3. Run `/sk:setup-connectors` in that project — it provisions. The SessionStart hook only reports; it never provisions.
4. Do any manual steps it reports red (create a read-only SA, `stripe login --project-name=…`, …).

## Prod-write pathway (separate, on-demand, confirmed, ephemeral)

Prod is read-only by default (`firebase-prod`, IAM viewer SA; the Stripe production CLI profile, a
restricted read-only key). A Vault-held live key can be full-access, so its vault-pointer route stays
GET-only unless Simon asks for that exact write. A write goes through a SEPARATE
`firebase-prod-write` record (`readOnly:false, gated:true, enabledOnDemand:true, ephemeral:true`):
`/sk:setup-connectors enable-prod-write firebase` mints the write key from GCP IAM, Simon confirms the
exact write, the one write is made, then the pathway is disabled and the key is deleted both on disk
and in IAM. Same pattern for Stripe live: `/sk:setup-connectors enable-prod-write <platform>`, then
Simon confirms the exact change.

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
| Supabase Management API logs | `curl --fail --silent --show-error --get "https://api.supabase.com/v1/projects/$PROJECT_REF/analytics/endpoints/logs" --header "Authorization: Bearer $SUPABASE_ACCESS_TOKEN" --data-urlencode "sql=select source, count() events, countIf(toInt32OrZero(log_attributes['response.status_code']) between 500 and 599) server_errors, min(timestamp) first_event, max(timestamp) last_event from logs where source in ('edge_logs','function_edge_logs','function_logs') group by source limit 10" --data-urlencode "iso_timestamp_start=$START_UTC" --data-urlencode "iso_timestamp_end=$END_UTC"` | ClickHouse; `server_errors` counts HTTP 5xx for `edge_logs` and `function_edge_logs`, not runtime errors in `function_logs`. | 2026-11-05; 24h UTC windows (the endpoint's maximum), every source; `bin/health-pulse.py` `LOG_SOURCES` runs the same dialect daily. |

## Known verification items (confirm during first live run)

- Same-named server at local vs project scope: local should win; confirm no conflict.
- Firebase MCP honoring `GOOGLE_APPLICATION_CREDENTIALS` for firestore/rtdb tools (else the write-guard + rule are the floor).
- Whether provisioner-added servers load same-session or next-session (if next, the hook advises restart up front).
- Exact `claude mcp add-json` flag form and local-scope project keying on this Claude Code version.
- Non-interactive Stripe active-account/profile check for the guard.
