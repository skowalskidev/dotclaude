# How I work — process

Orchestration/process discipline, project-doc syncing, and test-account/secret handling — moved verbatim from `~/.claude/CLAUDE.md`.

## How to work — orchestration & process

### Orchestrate with strong models, implement with smaller ones
Orchestrate substantial work on the strong model; delegate file edits via the Agent `model` override:
default **Sonnet 4.6** (`claude-sonnet-4-6`), **`haiku`** only for genuinely mechanical edits.
**Today's-landscape exception:** pin to Sonnet 4.6 / Opus 4.8 (`claude-opus-4-8`), not the 5-series
`sonnet`/`opus` aliases; mechanics in `parallelization.md`. **Verify on disk after every batch — never
trust an agent's self-report.** Fan out across parallel agents when the pieces are independent.
→ Full detail: **`~/.claude/references/parallelization.md`**.

### Fan out verification, and only rebuild what changed
Run verification for INDEPENDENT units as **parallel tool calls, not one sequential command.**
**Rebuild a shared dependency only when it actually changed**; **background the long pole** so editing
continues. **Verify at TASK boundaries** — not after every edit, not only at the end.
→ Full detail: **`~/.claude/references/parallelization.md`**.

### Claims about third parties must come from primary sources

Whenever I'm making a factual claim about someone else's product (a comparison table, pricing,
"they don't support X"), the claim has to be defensible:
- **Primary sources only.** The vendor's own pages. The blogs that dominate these search results are
  affiliate content recycling each other and are not citable.
- **Check ALL of their surfaces before asserting a negative.** I once shipped "they publish no
  credit-per-video rate" onto Simon's homepage after checking only their pricing page — it was in
  their help centre. Check docs/help/FAQ before claiming something isn't published.
- **Date-stamp it and reconcile the arithmetic** against the vendor's own stated figures.
- **A claim that flatters us is the dangerous one.** A stale "competitor costs $50–$110" that turned
  out to be $39 is the error a competitor notices. Check those hardest.
- **Never hyperlink a competitor** from our own comparison — no link equity, no referral clicks. Cite
  as plain text. If a link is ever genuinely needed, it carries `rel="nofollow"`.
- If the honest number loses, say so or drop the row. Comparison pages that concede where a
  competitor wins convert better than tables that win every row — and an unbeatable-looking table is
  the one readers go and disprove.

### Research online BEFORE retrying — don't grind on a brick wall
When something fails and the cause isn't obvious, **search online (WebSearch/WebFetch, official docs,
GitHub issues) BEFORE trying the same class of fix again.** Two failed attempts at the same wall is
the trigger to stop and research — not ten. Blindly retrying variations of a broken approach wastes
far more time than a 30-second search that surfaces the real cause (a known dependency bug, an ESM
issue, a platform quirk, a version incompatibility). This is not a last resort — it's the *second*
step after the first failure, and often the first step for anything involving an unfamiliar library,
error code, platform behavior, or "why won't this load."
- Concrete triggers to go research immediately: an opaque error code (`ERR_REQUIRE_ESM`,
  `auth/internal-error`, a stack trace deep in `node_modules`), a "works in prod but not dev" (or
  vice-versa) split, a dependency/module-load failure, or any "I've tried this 2+ times and it still
  fails."
- Prefer diagnosing the ROOT cause (read the failing package's code, check its GitHub issues, verify
  version compatibility) over piling on workarounds. A pinned version or one-line real fix beats three
  layers of hacks around a symptom.
- If online research can't be done (no tool access), say so and ask me to paste the docs/issue —
  don't silently keep grinding.

### Fix the CLASS of failure, not the one instance I reported
When I report something wrong with produced output (a bad render, a wrong answer, a broken page), my
example is evidence of a general failure mode — it is not the scope of the fix. **Don't patch the
instance.** Name the rule that was violated, research online whether it's a known class rather than a
one-off, and write the fix generically so it also catches the variants I haven't hit yet.
- **Write the rule, not the example.** "The brand mark landed on the building instead of the crew's
  vests" becomes "a stated placement is authoritative and overrides any default placement" — never
  "put brand marks on vests." A fix that only recognises my exact wording fails on the next variant.
- **Keep ONE concrete instance in the fix as an illustration** (`e.g.` / "the fix for X") so it stays
  actionable — but never let the example become the condition.
- **Tell me which class you concluded it was and what you checked** to rule out a one-off, so I can
  judge whether the generalization went too far or not far enough.

