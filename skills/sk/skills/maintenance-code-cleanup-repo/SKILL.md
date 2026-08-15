---
name: maintenance-code-cleanup-repo
description: Full file-by-file repo cleanup — dead code, duplicated rules, doc drift, and organization — run as an audit → adversarial-verify → fix → re-verify loop that keeps the build and tests green throughout. Use for "clean up the repo", "clean up the codebase", "find dead code", "make this DRY", "the README is out of date", "reorganize this repo", or any request to remove rot without breaking behaviour. Also use before a big refactor, so the refactor starts from a repo with no dead weight in it.
---

# Repo cleanup

Cleanup is not a tidying pass. It is an audit that produces claims, a verification step that kills
most of them, and only then a set of edits. Skipping the middle step is how a cleanup deletes
something load-bearing and nobody notices for a month.

## The one rule that governs everything else

**A tool reports what nothing IMPORTS. That is not the same as what nothing NEEDS.**

Every finding is a hypothesis until you have personally grepped for it. This is not caution for its
own sake — on the run this skill was written from, the first pass flagged nine "unused" files, and
three of them were live entry points invoked by node, playwright and the Next runtime rather than by
an import. Deleting on the tool's word would have removed a migration script.

## Order of work — do not reorder

Config first, then measure, then audit, then verify, then fix. Each step's output is the next step's
input, and doing them out of order produces confident nonsense.

### 0. Fix the config that governs the cleanup, first

If the repo has its own agent instructions (`CLAUDE.md`, `.claude/rules/*.md`, `AGENTS.md`), those
are the yardstick you are about to measure the code against. Check the yardstick before using it:
does every path it names exist, does every count it states still hold, does every rule it states
match what the code does? A cleanup driven by a stale rule file enforces last quarter's conventions.

Same for `~/.claude` when the task touches it. `hooks/config-contract.test.py` is the check.

### 1. Check CI HISTORY and the live deploy, not just your own machine

Before trusting any local gate, look at what the pipeline has actually been doing:

```bash
gh run list --limit 10          # how long has each job been green?
```

A job that has been red for a week is not a job. It has stopped being read, and it will not tell
you when your change breaks something. On the run this comes from, the production-build job had
failed on every push for eight days and nobody had noticed — while the "does it build" question was
the whole reason that job existed.

**"It builds locally" and "CI builds" are different claims.** The gap is almost always config your
machine has and CI does not: a `.env.local`, a credential, a tool version. Reproduce CI honestly —
move your env file aside and build with only what CI supplies. That is a two-minute check that
tells you whether the green tick you are about to trust means anything.

**And check the live site separately from the build.** They fail independently. Curl the deployed
URL, and pick a discriminator that proves WHICH build is serving — a route you deleted should 404,
a route that survived should still answer. Otherwise "deployment is failing" and "CI is failing"
get conflated, and you fix the wrong one.

When CI lacks config the app needs, **derive it from the deploy config rather than copying it into
the workflow or into repo secrets.** The deploy config already has the values, so a second copy is
a second thing to drift. Take only plaintext entries so a real secret can never be surfaced.

### 2. Record a baseline BEFORE touching anything

Run and write down the actual numbers:

```bash
nvm use && npx tsc --noEmit && npm run lint && npm run test:run
```

You need the exact test count, the exact lint problem count, and a clean typecheck. Without a
baseline you cannot tell "I broke 3 tests" from "3 tests were already failing", and you will spend an
hour on the wrong one. If the baseline is not green, say so and fix or quarantine that first — you
cannot cleanup on top of a red build.

Then merge the default branch in. Cleaning a branch that is 8 commits behind means re-doing the
conflicts later, and possibly deleting something main just started using.

### 3. Measure with knip, and configure it honestly

`knip` is the mainstream choice here (webpro-nl/knip, 150+ framework plugins, and the tool
*Effective TypeScript* names for this job). Add `knip.jsonc` — **not** `knip.json`, because knip
rejects a `//` key and the reasoning has to live next to the rules.

