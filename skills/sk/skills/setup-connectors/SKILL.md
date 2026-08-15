---
name: setup-connectors
description: Guided co-pilot to set up, health-check ("doctor"), add, or extend the connectors/credentials for the CURRENT project (Firebase, Linear, Stripe, Twilio, AWS, pal, …). Does everything it can automatically, then hands Simon numbered steps for the rest and waits. Use when connectors aren't working ("can't access Firebase/Stripe/Linear", "not enough permissions"), when first setting up a machine/project, when adding a new connector, to enable a one-off prod write, or to audit the existing setup for insecure credential handling (world-readable key files, a secret inside a repo, a CLI profile defaulting to the wrong work/personal account) and fix it. Reads the per-project manifest in ~/.claude/connectors/<project>.json; the deep spec is references/connectors-setup.md.
argument-hint: "[add | migrate | enable-prod-write <platform>]  — no arg = setup + doctor for the current project"
---

# Set up / doctor the connectors for this project

The premise: connectors + credentials are declared per project in `~/.claude/connectors/<project>.json`
and driven by a generic engine (`~/.claude/bin/connectors-provision.sh` + the guard + the SessionStart
hook). This skill is the guided front door. On a plain `/sk:setup-connectors` (no args) it AUTOMATICALLY takes
care of the whole setup for the current project — provisions what it can, diagnoses the rest
green/yellow/red (like `flutter doctor`), AND audits for insecure local approaches to migrate — then
proposes everything (auth steps + migrations) in ONE consolidated pass and waits for Simon's decisions.
He never needs to remember a sub-command; figure out what's needed and propose it. Always follow the
auth-gate protocol in `rules/connectors.md`: ask FIRST, numbered steps, then wait; never grind around a
missing connector.

The default (no arg) already does **setup + doctor + migration audit**. The named modes are optional
focused shortcuts: `add` = register a new connector; `migrate` = run ONLY the audit + migration proposal;
`enable-prod-write <platform>` = turn on a separate, temporary prod-write pathway.

## Mode: setup + doctor (default)

1. **Resolve the project.** `~/.claude/bin/connectors-provision.sh --manifest` prints this project's
   manifest. If empty, tell Simon no manifest matches this repo, show its `git remote get-url origin`,
   and offer to create one (`add` mode seeds it) — then stop.
2. **Provision what's automatable.** Run `~/.claude/bin/connectors-provision.sh`. It registers the
   manifest's MCP servers at local scope and warns about any declared key file that is missing. It
   fetches nothing — there is no vault. If it reports "NEW MCP servers were registered", they load
   NEXT session — per the auth-gate, tell Simon up front: "restart the session/app to load <servers>,
   then reply restarted", and wait.
3. **Diagnose each connector (green / yellow / red).** Run `~/.claude/bin/connectors-provision.sh --check`
   and combine with live signals:
   - **mcp-\*** — `registered` + not in `~/.claude/mcp-needs-auth-cache.json` = green; `registered` +
     flagged = yellow (needs `/mcp` re-auth); `missing` = yellow (provisioned, restart to load).
   - **secret-backed** (`key-missing`) — nothing fetches it, so missing = red: relay that connector's
     `auth.steps`, which are the commands that mint the key. Present = green.
   - **cli** (stripe/firebase) — check the profile/login is the right account. `firebase login:list`,
     run INSIDE the directory being worked in (the account is per-directory). For Stripe use
     `grep -E '^\[|display_name|account_id' ~/.config/stripe/config.toml` — **never `stripe config
     --list`, which prints live and test SECRET KEY VALUES into the transcript.** Then confirm the
     manifest's `cli.profile` exists and its `display_name` matches this repo's boundary; a profile
     that is missing, or whose `[default]` belongs to the other boundary, is red not yellow, because a
     bare command silently falls through to it. Logged in and correct = green.
   - **env** (twilio) — reachable via AWS at app startup = green; if AWS creds are stale = yellow (`aws sso login`).
4. **Do the automatable parts yourself** for every non-green connector, and collect the manual ones with
   their exact `auth.steps` from the manifest (numbered).
5. **Auto-audit for migrations (ALWAYS — no sub-command needed).** Run the scan + assessment from the
   *migrate* procedure below and fold any proposed migrations into the same plan; Simon never has to
   remember to ask for it.
6. **Present ONE consolidated plan, then act.** A single table covering everything at once: each
   connector's status (green/yellow/red), what you'll do automatically, the numbered steps you need Simon
   to do, AND any migration proposals (finding | risk | proposed move | why) with the choose
   all / mixture / specific / none options. Do the automatable parts, wait for the manual + decision
   items, re-verify (never mark green on trust), then report what's done and what's outstanding (incl.
   prerequisites below).

### Prerequisites only Simon can do (report as red with these exact steps)

- GCP (your work cloud project, prod): a **read-only** service account (roles `datastore.viewer` +
  `firebasedatabase.viewer`); mint its key to `~/.config/firebase-keys/work-prod-readonly.json` and
  `chmod 600` it. The exact `gcloud` commands are in that connector's `auth.steps`.
- Stripe: one named profile per boundary — `stripe login --project-name=work-sandbox`,
  `--project-name=work-prod`, and a personal one per that project's manifest. Never leave a repo
  relying on `[default]`.
- AWS: ensure creds are active (`aws sso login` or your configured refresh) so `dogfood()` provides Twilio.

## Mode: add (register a new connector — any kind, boundary-aware)