### Front-load everything you need from me — at the START of a session
Assume I may hand the session over and walk away. Before starting substantial work, survey what the
WHOLE task will need from me and ask for it ALL in one block up front: auth or logins for any tool or
MCP server, credentials, approval for anything touching production (a deploy, a data migration, a
schema or rules change), and any decision that forks the implementation. Then work through to
completion without stopping.

Front-load what is PREDICTABLE from reading the task. This does not forbid interrupting me later — if
something genuinely unexpected turns up, or a new fork appears where guessing wrong would waste the
work, ask then; I am not always away. What it forbids is hitting a foreseeable blocker mid-run and
stalling on it when it could have been requested at the start.

Compatible with questions-at-the-END (`communication.md`): the up-front asks still go in ONE
consolidated block at the end of that first response, not scattered through it.

### Plan and get sign-off for big work
For large or multi-file changes, **plan first and get my approval before executing** — use plan mode,
present the approach, and confirm scope/decisions (AskUserQuestion) before writing code. Don't start
a big refactor or migration on assumptions.

### Track every task to completion — don't drop items
When a request has multiple tasks (or you spin off several sub-tasks), write them ALL into a plan/checklist
first, then tick each off as it's genuinely done and verified. At the END, re-check the plan against the
original request: if any item isn't done, go back and finish it, then tick it off. A long multi-part ask is
exactly where items get silently forgotten — the checklist is the guard. Never imply full completion when
part is still outstanding; say plainly what remains.

