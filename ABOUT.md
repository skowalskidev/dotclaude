# Personal agent workflows

This private configuration provides Simon's cross-project skills, rules, hooks and reference guides.
`README.md` covers installation and the inventory; `AGENTS.md` covers maintenance instructions.

## Claude and Codex

Both agents use the same rules, references, skills and project connector manifests in this repository.
Codex receives linked instructions and reads the current connector definitions through its native
launcher. There are no separately maintained copies to synchronize. Work and personal authentication
stay in separate native credential homes. The README's Native Codex setup section covers installation,
Conductor, hook trust, authentication and the process restart required for connector changes.
Claude transcript metrics remain specific to Claude; native Codex hooks reuse the shared behavioral
checks without claiming those metrics are portable.

## Gauntlet dashboard

Invoke [sk] `/sk:work-gauntlet-loop` for Gauntlet, or [sk] `/sk:work-ralph-loop` for standalone Ralph.
Both use the `work-` group in the personal `sk` plugin; select those skill names in Codex.
The existing shared `sk` skill directory supplies both hosts. A newly added skill can require a new session.

At the beginning, Gauntlet asks you to choose the existing workflow or Ralph’s fresh-worker loop,
the separate Gauntlet judge on or off, reference input and iteration budget. The dashboard’s This run
panel then shows your selected options read-only. Fully specified invocation options count as your answer.
Standalone Ralph fixes its execution mode and asks for the remaining options. When Gauntlet selects
Ralph, it passes the same plan and confirmed choices, so you answer once and keep the same dashboard.
The host's agent tools execute the work. The Python helper only validates and displays task state;
it runs no model calls and requires no third-party Python packages.

Start with screenshots, platform names you like, or no references. The AI can draft the target,
iterate with you and use the version you approve as the reference for implementation and judgement.
Changing an approved target requires a new approval; ordinary implementation fixes do not.

The dashboard has section buttons and overall completion on the left, with Before, named Target and
Current evidence on the right. It displays verified outcomes, captures and next actions. Embedded
mockups retain their versions and feedback. Downloaded HTML opens offline; a local viewer follows
updates every two seconds. The template stays the same across tasks and execution modes.

One `.context/<slug>-plan.md` owns the task narrative and a version-1 `dashboard-state` JSON block.
That block records the engine, phase, revision, sections, criteria, evidence, target approval and judge
verdicts. HTML is a generated view. A section is done only after its required checks and any enabled
judge pass. The supervisor updates state with a revision check to avoid overwriting concurrent work.

Ralph defaults to ten worker iterations before a resumable checkpoint. This is an iteration budget,
not a time estimate or success condition. Model choice and costs follow the active host/account;
there is no fixed cost or automatic paid CLI integration. Missing delegation blocks the chosen loop.

Entry skills: `skills/sk/skills/work-gauntlet-loop/` and `skills/sk/skills/work-ralph-loop/`.
Shared runtime: `bin/workflow-dashboard.*`. Protocol and attribution:
`references/workflow-loops.md`. Validation: `python3 hooks/config-contract.test.py`.
Runtime plan/evidence files stay in the task workspace and must be preserved before deleting it.
