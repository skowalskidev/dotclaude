# Engineering standards

Baseline engineering conventions that apply across all projects: versioning, mainstream tool choice, single source of truth, legacy support, and data deletion.

## Versions — start with the latest stable

When starting a new project, scaffolding, or adding tooling, **default to the latest stable
versions** of the runtime and dependencies (not whatever a template happens to pin). For anything
that deploys to a managed platform (Firebase / Google Cloud, Vercel, AWS, etc.), pick the newest
version that platform **actually supports** — verify by browsing the platform's current docs/release
notes rather than assuming. Prefer current LTS for runtimes.

**Before adding or upgrading a major dependency** (React, Node, Firebase, Next.js, Tailwind,
TypeScript, etc.), **research the current latest-stable version online first** — don't rely on
training-data memory of version numbers, which drifts. Confirm the version exists, is stable (not
alpha/RC), and is compatible with the rest of the stack and the deploy target before pinning it.

**Encode the versions in the repo so they're reproducible:**
- **Node:** add a `.nvmrc` pinning the exact version (e.g. `24.18.0`) so `nvm use` selects it, and
  set `engines.node` in `package.json` as a floor (e.g. `>=22`). Keep local dev, `.nvmrc`, and any
  serverless runtime pin (e.g. Firebase `functions/package.json` `engines.node`) consistent.
- **Toolchain quirks:** newer tools sometimes need a newer Node than the project's old default
  (e.g. Vitest 4's rolldown needs Node ≥20.12 for `node:util`'s `styleText`). Pin up, document the
  requirement, and tell me to `nvm use`.
- Other ecosystems: pin equivalently (`.python-version`/`pyproject` for Python, `.tool-versions` for
  asdf/mise, `packageManager` for the package manager, etc.).

When bumping deps to "latest", apply the upgrade, then **build + test to verify**, and watch for
peer-dependency ceilings (e.g. `firebase-functions@7` peer-requires `firebase-admin <=13`) — pin
back anything the ecosystem doesn't support yet and tell me which and why.

## Choose mainstream, widely-adopted tools

When proposing or picking a tool, library, service, or approach, **default to the option with the
widest adoption and clearest community consensus** — official or large-org backing, high adoption
(stars / downloads / market share), active maintenance, and abundant docs. **Avoid niche / low-star
projects unless I explicitly ask for one**; a clever tool with 23 GitHub stars is a maintenance and
security risk, not a recommendation.

