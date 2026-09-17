# One task record, two execution modes, one dashboard

DO treat every task-bearing session as a gauntlet session with one dashboard and one living plan. Ordinary tasks
initialize `engine=current`, `gauntlet=false`, `referenceMode=none` and need no loop-options interview.
The `gauntlet` boolean enables independent judgement, not task tracking. Ralph and independent judgement
remain explicit execution choices. TEST: starting ordinary work produces one plan
and one dashboard without asking the four loop questions.

Before delegation, apply `references/parallelization.md` § Choose and preserve the agent setup.
Reconcile the living plan with the current chat's provider before every fresh worker, judge and retry;
never carry a stale cross-provider selection forward or switch providers to get past a failure. Loop engine names describe execution strategy, not the model/provider setup.

DO compose the execution mode and judge independently. Recommend
`--engine current --judge on`; use `--engine ralph` for fresh-context completion and
`--judge off` for ordinary verified task tracking. Keep the same plan, section IDs and viewer
when switching. TEST: switching modes creates zero new plan files and preserves evidence.

## Continuous request reconciliation

DO apply this lifecycle from the first task-bearing message through the last, whichever skill runs.
At the start of every turn and when a message arrives mid-run, read the same plan and all new source
messages. Read the hook's announced intent-ledger path, including any contention sidecar; without
hooks, record the requests directly from the conversation. Keep secrets out of the plan.

DO split EVERY actionable ask into stable IDs in `## Tasks`, with its source message, requested
outcome, acceptance criteria, dependencies and authorization. Link each ID to dashboard section/criterion
IDs; keep status and evidence only in dashboard state. Summarize requirements in full, including the
tail of long messages; the raw ledger is source evidence, not the execution checklist. Record answers,
constraints and corrections under `## Decisions & rationale`. A question needing an answer is work;
an illustrative example or brainstorm is recorded as context, not silently converted into authorization.

DO merge additions into the same plan before acting. Queue independent new work, preserve the current
item and its exact next step in `## Execution notes`, answer status questions briefly, then resume.
Change priority when instructed; cancel or replace work only on an explicit instruction, retaining
the old ID, source decision and replacement ID. A changed requirement reopens its affected checks.
Do not erase older requests because the newest message is more detailed or changes the topic.

DO recheck the complete queue after each item, new message, verification pass, restart, compaction
and handoff. Read the source messages as well as the plan to detect an ask never copied into it.
Continue ready authorized work until none remains; a green test for one item closes only that item.
Record a blocker with its next action and continue independent work. Keep deferred work open unless
Simon explicitly defers it; record who decided, when and the resume condition.

DO reconcile each source ask against its IDs before any final response or handoff. Record one outcome
per item: verified with evidence, answered with the answer location, explicitly cancelled/superseded
with the decision, or still open with its blocker/next action. Close a cancelled item's criterion only
with the recorded cancellation, never a claim it was implemented. Complete means zero unaccounted asks
and zero required unfinished items. A pause or blocked hand-back states every remaining item and the
resume point. Refresh the dashboard and append a fresh ledger reconciliation when the hook is available.

TEST: ask for A and B, add C while A runs, ask a status question, then resume after compaction. The
same plan still contains A, B and C; none passes without evidence, and the next action resumes B or C.
An explicit cancellation of B preserves its decision instead of silently deleting B.

## Supervisor ownership

DO let the active session own one supervisor, one plan and one viewer. Custom Gauntlet options or a
direct Ralph run also own one options answer.
Gauntlet uses the selected execution engine and runs the shared judge stage when enabled. A composed
Ralph call executes inside that supervisor’s confirmed run; direct Ralph owns the same lifecycle.
DO enter ordinary work in this order: resolve plan and authorization → export dashboard → execute one
ready item → verify → persist → export → repeat. Insert ask options → record answer before execution
only for requested custom options or direct Ralph; insert judge after verification only when enabled.
TEST: selecting an engine creates no second plan, dashboard, options interview or budget.

## Ask for run options first

DO begin a requested custom Gauntlet configuration or direct Ralph invocation with one consolidated run-options question in chat,
before dispatching builders or judges. Ask for execution (`current` or `ralph`), independent judge (`on` or `off`),
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

DO leave `optionsConfirmedAt=null` for ordinary work. Its running state is valid when
`engine=current` and `gauntlet=false`; the viewer labels it Task tracking and hides iteration-only
detail. TEST: an ordinary running plan validates without a fabricated options answer, while Gauntlet
and Ralph running plans still fail without one.

DO change options during a run only on an explicit request in chat. Record the revised answer and
timestamp, preserve the plan's IDs/evidence, and refresh the same read-only panel. Keep approved targets
on resume; source choices do not silently replace an existing approved design.

## Persistent state and interface

DO keep `.context/<slug>-plan.md` as the sole task record. Add exactly one fenced
`dashboard-state` JSON block under `## Dashboard state`. Keep narrative requirements and decisions
in the existing sections; store task status, criteria, assets and verdicts only in the JSON.
Generate `.context/<slug>-dashboard.html` from it. DO NOT hand-edit status in the generated HTML.
DO keep one canonical dashboard file per plan and one canonical mockup file per surface. Rebuild
those same files for every revision, retaining all earlier versions, variants and feedback in `#spec`.
TEST: the existing review link opens the latest proposal and its history after each rebuild.