1. Gather: `name`, `kind` (mcp-http | mcp-stdio | cli | api/service-key | env — open; if it's a new
   kind, capture how to provision/authenticate/guard it), `env` (dev/prod/sandbox/production), `boundary`
   (defaults to the project's), `readOnly`/`gated` (true for prod reads/gated writes), the `mcp` block or
   `cli` block (`{name, profile}`), an optional `secret` (`{path}` — where the key lives, not where to
   fetch it from), and `auth.steps` (the numbered fix, including the command that mints the key).
2. Append the record to this project's `~/.claude/connectors/<project>.json` (create the file with a
   `match` from the git origin if it doesn't exist). **jq-validate** the file before saving.
3. Run the default mode to provision + diagnose the new connector. The data-driven guard covers its
   boundary automatically — no guard edit. NEVER write a secret value into the manifest; only a
   machine-local path.

## Mode: migrate (audit the existing setup + propose secure migrations)

(The default `/sk:setup-connectors` runs this audit automatically as part of its pass; `migrate` runs
ONLY this.) Scan the CURRENT project for insecure credential handling and propose fixes.
NEVER print a secret VALUE — work with names, paths, and presence only. Recommend, give steps, and let
me choose — never force.

**There is no secret manager in this setup, and proposing one is not a finding.** Machine-local
plaintext under `~/.config/**`, in a gitignored `.env*`, or in a key file outside the repo is the
INTENDED design: the provider's IAM is the source of truth and a key is minted on demand. So the
remediation vocabulary is scope, file mode, location and rotation — never "move it into a vault".
Suggest a secret manager only if Simon asks for one.

1. **Scan (values never printed):**
   - Gitignored `.env*` files: list only secret-looking var NAMES, e.g.
     `grep -oE '^[A-Za-z0-9_]+=' <file> | sed 's/=$//' | grep -iE 'TOKEN|KEY|SECRET|AUTH|PASSWORD|CREDENTIAL'`.
   - On-disk key/cert/credential files (`*serviceAccountKey*.json`, `*.pem`, `*.p12`, `*credentials*.json`):
     note each path + whether it is gitignored and tracked.
   - Hardcoded secrets in tracked source — prefer the repo's own scanner or `gitleaks` if installed.
   - **File modes** on every credential file and its directory (`stat -f '%Sp %N'`). A `644` key is a
     real finding; this is the check that actually fires most often.
   - **CLI profiles that default to the wrong boundary** — e.g. `[default]` in
     `~/.config/stripe/config.toml` belonging to work while the repo is personal. A bare command
     falls through to it silently, so this is red.
2. **Assess.** Classify each: (a) acceptable as-is — gitignored or outside the repo, `600`, correct
   boundary, has a committed `.example`; or (b) needs fixing — world-readable, inside a repo, tracked,
   over-scoped, or pointing at the wrong boundary.
3. **Propose per item, in this order of preference:** tighten the mode (`chmod 600` file, `700` dir) →
   move it outside the repo (`~/.config/**`) or into the gitignored env file → narrow the key's scope
   (a viewer-only IAM key, a restricted key) → pin the correct CLI profile → rotate if it was exposed.
   Show a table: finding | risk | proposed fix | why.
4. **Let me choose — never force:** offer migrate ALL, a MIXTURE (I pick which), specific items, or NONE
   ("leave it, it's fine"). Present it clearly and wait for my reply.
5. **Apply each chosen item (secrets never pass through your output):**
   - `chmod`/`mv` are yours to run directly — you never need to read the value to fix the mode or the
     location, so do it and verify with `stat`, not with `cat`.
   - Anything that needs the VALUE (creating a profile, minting a key, rotating) is Simon's step:
     give the exact command from the connector's `auth.steps` and wait.
   - **Record it in the manifest** (`~/.claude/connectors/<project>.json`) so it is remembered on every
     future worktree: a `secret.path` for a key file, a `cli.profile` for a CLI. The guard reads those,
     so declaring it is what makes the boundary enforceable rather than remembered.
   - If a secret was exposed (world-readable, committed, or pasted anywhere), recommend ROTATING it —
     tightening the mode does not un-expose what was already readable.
6. **Report** what changed, what was left as-is (and why), and offer `/sk:claude-config-sync` for the manifest change.

## Mode: enable-prod-write <platform> (separate, on-demand, confirmed, ephemeral)

Prod is read-only by default; a write goes through a SEPARATE pathway that must be enabled, confirmed,
and torn down. For the platform's `enabledOnDemand` write connector (e.g. `firebase-prod-write`):
1. Mint its write key from the provider's IAM using that connector's own `auth.steps`, to
   `<secret.path>` (`chmod 600`). Nothing is pulled from a store; the key does not exist until now.
2. Register it: `claude mcp add-json <name> "<mcp-block>" -s local` (from the manifest record).
3. Tell Simon: name the EXACT change and ask him to confirm ("yes, write <X> to prod"). Only after his
   explicit yes, run the guard's confirmation for that write (the write-guard requires `CLAUDE_PROD_WRITE_OK=1`
   for the gated tool — set it only for the confirmed write).
4. **Tear down** immediately after: `claude mcp remove <name> -s local`, `rm -f "<secret.path>"`, and
   **delete the key at the provider too** (`gcloud iam service-accounts keys delete …`) — a deleted file
   whose key is still valid in IAM is not a torn-down pathway. Clear the flag, confirm it is gone. One
   confirmed write, then off.

## Pickup timing

A brand-new skill FOLDER needs a Claude Code restart to appear in the slash menu; edits to an existing
SKILL.md are live. Newly-registered MCP servers load on the NEXT session (advise a restart). After any
change under `~/.claude`, offer `/sk:claude-config-sync` to commit it (it secret-scans; NEVER commit secrets).
