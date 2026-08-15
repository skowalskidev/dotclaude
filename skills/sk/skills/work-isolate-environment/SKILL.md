---
name: work-isolate-environment
description: Give this session its own lane of local dev ports, so two or more stacks can run at once instead of fighting over :3000. Allocates a stable slot per worktree, wires each service through the env knob it already reads, sweeps whatever a dead session left behind, and tears down clean. Use for "isolate my environment", "give this session its own ports", "run two stacks at once", "EADDRINUSE", "AxiosError Network Error", or when a second dev server will not boot. Works in any repo, personal or work, containerised or not.
argument-hint: "[optional: services to isolate, e.g. 'web and api']"
---

# Isolate this session's environment

**Why this exists:** several sessions run at once in different worktrees, every one of them wants
`:3000` and `:4000`, and none of them can see the others. The second stack to boot gets `EADDRINUSE`,
or worse an opaque `AxiosError: Network Error` that reads like a bug in the code rather than a
neighbour holding the port. The fix is a **lane**: slot N means `base + N*10` for every base port the
project uses, so slot 1 of a `{web 3000, api 4000}` project is `{3010, 4010}`.

**Git worktrees give code isolation, not environment isolation.** That gap is the whole problem.

## What is already built, and what is yours to do

`~/.claude/bin/port-slot.sh` owns the deterministic half and you should never re-derive it: picking a
slot, arbitrating it against `port-registry.sh`, sweeping what previous sessions left, recording the
run. `~/.claude/references/dev-server-hygiene.md` owns the protocol, including the liveness table the
sweep implements and the preflight and teardown rules.

**Yours is the judgement half:** which services in THIS project bind a host port, which env knob
carries a port into each one, which ports cannot move at all, and what to do when the answer is
"nothing here can be isolated without a bigger change than you were asked for".

## Phase 0 — sweep and take a lane

```bash
~/.claude/bin/port-slot.sh                 # sweeps, then prints the lane. Claims nothing yet.
```

Read the sweep output aloud to Simon if it did anything. Claiming is **lazy** on purpose: a run that
never boots a server must never leave a registry row, which is what stops rows piling up over a day.

## Phase 1 — discover what actually binds a port

`port-slot.sh` does a mechanical scan (an explicit `-p`/`--port` in a package.json `dev`/`start`
script, and host-side ports in compose files). **Treat that as a floor, not an answer.** It cannot see
a port that arrives through config, and those are the ones that matter most.

Go and look, in this order:

1. The project's own docs first: `CLAUDE.md`, `CLAUDE.local.md`, `README`. A repo usually states its
   ports, and re-deriving what is written down wastes a pass.
2. Every workspace's `dev` and `start` script. Note the ones with **no** `-p`, because those take
   their port from config and the scan missed them.
3. `.env.example` and any `config/` module, for `*_PORT` / `*_URL` names.
4. Non-JS services. A Go or Python service reads its own env var (`os.Getenv("HEALTH_PORT")`), which
   no package.json scan will ever find.
5. Anything that binds implicitly: an emulator suite, a metrics endpoint, a bundler, a mobile packager.

Then hand the real map to the allocator and record it, so the next run in this worktree is instant:

```bash
~/.claude/bin/port-slot.sh --base web=3000,api=4000,esipc=8080 --claim
```

The map is cached in `.claude-slot.json` in the worktree, ignored through `~/.gitignore_global`.
Fill in each service's `env` field there, because that is what makes `--env` emit the right variable
names instead of generic ones. **A cached map whose `workspace` field does not match this worktree is
rejected and rediscovered**, because Conductor copies `.env*` and `CLAUDE.local.md` into new
workspaces and an inherited map silently boots a fresh workspace on a neighbour's ports.

## Phase 2 — pick the branch

**Containerised (a compose file that runs the app itself).** Offset only the HOST side and leave the
container-internal port alone:

```yaml
api:
  ports: ["${API_PORT:-4000}:4000"]   # host varies per lane, container is ALWAYS 4000
```

That is what makes it safe: app config hardcoding `http://localhost:4000` keeps working, because
inside that container the API really is on 4000. So **never rewrite the app's own port config here.**
Also set `COMPOSE_PROJECT_NAME` from the worktree, or Compose reuses containers, networks and volumes
across worktrees. It isolates those but *not* host ports, so it is necessary and not sufficient.

**Host-run (the usual case for a JS monorepo).** Offset with exported env vars and appended CLI flags,
per Phase 3. The mechanism matters more than it looks:

- A variable the server reads **before** any env file loads must be a real process env var. Next.js
  documents that `PORT` cannot be set in `.env` at all, for exactly that reason.