DO derive the dashboard's Session record from the plan's narrative sections. Show the user journey,
system journey, tasks, decisions, risks, sources, execution notes, out-of-scope choices and changelog;
compute the artifact index and remaining-action index from dashboard state. Never copy any of them into
a second dashboard-owned store. TEST: changing plan prose or state changes the next export, and every
record entry traces to the plan.

DO make the ONE dashboard the whole task's record AND action surface — the single place the user opens
to see EVERY resource, decision and pivot, and to act. Embed each artifact the task produced as its own
section asset (`kind=html`/`image`), by default, not on request. An artifact AWAITING the user's
approval goes in the **Reference / target** panel (the PROPOSED thing to approve), NEVER the Current
panel (which reads as the live/done state), with `status:"review"` — the shell marks a review section
with a red unread dot in the nav — and its `Open mockup` full-view. TEST: at any check-in every
approval-pending artifact is embedded in its section, in the target panel, with the review red-dot and
a full-view, and every resource/decision/pivot the task used is reachable from the one dashboard. (e.g.
three merge previews sat as loose files beside an empty "No capture yet" section until the user asked
three times, then were shown as "Current" so approving them read as nonsense.)

DO base each visual increment on the last user-approved version and the product's current design.
Record the proposed revision/hash separately from the approved revision/hash. Announce the specific
change before editing, show that revision through the canonical link, and wait for its review before
adding the next visual increment. Approval of one increment covers only its shown scope. Continue
independent authorized work while review is pending. TEST: each implemented visual change traces to
an explicit approval of the same revision/hash; a newer proposal never inherits an earlier approval.

DO update the dashboard target and revision together whenever its canonical mockup changes. Give the
user a direct URL containing the task section, asset and open view. Preserve that selection on reload
and browser Back/Forward. Escape closes the innermost open overlay first, including when focus is
inside a nested capture. TEST: the shared URL reopens the reviewed surface and nested Escape closes
one overlay without losing feedback.

DO use `bin/workflow-dashboard.html` unchanged as the shared shell. When feedback on the dashboard itself
arrives mid-loop ("open the mockup in a new tab", "the modal clips"), it is a config change: run
`/sk:claude-config-update` in a background agent and keep the loop's task on its own deliverable.
Put overall completion above the left section buttons. Put Before, Reference / target and Current
in three right-hand panels, one slide per section. Use 2–5 word section titles and one sentence
of summary. Put tests, judge evidence and source detail behind Details. For visual work, embed
real captures; for work without a screen, use named text/diagram evidence or verified progress.
Never label a diagram or proposed mockup as an implementation screenshot.

DO set each implemented surface's section-level `previewUrl` to its working HTTP(S) page as soon as
the preview is available. Keep one visible `Open preview ↗` link in that section's Current header,
including when no capture exists; open it in a new tab and retain the screenshot's zoom action.
Update the URL when the preview moves and remove it when the preview is retired. Keep credentials
out of URLs. TEST: Current opens the same page from the live dashboard and saved HTML without opening
Details, and sections without a preview show no link.

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

DO build every preview/mockup asset through the standard shell —
`python3 ~/.claude/bin/mockup-build.py <spec.json> <out.html>`, which inlines the `#spec` into
`~/.claude/bin/mockup-shell.html` — never hand-roll a bespoke self-contained HTML. The shell owns
fit-to-viewport scaling, so a mockup built through it is uniform and full-width; a hand-rolled fixed-
width iframe renders clipped, with a dead side gutter, and every surface looks different. When the build
is fanned out to a subagent, the orchestrator's brief passes the shell path and says "author a
shell-conformant `#spec` and render it with `mockup-build.py`" — never "build a self-contained HTML"
free-hand. The mechanic itself lives in `/sk:ship-mockup-before-after` § "One shell for every mockup";
don't restate it here. TEST: every preview file under `.context/previews/` round-trips through
`mockup-build.py --extract`, and no subagent preview prompt asks for a hand-built HTML. (e.g. four
fanned-out replacement previews hand-rolled at a fixed 1280px came back clipped and non-uniform until
rebuilt through the shell.)

