# One plan, two execution modes, one dashboard

Before delegation, apply `references/parallelization.md` § Choose and preserve the agent setup.
Carry the living plan's selection into every fresh worker, judge and retry; never switch providers
to get past a failure. Loop engine names describe execution strategy, not the model/provider setup.

DO compose the execution mode and judge independently. Recommend
`--engine current --judge on`; use `--engine ralph` for fresh-context completion and
`--judge off` for ordinary verified task tracking. Keep the same plan, section IDs and viewer
when switching. TEST: switching modes creates zero new plan files and preserves evidence.

## Shared lifecycle and ownership

DO let the invoked entry skill own one supervisor, one plan, one options answer and one viewer.
Gauntlet selects an execution engine and runs the shared judge stage over its results. A composed
Ralph call executes inside that supervisor’s confirmed run; direct Ralph owns the same lifecycle.
DO enter in this order: resolve plan and authorization → ask options → record answer → start viewer →
resolve any required target → execute one ready item → verify → judge when enabled → persist → repeat.
TEST: selecting an engine creates no second plan, dashboard, options interview or budget.

## Ask for run options first

DO begin each direct invocation with one consolidated run-options question in chat, before dispatching
builders or judges. Ask for execution (`current` or `ralph`), independent judge (`on` or `off`),
reference input (`images`, `names` or `none`, including platform names), and iteration budget.
For Gauntlet, offer existing workflow (`current`) or Ralph (`ralph`) and recommend the judge on.
For direct Ralph, fix `engine=ralph` and recommend the judge off. A composed engine reuses the
supervisor’s confirmed options without another question. Pre-fill supplied arguments and existing
plan selections on resume; recommend no references and 10 iterations only for unanswered fields. Use the host's actual
question tool or one concise chat question; wait for the answer before starting the run.
If the user supplied every option explicitly in the invocation, treat those as the answer and show
the selected values once without asking again. A preselected default or elapsed time is not an answer.

DO write the answer into `engine`, `gauntlet`, `referenceMode`, `inspiration`, `maxIterations` and
`optionsConfirmedAt` in the plan's state. Only then mark the run `running` and dispatch work.
Keep these values read-only in the viewer's This run panel; it reports the active run's choices,
not controls for a future run. Do not expose editable selectors or a generated start command there.
TEST: the run-options question precedes the first dispatch, running state has a confirmation timestamp,
and the dashboard displays the exact recorded values without input controls.

DO change options during a run only on an explicit request in chat. Record the revised answer and
timestamp, preserve the plan's IDs/evidence, and refresh the same read-only panel. Keep approved targets
on resume; source choices do not silently replace an existing approved design.

## Persistent state and interface

DO keep `.context/<slug>-plan.md` as the sole task record. Add exactly one fenced
`dashboard-state` JSON block under `## Dashboard state`. Keep narrative requirements and decisions
in the existing sections; store task status, criteria, assets and verdicts only in the JSON.
Generate `.context/<slug>-dashboard.html` from it. DO NOT hand-edit status in the generated HTML.
Keep the HTML path stable throughout the task. TEST: rebuilding from the plan reproduces the view.

DO use `bin/workflow-dashboard.html` unchanged as the shared shell.
Put overall completion above the left section buttons. Put Before, Reference / target and Current
in three right-hand panels, one slide per section. Use 2–5 word section titles and one sentence
of summary. Put tests, judge evidence and source detail behind Details. For visual work, embed
real captures; for work without a screen, use named text/diagram evidence or verified progress.
Never label a diagram or proposed mockup as an implementation screenshot.

DO count only `status=done` sections in overall completion; give every required section equal weight.
Show per-section progress as passed criteria / all criteria. A 100% criteria count with a pending
judge stays `review`, and contributes zero completed sections. Include docs, checks, integration and
cleanup in the criteria when required. TEST: an unfinished required section prevents overall 100%.

DO name every target and record its source, capture time and viewport/theme for visual comparisons.
Preserve BEFORE captures. Increment `artifactRevision` whenever implementation, reference, criteria or
comparison conditions change, reset affected checks, and acquire a fresh judge verdict. The update
helper invalidates the previous judge automatically when `artifactRevision` changes.
TEST: an earlier revision's judge verdict cannot mark the changed section done.

DO retain existing mockup data islands and all their versions, variants, comments, pins and picks.
Use a `kind=html` asset to inline the surface's canonical self-contained mockup into its target panel.
Let that embedded document own its specialist editing controls; the shared shell owns task navigation.
Keep its grid, focus/filmstrip, persona and variant selectors, version HUD, 3-up comparison, field diff,
picks, pins, verdicts and hand-back controls. Render captures at their recorded desktop viewport and
scale them to fit; Open mockup exposes the full interactive surface. Never force a desktop capture
into a narrow mobile layout.
New task overviews use this shell, not a second bespoke gallery. Reuse an existing canonical entry
path when connecting an ongoing surface. TEST: opening an old version still shows its original picks.