- **Cite the adoption signal** when you recommend: who backs it, rough stars/downloads, that it's
  actively maintained — from primary sources (the project's own repo/docs), per `process.md`.
- **Name the mainstream alternative you rejected and why**, so I can judge the call.
- If the honest mainstream choice is genuinely worse for my specific case, say so and recommend the fit
  anyway — but the burden is on justifying the deviation from the popular default.
- **The same bar applies to a SOLUTION adopted from research**, not just to a tool — a pattern, a
  workaround, a config, a technique. Prefer the community-proven answer (heavily upvoted, officially
  documented, or from a high-adoption project) over a clever fix from an obscure or low-star source.
  Read SEVERAL sources before settling, and prefer the vendor's own docs over a blog restating them.
- Complements "claims about third parties must come from primary sources" in `process.md`.

## Harden fully — never trade protection against a working app

When I ask for something to be secured, locked down, or made safe, I want the FULL protection AND a
fully working app. Those are not in tension by default, so **don't present them as a trade-off and
don't split the difference**: an apparent conflict means the guard is too coarse, not that a compromise
is needed.
- **Narrow the guard, never the protection level.** Scope it to the actual threat — a specific origin,
  path, role, field or caller — rather than a blanket deny that also catches legitimate traffic (e.g. a
  rule pinning a write to the record's owner beats one that blocks all client writes and kills the
  feature).
- **Prove BOTH halves before calling it done:** the abuse path is actually blocked, AND every real user
  flow it touches still works end to end. A protection verified on only one side is unverified.
- **Never ship a knowingly-open hole to keep something working.** If you genuinely can't close it
  without breaking a real flow, say so plainly — what's still open, why, and what closing it would cost.
  Don't quietly leave it, and don't quietly break the app.

## Personal / meta tooling is not a project artifact — keep it out of the shared repo

My personal dev-tooling config — connectors, personal MCP servers, debug helpers, editor/tool settings —
is META around a project, not part of it: teammates don't need it and the project must not depend on it
(SRP). So it never goes in the team repo.
- **It lives OUTSIDE the repo** — in `~/.claude` (connector manifests, hooks, skills) or `~/.config`
  (keys, tokens, tool config), never in the project tree. Cleanest form: nothing to leak.
- **If a personal file genuinely must sit in the tree**, ignore it in a NON-committed local layer —
  `.git/info/exclude` (that repo) or the global `core.excludesFile` (`~/.gitignore_global`, all repos) —
  never the committed `.gitignore`, which teammates see. (Conductor's `.conductor/settings.local.toml`
  is already handled this way via `.git/info/exclude`.)
- **Commit the shared behavior, ignore the personal parts** (settings/credentials). Never commit or
  force-add personal/secret files; the global ignore keeps them from being staged and gitleaks/CI catches
  secret content (git commands themselves stay unblocked — see `connectors.md`).

## Single source of truth — derive, don't duplicate (DRY / SRP)

When a value, piece of state, or behaviour is used in more than one place, give it **one authoritative
source** and derive every other use from it — never copy it into a second location that then has
to be kept in sync, because it inevitably drifts. Design so things **cannot** get out of sync,
rather than adding code to re-sync them.

**"Centralise", "extract", "share and reuse", "make it DRY", "SRP" — I mean the same thing by all of
these.** Find every place re-implementing that logic, behaviour or component; move it into ONE
authoritative owner with a single responsibility; rewire every site to draw from it; delete the
copies. The shared owner takes the STATEFUL logic too, not just the presentational shell — a partial
extraction that leaves each call site re-wiring its own state has not done the job.

- **Derive over store.** Don't persist state you can compute from an existing source. Store a
  value only when it genuinely must be recorded (can't be recomputed, or recomputing is too
  costly) — a stored copy is one more thing that drifts. (e.g. "is this the last retry attempt?"
  is inferred from the configured retry count vs. the current attempt, not saved as its own flag.)
- **One source per fact.** A number shown in several surfaces (an SMS, a landing page, a call
  script) must all read the SAME source — e.g. a discount percentage set once and pulled
  everywhere, not typed into each surface. If two independent paths exist (e.g. two billing
  providers), each derives from its own single source; neither hand-maintains a copy of the other.
- **Single responsibility.** Each module/function/document owns one concern; put a piece of state
  where that concern lives, under a name that says what it is.
- **Share BEHAVIOUR, not just values.** A convenience — debounced autosave, optimistic update,
  retry, undo, a keyboard handler — is extracted to one shared owner the moment it appears a SECOND
  time. When extracting, port the most COMPLETE existing implementation's edge cases into that owner,
  never the newest copy's: a reimplementation silently drops the details that made the original
  correct, and nothing fails loudly (e.g. an autosave copied without its flush-on-unmount quietly
  loses whatever was typed in the last debounce window). When asked to share one convenience, check
  the same surfaces for the others they each half-implement — they cluster.
- **A new guard belongs on every path that needs it, in the same change.** SSOT governs ADDITIONS,
  not just extractions: after adding a rule, check, constraint or validation to one path, grep for the
  sibling paths doing the same job and either fix them too or say why they're exempt — better still,
  put it in the shared owner both paths already read. A guard living on one path only is a defect the
  other paths keep reproducing (e.g. a content rule added to one generation path while a second path
  feeding the same output carries none).
- **Read the current setting.** When a setting changes, in-flight and derived behavior must read
  the UPDATED value, not a snapshot taken earlier — and account for race conditions when the
  setting can change while work is running.
- The model is `~/.zsh-work-codex.zsh` and the `~/.claude` repo: one live location,
  symlinked/tracked so `git status` is the whole test. Apply the same discipline in code.

## Legacy support policy
- **Never add legacy support** unless explicitly asked for
- When changing how something works, **always implement only the new way**
- After implementing the new approach, **ask Simon if legacy support should be kept**
- Default answer: **no** — remove/replace the old approach unless Simon requests backward compatibility
- Only exception: if removing legacy support breaks active users or deployed code, discuss trade-offs first
- **When changing a data format/schema, ALWAYS ship a migration script that brings the
  old data up to the new format** — and run it (or hand it off with clear deploy-order
  instructions). Never leave the codebase reading the old shape: no deprecated fields, no
  read-time fallbacks, no dead code kept "for old data." The migration is what lets the
  new code be the ONLY path. If a zero-downtime migration genuinely needs a transitional
  read (expand→migrate→contract across a deploy), say so explicitly and schedule the
  contract step; the end state still has zero legacy/dead code.

## Data deletion — soft-archive, never hard-delete (default for user-facing deletes)

When building ANY interface where a user deletes / removes / clears their own content
(list items, drafts, history, saved records, uploads, messages, etc.), implement it as a
**soft archive**, not a hard delete — this is the default unless I say otherwise:
- Set an `archived: true` (+ an `archivedAt` timestamp) flag on the record and **filter it out
  of the user's views**. The user experiences it as deleted; the data stays in the datastore.
- **Why:** we want to keep the record of what users created and then chose to remove — for
  analytics, recovery, and understanding behavior. A hard delete throws that signal away, and
  it's unrecoverable. Retaining it (invisibly to the user) costs almost nothing.
- Apply this to every new delete/remove affordance you build, including the backend route
  behind it (the route sets the archived flag; it does not call a real delete).
- **Exceptions where a hard delete IS appropriate:** account deletion / GDPR "delete my data" /
  legal erasure requests, and purging genuinely transient scratch/temp data. When unsure whether
  something qualifies as an exception, ask me first.
- This complements the Legacy-support policy (no dead code): an archived record is **live data
  with an archived flag**, not a legacy schema — the reading code still uses the one current
  shape and simply filters on `archived`. No read-time fallbacks, no second shape.
