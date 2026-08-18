---
name: claude-config-metrics-self-analysis
description: Run self analysis on Simon's dotclaude config from real usage metrics — surface the underused and silently dead parts, show which parts of my config are dead or barely used and the inputs that should reach them, and judge whether each low-usage part is warranted or a broken trigger to fix. Reads the dotclaude-metrics store (per-part usage, error and denial rates, recency, run backlog), scores every part two-axis (reachable × used), and proposes a trigger FIX so a dead part gets used — never a removal by default. Use for "run config self analysis", "surface underused config parts", "which parts of my config are dead", "config metrics", "what config is not being used", "analyse my config usage", "self optimise the config from metrics", or /sk:claude-config-metrics-self-analysis.
disable-model-invocation: false
argument-hint: "[optional focus, e.g. 'skills', 'hooks', 'just the dead ones']"
---

# Self-analyse the dotclaude config from real usage metrics

The premise: the config has ~80 parts and no one knows which actually get used. This reads the
dotclaude-metrics store, scores every part, and — for the dead and underused ones — decides the FIX
that would make them get used. It proposes; it never edits. Every change routes through
`/sk:claude-config-update`.

**The governing rule: a dead part is a broken TRIGGER, not a worthless idea.** The default action is
to repair the trigger so the part gets used, NEVER to remove it. Removal is a rare last resort, only
when the intention itself is genuinely obsolete, proposed explicitly. This is `rules/self-healing-config.md`'s
insight, now driven by data instead of a sample of one.

## Method

1. **Generate the scoreboard.** Run the aggregator under the metrics venv:
   ```bash
   ~/.config/claude-metrics-venv/bin/python ~/.claude/bin/config-metrics.py --html
   ```
   It loads the canonical parts list from `contracts/config_contracts.py` (so a newly-added part is
   always included), reads usage from the store, scores two-axis, writes `aggregates/latest`, and
   writes the HTML console. If it says no project is reachable, stop and point at
   `references/dotclaude-metrics-setup.md`.

2. **Read the two axes, not the count alone.** A part is `dead` only when it is BOTH unreachable AND
   unused. A reachable part with zero usage is an `instrumentation-gap` (suspected) or `new/unmeasured`
   (added recently), never dead. Denial rates carry a Wilson lower bound and a `low_confidence` flag
   below 20 events — do not read a 1-of-3 rate as signal.

3. **Skip the expected-dormant.** `part_criticality.py` tags safety/security/compliance parts
   (`safety`, healthy-by-design) and deliberate placeholders (`planned/stub`). Never propose a fix or
   removal for these on low usage — a guard that rarely fires is doing its job.

4. **For each dead / underused-defect part, decide the trigger fix** and show the evidence (the part,
   its numbers, and the actual prompt/tool-call from the store that should have reached it):
   - a skill nobody reaches → reword its `description` to how Simon actually phrased the task, or add
     a `routing_scenarios.py` scenario;
   - a reference never read → fix the skills that should cite it;
   - a hook that never fires → correct its `settings.json` matcher;
   - a guard with a high denial rate on legitimate work → narrow it (harden without breaking);
   - overuse (fires where it adds nothing) → narrow the trigger DOWN, still not remove.

5. **For context-only rules** (auto-injected, never counted), run an LLM-judge influence pass over
   sampled raw transcripts MULTIPLE times and require agreement — treat it as weak evidence, never
   sole grounds for a change, and strengthen wording rather than delete.

6. **Clear the optimization backlog.** Read `runs` where `optimized == false`, analyse them in
   aggregate (a finding recurring across runs is the durable-fix trigger), propose the config changes,
   and mark the processed runs `optimized: true`.

7. **Propose through the gate.** One verdict per flagged part, then hand the exact edits to
   `/sk:claude-config-update`. Propose only; never edit here.

## Output

A TLDR: the worst-performing parts first (dead, erroring, instrumentation-gap), each with a proposed
trigger fix and its evidence; then the healthy/hot summary; then the pipeline-health line (staleness,
outbox depth) so a broken collector is visible. The HTML console path for the visual view.

## Rules

- **Propose, never apply.** Every change goes through `/sk:claude-config-update`.
- **Fix to use, don't remove.** Removal is the rare exception, never the default.
- **Never flag a warranted-dormant part.** Safety and stub parts are expected to be quiet.
- **Name the evidence.** A finding with no part, number, and store record behind it is not a finding.
