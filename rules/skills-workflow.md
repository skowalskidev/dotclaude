# Skills & workflow rules

Rules governing how skills are listed/recommended and when to use them, moved out of `~/.claude/CLAUDE.md`.

## Rule for Claude
When listing or recommending skills, ALWAYS prefix with the repo name:
[gstack] /design-consultation
[impeccable] /polish
[agency-agents] design-brand-guardian.md
Never mix skills from different repos in a flat list without labels.
When asked about skills, always explain which repo it comes from and how to invoke it.

## Installed Skills — organised by repo source

### How my own skills are organized (convention — follow when creating skills for me)
My self-created skills live in **skills-dir plugin folders** inside `~/.claude/skills/` — a folder
with `.claude-plugin/plugin.json` + `skills/<skill-name>/SKILL.md`. Each plugin is a namespace, so
every skill is invoked as `/<plugin>:<skill>` and **typing the prefix in the slash menu filters the
(otherwise overcrowded) list down to just that group**:
- Type `/sk` → lists ALL of my skills (both groups share the prefix).
- Type `/sk-work` → narrows to just my work-skills plugin (e.g. `sk-work`).
- The bare prefix is a **menu filter only, not a runnable command** — pressing enter on `/sk` alone
  gives "Unknown command". Always complete to the full `/sk:<skill>` / `/sk-work:<skill>` name.

**Name a new skill `<group>-<what-it-does>`** (group first, so typing it narrows the menu). Groups live
in `contracts/skill_naming.py`.

Rules (verified against the official Claude Code docs):
- New personal skills go in `~/.claude/skills/sk/skills/<name>/SKILL.md`. Never put my skills loose in
  `~/.claude/skills/` or `~/.claude/commands/`.
- **Work-only skills go in `~/.claude/work/sk-work/skills/<name>/`** (`skills/sk-work` symlinks
  to it). `work/` is untracked, so a work skill is never committed, synced, or backed up.
- Grouping subfolders in `~/.claude/skills/` are NOT supported (nested discovery only works for
  project `.claude/skills/`) — always use the plugin-folder pattern above.
- Creating a NEW top-level folder in `~/.claude/skills/` requires restarting Claude Code — sessions
  started before the folder existed will never see it (start a fresh session/chat); edits to
  existing SKILL.md files are picked up live.

### [sk] / [sk-work] — my own skills (not enumerated here)
Not listed — a hardcoded list goes stale. Names + descriptions surface at runtime (see "Use one of my
own skills when it fits"). Source: `~/.claude/skills/sk/`, `~/.claude/skills/sk-work/`.

### Third-party skill packs (surface at runtime — curated usage in Workflow Rules)
Installed under `~/.claude/skills/`, discoverable in the runtime skill list (a hardcoded per-skill list only goes stale):
- **[gstack]** (garrytan/gstack) — design/planning/QA/ship slash-commands (`/design-consultation`, `/design-review`, `/plan-*-review`, `/investigate`, `/ship`, `/land-and-deploy`, the `/careful`·`/freeze`·`/guard` safety set…).
- **[impeccable]** (pbakaus/impeccable) — design finishing slash-commands; recommended chain before a page goes live: `/audit` → `/normalize` → `/polish`.
- **[agency-agents]** (msitarzewski/agency-agents) — design/marketing/product agent `.md` files, pasted into chat as context (NOT slash commands).

When listing/recommending a skill, prefix with its repo (`[gstack]`, `[impeccable]`, `[agency-agents]`, `sk`/`sk-work`) and say how to invoke it; the recommended chains live under "Other repos' skills" in Workflow Rules.

## Workflow Rules

### The map lives in ONE place — `~/.claude/references/skill-stack.md`
Which skill fits which task shape, and which third-party skill genuinely stacks on top of it, is in
`references/skill-stack.md` — including the adoption bar each pack had to clear. Read it at task
start; the task-intake gate (`hooks/task-intake.sh`) points you there on every new task. Don't
duplicate that mapping into individual skills — one home, so it can't drift.

### Use one of my own skills when it fits — check first, don't wait to be asked
My personal skills live in `~/.claude/skills/sk/` (work-only ones in `~/.claude/skills/sk-work/`),
invoked as `/sk:<name>` / `/sk-work:<name>`. Their names and descriptions are surfaced to you at
runtime, so I don't keep a hardcoded list or trigger table here (it only goes stale). Before and during
a task, check whether one of these skills fits the scenario; if one clearly applies, load and use it
proactively — without me typing the command — and say which one and why. If none fits, don't force it:
using them is optional, driven by the task at hand.

**When one fits — Simon named it, or its trigger fired — INVOKE it via the Skill tool and FOLLOW its
steps; never reconstruct it from memory** (a paraphrase drifts from the tested procedure and records
zero uses, since the metrics recorder only logs a Skill tool-call as a use — the run that
hand-reconstructed `/sk:work-hyperspeed` skipped its polling, reconcile log and teardown, and logged
`uses:1`).

### Other repos' skills (manual — suggest, don't auto-run)
Which third-party skill stacks on which task shape (the design chain, `/investigate` before fixes,
brand-guardian as context) lives in `references/skill-stack.md`, not duplicated here. Never auto-run
them; when asked which to use or when listing, name the repo + how to invoke, read from the runtime
list, and show what is actually installed.