```bash
npx knip --no-exit-code            # first look, before any config
```

Then write the config, and keep it minimal:

- Declare ONLY entry points no plugin can infer — scripts invoked by `node`, a test file matched by a
  regex `testMatch`, a framework file the plugin does not know yet. Run `--include configHints`:
  knip will tell you which of your entries are redundant. Delete those; a redundant entry is a place
  future dead code can hide.
- `ignoreDependencies` is for things reached from outside TypeScript — a CSS `@import`, a config
  string. Verify each one is genuinely reachable before adding it.
- **Never silence a true positive.** If something is unused, delete the file. An ignore entry is how
  the rot you are removing comes back.

Split the scripts by scope, because they have different jobs:

```jsonc
"knip":     "knip --include files,dependencies,unlisted,binaries",  // the CI gate — must be clean
"knip:all": "knip"                                                  // the report — includes exports
```

Export analysis stays out of the gate when the repo vendors a component library (shadcn/ui and
similar regenerate their full re-export surface, so ~half the "unused exports" are noise that will
come straight back). Triage those separately rather than parking them behind a passing gate.

### 4. Audit in parallel, by concern

Fan out read-only agents, one per concern, each with the baseline facts stated up front so they do
not re-derive them and contradict each other:

- **doc drift** — every checkable claim in every doc: file paths, npm scripts, route paths, env vars,
  counts, model names, limits. Each one gets verified against the code.
- **DRY / SRP** — the same rule, limit, list or shape in two places. Prioritize anything enforced on
  BOTH the front end and the back end; that is where drift costs the most.
- **dead code and legacy** — beyond knip: read-time fallbacks, deprecated fields, feature flags that
  are permanently on, routes with no caller, TODO markers.
- **organization** — directory-level SRP, naming consistency, oversized files, test colocation.
  Research the framework's CURRENT documented layout from primary sources first, and if the repo
  already matches it, make no finding.
- **tooling and CI** — dependency currency, missing quality gates.

Give every agent the worktree path and a DO-NOT-TOUCH list. Tell them explicitly that a finding
without pasted command output will be thrown away.

### 5. Adversarially verify every finding

Spawn a verifier per finding whose job is to REFUTE it, defaulting to "not real" when it cannot
confirm. On the run this was written from, verification killed 26 of 56 config findings and 53 of 63
codebase findings. Most audit findings are wrong. Acting on an unverified list is the failure mode.

A finding is refuted if: the "duplication" is two things that only look alike, the "dead code" is
reachable dynamically or is a framework convention file, or the "stale doc" is actually accurate.

**A refuted finding is not a finished finding.** The auditor smelled something; it was usually
there, just not where they pointed. Two modules flagged as "the same job under different names"
turned out to be unmergeable — a fixed registry of JSON objects versus unbounded per-user keys
holding raw strings — but underneath them sat a genuinely duplicated accessor, a header claiming an
exclusivity that was already false, and a comment citing a key convention the other module had
abandoned. Refuting the proposed FIX and dropping the finding entirely are different acts. Ask what
made the auditor look twice, and fix that instead.

### 6. Fix, in this order, committing each as its own logical unit

Deletions first (they shrink the surface for everything after), then centralizations, then docs.

## What the fix actually is, when it is not obvious

### An unused helper is usually a centralization, not a deletion

Before deleting an exported helper nothing calls, grep for its VALUE. If the call sites hardcode what
the helper returns, the helper is not dead — it is the intended single source of truth that nobody
was routed through, which is the more expensive version of the same bug.

The instance this comes from: a `marketingUrl()` helper had zero callers, while 22 places across 15
files hardcoded the URL it returns, including JSON-LD blocks and OAuth discovery metadata. Deleting
it would have been the tool-obedient move and exactly wrong. Routing all 22 through it immediately
surfaced a real bug — one call site was reaching the marketing host for a link that has to go to the
app host, which as a bare string nobody was going to notice.