- Turborepo 2.x defaults `envMode` to **strict**, so a variable absent from `globalEnv` / `env` /
  `passThroughEnv` never reaches the task. `--env-mode=loose` fixes that from the command line.
- A loader inside the task (`env-cmd -f .env`, `dotenv`) may override the process env from a file.
  env-cmd 10.x is file-wins, so check whether the key is actually IN that file; if it is absent, the
  export lands.

**If the project has no isolation mechanism at all** — nothing containerised and no port that can be
moved by env — say so and stop. Containerising a project that was never containerised is a much bigger
change than this, and it is Simon's call, not yours.

## Phase 3 — wire it from OUTSIDE the repo

**Isolation is external to the project. It must not pollute the repo at all.** The repo has no use for
it: nobody else on the team needs this session's ports, so a lane must never appear in a tracked file,
not as a commit and not as a local edit sitting in `git status`. This is
`rules/engineering-standards.md` § "Personal / meta tooling is not a project artifact", applied to
ports.

So the lane is applied with **exported env vars and CLI flags only**. Three escape hatches make that
possible far more often than it looks, and all three were verified rather than assumed:

- **A later CLI flag beats an earlier one.** `next dev -p 3011 --port 3012` binds **3012**. So
  `yarn workspace <pkg> run dev --port <lane>` reuses the committed script verbatim and only appends,
  which means a hardcoded `-p 3000` needs no edit. Check the same for `vite`, `nest`, `rails`: most
  arg parsers take the last occurrence.
- **A task runner's env filtering has a flag.** Turborepo strips undeclared vars under its default
  strict `envMode`, but `turbo dev --env-mode=loose` passes everything, so `turbo.json` needs no edit.
- **An env var the project already reads is free.** Exporting it works as long as no loader
  *overrides* it from a file. env-cmd 10.x defaults to file-wins, so check whether the key is actually
  present in that file: if it is absent, the export survives.

If a project genuinely cannot be offset from outside — a port baked into a tracked file with no flag
and no env knob — **stop and ask.** Do not edit the repo to make it fit. That is a change to a shared
artifact for one session's convenience, and it is Simon's call, not yours.

The only files a lane may write are ones git does not track at all: `.claude-slot.json` (ignored
globally) and, where a project's own local env file is already gitignored, that file. Even then prefer
the export, because Conductor copies `.env*` into new workspaces and an inherited value silently boots
a fresh workspace on another lane's ports.

## Phase 4 — boot and prove it is yours

**Run the project's own one-time setup FIRST, and DISCOVER it rather than assuming it.** Every project
sets up differently, so there is nothing to hardcode here: read this project's `CLAUDE.md`, then its
`CLAUDE.local.md`, then a playbook if one exists, and do what they say. Never infer the setup, and never
assume a checkout is prepared.

The reason this is a step and not a footnote: **an unprepared checkout fails in ways that look exactly
like broken isolation.** A missing dependency install, an unbuilt workspace package, an uncompiled
native binary, the wrong runtime version — each produces a server that will not boot, and none of them
is a port problem. Diagnosing a lane you never actually managed to boot wastes the whole pass. That rule
is `references/testing-strategy.md`'s ("an unprepared checkout's failures are not a test baseline"), and
the discovery order above is the one it states.

What to look for, stated as shapes because the commands differ per project: an install step, a build
step for shared or generated code, a compile step for anything non-JS the dev script shells out to, and
a pinned runtime version. If the docs do not say and you cannot tell, ask rather than guess.

Then preflight both the registry and the machine; if the project already has a preflight script, use it
rather than writing a second one. Then verify identity, per `dev-server-hygiene.md`: something
answering on the port is not the same as your server being up. Finish with one line:

```
slot 1 — web http://localhost:3010 · api http://localhost:4010
```

Confirm each app talks to **its own** lane, not its neighbour's. A portal on 3010 calling the API on
4000 looks like it works and is reading another branch's data.

## Phase 5 — tear down

Kill the process group, release the lane, then verify the port AND the registry are clear.

```bash
~/.claude/bin/port-slot.sh --release
```

If teardown never happens, the next run's sweep recovers it. That is the design, not an excuse to skip
this.

## Phase 6 — learn, and only when it recurs

Every run appends a line to `~/.claude/logs/isolate-runs.jsonl`. Read it back at the end.

**Propose a durable change only when a pattern shows up across three runs, or two consecutive ones.**
A single run is a sample of one, and `rules/self-healing-config.md` is explicit that its evidence bar
drags every fix toward the incident that produced it. Route anything real through
`/sk:claude-config-update`, propose at most one thing, and **say nothing when nothing recurs** —
silence is the normal outcome, and a skill that proposes something every run is a nuisance, not a
feature.