DO signal a rebuilt preview/mockup through the ONE dashboard, never by opening it. After building or
updating any preview/mockup asset, regenerate the gauntlet
(`python3 "$HOME/.claude/bin/workflow-dashboard.py" link`) and play one short sound
(`afplay /System/Library/Sounds/Glass.aiff`) — the user keeps the gauntlet open and wants one place
refreshed plus an audio cue, not a stack of tabs. NEVER run `open <file>` on a preview, and NEVER put
`open` in a subagent brief; a fan-out brief says build/update the file and return, and the orchestrator
regenerates the gauntlet and plays the sound ONCE. The gauntlet embed replaces the manual `open` that
`/sk:ship-mockup-before-after`'s render-check once meant. TEST: no preview/mockup build step runs
`open`, no subagent brief tells the agent to open the file, and after an update the gauntlet is
regenerated and one sound plays. (e.g. a fan-out of preview-rebuild subagents each ran `open` on its
file and spammed browser tabs, when the user only wanted the gauntlet refreshed with a sound.) An
already-open offline (`file://`) dashboard tab auto-refreshes itself on regain-focus/visibility and a
slow idle interval, so the sound cue lands on an up-to-date tab; the reload keeps the `#section`/`#asset`
hash and is suppressed while a modal is open or the user is typing feedback.

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
`previewUrl` is optional on each section and independent of its `current` asset; use an absolute
HTTP(S) URL without credentials or whitespace, e.g. `http://localhost:3000/settings`.

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
python3 "$HOME/.claude/bin/workflow-dashboard.py" init --root .
python3 "$HOME/.claude/bin/workflow-dashboard.py" link
python3 "$HOME/.claude/bin/workflow-dashboard.py" stop .context/task-plan.md --expect-pid 12345
python3 "$HOME/.claude/bin/workflow-dashboard.py" handoff .context/task-plan.md --by agent-A --note "quota wall"
python3 "$HOME/.claude/bin/workflow-dashboard.py" resolve --target "<dashboard url | dashboard.html | plan.md>"
```

DO run `init` on the first task-bearing prompt. It locks initialization, reuses one active plan or
creates one ordinary `engine=current`, `gauntlet=false` intake skeleton and exports its dashboard. Task
intake runs it mechanically; native hosts and the front-door skill run it directly when hooks are not
available. Replace the skeleton with the approved task before execution. TEST: two simultaneous or
repeated initializations leave exactly one active plan and dashboard, including unattended intake.

DO use `link` from any later session to find the workspace's one active plan, regenerate its canonical
offline HTML and print `DASHBOARD_PATH=<absolute path>`. One active plan wins over completed history;
zero plans or two active plans fail with the candidate paths. Return that path as the clickable link.
TEST: link never selects by modification time and never returns a dashboard older than its plan.

DO open the printed `DASHBOARD_URL`. The helper binds 127.0.0.1 on an OS-assigned port, prints its PID
and serves only `/`, `/dashboard.html` and `/state`. It records the PID, URL, plan and output in the
plan's `.context/*-dashboard.runtime.json` sidecar; that runtime receipt is disposable and never task
state. The page polls every
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

DO remove dashboard runtime with its worktree. Before teardown, verify the runtime receipt's plan path
belongs to that worktree and its PID command names that same plan; stop only that viewer, re-run the idle
gate, then remove the worktree normally. The canonical dashboard, receipts and evidence disappear with
`.context/`. TEST: cleanup blocks on a mismatched receipt or any other live process, and the removed
worktree leaves no dashboard path, viewer PID or local branch ref.

## Handoff and resume (chainable, same machine)

DO treat the living plan as the whole handoff artifact: it already holds state, narrative and options,
and the canonical dashboard is a self-contained render of it. A quota wall or an agent switch never
loses context, because a fresh agent resumes from that one file. This is the SSOT for handoff; the
`prepare` and `pick-up` sides both compose these steps, and no other file restates them.

DO stamp a resume manifest on the prepare side with `workflow-dashboard.py handoff <plan>`. It writes
`handoff` into the plan state (a `hop` count, the absolute `plan`, `worktree` and `dashboard` paths, the
live `dashboardUrl` when a viewer is serving, plus optional `--by`/`--note`), bumps the revision and
re-renders the dashboard with a visible "Handed off" banner. Then hand the user the printed
`HANDOFF_LINK` to copy. Commit the plan and dashboard first when the worktree is tracked, so the record
is durable. TEST: after handoff the dashboard shows the banner and `HANDOFF_LINK` names the loopback URL
when serving, else the `file://` dashboard.

DO make handoff REPEATABLE, so A→B→C chains without bound. Each call increments `hop` from the same
plan; nothing accumulates and no context degrades, because every hop regenerates from the one SSOT.
TEST: a second handoff reports `hop` one higher and the plan validates.

DO resume on the pick-up side with `workflow-dashboard.py resolve --target "<pasted>"`. It maps a pasted
loopback dashboard URL, a `file://`/filesystem dashboard `.html`, or a plan `.md` back to its plan on
THIS machine and prints `PLAN_PATH`, `WORKTREE`, the recorded `ENGINE`/`GAUNTLET`/`ITERATION`/
`MAX_ITERATIONS`/`PHASE` and the `HANDOFF_HOP`. Same machine only by design: a loopback URL and a
worktree path do not cross machines. Resume the recorded engine from `PLAN_PATH` WITHOUT a fresh
run-options interview — the options are already confirmed in the plan. TEST: resolving any of the three
target forms returns the same `PLAN_PATH` and the recorded options; a gauntlet resumes without re-asking.

DO preserve the `handoff` manifest across later updates by round-tripping the whole state through
`update` (read-modify-write); advancing sections never drops it. The next `handoff` refreshes it.
TEST: after a normal section update the plan still carries its `handoff` manifest.

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