**Ask "why does nothing call this?" before "should this go?"**

### Two implementations of one thing: keep the more complete one, and expect drift

When the same concept exists twice, they have almost always already drifted, and the drift is the
tell. Diff them properly rather than keeping the newer or the shorter one.

Two `useIsMobile` hooks: one used `useSyncExternalStore` with a configurable breakpoint, the other
was the generated boilerplate with `setState`-in-effect and a hardcoded value. The better one had 15
callers; the worse one had one caller which was itself dead. Port the more complete implementation's
edge cases into the survivor — a reimplementation silently drops the details that made the original
correct, and nothing fails loudly.

### A named gate that nothing calls is a correctness bug, not clutter

If an exported predicate expresses a rule and the real enforcement sites inline their own version,
compare them. When they disagree, the exported one is usually WEAKER, and the next person to reach
for it will let something through. Widen the helper to match what is actually enforced, then route
the sites through it. Do not just delete it.

### A read-time fallback with no migration is not deletable yet

A branch reading an old data shape looks like dead code and is not. Check `scripts/` for a migration
that already ran. If one exists, the branch is dead — remove it. If none exists, the finding is
"missing migration", and deleting the branch destroys data. Write the migration, get it authorized,
run it against production, THEN remove the branch. Say so plainly rather than doing half of it.

### Back-compat comes in PAIRS, and neither half is removable alone

A client reads `newField ?? oldField`, commented "fallback during rollout". The server writes
`oldField`, commented "kept for the client's back-compat". Each half exists solely for the other,
so anyone opening one file alone correctly concludes it cannot be touched. That is exactly how a
temporary shim becomes permanent — nobody is ever wrong, and it never leaves.

So when a fallback's comment names another component, go read that component before deciding. Then
remove both halves in ONE commit, and change the test from asserting the field is PRESENT to
asserting it is GONE — otherwise the next cleanup re-derives the same question from scratch.

Prove the fallback is unreachable rather than assuming it: walk every branch that builds the value
and confirm each sets the field the `??` tests. Also check nothing else reads the field you are
dropping. One retryable-flag reader made that removal safe; had it read the dropped field instead,
the same edit would have silently disabled retries.

### A read path with no writer is not a broken feature, it is a superseded one

Before extending, fixing, or backfilling anything, check that something still WRITES it.
`grep` for the write, not the read. This costs one command and changes the whole task.

A field can be read in four files, rendered by a real component, typed, and completely dead —
because the commit that introduced its replacement deleted the writer and left the reader
standing. Nothing fails. The UI simply never activates, and every reader looks load-bearing.

The tell is a feature that seems to "not work" rather than to error. Confirm it against the data
and the history together: when was the newest record written, and which commit removed the writer.
Both, because either alone is ambiguous — no recent records might just mean a quiet feature.

Then look at what the replacing commit put in its place. It is usually BETTER, and it usually
already covers the thing you were about to build. A version archive that sealed old versions into
a side array was replaced by versions that append with a parent link; the successor carries strictly
more information. Building the requested fix onto the dead path would have added new code to a
branch that never executes.

**And the request that sent you there may be premised on the dead thing.** Say so plainly, with
the commit and the counts, rather than quietly building it or quietly not building it. "Per-item X
is not a missing feature, it is contrary to the current design, and here is the commit where that
was decided" is the useful answer, even when the ask was to add per-item X.

**Deleting the reader makes its replacement load-bearing, so pin the replacement in the same
commit.** Check that the successor's own test actually asserts the property you are now relying on
— a criterion that says "parented to the version being retried" while its test only checks a tag is
a claim nobody verifies, and it becomes the single point of failure the moment the old path goes.

### Before deleting an unreachable branch, prove the input domain is CLOSED

"Grep found no callers" is worthless if the value can arrive from outside — a provider's response
body, a user's input, a stored document. It is decisive only when every value that reaches the code
is one you construct. Establish which case you are in FIRST.