What the log is worth reading for: repeated `slot_wanted` != `slot_granted` (the hash is poor or ten
lanes is not enough), the same entry in `services_skipped` (a port that genuinely cannot be isolated,
which belongs in the project's docs), `discovery_source` never reaching `cache` (the map is not being
recorded), and a `sweep.reported_unclaimed` that keeps firing (Simon starts servers by hand more than
this assumes).

## Stop and ask, rather than guessing

- **A port a third party has registered.** OAuth and webhook redirect URIs are registered with the
  provider and cannot move, so those flows only work on the lane whose port matches. Name the flow and
  the lane; do not silently break the login.
- **A shared service.** An emulator suite whose ports come only from a committed config file cannot be
  offset per worktree. Say which sessions must therefore share it, or which package a second lane has
  to exclude.
- **No mechanism at all.** See Phase 2.

## Worked example: a work monorepo (`codebase`)

Verified 2026-08-07 so a future run does not re-derive it. **Not one tracked file is touched.** Slot 1's
lane is `{3010 web, 4010 api, 8090 es-ipc}`:

```bash
eval "$(~/.claude/bin/port-slot.sh --base web=3000,api=4000,esipc=8080 --claim --env | sed 's/^/export /')"

# API + supporting services. --env-mode=loose is what carries HEALTH_PORT through, instead of
# editing turbo.json. BACK_PORT survives because apps/api/.env does not define it.
BACK_PORT=4010 HEALTH_PORT=8090 NEXT_PUBLIC_BACK_URL=http://localhost:4010/ \
  npx turbo dev --filter='!agents-portal' --filter='!serverless' --env-mode=loose

# Portal. The appended --port beats the script's hardcoded -p 3000, so package.json is untouched.
NEXT_PUBLIC_BACK_URL=http://localhost:4010/ NEXT_PUBLIC_FRONT_URL=http://localhost:3010/ \
  yarn workspace agents-portal run phoni:dev --port 3010
```

Its setup step, which came from reading this repo's own `CLAUDE.md` and is exactly the kind of thing the
discovery in Phase 4 is for: `yarn install`, then `cd apps/es-ipc && go build -o esipc .` because that
package's dev script runs the compiled binary and `turbo dev` otherwise dies with exit 127, and **Node
20** (`nvm use 20`) because Node 24 breaks the `config` package.

**Plus one step its docs do not list**, found on 2026-08-07 and worth carrying because it costs two
failed boots to rediscover:

```bash
npx turbo build --filter='api^...' --filter='agents-portal^...'   # ~20s, cached after
```

The `dev` task has no `dependsOn`, so `turbo dev` starts `api` and `admin` at the same time as the
shared packages' watch builds. On a checkout where `@your-work-org/functional` and `@your-work-org/common` have
no `dist/` yet the consumers win that race and both die with `MODULE_NOT_FOUND`, which reads exactly
like a port fault and is not one. This is the general case of why Phase 4 exists: **the failure a
missing setup step produces is indistinguishable from broken isolation.** Simon was offered this as a
`CLAUDE.md` fix and declined it, so it lives here rather than in the repo.

Why each piece, checked in the code:

- `BACK_PORT` reaches `startup.ts:76` through `apps/api/src/config/defaults.ts:24`, and `dogfood()`
  cannot clobber it: `Sdk.OverrideMaybe` is `process.env[key] || value`
  (`packages/sdk/src/index.ts:348`), so the AWS secret only fills what nothing else did.
- `NEXT_PUBLIC_BACK_URL` is read at `src/config/dev.ts:13` and is already in `turbo.json` `globalEnv`,
  so it survives even strict mode. `NEXT_PUBLIC_FRONT_URL` likewise, at line 9.
- `HEALTH_PORT` is read by `apps/es-ipc/main.go:227` (default 8080, which already collides with the
  firestore emulator before any of this). It is NOT in `globalEnv`, which is the only reason
  `--env-mode=loose` is needed.
- **`serverless` is excluded, not offset.** Its dev script starts the Firebase emulators, whose ports
  come only from the committed `firebase.json`, so they cannot be per-worktree. One session may run
  them; the rest exclude that package.
- **Slot 0 only** for OAuth: `src/config/dev.ts:43,44,47,48` hardcode `localhost:3000` MSAL and
  Microsoft redirect URIs registered with the provider. Same for `LOOP_SHORT_URL` (line 17) and
  `ADMIN_URL:3999` (line 18).
- Elasticsearch 9200, Kibana 5601 and Redis stay shared.

## Read these

`~/.claude/references/dev-server-hygiene.md` for the protocol, the liveness table and teardown.
`~/.claude/rules/process.md` for cleanup and the ask-before-browser rule.