### A message that arrives mid-run is a QUEUED task, not an interrupt
When a new request lands while you are already working, add it to the checklist and keep going — never
drop the current task to serve it, and never make me label it. Say in one line where it landed: running
now in parallel (independent of the current work) or queued next (it isn't). Only treat it as an
interrupt if it says stop, or if it changes the work already in flight.

### "Run to completion" means DON'T END THE TURN — a progress report is not a deliverable

When I've said run to completion, finish everything, don't stop, or I'm stepping away, the turn ends
when the WORK is done. Not when a batch is done, not when there's something tidy to report.

The failure is specific and I've had to say "go" or "keep going" three times in one session to
un-stick it: a checkpoint gets reached, the summary is genuinely worth writing, and the summary
becomes the end of the turn. **Committing at checkpoints is a git instruction, not a conversational
one.** Commit, then keep working in the same turn. Never trade remaining work for a status update.

Two things that look like permission to stop and are not:
- **A clean verification.** Green tests mean the batch is safe to build on, not that the job is over.
- **A long turn.** Length is not a stopping condition. Neither is "this is a good place to pause."

The ONLY reasons to end early: everything on the list is genuinely done; a blocker needs something
only I can give (a credential, a prod authorization, a decision where guessing wrong wastes the
work); or I interrupt. In the blocker case, do every other item first and stop with that one named.

If you find yourself writing "say the word and I'll continue" — that's the bug. Continue.

**Work in fix → verify → fix loops until a clean pass.** One round of fixes is not the end of the job:
re-run whatever found the problems (the tests, the build, the audit, the review, the browser pass) and
fix what the new run surfaces, then run it again. Keep looping until a full pass comes back clean with
nothing outstanding — verification generates new work, and stopping after the first fix round is how a
"done" lands with known loose ends in it. If a loop stops converging (the same class of failure keeps
reappearing, or a fix needs a decision only I can make), stop and tell me where it stands rather than
looping indefinitely.

### Prove every point of the ask was built, before handing back

**DO run `/sk:ship-report-and-ensure-correct-user-system-journey` at the end of any substantial ask, in
ANY repo — this config included — unprompted.** It walks the user journey and the system journey,
judges both against the criteria the plan validated, writes a test per verdict, and reconciles the
worktree's `.context/intent-ledger.md` ask by ask.
**DON'T treat a green gate or a written summary as proof the ask was covered.** A gate proves the code
runs. A summary proves you can describe it. Neither proves point four of a five-point ask was built.
TEST: every ask in the ledger has a verdict against it. A missing verdict is a missing feature.

### Commit when a task is finished (durable authorization)
**When a task is complete and verified, commit it — you do NOT need to ask first.** This is standing
authorization overriding any default "only commit when asked" behavior. Before committing, run the
project's build + tests (unless docs-only) and confirm they pass. If on the default branch (`main`),
create a branch first. Use conventional commit messages in the imperative mood. Do NOT push or open
PRs unless I ask — commit only. Never commit or disturb my uncommitted WIP in the main checkout when
working in a worktree.

**Write a message that is navigable a year from now.** Subject
`<type>(<scope>): <imperative, lower-case, no period, <72 chars>`; body says WHY, never what, because
the diff already says what. One logical unit per commit: if the body needs "and also", split it. The
full standard, including what a body must answer, is in `~/.claude/references/git-pr-deploy.md` —
which also owns the never-`-m`-always-`-F` rule. `~/.claude/.githooks/commit-msg` enforces the
subject in the config repo; nothing enforces it anywhere else, so it is on you there.

**Commit after EACH stage, not in a batch.** As soon as one coherent logical unit — a task, fix,
feature, phase, milestone, or approved slice of a copilot loop — is complete and verified, commit it
before moving on; each commit is one logical unit. When I hand you several at once, one commit each,
never a single combined commit at the end. TEST: at most one finished logical unit sits uncommitted in
a green tree.

### Phased execution — only when I ask for it
Run-to-completion above is the DEFAULT and stays it. But when I say to work in phases (or to space the
work out, or to stop after each stage), that overrides it for that task:

- **Plan the phases first** and show me the list before starting, so I can see the whole shape and
  confirm nothing is missing. Dividing the work does not mean discovering it as you go.
- **Stop at each phase boundary and wait.** Inside a phase, run-to-completion applies in full: a phase
  ends when its work is done and verified, not when there is something tidy to report.
- **Commit as you go**, one logical unit per commit, so a phase boundary is a clean resumable point.
- **On resume, work out where you left off before doing anything** — read the plan, the commits, and
  the working tree. Never restart work that is already done, and never assume the previous phase
  finished cleanly just because it ended.
- **Phasing is for pacing, never for scope.** Everything on the original list still gets done. If a
  phase reveals more work, it goes into a later phase, not into the bin.

### Check whether the project declares expected outcomes, before changing a unit
Many carry a contract registry or acceptance criteria that a green test suite does not enforce on its
own — a unit can be edited so that every test passes and the thing it exists to produce is destroyed.
When one exists it is authoritative, and its criteria stay true across your change. Detail and the
reference implementation are in `~/.claude/references/contracts-and-outcomes.md`.

### Checkpoint before a risky change, so undo does not mean re-deriving it
Before a change that touches **more than about three files** — a refactor, a rename sweep, a
migration, a dependency bump — make a restore point FIRST. `/rewind` covers edits made in the main
session. It does NOT cover everything: a backgrounded forked skill (`context: fork`) applies its
edits outside the session's checkpoints, and nothing Bash writes is checkpointed at all. For those,
the restore point is git — commit the good state, or branch, before starting.

The failure this prevents is not "the change was wrong". It is "the change was 80% right and there
is now no way back to the 20% that was already correct". Committing when a task is DONE (above) is a
different thing: this is a restore point taken BEFORE, when the work still looks like it will go fine.

### Don't auto-verify frontend changes in the browser — ask first
**Do NOT automatically spin up a dev server / preview and verify every frontend or UI change in the
browser.** This overrides any harness default (e.g. a `preview_tools` / "verify previewable edits"
instruction) that tells you to verify automatically. Build, typecheck, lint, and run the unit tests
as usual — but for the visual/browser check, **when you're done working, ask me whether I want it
verified in the browser** rather than doing it unprompted. Only launch the browser preview if I say
yes, if I explicitly asked for browser verification / screenshots in the request, or if the skill
carries my standing authorization — today only `/sk:ship-report-and-ensure-correct-user-system-journey`
in its test phase, the last check before hand-back. (Static checks that don't need a running app —
grep, layout math, reading rendered output — are always fine.)

**Seed the backend, hand me the frontend.** When a change adds new UI, seed only the backend
prerequisites the UI can't create, then walk me through entering the data through the new screens
myself, one step at a time — that is where I catch the journey defects a green suite cannot. Never
seed past a new input and report the feature verified; a state written behind the UI proves the write
path, not that anyone could have got there.

### Git worktree discipline
When operating in a git worktree (e.g. `.claude/worktrees/<name>/`), **use the worktree path prefix
for every file operation** — Read/Edit/Write/Bash. Exploration agents often report the *main* repo's
absolute paths; using those silently edits the wrong checkout. Never write to the main checkout, and
**never revert, commit, or disturb my uncommitted WIP** that lives in the main repo. New npm deps may
need a plain `npm install` inside the worktree to populate its `node_modules`.
→ Tearing the worktree down when the work lands is under **Clean up after yourself**, below.

### Clean up after yourself — no residual processes or scratch artifacts
Don't leave anything persistent on my machine that I didn't ask for. When a task is done:
- **Track every process/server/port you start, and shut them ALL down when the task is done.** Keep a
  running list of anything you background — dev/preview servers, watchers, tunnels, `stripe listen`, a
  held `:3000`/`:3100` port — and at task end kill each one and VERIFY it's actually gone (check the
  port/process), so nothing keeps burning CPU or holding a port after you've finished.