The cheap proof: find the type gate. A switch that only ever runs on `error instanceof OurError`,
where `OurError` is constructed in three enumerable places, has a closed domain and grep is
exhaustive. The same switch, one branch earlier where the argument is a parsed JSON body, does not.

### A hand-written copy of a type union is a latent bug, not just duplication

The most valuable thing in that switch was not the dead arms. It was the fifteen live ones: a
by-hand second copy of a union, in a function taking `string`, so the compiler could not check it.
Adding a sixteenth member meant it fell through to the default and a correctly-classified error
silently lost its identity, with nothing failing.

Look for the exhaustive runtime form of the union — a `Record<TheUnion, X>` that TypeScript already
forces to be complete — and derive the check from it. This pattern hides wherever a union is
"validated" by a switch, an array of literals, or an `if (x === "a" || x === "b" || …)` chain. It
reads as tidy duplication and behaves as a silent downgrade.

### Duplicated prose: near-copies are worse than exact ones

An exact-match duplicate check passes on the case that matters. Two copies of a rule that have
drifted apart now say different things, and whoever reads the weaker copy gets the weaker rule.
Compare at ~80% similarity, not equality.

### The setup file drifts in BOTH directions, and only one direction is visible

`.env.local.example` (or its equivalent) is the only instruction anyone gets for standing the
project up, and usually nothing checks it. Check both ways:

- **Missing** — set in the deploy config but absent from the example. This is the damaging one and
  it is invisible, because the person who hits it gets a subtly broken app with nothing to explain
  why. One instance: the example omitted the var that decides which host product deep-links point
  at, and the repo's own comment recorded that getting it wrong had once silently killed every
  verification email.
- **Stale** — in the example, read by nothing. Usually the residue of a migration that updated the
  code and the deploy config but not the example.

The tightest non-noisy invariant is **the deploy config is the production environment, so anything
it declares is something a local environment needs**. Assert in both directions against that.

Then check the deploy config itself for entries nothing reads — dead production config is real, and
its comment will often confidently describe a use that no longer exists.

### Check the framework's own docs BEFORE calling a shape "drift"

Two things that looked obviously wrong on one run and were both correct:

- **Several `components/` directories** — a top-level one plus one per feature and route. That is
  the Next.js docs' "split project files by feature or route", applied properly. Merging them
  would have been a step away from the documented convention.
- **A crowded repo root** — 28 files. Classifying every one showed each sits where Next.js,
  Firebase, or its own tool looks for it. Nothing could move without breaking discovery.

Classify before you reorganize: for each item, name the tool that requires it there. What is left
unclassified is the actual mess, and it is usually one or two files. Then write the conclusion into
the repo's `CLAUDE.md`, so the next agent checks instead of re-proposing the same reorganisation.

### A move is only pure if you diff the OUTPUT

Tests, types and lint passing prove the code still compiles and behaves. They do not prove a
1400-line page still RENDERS the same, because none of them look at the markup.

For a pure move, capture the built artifact first, move, rebuild, and diff. For a prerendered page
that is the HTML in the build output; normalize the two or three things that legitimately change
every build (chunk hashes, module ids, the build id) and everything else must be identical.

This is not belt-and-braces. On the run this comes from, the extraction silently replaced a
non-breaking space around a `×` with a regular one — invisible to tsc, lint and 2000 tests, visible
on the page. The byte comparison is what caught it.

### The lower layer must not import the higher one

Check the direction of every import across your layer boundary — typically `lib/` (or `core/`,
`domain/`) versus `app/`. The violations are almost always a TYPE or a data constant, because those
feel weightless: an editor auto-import completes, the build passes, and a server-side service now
depends on a `"use client"` component to know what `"light" | "dark"` means.