DO store evidence below the plan directory, as relative paths. Inline images and HTML on export;
serve no directory listings or arbitrary files. Compress images to display size. The viewer embeds
trusted local mockup HTML with same-origin nested-frame controls and a network-blocking content policy.
Capture HTML must already be self-contained; nested controls that require external APIs are not supported.
Use raster captures for untrusted third-party pages, never their executable scripts.

## Reference setup: screenshots, names or none

DO accept `--references images|names|none`; recommend `none` in the initial options question when no reference is supplied.
For names, accept `--inspiration "Linear, Stripe"` or platform names in ordinary language. These
are inspiration, not a claim that screenshots were supplied or a frozen quality bar.

DO handle the three paths before implementation:
- Images: use the supplied captures as inputs and identify the exact target the user approves.
- Names: inspect accessible public product examples, label the platform and observed patterns,
  and draft an original target design grounded in the project's actual before capture and tokens.
- None: draft a target from the user's goal and the actual product context. Ask only for missing
  requirements that prevent a meaningful proposal; missing inspiration never blocks drafting.

DO put the AI-drafted design in the Target panel, labelled Proposed target, and iterate on it with
the user. Keep Current as Not started until implementation is authorized. The named reference is
then the design the user and AI developed together, not the inspirational platforms themselves.
DO freeze the approved target revision before the implementation/judge loop: record `origin=generated`,
`targetRevision`, and `approval={by:"user", targetRevision:N, evidence:"user confirmation + timestamp"}`
on the target asset. Save the approved asset at a versioned immutable path. Pass that exact asset to
builders and judges. Never silently move the target to match what the implementation produced.
TEST: a generated target without explicit approval of its current revision cannot receive a judge pass.

DO keep later design changes in a new target revision with pending approval. Previous approval stays
in the surface's version history; ask for approval only when the target changes, not on each build fix.
Use the existing mockup feedback/pick loop for design approval. A dashboard comment is proposed feedback;
only the user's explicit approval (in chat or an exported approve verdict the agent reads) freezes it.

## State schema (version 1)

DO initialize every field shown below. Add sections and criteria for the real task; do not retain
example completion claims. `planPath` is relative to the worktree for resuming the task.
`before`, `target` and `current` are optional; omitted current renders verified progress.

```json
{
  "schemaVersion": 1,
  "title": "Task name",
  "planPath": ".context/task-plan.md",
  "revision": 1,
  "updatedAt": "2026-09-07T00:00:00+00:00",
  "phase": "planning",
  "engine": "current",
  "gauntlet": true,
  "referenceMode": "none",
  "inspiration": "",
  "optionsConfirmedAt": null,
  "iteration": 0,
  "maxIterations": 10,
  "sections": [{
    "id": "surface",
    "title": "Main surface",
    "summary": "One sentence describing the intended result.",
    "status": "todo",
    "artifactRevision": 1,
    "next": "Capture the real before state.",
    "before": {"kind": "text", "label": "Not captured", "text": "Awaiting real screen."},
    "target": {"kind": "text", "label": "Named target", "text": "State the quality bar.", "source": "User brief"},
    "criteria": [{"id": "surface-1", "text": "Required observable outcome", "passed": false, "evidence": ""}],
    "judge": {"verdict": "pending"}
  }]
}
```

DO use section states `todo | doing | blocked | review | done` and run phases
`planning | running | paused | blocked | complete`. A blocked section needs `next` naming the
missing input and action. A passing criterion needs an evidence path/result. A judge pass needs
`agentId`, a different `builderId`, `artifactRevision`, `reference` and `evidence`.
Image assets use `kind=image`, `label`, `path`, `source`, `capturedAt` and `viewport`; HTML assets
use `kind=html`, `label`, `path` and `source`. Text assets use `kind=text`, `label` and `text`.

## Render and update

DO run the helper with Python 3.9 or newer. Use the installed path below (quoted for shell safety):

```sh
python3 "$HOME/.claude/bin/workflow-dashboard.py" serve .context/task-plan.md
python3 "$HOME/.claude/bin/workflow-dashboard.py" state .context/task-plan.md
python3 "$HOME/.claude/bin/workflow-dashboard.py" update .context/task-plan.md --input .context/next-state.json --expect-revision 1
python3 "$HOME/.claude/bin/workflow-dashboard.py" export .context/task-plan.md
```

DO open the printed `DASHBOARD_URL`. The helper binds 127.0.0.1 on an OS-assigned port, prints its PID
and serves only `/`, `/dashboard.html` and `/state`. Record URL/PID in the plan. The page polls every
2 seconds, preserves the selected section and shows the last valid revision on failure. File opens
are explicitly labelled Offline snapshot; Save HTML embeds the latest displayed state for sharing.
Embedded mockups must write review edits into their `#spec`; the viewer captures that state and form
values through an embedded-frame message bridge. Save HTML carries feedback drafts. Live updates reapply
drafts only to the same source hash; changed sources retain older drafts in Feedback drafts for
explicit reconciliation. Import feedback into the surface record before recording approval.
A live connection means the viewer is connected, not that an agent is working. Use the update age
and run phase to see stalled work. TEST: a stopped server shows Connection lost, never a fake heartbeat.