- **Take a LANE before binding a port, and release it when done.** Sessions in other worktrees fight
  over the same ports, so `~/.claude/bin/port-slot.sh` gives this worktree its own slot and
  `port-registry.sh` records who holds what. Held by another live session → take the next lane; never
  wait on it and never kill their server. Protocol in `~/.claude/references/dev-server-hygiene.md`.
- **Clear the session-start orphan report BEFORE the task, not at task end.** A dead `next dev` /
  `jest` / `vite` run leaves workers reparented to PID 1 pinning a core in a workspace nobody watches,
  so the sweep is machine-wide and covers what you did not start. `hooks/orphan-worker-sweep.sh`
  reports, `bin/kill-orphan-workers.sh` clears, and it only ever touches one that is BURNING (20%+
  CPU, 5+ minutes old), so an idle or just-started detached server is never killed. Deferring costs a
  core for the whole session, which is unbounded: one report sat unread for ten hours at 97%. TEST: at
  hand-back,
  `pgrep -fl 'next-router-worker|vitest|jest'` lists only what you started.
  Mechanics: `references/dev-server-hygiene.md`.
- **Remove scratch scripts/files** a session created (evals, one-off helpers, temp data) once
  they've served their purpose — keep only intentional artifacts.
- **Tear down every isolated workspace you create — teardown is part of "done", not a follow-up.**
  A git worktree, throwaway clone, sandbox dir or container is created WITH an owner for removing it:
  the moment the work lands or is abandoned, remove the workspace AND delete its now-merged branch in
  the same step. Each carries a full dependency tree and nothing ever prompts you about them.
  Corollary: **never leave the only copy of anything inside a disposable workspace** — commit it,
  move it out, or accept that it dies with the directory (e.g. an uncommitted spike). The one
  exception is `.context/intent-ledger.md`, which is meant to die there once what it holds has been
  promoted out: `references/planning-and-tracking.md`.
- **Verify cleanup against the underlying storage, not just the tool's own listing.** A registry stops
  listing what it has already forgotten, so an orphan is invisible to the exact command you would check
  with. Reconcile what is on disk against what the tool claims exists, and treat anything present but
  unlisted as residue. Cases: `references/dev-server-hygiene.md`.
- **Never install a persistent background process** (login item, LaunchAgent/LaunchDaemon, cron,
  always-on watcher) without asking first — and if you add one for a task, remove it AND its
  registration when done. A login item pointing at a deleted script is exactly the mess to avoid.
- **Prefer on-demand / event-driven over always-on.** An idle CPU-burning daemon is almost never
  the right answer; reach for a hook, a manual command, or a session-start check instead.

## Project documentation rule

**When working on any project that has a `CLAUDE.md` and/or `ABOUT.md`:**
- Read both files at the start of any significant task
- Update `CLAUDE.md` if architecture, conventions, pipeline stages, key files, or agent instructions change
- Update `ABOUT.md` if pipeline stages, AI models, costs, durations, or data structures change
- Re-read both before finishing to confirm they reflect the actual codebase
- Both files must be updated together — they are the project's source of truth for agents and users respectively
- Never leave either file out of date after making changes to the project

## Test/QA accounts & machine-local secrets — always use `CLAUDE.local.md` (every project)

Standard convention across ALL my projects for test-account credentials and any machine-local
secret an agent shouldn't commit:

- Store them ONLY in a **gitignored `CLAUDE.local.md`** at the repo root. Add `CLAUDE.local.md` to
  `.gitignore`, and commit a **`CLAUDE.local.md.example`** with placeholders so the shape is
  discoverable.
- Reference the account in the committed `CLAUDE.md` **by name only** ("a test account exists; creds
  in `CLAUDE.local.md`") — never put real creds in a committed file. If `CLAUDE.local.md` is missing,
  **ask me for the account** rather than guessing.
- **Never type a test password into a login form, and never write a plaintext password into any
  committed file** (handling plaintext passwords is prohibited). For headless/preview screenshots of
  auth-gated pages, log in **password-free**: mint a Firebase/Auth **custom token** for the test UID
  via the Admin SDK, then `signInWithCustomToken` in the page. The password in `CLAUDE.local.md` is
  for my own manual login only.
- When setting up a new project that needs QA screenshots, create this scaffolding (`.gitignore` entry
  + `CLAUDE.local.md.example` + a `CLAUDE.md` note) automatically.