Fix by moving the shared thing DOWN, never by moving the consumer up, and delete the re-export you
were tempted to leave behind — that is the back-compat shim you are here to remove. Then pin it with
a test, because this drifts back one auto-import at a time.

### A tool's confusing error is often the wrong runtime, not a tool bug

When a tool dies with a message that points at its own internals, check the runtime version before
debugging the tool. `knip` failing with "node:util does not provide an export named 'styleText'"
reads as a knip bug and is actually Node being older than the tool needs.

Run `nvm use` from the repo root before anything else, and if the shell's version does not match
`.nvmrc`, say so out loud — half the "flaky" behaviour in a session traces to a shell that never
picked it up. Two checkouts of the same repo can differ, which is exactly how one worktree passed
and another failed on identical code.

### Measure a guard by its false-positive rate, not its rule count

A protective rule that blocks real work gets switched off, and a switched-off guard protects
nothing. So when a cleanup meets a guard, hook, lint rule or check that keeps firing on legitimate
work, that is a finding — not an inconvenience to route around.

Judge it on evidence: how many times did it fire this month, how many were real? On the run this
comes from, a security hook had fired 208 times on real work with ZERO true positives and had been
manually disabled three times. Its replacement then false-positived four times in one session. The
answer was to retire it, because the shape was wrong: it matched on a command's TEXT, so naming a
sensitive path was indistinguishable from reading one.

**Removing a control means updating everything that claims it exists** — the rule file, the README
inventory, the setup steps, the acceptance criteria. A doc promising protection that no longer runs
is worse than an admitted gap, because it stops anyone looking. And state plainly what the removal
opens up rather than glossing it.

### Moving a file can drop it silently out of a glob

Any path list that named the old location stops covering it: a CI path filter, a codeowners entry,
a test-selection glob, a lint override. Grep for the old directory across every config file after a
move. One instance: moving pricing data out of `app/features/pricing/` removed the live Stripe price
IDs from the money-path test trigger, which is the single change most worth running that suite for.

### Encode the rule as a test — it finds instances that reading for it does not

When an audit names a few instances of a pattern, do not fix those few. Write the check that
enforces the rule, run it, and fix everything it names. The delta is consistently large:

- an audit found 3 components hardcoding an upload `accept` allowlist; the test found **7**,
  including two more wildcards that let users pick files the server rejects
- an audit found 1 admin route hand-rolling its auth gate; the check found **5**

Reading finds what you looked at. A check finds what exists. This is also the only way the fix
stays fixed, because the same check then fails on the next instance someone adds.

**Expect your first version of the check to be wrong, and check the failures before believing
them.** A pattern matching `withAuth` followed by an open paren reported five correctly-gated
routes as having NO authentication, because they call it with an explicit generic. Acting on that
would have meant "fixing" working auth. When a new check fires on something you believe is
correct, suspect the check first.

### A directory nothing links to is where outstanding work goes to die

Find the docs no index references:

```bash
for f in docs/**/*.md; do grep -qrl "$(basename $f)" README.md CLAUDE.md docs/runbooks/ || echo "orphan: $f"; done
```

Then READ them, because the danger is not that they are stale — it is that they contain live
obligations nobody is being reminded of. One orphaned `*-DEPLOY.md` held a seven-step runbook with
steps 1-4 ticked and **5, 6 and 7 still open since three days earlier**, including a production data
migration and a security-rule contraction that was verifiably still un-applied.

The fix is not to delete the file. Lift the OUTSTANDING items into the doc the project's index
actually points at, leave the reasoning where it is, and label the directory an archive so the next
person knows which it is. Then say the rule out loud in that label: a plan's deploy steps go into
the runbook the day the plan is WRITTEN, not the day it ships.

### Docs: state no number that nothing pins

Every hardcoded count in a doc drifts, and a stale one is worse than no count because it teaches the
next reader to accept a wrong number. Found in one repo in a single pass: "65-case suite" (77),
"25 units, 145 criteria" (31 and 180), "35 probe patterns" (106). Delete the number and name the
live source, or pin it with a test. Never just correct it — it will drift again.

