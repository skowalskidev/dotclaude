# Self-healing config

Always-on rule: turn a resolved config problem into a durable fix, with my approval. Applies to my
WHOLE `~/.claude` config (rules, hooks, `bin`, `connectors/*.json`, `settings.json`, skills, CLAUDE.md),
not just connectors. The mechanism is `/sk:claude-config-update`; the sync is `/sk:claude-config-sync`.

## When (event-driven only — never a cron, never a periodic scan)

Two triggers. Both fire at the end of the work that revealed them, never on a schedule.

**1. A config part underperformed.** Any part, not just a broken one: a rule that should have fired
and didn't, a skill whose method didn't fit, a reference missing the answer, a hook that blocked
something harmless, a stale manifest doc (`README.md` inventory, `AGENTS.md`, the `CLAUDE.md` index,
`ABOUT.md`, the `Brewfile`), a connector that stopped working, a wrong path or setting.

**2. The right part wasn't used at all.** At the end of a task, check what the config offered against
what actually got used. Was there a skill that fitted and never got invoked? A reference catalog that
held the answer you worked out from scratch? A hook or guard that should have caught this? Check it against the worktree's
`.context/intent-ledger.md`, not your memory of the session.

**3. A parallel run left logs.** `/sk:work-superspeed` writes a run directory with per-slice timings, token
and cache counts, ownership records and an `analysis.json`. Run `/sk:claude-config-self-optimize-analysis-after-run` on it.
Most of what it finds is about that RUN (re-cut the partition, split the slow slice) and belongs
nowhere near the config. But when the same finding recurs across runs, it has stopped being a run
defect and become a config one, and that is this rule's trigger: fold it into
`references/parallelization.md` or the skill itself via `/sk:claude-config-update`.

The analyser also reports its own blind spots under `INSTRUMENTATION GAPS`. A question the logs cannot
answer never surfaces on its own, because a missing field looks exactly like a clean run. Treat a
recurring gap as a durable fix to `~/.claude/bin/superspeed-dispatch.sh`, not as a note.

Not-invoked is the more valuable trigger, because it is invisible. A rule that misfires gets noticed;
a skill that never fires just looks like it wasn't needed. **The root cause is almost never the task
— it is the part's own trigger.** A `description` that doesn't match how the task was phrased, a
missing row in `references/skill-stack.md`, a rule scoped so it never loads. Fix the trigger, in the
part that owns it. Never a note reminding yourself to remember next time.

## Guards (the failure mode is inventing findings, not missing them)

- **Name the exact file and the exact edit**, or it isn't a finding.
- **Fix the class, not the incident** (`process.md` § "Fix the CLASS of failure"). It bites hardest
  here: this fires the moment ONE problem was resolved, so the vivid specific incident is the only
  evidence in hand. Name the mechanism; keep the incident as illustration.
- **Silence is the normal outcome.** Most tasks teach nothing. Reporting nothing is success, not a
  skipped step. A manufactured improvement costs more than a missed one, because it spends the
  question channel that has to stay sharp for auth and prod decisions.
- **One per response.** Never re-raise something already declined this session.
- **Keep the contracts true.** The part's entry in `contracts/config_contracts.py` states what must
  survive a change. If the fix can't preserve it, change the contract in the same proposal and say so
  out loud. That is the whole no-regressions guarantee.

## What

1. **Classify the root cause:**
   - **Config bug** — something in the config is wrong/broken → propose a *fix*.
   - **Unhandled edge case** — the config was right but didn't cover this case → propose an *expansion*.
   - **Not a config problem** — a transient outage, an upstream bug, a genuine one-off → name it and
     drop it; do NOT force it into a config change.
2. **Propose + ask (a gate, not a silent auto-fix):** present the exact durable change and ask whether
   to fold it in via `/sk:claude-config-update`. Never auto-apply without my yes. Never paper over a
   real bug — fix the config, don't mask the symptom.
3. **Reversible + auditable:** the change lands as a git-tracked `~/.claude` edit; offer `/sk:claude-config-sync`
   to commit it (secret-scanned). If I decline, leave the config untouched.

Keep the proposal terse: what broke, why (bug vs edge case), the exact edit, and which file/home it
belongs in (route via `/sk:claude-config-update`'s structure router; keep top-level `CLAUDE.md` thin).

**Cross-project.** The same ask-first, keep-docs-in-sync discipline applies in ANY project, not just
`~/.claude`: when a change I make leaves a project's `CLAUDE.md` / `ABOUT.md` / `README` stale (per
`process.md`'s project-documentation rule), propose the doc fix and ask — same gate, same "never silently
skip it." Updating the relevant companion docs is part of "done" for a change; self-healing is the
backstop for when it's missed.
