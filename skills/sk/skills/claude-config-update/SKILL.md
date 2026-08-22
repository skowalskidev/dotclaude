---
name: claude-config-update
description: The ONE way to change the user's OWN PRIVATE Claude config (~/.claude — the instruction files Claude reads) — whether folding in a correction, adding a standing rule, OR creating/editing/removing a whole part (a new skill, a rule file, a reference catalog, a hook, a bin script, a connector manifest, settings wiring). A hard-blocking hook stops ad-hoc ~/.claude edits outside this flow, so route ANY config change through here. NOT the built-in /update-config, which edits settings.json hooks and permissions. Targets any of: an always-on rule file (~/.claude/rules/*.md), a reference catalog (~/.claude/references/*.md), the user's own skills (the sk / sk-work plugins only, this skill itself included — never third-party or project skills; discovered at runtime), the executable/wiring layers (hooks, bin, connectors/*.json, settings.json), or a CLAUDE.md they maintain (the global ~/.claude/CLAUDE.md, a project's committed CLAUDE.md, or a project's local gitignored CLAUDE.local.md). Just PASTE the past correction-prompts or state the new part (no need to name a target); this extracts the underlying learning, generalizes it, PROPOSES where it belongs (you confirm or redirect), previews the exact change, and only edits after you confirm. Use whenever any part of the config should change — "create a new skill", "add a skill / hook / rule", "change my config", "update my ~/.claude", "here are the prompts I kept sending, make this stick", "update /sk:X with this feedback", "add this to my global CLAUDE.md", "add this rule to my UI conventions", "make this correction permanent".
argument-hint: "paste the correction-prompts / rule to fold in — the target is proposed for you"
---

# Change the private Claude config, always through this flow

The premise: some part of `~/.claude` should change — Claude did something wrong, the user has a new
standing rule, OR the user wants a whole new part built (a new skill, rule, reference, hook, `bin`
script, connector manifest, or settings wiring). Whichever it is, the change should land IN the config
that governs the next run — a `rules/*.md`, a `references/*.md` catalog, a skill, a CLAUDE.md, or the
config's executable/wiring layers (a hook, a `bin` script, a connector manifest, `settings.json`,
`~/.claude.json`) — coherently and at the right altitude. Your job is to route the change to its right
home, show it for approval, then apply it. This skill is also the mechanism the `self-healing-config`
rule uses to fold a resolved config fix back in.

**This is the ONLY sanctioned path for editing `~/.claude`.** `hooks/config-edit-guard.py` hard-blocks
an Edit/Write to a tracked config file (`rules/`, `references/`, `skills/`, `work/`, `hooks/`, `bin/`,
`connectors/`, `contracts/`, `dotfiles/`, and the top-level config files) unless this flow has set its
authorization sentinel. So a config change never happens ad-hoc: it runs through the gate below, which
is what caught the lessons a hand-edit skips (a missing contract entry, a missing routing scenario, an
unverified figure). When Simon asks for ANY change to `~/.claude` — including "create a new skill" —
this flow is how it gets done, without being asked to use it.

Never skip the confirmation gate (Step 5). Never edit a file you weren't asked to. Never make a skill
narrower — a learning from one task must not overfit the skill to that task.

**Scope: the user's OWN PRIVATE config only** — five families of target.

The name is deliberate on both halves. **Config**, not "skill", because the config outgrew skills — an
always-on rule now usually belongs in `rules/*.md`, not in a skill body. **Private**, because Claude Code
ships its own built-in `/update-config`, and that one is a different job: it edits `settings.json` (hooks,
permissions, env vars), which the HARNESS enforces deterministically. This one edits the instruction files
Claude READS and is meant to follow. When a new rule must fire every time with no judgement involved, it
belongs in the built-in's territory as a hook or permission, not here; when it needs judgement, it belongs
here. Something both critical and judgement-driven gets both, with the written rule primary and the hook as
a backstop — the shape `rules/security.md` already uses.

1. **An always-on rule file** — `~/.claude/rules/*.md`, auto-loaded every session at the same priority
   as the global `CLAUDE.md`, one concern per file (security, communication, copy quality, process,
   engineering standards, UI conventions, …). **This is the default home for a behavioral rule Claude
   must apply without being asked.** Some are path-scoped via frontmatter `paths:` (e.g. `ui-conventions.md`
   loads only for `*.tsx/jsx/vue/svelte/css`), so a rule that only applies to one kind of work belongs in
   the scoped file rather than the global CLAUDE.md — it costs nothing on turns that don't touch it.
   Read the file's frontmatter before adding, and keep the file to its one concern; a rule that doesn't
   fit any existing one gets a new `rules/*.md` plus a line in the CLAUDE.md index.
2. **A reference catalog** — `~/.claude/references/*.md`, deep task-only how-tos loaded on demand (see
   Step 1's catalog-first note).
3. **The user's own skills** — the `sk` and `sk-work` plugins under `~/.claude/skills/`. Works on every
   current `sk`/`sk-work` skill AND any created later, discovered at runtime, never a hardcoded list. NEVER
   edits third-party or installed skills (gstack, impeccable, agency-agents, anthropic-skills, any other
   plugin) or project-local skills — those aren't the user's to maintain here and get overwritten on upgrade.
   A skill target outside `~/.claude/skills/sk`, `~/.claude/skills/sk-work` or its real home
   `~/.claude/work/sk-work` → refuse. `sk-work` is a SYMLINK into the untracked `work/` dir, so
   resolve the path before checking it and accept either form; checking only the `skills/` prefix
   refuses the work skill outright.
4. **A CLAUDE.md the user maintains** — one of three levels:
   - **Global** — `~/.claude/CLAUDE.md`, the user's private instructions for ALL projects.
   - **Project (committed)** — the current project's git-tracked `CLAUDE.md` at the repo root.
   - **Project (local)** — the current project's gitignored `CLAUDE.local.md` (machine-local config/secrets-by-reference).

   Only these. Never touch a project CLAUDE.md that isn't the current project's, and never a third party's file.
5. **The config's executable + wiring layers** — when a lesson needs enforcement or activation, not just
   prose. `~/.claude/hooks/*` (PreToolUse/SessionStart enforcement), `~/.claude/bin/*` (engine scripts),
   `~/.claude/connectors/*.json` (per-project connector manifests), `~/.claude/dotfiles/*` and the
   machine-level files symlinked to them (e.g. `~/.gitignore_global` — tracked here, so a rule needing
   a machine-wide git or shell setting lands in the repo rather than as untracked machine state), and
   the ACTIVATION layer that turns a rule/hook on: `~/.claude/settings.json` (hook wiring,
   `permissions.deny`, PreToolUse matchers) and `~/.claude.json` (MCP server entries). The built-in `/update-config` also edits `settings.json`; this
   skill MAY drive the settings wiring needed to activate a rule/hook it just wrote (or hand off that
   mechanical part) so a change lands COMPLETE, not half-wired. A capability that spans layers (a rule +
   a hook + a `bin` script + a manifest + settings wiring + a skill) gets ALL its needed pieces created
   coherently and NONE that aren't. This is also the home for **adding a connector** (write the
   `connectors/<project>.json` record; the data-driven guard + provisioner cover the rest).

**Structure/altitude router — keep the layout clean.** Route each piece to its right home: always-on
behavioral → `rules/`; deep how-to → `references/`; executable enforcement → `hooks/`; engine logic →
`bin/`; user-invocable flow → `skills/`; per-project specifics → `connectors/*.json` (or a project
`CLAUDE.local.md`); deterministic wiring → `settings.json`. **Top-level `~/.claude/CLAUDE.md` stays a
thin index** (one line per rule/reference), never the detail.

## Step 1 · Resolve the target (INFER + PROPOSE — don't ask upfront)

The usual input is just the correction-prompts Simon pastes (the messages he sent Claude in the past to
get it back on track) — he does NOT pre-name a target, and shouldn't have to. So **do NOT stop and ask
which skill upfront.** Instead:
1. Extract + generalize the learning FIRST (Steps 3–4).
2. INFER the best-matching target from the learning's content — match its topic against each `sk`/`sk-work`
   skill's frontmatter `name:` + `description:` (glob them at runtime, below), and against the CLAUDE.md levels.
3. PROPOSE that target (with a one-line "why this one") at the confirmation gate (Step 5); Simon confirms it
   or redirects to a different skill / CLAUDE.md.

Only stop and ask upfront if the content genuinely points to no candidate, or fits two roughly equally —
then present the top options and let him pick. Candidates:
- a specific `sk`/`sk-work` skill (the common case),
- a shared **reference catalog** in `~/.claude/references/*.md` (a deep, task-only how-to loaded on demand — code best practices, planning, testing, parallelization, git/PR/deploy, api-empirical-iteration). If the learning is a detailed process rule, it usually belongs in the matching catalog, and the skills that use it already point to it, so one edit updates every consumer (DRY),
- the **global** `~/.claude/CLAUDE.md` (an always-on cross-project behavioral rule — security, response/copy style, orchestration — that must be in context every turn, not lazy-loaded),
- the current project's **committed** `CLAUDE.md`,
- the current project's **local** `CLAUDE.local.md`.

**Catalog-first for deep rules; skills stay thin.** The `sk` skills are now thin: SKILL.md is a short pointer that tells the agent which `~/.claude/references/*.md` catalog(s) to read. So when a learning is a detailed process/how-to, fold it into the CATALOG, not into the skill body — adding prose to a skill that should just point is the anti-pattern. Reserve edits to a SKILL.md itself for its trigger `description`, its pointer list, or genuinely skill-specific orchestration. Always-on behavioral rules go to CLAUDE.md; deep task-only detail goes to a `references/` catalog.

**Resolving a skill target.** Discover the user's own skills by globbing ONLY their two plugin dirs, so
newly-created skills are found automatically. Read each SKILL.md's `name:` — never work from memory:
```bash
find -L ~/.claude/skills/sk ~/.claude/skills/sk-work -name SKILL.md 2>/dev/null
```
**`-L` is load-bearing.** `skills/sk-work` is a symlink into `work/`, and BSD `find` does not
descend a symlink passed as an argument. Without it the work skill returns NOTHING and this step
reports "no match" instead of failing, so the bug looks like a missing skill rather than a broken
search.

Match the user's words against each skill's frontmatter `name:` and folder name (they live at
`~/.claude/skills/<plugin>/skills/<name>/SKILL.md`; the plugin is the `/sk:` / `/sk-work:` namespace).
Hard guard: the path MUST be under `~/.claude/skills/sk/`, `~/.claude/skills/sk-work/`, or that
symlink's real target `~/.claude/work/sk-work/`; a skill that isn't one of theirs → refuse and
offer to capture the learning in one of their own files instead.
If the name matches both plugins, show the matches and ask which.

**This skill can target ITSELF.** When the correction is about how `update-private-config` itself
behaves — how it extracts, generalizes, what altitude/example it writes, its gate, this very
process — the target is its own SKILL.md (`~/.claude/skills/sk/skills/claude-config-update/SKILL.md`);
fold it in like any other `sk` skill. You're editing the skill mid-run, so the change takes
effect on the NEXT invocation, not this one — still preview and confirm as normal.

**Resolving a CLAUDE.md target** — this is where the worktree matters, so get it right:
- **Global** → `~/.claude/CLAUDE.md`. One file, no worktree subtlety.
- **Project committed `CLAUDE.md`** → edit the copy in the **CURRENT worktree/session you're running in**.
  It's git-tracked, so the edit rides the branch and ships in the PR when it merges. Do NOT reach back to the
  main checkout for this one — that would edit a different branch's copy and skip the PR.
- **Project local `CLAUDE.local.md`** → edit the copy in the **MAIN project checkout root**, NEVER the
  worktree's copy. `CLAUDE.local.md` is gitignored and machine-local, so a worktree copy is disposable —
  deleting the worktree loses the change. The main checkout persists it. Resolve the main root (works even
  from inside a worktree):
  ```bash
  dirname "$(git rev-parse --path-format=absolute --git-common-dir)"   # → main checkout root
  ```
  Then target `<main-root>/CLAUDE.local.md`. When NOT in a worktree the main root == cwd, so it's the same
  file either way. If the file doesn't exist yet, confirm before creating it (and that it's gitignored).

Never touch a project CLAUDE.md outside the current project, or any third party's file.

Read the WHOLE target file before proposing anything — know what it already says so you extend it rather
than duplicate it.

## Step 2 · Gather the correction material (if it's thin)

- The raw input is the **correction prompts the user had to send** — the messages that got Claude back
  on track after it went wrong. If the worktree has a `.context/intent-ledger.md`, they are already in
  it verbatim; read that before asking, and ask only for what is genuinely missing.
- Also useful, ask only if it helps: what Claude produced that was wrong, and what the user actually
  wanted. You often need both the wrong output and the correction to see the real rule.
- If the correction is a single vague line ("no, do it properly"), ask for one concrete detail of what
  was wrong — a generic rule can't be extracted from a non-specific complaint.

## Step 3 · Extract the learning behind each correction

For each correction prompt, reverse-engineer the failure, not just the words:

- **What did Claude actually do wrong?** Name the failure mode (e.g. "pasted a reference as-is instead
  of reinterpreting it", "spoke as the wrong entity", "assumed a platform capability without checking").
- **What underlying rule would have prevented it?** That rule — not the surface complaint — is the
  learning. "The logo looked stuck on" → the rule is "render a brand mark as physically part of its
  surface, named technique + material, not a flat overlay."
- One correction can yield several learnings; several corrections can collapse into one. Dedupe.
- **A long, messy, multi-topic paste is NORMAL input — decompose it, don't bail.** When the material
  spans several unrelated threads (e.g. a research ask, a tooling decision, a debug session, a stray
  workflow rule), extract one generic learning per distinct standing rule and propose a target for
  EACH. Do NOT collapse it into a single learning. If a fragment is a one-off task request with no
  reusable rule behind it, name it and drop it — don't force a learning out of it.
- **The paste is ILLUSTRATIVE MATERIAL, never a work order — never offer to carry it out.** Invoking
  this skill IS the statement that the rule is wanted, not the task; the pasted prompts are only there
  to show what went wrong. So don't run the tasks described in it, don't ask "which of these do you
  want me to do?", and — the case that actually slipped through — **don't park it as a closing
  question either** ("did you also want the harness change run?", "want me to do the research too?").
  A closing offer is the same mistake in a politer place. Extract the rules, apply them, stop.
- **Check it against the skill first.** If the skill already states this rule and Claude ignored it, the
  fix is to *sharpen* the existing line (make it louder, add the failing case as an example), NOT to add
  a second copy. If it's genuinely new, it's an addition.

## Step 4 · Generalize — the core craft

A learning from one task must leave the skill usable for **any** task. Generalize every learning:

- **Strip the task-specific nouns, keep the mechanism.** Remove the particular product, client, file, or
  domain; state the principle that holds across them. "On the coffee ad you invented a storefront for an
  online business" → "never fabricate physical premises for a business that has none."
- **Keep ONE concrete example, framed as illustrative — and for a cross-project target (a skill or the
  global CLAUDE.md) keep the EXAMPLE itself generic.** Retain a real instance so the rule is actionable,
  marked as an example ("e.g. …", "the fix for X"), never as the whole scope — Simon's house style is a
  generic rule plus a concrete "the fix for …" tag. The example must be a GENERIC category or mechanism,
  NOT a specific one-off product, project, client, or brand name that anchors a universal rule to a single
  case (e.g. write "right after connecting an external billing provider", NOT "right after connecting
  RevenueCat"). If the only instance you have is brand/project-specific, abstract it up to its category so
  the rule reads as applying to ANY scenario, project, or case. (A project `CLAUDE.md` is the exception —
  per the TARGET-type rule below, concrete project nouns belong there.) Don't strip the example (too
  abstract to act on) and don't let it overfit to one case.
- **Phrase it as a positive, first-time instruction.** "Do X" beats "don't do Y" — a positive material
  instruction is followed more reliably than a prohibition. Write it so Claude does the right thing
  proactively on the next run, not so it recognizes the mistake after making it.
- **Write every line to `~/.claude/references/config-writing-standard.md`.** It is the one standard for
  rules, references, skills and the contract registry: DO-led, a DON'T only where the wrong way is the
  default, the three things a rule must state, the banned hedge words, and the mission format. Read it
  before writing. `hooks/config-contract.test.py` fails what breaks its mechanical half.
- **Write it as a checkable instruction, not a principle.** State, in this order: the DEFAULT to
  apply, the NUMBER or threshold, and the TEST that catches a violation. If you cannot name the
  test, you have not found the rule yet.

  These are rules:
  - "Cut the number of text sections to the minimum a human can scan-read. Count them before and
    after; if the count didn't drop, you compressed instead of deleting."
  - "Default to a label only: 2-5 words, no verb. A sentence needs a reason to exist."
  - "Every section a human reads is TL;DR-first and actionable — assume a short attention span and
    that they read the first line only."

  These are not rules. They are the thinking that produced one, and they leave the next run exactly
  where it started:
  - "Prefer less text." — no default, no number, no test.
  - "Consider whether the section is needed." — a question, and Claude will answer yes.
  - "Ask what decision the user makes from this block." — instructs a deliberation, not an act.

- **Match the skill's altitude.** A broad harness skill gets a broad principle; a narrow single-purpose
  skill can take a sharper, more specific rule. Don't drag a whole skill down to one task's specifics.
- **Match generalization to the TARGET type.** A skill and the **global** `~/.claude/CLAUDE.md` hold
  cross-project rules → strip the task/project nouns, keep the mechanism (as above). A **project** `CLAUDE.md`
  is SUPPOSED to be project-specific → keep the concrete file paths, commands, and names; don't over-
  generalize it into uselessness. A **`CLAUDE.local.md`** holds machine-local specifics (test accounts, local
  paths, secrets-by-reference) → keep them concrete, but never write an actual secret VALUE into it — reference
  where it lives (e.g. "the service-account key path", "`TEST_PASSWORD` in `.env.local`"), matching how the
  rest of that file reads. Every `CLAUDE.local.md` is auto-loaded into context at session start, so a value
  written there is a value in every future transcript — that is the reason for the rule, not just committing.
- **Ground every factual claim against its source before you write it — never restate from memory.**
  When the new text asserts a measured figure, a threshold, or how another part behaves ("superspeed
  buys ~33s", "the gate caps at 7 findings", "skill X does Y"), open the source that owns that fact —
  the other skill's SKILL.md, its `contracts/config_contracts.py` entry, the `references/*.md` catalog,
  or the measurement log — and quote what it actually says. TEST: every number and every "part X does
  Y" line in the change traces to a file you opened THIS run. This is the rule the ~33s slip broke:
  a fixed ~33s advantage of the parallel harness over in-session agents got written up as if it capped
  parallelism itself, because it was recalled instead of read.
- **Preserve Simon's voice.** Skill text is agent-instruction prose (the anti-em-dash / anti-AI-copy rule
  is for human-facing copy, not this) — but keep it terse, imperative, concrete, declarative, the way the
  existing sections read. No filler, no throat-clearing.

## Step 5 · Propose the additions and get explicit confirmation (the gate)

Before touching the file, show the user exactly what will change:

- For each learning: the **target section** (an existing heading to extend, or a new heading), and the
  **verbatim text** to be added or the sharpened replacement line.
- Show it as a clear before/after or a bulleted "these lines will be added under `## Section`" — the user
  must see the actual words, not a summary of them.
- State briefly, per item, which correction it came from and how you generalized it, so the user can judge
  the generalization.
- **Lead with the proposed target:** "I'd fold these into **`<plugin:name>`** because <one-line reason>."
  Then show the additions. Ask: apply to that target? Simon can approve, edit wording, drop individual
  items, or **name a different skill / CLAUDE.md** — then re-resolve against that target and re-preview.
  **Only proceed on a clear yes.**
- **Ask for anything else the change needs, with copy-paste instructions to get it — in the same block.**
  Before applying, survey what would make the change land COMPLETE and name anything only Simon can
  supply: a decision that forks the design, a value or credential you can't read, a file or doc to
  fetch, an example he referred to, a source to confirm a claim against. For each, give the exact
  numbered steps for him to get it for you (the command to run, the page to open, the file to paste),
  the way `process.md` front-loads asks. Put them all in ONE block with the gate question, then wait —
  don't discover a foreseeable blocker halfway through applying.

## Step 6 · Apply the edit

- **Authorize the edit first, only now that Simon has confirmed.** `hooks/config-edit-guard.py` blocks
  every Edit/Write to a tracked config file until the sentinel exists. Set it right before editing:
  ```bash
  touch ~/.claude/.config-edit-authorized
  ```
  This is what separates a sanctioned change (past the gate) from an ad-hoc one. Never set it before
  Step 5's yes, and never leave it set — Step 7 removes it. It is not needed for a project `CLAUDE.md` /
  `CLAUDE.local.md` target (those live outside `~/.claude` and the guard ignores them).
- Edit the target file in place (the SKILL.md or the resolved CLAUDE.md): extend the right section or add a
  tightly-scoped new one. Prefer extending an existing section (DRY) over adding a near-duplicate heading.
- Keep the file coherent — additions read as if they were always there, same formatting and altitude.
- **Do not bloat.** If an addition overlaps an existing line, merge them into one sharper line rather than
  stacking both. A skill that doubles in size per correction stops being usable.
- **DO extract a mechanic a NEW skill shares with an existing part into ONE SSOT, and point both at it.**
  When the new skill reuses a sibling's plumbing (a git ritual, a poll loop, a handoff shape), move that
  mechanic into the `references/*.md` catalog that owns the domain, trim the sibling to a pointer, and have
  the new skill compose the same section — a legitimate cross-file refactor, not scope-creep.
  **DON'T leave a pointer that names a sibling's step by NUMBER** ("its Steps 1-4"): it drifts the moment
  the sibling is re-sectioned. (the fix for a new offshoot skill that first pointed at "hyperspeed's Steps
  1-4"; the shared START+paste-block+poll handoff moved to `references/parallelization.md` and both skills
  now compose it.) TEST: the new skill names no sibling's step by number, and any mechanic two parts share
  appears in exactly one file.
- Update the frontmatter `description` ONLY if the new learning changes when the skill should trigger;
  otherwise leave it.
- **Keep the `~/.claude/CLAUDE.md` index honest.** It carries a one-line summary per `rules/*.md` and
  `references/*.md`. If the addition broadens what a file covers (or adds a new one), update that line in
  the same pass — a stale index is how the wrong target gets picked next time.
- Change only the target file — plus, when a new part shares a mechanic with a sibling, the SSOT
  extraction above (move the mechanic to a reference, trim the sibling to a pointer). Never widen the edit
  into an UNRELATED cleanup.

## Step 6b · Keep the tests in step with the config, then run them

The config's own tests are what stop a self-improvement pass quietly degrading it. They only work if
they grow with the config, so this is part of applying the edit, not a follow-up.

**Update alongside the edit:**

- **`contracts/config_contracts.py`** — a NEW config part needs an entry (what it's for, what must
  stay true). A CHANGED part whose guarantees moved needs its criteria updated. The suite fails both
  ways: a part with no entry, and an entry naming a file that no longer exists.
- **`contracts/routing_scenarios.py`** — a new skill needs a scenario saying how Simon would ask for
  it, in his words. A changed `description` needs its scenario re-checked. A new hook or a changed
  `settings.json` matcher needs a `HOOK_ROUTING` case, including the awkward variants (the
  `mcp__*__AskUserQuestion` form is in there because missing it deadlocked a whole session).

**Then run it, and loop until clean:**

```bash
/usr/bin/python3 ~/.claude/hooks/config-contract.test.py
```

Zero model calls, milliseconds, so run it freely. A failure is the point of the exercise: fix the
config, not the test. Only change a criterion when the guarantee genuinely moved, and say so out loud
in the same breath.

**Read the failure before believing it.** These checks can be wrong too. The collision check fired on
two false positives the first time it ran, because matching "every word appears somewhere" is
satisfied by accident in any long description. That was fixed by narrowing the CHECK. A guard that
cries wolf gets switched off, so a false positive is a defect in the check, not something to work
around with an exception.

**Looping raises adherence.** Running the suite, fixing what it surfaces, and running again is what
converts a written rule into one that actually holds. Stop when a full pass is clean, not after the
first fix.

## Step 7 · Confirm

- **Clear the authorization sentinel — always, even if the edit failed partway.** The guard must return
  to blocking the moment this flow ends, or the hard block is defeated for the rest of the session:
  ```bash
  rm -f ~/.claude/.config-edit-authorized
  ```
- **Reconcile before reporting.** Step 3 decomposes a multi-topic paste into one learning per standing
  rule, and that is the drop-prone step: fold in three of four and the run still reads as a clean
  success. So check every extracted learning, and every ask in this worktree's
  `.context/intent-ledger.md`, against what was actually applied, one verdict each. A learning dropped
  at the gate is `deliberately dropped` with who decided and when, not an omission. Append the result
  with `~/.claude/hooks/intent-ledger.sh note reconcile <scratch.md>`.
- Report what changed: the target file, the section(s), and a one-line summary of each learning folded in.
- **Pickup timing:** edits to an existing SKILL.md are picked up live (active now); a brand-new skill FOLDER
  needs a Claude Code restart. A **CLAUDE.md** is loaded at session start, so its edit applies to the NEXT
  session (or on re-read) — say so rather than implying it's live this turn. For a **committed project
  `CLAUDE.md`**, remind the user the change is unstaged in the current worktree and ships when the branch's PR
  merges; for a **`CLAUDE.local.md`**, it stays on this machine (in the main checkout) and is never committed.
- **Sync the config repo.** If the target lives under `~/.claude` (a `sk` skill — including this
  one — or the global `~/.claude/CLAUDE.md`), that dir is Simon's config source of truth (a private GitHub
  repo). **Exception: `sk-work` / `work/` is untracked**, so never offer to
  sync it — the offer would produce an empty diff. Say plainly that the change is local only and has
  no backup. After applying anything tracked, OFFER to commit + push it via **`/sk:claude-config-sync`**
  (it reviews the diff and secret-scans first; NEVER commit secrets). A project `CLAUDE.md` / `CLAUDE.local.md`
  is NOT in that repo, so this doesn't apply to those.
- Offer to run it again if there are more corrections or rules to fold in.