A doc-freshness check is cheap and worth adding permanently: fail when a doc names a source file
that does not exist. Two false-positive classes it must handle, and both are worth keeping rather
than suppressing — a "removed/superseded" section legitimately names files that are gone, and a
shipped plan document is a record of the past. Detect those by heading and by directory, not by
weakening the check.

## Verification, every time

After each batch, all four, and compare against the baseline:

```bash
npx tsc --noEmit && npm run lint && npm run knip && npm run test:run
```

Test count must not DROP. A drop means you deleted a test, not that you cleaned something.

Never trust a delegated agent's report. Re-run the grep yourself and read the diff — agents report
files clean that they never opened.

### Every guard you add must be proven in BOTH directions before you believe it

A check that cannot fail is worse than no check, because it reads as coverage. For each one, plant a
known-bad input, watch it fail and name the thing, then remove it and watch it pass. This is not
ceremony — on the run this skill came from it caught, in this order:

- a doc-freshness regex written as `Node\.?js?` that required a literal "j" and therefore matched
  nothing, so the EOL runtime pin it existed to catch survived its first run
- a duplicate-prose check comparing for exact equality, which passed on the already-drifted copy
  that was the entire reason for writing it
- an env checker blind to two accessor shapes, because the config files sat outside the directories
  it scanned and a plain node script read its vars through a helper rather than `process.env`

- a "does any file call `localStorage` directly" sweep that stripped string literals before looking
  for the identifier, on the sound-sounding theory that a comment mentioning it is not a call. The
  one real bypass in the repo lived inside a template literal, because it was an inline `<script>` —
  invisible to the very detector written to find it, along with every future script bypassing the
  module the same way. Matching the CALL shape (`.getItem`/`.setItem`/…) after stripping comments
  only sees through the quoting and still ignores prose.

All four looked correct and all four were vacuous. Assume yours is too until you have seen it fail.

Give every sweep a discovery-sanity floor as well, so a broken glob cannot make it pass over zero
items.

### Check the exemption list in both directions too — a stale exemption is an invisible hole

Every sweep grows a list of files allowed to break its rule. Assert the converse as well: each
exempt file must still be doing the thing it is exempt FOR. Nothing else will ever tell you, because
an exemption failing open produces no output at all.

This is not hypothetical. On the run this came from, that check fired immediately — a module had
been moved onto the shared accessor mid-edit and no longer needed its exemption, so the list was
already carrying a hole nobody could see, in a test written minutes earlier. Exemptions are added
under time pressure and never revisited; the converse check is what revisits them.

Make each entry carry its REASON in code, so removing an exemption means deleting a justification
someone has to argue with rather than a line in a list.

## Guardrails

- **No billable calls.** Cleanup never needs a real image, video, audio or LLM call. If a check wants
  one, it is the wrong check.
- **Commit at every checkpoint**, so a quota or context limit mid-run costs one step, not the session.
  One logical unit per commit, with the reasoning in the body — the *why it was safe to delete* is the
  part nobody can reconstruct later.
- **Deleting an HTTP endpoint is a deploy note**, even with zero callers in the repo. Say so.
- **Sub-agents can commit and push.** A read-only audit agent with write tools committed and pushed to
  a config repo mid-run on the source run for this skill. Say "do not write, do not commit, report
  only" in the prompt, and check `git log` after a fan-out.
- **Leave the repo greener than the baseline, or say what you left.** If something is genuinely
  blocked (a migration needing production authorization, an unused export needing a judgement call),
  list it explicitly. A cleanup that quietly skips the hard half is worse than one that names it.

## Stacks with

`/simplify` (built-in) for reuse and simplification fixes on the changed code, and `[gstack] /health`
for the quality dashboard. See `~/.claude/references/skill-stack.md`. Run those AFTER this skill's
deletions land, so they are not analyzing code that is about to go.