DO have one supervisor write the state through `update`; workers return results. The helper locks
and checks `--expect-revision`, increments the revision, stamps the time and atomically replaces the
JSON block, then regenerates the derived HTML with a separate atomic file replacement. On conflict, re-read and merge the actual changes. Never retry a stale payload
with a newer revision number. Update after dispatch, completion, test, judgement, failure or user
steering, and at least once per minute during active work. Export once more before handoff.
Stop only the recorded viewer PID when the user closes the live review or requests cleanup.

## Existing workflow execution (`current`)

DO run the existing workflow selected by the entry skill with the confirmed plan and options. Leave an existing planning lock in force
until the user's build authorization; never ask for an authorization already given in this session.
The dashboard is a view, not permission to implement. After each item, verify the criteria and run
the judge when enabled. Keep working through unfinished items, writing outcomes into the same plan.

## Ralph execution (adapted, not the upstream shell runner)

DO dispatch one ready unfinished section to a fresh worker, wait for its result, verify it, persist
learnings, then dispatch the next fresh worker. Use dependencies recorded in the plan. Use the confirmed
`maxIterations` for the invocation; recommend 10 when asking for options. This is a checkpoint
budget, not a definition of done. On exhaustion record `paused`, unfinished IDs and the resume
command; never complete on a promise string. Resume retains section IDs, evidence and learnings,
and starts a new invocation budget while recording the previous round in Changelog.

DO use the host's actual delegation tool. In Codex, use a new `collaboration.spawn_agent` with
`fork_turns="none"`; in Claude Code use a fresh Agent/Task call without a resume ID. Pass the
worktree, scoped instruction paths, objective, selected section, acceptance criteria, dependencies,
reference paths, allowed file scope, verification commands and durable learnings explicitly.
Include the already granted authorization scope in each worker brief, with “no need to ask” for
that scope only. The existing intake hook recognizes standing authorization; do not add another
permission gate or disable real account boundaries. Never assume a `/loop` or `/goal` string launches anything. If fresh delegation is unavailable,
record the Ralph run blocked and offer current execution; do not relabel same-context work as Ralph.

DO keep one builder active by default. The supervisor owns the plan; the worker edits only its
assigned implementation files and returns changed paths, checks with outcomes, captures, blockers
and learnings. Persist the useful learnings in `## Execution notes` in the plan before releasing the
worker. Check the actual diff and evidence before accepting its claims. Preserve the current branch
and unrelated changes; commits, pushes, external writes and deployment follow existing authorization.
Never invoke upstream permission-bypass flags or silently install an upstream runner.

## Shared judge stage (over either engine)

DO keep one owner for judgement: the outer supervisor in composed runs, or the direct entry
supervisor in standalone runs. Use the frozen target from Reference setup as the named, retrievable
comparison for judgement.
For nonvisual work use an approved behavioral specimen, test corpus, benchmark or acceptance target.
An unavailable approved target blocks that judgement; optional inspiration never blocks target drafting.
Never fabricate a competitor capture. A generated target carries its own name and approval record.

DO spawn a separate fresh judge for each reviewed artifact revision, with no builder conversation,
effort narrative or claimed verdict. Give it the objective, frozen acceptance criteria, verification
outputs and comparable evidence at matching viewport/data/theme. For a comparative reference,
randomize A/B filenames and keep their mapping outside the judge brief. Ask for `A | B | tie |
unjudgeable`, evidence and the largest actionable gap. Require the implementation to win; ties and
unjudgeable comparisons do not pass. Disclose limited blinding when branding identifies a source.
For an acceptance target, use binary met/not-met checks and record `comparison=acceptance` in the
judge evidence; never call that a blind A/B win.

DO translate a failed judgement into a concrete task delta, fix it, rerun affected checks and send
the new revision to a new judge. The judge reads and reports only; it cannot edit source, criteria,
reference or the plan. Use host read-only tools/sandbox when available and audit for unexpected file
changes afterwards. If separate judgement is unavailable, leave the gate blocked, not passed.

DO finish only when every required section has evidence-backed checks, all loose ends are closed,
and every enabled judge passes the current revision. Reconcile against the original request and
plan, including required documentation and cleanup. User cancellation, missing input, budget limits
or a repeated no-progress result are paused/blocked outcomes. After 3 successive rounds with no new
verified criterion and the same judge gap, checkpoint and explain the blockage; never erase it.

## Provenance

DO retain this attribution when adapting or distributing these instructions. This is a modified
adaptation of [Jay E / RoboNuggets' Gauntlet Loop](https://github.com/robonuggets/gauntlet-loop),
licensed [CC BY 4.0](https://creativecommons.org/licenses/by/4.0/), with the Gauntlet technique
credited by that project to Matt Shumer. Changes: modular execution, bounded checkpoints, persistent
verified state and a reusable dashboard. The optional fresh-worker pattern is inspired by
[snarktank/ralph](https://github.com/snarktank/ralph) (MIT); no upstream runner code is copied.
[duolahypercho/gauntlet-loop](https://github.com/duolahypercho/gauntlet-loop) was evaluated, not adopted.
