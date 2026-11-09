"""What every part of this config is FOR, and what must stay true about it.

Why this exists
---------------
Claude proposes edits to this config through `rules/self-healing-config.md`. An edit that looks
sensible in isolation can quietly destroy what a file exists to do, and nothing would notice: a rule
still parses, a hook still exits 0, a skill still loads. That is the same failure a personal project hit,
where a stage was edited so all 1,566 tests passed and the thing the stage produced was gone.

So each part declares its purpose and the properties that must survive a change.
`hooks/config-contract.test.py` enforces coverage in BOTH directions: a config part with no entry
here fails, and an entry naming a file that does not exist fails. Coverage cannot rot silently.

Why a registry rather than a header in each file
------------------------------------------------
Anything written into `rules/*.md` loads into every session. That directory is near a hard byte
budget, and a contract is read when someone EDITS the part, not on every turn. Keeping it here costs
nothing at runtime.

`mission`  — the OUTCOME this part produces, naming who benefits and what changes for them. It
             OUTRANKS `criteria`: a change can satisfy every criterion and still leave the part
             worse at its job. TEST: read a proposed diff against it and say "this serves it" or
             "this trades against it". Anything optimising this config reads the mission FIRST, so
             a local metric cannot be improved at the mission's cost. Format: see
             references/config-writing-standard.md.
`purpose`  — one line: what this produces or prevents.
`criteria` — the properties a change must preserve. Prose, deliberately: most are not mechanically
             checkable, and a criterion a human reads before editing is worth more than one narrowed
             until a regex fits. Where a criterion IS checkable, the check lives in
             config-contract.test.py under a matching id.
"""

CONTRACTS: dict[str, dict] = {
    "bin/node-runtime.zsh": {
        "mission": "Simon runs the same Node 24 toolchain from terminals and agents in every working directory.",
        "purpose": "Select the newest installed stable nvm Node 24 without interactive shell initialization.",
        "criteria": [
            "Select Node, npm and npx from one Node 24 installation; skip incomplete and prerelease installations.",
            "Reapply after login PATH setup without duplicate entries or changes to unrelated paths; report a missing installation explicitly.",
            "Verify login and non-login shells, directory independence, numeric patch ordering and repeated sourcing in temporary fixtures.",
        ],
    },
    "bin/local-capacity.py": {
        "mission": "Simon's simultaneous sessions share heavy local capacity without stealing devices or silently overlapping abandoned work.",
        "purpose": "Bounded foreground scheduling for heavy work, simulators and Docker dev stacks, with ownership checks and a read-only watchdog.",
        "criteria": [
            "Admit at most HEAVY_SLOTS (3) heavy leases across workspaces, one per owner; a fourth request and unknown simulator state cannot succeed.",
            "Stay executable with its python3 shebang; every documented run command carries --owner.",
            "Defer ordinary admission, stack starts included, only below 20% CPU idle or above 1.5 load per core while idle is below 35%; cpu reports the reading. Never read or defer on memory pressure (swap on the SSD absorbs it): a memory warning or critical level with CPU headroom admits.",
            "Admit one supervised priority command under CPU contention for its own --max-min, including simulator stages. Ordinary non-priority work still defers.",
            "Check allowance priority every ten seconds; stop only the owned group on expiry or replacement. Preserve lease cleanup and all simulator, stack and ownership boundaries.",
            "Sample the host before taking a legacy bridge lock, poll a held lock for at most 3 seconds, then refuse naming each live holder's PID and command name, never its arguments.",
            "Every deferral names the real blocker and next action. A --wait-min above 60 exits 1 naming the cap in minutes; a --max-min expiry names that limit.",
            "Prove priority checkout ownership at admission, then bind that proof to one supervisor and its exact cwd device/inode. Heartbeats verify that identity and the live grant without repeating ownership subprocesses; allow same-scope renewal and reject changed, expired or unknown scope.",
            "Verify an unreaped child PID, parent, start and private PGID before every teardown signal. Keep the leader unreaped until descendants stop; accept EPERM only for a proven zombie-only group. Retain evidence on unknown/live signal refusal and never repeat a failed teardown.",
            "Keep one token-bound contention allowance machine-wide until its verified lease releases; replacement priority cannot admit another.",
            "Bind priority to repeated --workspace entries and nested linked worktrees; canonicalize workers to one owner and exclude unlisted siblings. Read existing single-workspace grants without rewriting or renewing them; retain validation and grant binding. Name coverage mismatches and their repair command.",
            "A failed CPU or load probe defers with exit 75 like every other deferral; exit 1 means a fault to inspect, never defer.",
            "Sample CPU/load once per admission attempt and reuse the snapshot. Read CPU from the second one-second iostat sample with a five-second timeout; require its header and two valid rows. Classify failures without printing raw output.",
            "Retry only state-lock contention for completed-run cleanup for at most 30 seconds, revalidating token and resources. Preserve payload result after release; never relaunch or retry an ownership/resource refusal.",
            "Retry stage metadata lock contention for at most 30 seconds within its deadline, revalidating the same lease before one payload grant. Honor cancellation; retain failed cleanup receipts. Never retry payloads or ownership/resource refusals.",
            "Retry priority-state lock contention within one 10-second heartbeat and the command deadline; an expired or replaced priority stops only the owned payload.",
            "Snapshot status/watchdog metadata under a short lock; run external probes outside it. Reclaim mutations revalidate the current owner and lease, never trust a stale diagnostic snapshot.",
            "Count at most MAX_BOOTED_SIMULATORS (1) device machine-wide: claimed, leased or not Shutdown, unleased devices included; a second claim-sim or simulator run exits 75 naming the holder, the same owner included.",
            "Reserve one slot while the priority owner lacks a lease; admit secondary owners into spare slots under ordinary guards. Keep priority expiry at default 60, maximum 180 minutes; never steal another owner's lease.",
            "Retry foreground run admission every 10 seconds for 5 minutes by default, configurable to 0..60 minutes; launch once, never restart a started command, and return 75 on exhausted admission.",
            "Pause only explicitly pause-safe owned groups during another primary's pressure; recheck token, PID/start and PGID before every signal, resume after two healthy samples, and leave busy work running without a primary.",
            "Reserve the first slot for one legacy bridge or old slot directory in compute mode; reject ambiguous multiple lanes. Use at most two remaining slots without the mutex; reject compute simulator/stage use and retain all host guards.",
            "Retain paused leases and memory; count paused wall time toward the command deadline and end a 5-minute pause. Continue a stopped owned group after TERM for cleanup; reject simulator, stage and legacy-bridge pause-safe runs.",
            "Grant priority only on Simon's own chat message; simulator claims and shutdown-before-release rules do not change for the priority owner.",
            "Cap Docker dev stacks at floor(VM GiB / 3), at least 1 and at most 2, counting labelled running stacks plus leases inside 15 minutes; unknown VM size admits 1.",
            "Stop only idle Supabase stacks (no live session, no change for 60 minutes) on stack-acquire or stack-sweep --apply, never on a timer; prune containers and network by label and keep every data volume.",
            "Use port-registry ownership for idle-stack decisions: live Claude/Codex sessions protect their checkout and physically nested linked worktrees of the same repository; sibling and unrelated repositories remain reclaimable. A failed session or ownership probe stops no stack and never fails the asking command.",
            "Watchdog and status flag, read-only, processes at or above 200% ps CPU aged 120 seconds or more, unleased booted simulators, idle claims and extra Chrome for Testing instances, naming each simulator's owner; they stop nothing.",
            "Retain interrupted, orphaned and PID-reused owners for inspection; never expire a lease by age alone.",
            "Auto-release on acquire, status and watchdog only a provably dead lease: owner PID gone or reused, recorded command and stage groups empty, no simulator, a live priority session's lease included; recheck the exact lease under the lock, print the owner and slot, and log a telemetry event. A pending launch, an unrecorded group or a failed probe keeps the lease.",
            "reclaim-sim shuts down and unclaims a simulator only when its claim owner has no live session and no lease holds it; it exits 1 naming a live owner and never deletes the device.",
            "Record a new simulator claim's checkout without changing the owner-label API. Retain label-only claims while any session is live; use shared workspace ownership for recorded claims, including live parents of nested worktrees.",
            "Print the reclaim command on run, claim-sim and watchdog output only for an ended claim owner; a failed session probe is never read as ended.",
            "Bound boot to 60 seconds, bootstatus and install to 120 seconds each, and the foreground run to 60 minutes by default; a failed boot starts no later stage.",
            "Attempt bounded shutdown of only the recorded simulator after command groups stop on success, failure or timeout; retain the lease if any device is not Shutdown.",
            "Release only the matching token after recorded child processes, its own simulator and simulators its owner claimed are clear; another session's booted simulator never blocks it. Signal only the runner's own process group.",
            "Bridge existing BSD file locks through untracked bridge.json; keep simulator claims and orphaned owners with any live group, simulator or unknown state until inspected.",
            "Reject stages whose Python intermediary lost inherited legacy lock descriptors before any payload runs; explicit pass_fds preserves the bridge and excludes competing lock owners.",
            "Migrate an older lease schema explicitly under lock, preserving its owner and child identity; ordinary reads never silently replace it.",
            "Store no command arguments or environment values; reject unsafe state paths and malformed lease data.",
            "Refuse run and acquire inside a leased run on the same root with exit 1 naming stage, and name stage in the same-owner deferral, so no owner waits on its own lease.",
        ],
    },
    "bin/config-land-check.py": {
        "mission": "A validated repair of Simon's own config lands on main with no question, and an unchecked head cannot.",
        "purpose": "Verifies a config-repo head (contract suite, secret scan, hash-bound diff review, fast-forward) and records its sha for hooks/git-commit-guard.py.",
        "criteria": [
            "Refuses a checkout outside the ~/.claude repository, uncommitted tracked changes, a head that does not fast-forward the fetched remote main, and a reviewed hash that differs from the current diff.",
            "Records the head sha in the shared Git directory only after the contract suite and dotfiles/secret-scan.sh --range both pass on that exact head; a new commit needs a new run.",
            "hooks/git-commit-guard.test.py drives its refusals; the landing itself proves the success path.",
        ],
    },
    "bin/session-performance.py": {
        "mission": "Simon receives independently published session evidence without lost reports, duplicate review or another background workload.",
        "purpose": "Bounded local registration, snapshots, atomic report publication and asynchronous review receipts.",
        "criteria": [
            "Publish reports exclusively and atomically in separate UUID directories; later evidence uses addenda without replacing the original.",
            "Ignore unfinished drafts, retain missing participant counts and identify unseen report content by hash across restarts.",
            "Reject a review receipt for a hash different from the inspected report; malformed participants cannot hide healthy reports.",
            "Bound observation commands and output, record unavailable metrics explicitly, and never start models, benchmarks, simulators or background watchers.",
            "due answers read-only whether a report is owed for new work since the workspace's newest published report (its watermark): at least 100 new tool calls, or 30 with a failure, a correction or a reconciled task; never while background work runs, a one-shot wakeup is pending, the turn made under 3 calls or it ends on a question.",
            "aggregate claims the batch exclusively for six hours and writes one URL-redacted digest and manifest of unreviewed reports; reviewed-manifest receipts only unchanged hashes and releases the claim.",
        ],
    },
    "references/session-performance.md": {
        "mission": "Every task teaches Simon's coordinator what consumed time without interrupting work or inventing performance claims.",
        "purpose": "Shared lifecycle for ordinary, gauntlet and asynchronous multi-session performance analysis.",
        "criteria": [
            "Queue analysis after the requested work for every task; preserve it through handoff and avoid recursive analysis of analysis.",
            "Participants publish without waiting for peers; delegated participants return evidence, and the active session owns authorized repairs without draining the shared cloud backlog.",
            "Keep late and missing reports pending until reviewed or the user changes the roster; a file write never claims to wake a dormant chat.",
            "Separate observed data, unknowns and inference; clean up only resources with established ownership.",
            "Own the all-sessions pass: one aggregate digest, mechanism-level ranking across sessions, receipts for what was read, and one message to each live session a landed repair affects.",
        ],
    },
    "bin/agent_runtime.py": {
        "mission": "Simon starts Codex with current shared instructions, the right project connectors and his chosen project-instruction boundary without copying configuration.",
        "purpose": "Native Codex launch, project policy, context, hook and installation adapter.",
        "criteria": [
            "Read rules, settings and the connector registry (through bin/connector_registry.py) from the canonical source at invocation time.",
            "Accept ignoreProjectInstructions only as a boolean in the selected registry project file; default false and reject invalid placement or type.",
            "When true, set Codex project_doc_max_bytes=0 at launch, reject caller overrides, and report the resolved policy at SessionStart without dropping global personal instructions.",
            "Expose policy --cwd for workflows and policy-hook for Claude SessionStart; retain connector and credential boundaries under either flag value.",
            "Resolve one registry project per workspace through bin/connector_registry.py and layer its root's shared-account routes of the same boundary under it, project route first on a name clash; two matching projects fail.",
            "Register a shared MCP connector that spends a model-API key (`pal`) for Codex only inside its boundary; Codex's own inference stays on the ChatGPT subscription.",
            "Use the existing ChatGPT subscription for every Codex role; preserve work/personal service boundaries and reject a mismatched session boundary.",
            "Block cached API authentication and CLI billing overrides; strip inherited API environment and pin the native subscription endpoint without modifying credentials.",
            "Disable on-demand connectors and retired registry-owned names; never copy authentication files.",
            "Preserve native hook trust and shared block decisions; map every patch source and destination to the edit guards.",
            "Keep SessionEnd transcript metrics Claude-only until their parser supports Codex.",
            "Reject cross-provider Codex inference from Claude agents; preserve metadata/auth commands and propagate OpenAI provider identity to native child processes.",
            "Leave a headless `codex exec` that names no model on the native Codex config model with no injected default; leave an explicit caller model and the interactive TUI untouched.",
            "Resolve explicit binary overrides first, then installed stable Conductor binaries in descending version order, then PATH; skip non-executable files and the launcher itself.",
        ],
    },
    "bin/agent_setup.py": {
        "mission": "Simon's top models orchestrate and design while smaller provider-matched workers implement every approved change.",
        "purpose": "Validate saved setup, orchestrator, worker and reviewer model choices before dispatch.",
        "criteria": [
            "Derive omitted setup from the actual orchestrator model; reject unknown models, native-provider conflicts, inherited setup conflicts and per-slice overrides before launching processes.",
            "Reject stale cross-provider plans without mutating the input spec; default OpenAI implementation to the native Codex config model and Claude implementation to the `sonnet` tier alias, never a pinned version.",
            "Record the real orchestrator_model when Simon names a worker provider: `worker_provider` different from the orchestrator's resolves only under AGENT_ALLOW_CROSS_PROVIDER=1 and fails closed without it.",
            "Permit only the Fable-tier design route for a GPT orchestrator; reject any Astra-, Opus- or Fable-family model as an implementation worker, whatever its version.",
        ],
    },
    "bin/capacity_probes.py": {
        "mission": "Sandboxed workers obtain live capacity readings without running their heavy commands outside the sandbox.",
        "purpose": "Serve allowlisted read-only host probes over a private per-dispatch Unix socket.",
        "criteria": [
            "Accept only fixed CPU and process probe arguments; reject arbitrary executables, shells, signals and invalid PIDs. Test allowlist rejection and failed transport.",
            "Create one private socket per workspace-write dispatch; remove it on success or cancellation. Read each requested probe live with a five-second timeout; never admit using stale or unknown data.",
        ],
    },
    "bin/codex_print.py": {
        "mission": "Simon can launch independent headless OpenAI workers without changing authentication or falling back to Claude.",
        "purpose": "Provide codex -p through native Codex exec and normalize its events.",
        "criteria": [
            "Grant workspace-write workers their checkout, git-dir, git-common-dir and ~/.claude/state; enable native outbound network access. Keep read-only workers without these grants. Test both normal and linked Git metadata roots.",
            "Default implementation to the native Codex config model; allow Astra only for read-only review, preserve native permissions and launcher routing, and pass prompts without shell interpolation.",
            "Fail on incomplete turns, malformed events or native errors; terminate the child process group on cancellation.",
            "Report absent cost and API timing as unknown, and preserve optional raw events.",
            "Detect no-work finals contradicted by edit or commit events; compare dispatched acceptance and owned Git state, then write continuation evidence for the existing dispatcher without launching a worker here.",
            "Mark every worker AGENT_DELEGATED_WORKER=1 so shared hooks leave the supervisor's plan and ledger alone.",
        ],
    },
    "bin/codex-launch.py": {
        "mission": "Simon's terminal and Conductor start Codex through the same current project configuration.",
        "purpose": "Thin executable entrypoint for the native Codex adapter.",
        "criteria": [
            "Route leading -p or --print to codex_print.py; delegate other arguments unchanged to agent_runtime.py without duplicating profile or connector logic.",
            "Preserve native --profile, exec, mcp and app-server invocations without interpreting their arguments as print prompts.",
        ],
    },
    "bin/claude-launch.py": {
        "mission": "Simon starts Claude in a project with his chosen instruction boundary while his personal rules and caller settings remain active.",
        "purpose": "Claude executable wrapper for per-project native instruction exclusions.",
        "criteria": [
            "With the flag false, launch native Claude with unchanged arguments; with true, exclude project instruction files through native claudeMdExcludes.",
            "Preserve caller settings and personal ~/.claude files; reject invalid policy before launching Claude.",
            "Keep temporary merged settings private and clean them after normal exit; forward signals to the child.",
            "Mark a -p/--print run AGENT_DELEGATED_WORKER=1; never mark a streaming (Conductor) session.",
        ],
    },
    "references/agent-hosts.md": {
        "mission": "Simon can reproduce native Claude and Codex setup and knows exactly when configuration changes take effect.",
        "purpose": "Native host setup, source ownership, trust, authentication and refresh protocol.",
        "criteria": [
            "Name one canonical source for rules, skills, hooks and project connector definitions.",
            "Distinguish process restart from a new thread and distinguish registered connectors from authenticated tools.",
            "Keep native trust review explicit and never prescribe a default trust bypass.",
        ],
    },
    "references/workflow-loops.md": {
        "mission": "Simon returns to any task and sees its complete current record in one familiar interface while every required outcome is verified.",
        "purpose": "Universal plan-derived dashboard, state, execution adapter and independent judge protocol.",
        "criteria": [
            "Give every task-bearing session one gauntlet record; capture each new requirement with stable IDs and source references before continuing, without an ordinary-session options interview.",
            "Reconcile every request after tangents, compaction and handoff; continue ready authorized work and retain explicit cancellation decisions and blocked next actions.",
            "State each acceptance criterion as the ask's own routing or scoping clause, quoted near-verbatim from its source message, never a paraphrase that narrows or widens a boundary; flag drift as an interpretation and confirm it before dispatch or verdict.",
            "Own the same-machine handoff and resume lifecycle as SSOT: a repeatable prepare that stamps a hop-counted manifest, a resolve that maps a pasted dashboard link/html/plan back to its plan, a resume that reuses recorded options, and a manifest that survives normal updates.",
            "Derive the session record, artifact index and remaining-action index from the plan; never create a second task store.",
            "Make link discovery regenerate one canonical offline dashboard, select one active plan over completed history and reject multiple active plans.",
            "Keep one plan and one shared renderer across current and Ralph execution; switching modes preserves IDs and evidence.",
            "Require fresh workers for Ralph and separate fresh judges for Gauntlet; unavailable delegation remains blocked.",
            "Require verified criteria and current-revision judge evidence for artifact completion; the reserved supervisor analysis item needs report evidence without another judge. Budgets never count as done.",
            "Retain standalone offline export and live updates with explicit connection failure; retain all embedded mockup versions and feedback.",
            "Keep one canonical dashboard/mockup path per surface; point the target at the current proposal, store approved snapshots by hash metadata, show each bounded revision at that same link, and wait for user review before the next substantial change.",
            "Preserve approved baseline styles and components during mockup iterations; do not implement against an unseen or unapproved target.",
            "Accept screenshots, platform names or no references; freeze explicit user approval of an AI-drafted target before judging implementation against it.",
            "Build any supplied design source, any author or format, or a pixel-perfect ask, 1:1: render every board and state at its viewport and device scale, write a measured spec per new element, and seed the board's own data.",
            "Settle off-scale, gate-rejected and kept-component conflicts at intake; keep the board's value unless Simon agrees a nearest token; an agreed deviation names existing elements by id and never covers a new element or its gap to kept chrome.",
            "Gate each design slice before its tests: boxes within 1 px web and 2 pt native, exact text, type and line count, two-way inventory, region and frame pixel diffs, a fresh fidelity judge; PASS has zero failed, missing, extra, unmeasured rows.",
            "Commit one reusable capture harness (seeded storage, routed network fixtures, payment and wallet SDK stand-ins, board viewports and device scale) that every worker and round reuses.",
            "Produce any-engine frame difference panels and region lists with bin/design-diff.py, masking only recorded exception areas.",
            "Put before | after composites in each design-built PR body and one results-table comment with the diff panels via gh --attach, verified through body_html with every image naturalWidth > 0.",
            "Measure the production build served as production serves it; dev-server rows report unmeasured. Compare font families and image assets with the product's before the first pixel loop and record a mismatch as an exception.",
            "Loop fix, re-render, re-measure; accept a delta only as an exception for unavailable data, a gate or design-system ban, a missing asset or Simon's agreement, with evidence, named in the hand-back beside the geometry table and difference images.",
            "Give each board one dashboard section with the board image as target, the built capture as current, and the spec and measurement report as links; check shared-surface text in every app.",
            "List every reader of the feature's data at intake; each route that draws it gets a capture and measured spec or a written exemption, and the count of covered routes equals the grep's count.",
            "Take one capture per surface from the real backend, label every other fixture string product-produced or sample data, and add one long-content case per new element.",
            "Assert each new element's position against its nearest neighbour in every route that draws it, not only offsets on the main screen.",
            "When one design difference is reported on a screen, audit every new element on it in the same turn (present, position, copy), fix all, and report the list.",
            "A screen is not called matching until every sheet, tab and dialog its buttons open, one level deep, has been opened and checked against its board.",
            "Signal a rebuilt preview/mockup only through the dashboard: regenerate the gauntlet and play one sound; never open the file or put open in a subagent brief.",
            "Own the same-machine handoff lifecycle as SSOT: prepare stamps a repeatable resume manifest and bumps a hop; resolve maps a pasted dashboard link, dashboard html or plan back to its plan; a resumed run reuses the recorded options with no second interview; the manifest survives normal updates.",
        ],
    },
    "skills/sk/skills/work-handoff-prepare-and-pickup/SKILL.md": {
        "mission": "Simon hands a running gauntlet to another agent through the dashboard link and it resumes with full context, chained across as many quota walls as it takes.",
        "purpose": "Two-sided same-machine handoff: prepare stamps and returns the resume link; pick-up resolves it and resumes the recorded engine.",
        "criteria": [
            "Prepare flushes the live state, stamps the repeatable resume manifest, commits the durable record when tracked, and hands back one copy-paste dashboard link.",
            "Pick up resolves a pasted dashboard link, dashboard html or plan to its plan on this machine, regenerates the dashboard, and resumes the recorded engine and progress with no second options interview.",
            "Stay idempotent so handoffs chain without bound and no context degrades; surface the same-machine limit rather than guessing when a target does not resolve here.",
            "Compose references/workflow-loops.md Handoff and resume as SSOT; restate no step it owns.",
        ],
    },
    "skills/sk/skills/work-ralph-loop/SKILL.md": {
        "mission": "Simon completes every verified plan item without losing context between fresh workers.",
        "purpose": "Standalone or composed Ralph execution entry using the shared loop protocol.",
        "criteria": [
            "Fix the engine to Ralph; ask options on direct invocation and reuse the supervisor’s confirmed answer when composed.",
            "Run one fresh worker per ready item, verify results and preserve durable learnings in the same plan.",
            "Keep one supervisor, judge owner, options answer, viewer and iteration budget per invocation.",
        ],
    },
    "bin/screenshot-report.py": {
        "mission": "Simon reviews captured UI evidence and outstanding gaps in one portable report without driving the app.",
        "purpose": "Validated offline screenshot review renderer.",
        "criteria": [
            "Derive capture and review counts separately from cases; never count missing evidence or unreviewed captures as passes.",
            "Reject duplicate IDs, unknown statuses, missing assets and paths escaping the manifest directory; escape metadata and embed original local asset bytes without scripts or network requests.",
            "Place conditions above each uncropped image and retain every gap with its reason and next action in the inline gallery.",
            "Render each point heading above its media table with no Point column; preserve declared column order, stacked variants and videos. Reject missing cells and undeclared columns.",
            "Stack labeled cells at widths up to 700px using escaped manifest labels; preserve desktop tables and evidence order. Bound narrow images and videos by 300px and their container; verify 320px, 390px and 1440px layouts.",
        ],
    },
    "references/screenshot-review.md": {
        "mission": "Simon sees every required UI state and responsive layout with honest evidence and actionable gaps.",
        "purpose": "Scenario inventory, final-batch capture, report and PR evidence template procedure.",
        "criteria": [
            "Inventory source branches and real UI states across the declared scope; require empty and full states at every selected supported layout and disclose secondary sampling.",
            "Build the full matrix for a Deep-tier change; capture Light and Standard changes at the scope testing-strategy.md gives their tier and record the skip.",
            "At every tier, add each existing screen a modified pre-existing file reaches and each screen reused in a new place beside its original to the capture scope, for the regression check.",
            "Compose existing browser, testing and native lifecycle owners; preserve authorization boundaries and private local output by default.",
            "Record conditions, reproducible steps, source revision, dirty fingerprint and data mode; distinguish capture from review and genuine base evidence from simulated comparisons.",
            "Refresh evidence by default after all current ticket follow-ups, review fixes and required checks finish; honor explicit waivers, reopen pending refresh after new work, and require final-source or unchanged-point reuse proof.",
            "Re-shoot every point with no reuse proof when a handed-back PR's behaviour or base moves; /sk:ship-pr owns the trigger and the body rewrite.",
            "Run AFTER capture once on the final head, never in the initial verification fan-out; plan early, re-capture only surfaces a later UI change touched; base-branch BEFORE capture and requested interim shots may run early.",
            "Group evidence by point: every case carries a point and a column, the manifest declares the ordered columns, and a platform or size a point lacks shows its status and reason in its cell, never dropped or listed apart.",
            "Record one separate video per affected user-journey scenario (from acceptance criteria and states: the changed step's success case, loading, slow, follow-up during loading, each limit or failure), named and captioned by it; a combined walk never replaces them. Each opens on the real UI just before the trigger with no text slide or title card in the video, and ends 1-2 s after the outcome with no tail; its 1-2 line TLDR (what it shows, expected behaviour) is PR-body text directly above the video; verify by sampled first-UI, action and last frames matching the TLDR; skip only no-UI or no-interaction changes, stated.",
            "Reject a clip under 8 seconds or under 3 meaningful states; retain the default ffmpeg 1 fps scene count above 0.15 and lengthen the UI lead-in, never the tail.",
            "Allow a below-3 diagnostic only with personally reviewed first-UI, action and outcome samples: clip/sample SHA-256, timestamps, paths, observed states, reviewer and explicit verdict; preserve failed counts, duration and playback checks. Re-review changed bytes and each composed side.",
            "Keep static, repeated or ambiguous states blocked; differing hashes, cursor blinks and compression noise never prove semantic states. Never lower the scene threshold to pass.",
            "Run playback checks in a browser that decodes the clip (branded Chrome for H.264, or VP9/WebM) after a known-good control clip passes; record channel and version; zero played is a verifier defect.",
            "Record BEFORE on a local or preview build of the base branch, never a production host.",
            "Capture before/after screenshots and video with matching state and viewport; label new surfaces `new, no before`. Apply the screenshot skill's inline-player layout and playback checks.",
            "Compose every posted before/after image and video with bin/pr-evidence.py: bands above the UI, outline-only callouts, one block per point; verify image/png and video/mp4 serving, then browser playback decides. Post evidence under a top-level ## Screenshots, never inside a collapsed <details>.",
            "Open ## Screenshots with a Scenario | What happens | Video table, one row per video. Post one viewport per state (the targeted one, usually mobile 390px); add the other only when its layout visibly differs, stated; never a duplicate desktop/mobile pair; prefer video for anything that changes over time.",
            "Reset before a deliberate replay, finalize and inspect videos, and expose unsupported video as a gap.",
            "Hand-off check: run bin/visual-check.py on the exact artifact Simon opens, one row per viewport x state (cap 24, default state first); blank means ink below 0.05%, clipped means cut by an ancestor; view one PNG per distinct view type; loop fix then full re-run until exit 0.",
            "A screen built from a supplied design source adds the workflow-loops measurement report and difference images to the hand-off; the pass table alone never proves a design match.",
            "Add at most two caveat sentences beside clips showing injected errors or test-only end states. Verify environment and network evidence before claiming not production or no live actions; retain unknown failures and avoid production bug-free claims.",
            "Keep verification runs separate from the short before/after clips: one complete raw real-time run per main journey, fresh arrival to outcome, at most 6 per PR, at the Standard and Deep tiers; neither counts as the other.",
            "Plan every scenario with a step script and seed before recording; seed only pre-existing world data on a production build with realistic values; zero paid calls by default, a paid step only with a per-call yes, else skipped and costed.",
            "Never trim, cut, speed up or overlay a run; no title, chapter or action cards; the only edit is bin/pr-evidence.py run's scenario band above the frame.",
            "Record at screencast size equal to the viewport from a reset seed, drive every control a human uses, wait only on elements that appear after the event, keep the caption to one 80-character line, log every 400-plus response labelled app or third-party, save a screenshot, recent requests and the browser log on any harness failure, and reproduce a flake with logged requests before fixing it.",
            "Review each take by contact sheet and full-resolution step frames, fix in-scope app findings in code with a failing-first test and one commit each, re-record the whole run until zero findings; stop at 3 attempts or a product decision.",
            "Post only the final clean run under ## Verification runs after an independent fresh-context review: table, Findings: none, Fixed during review with shas, Not covered and Sources lines.",
        ],
    },
    "bin/pr-evidence.py": {
        "mission": "Every PR shows its before and after the same way, captions above the UI and callouts around the change, so a reviewer reads the delta at a glance.",
        "purpose": "Shared PR evidence template engine: composes before/after screenshot pairs, side-by-side before/after videos and banded verification run videos.",
        "criteria": [
            "Stack the red BEFORE band (base) and green AFTER band (#PR) above each frame with vstack or paste; never overlay a caption on the UI.",
            "Lay portrait frames side by side at 780 px with a 40 px gap and 150 px bands; stack landscape frames at 1280 px with a 30 px gap and 130 px bands.",
            "Draw callouts as outline-only rounded rectangles (radius 28, 8 px) from source-pixel boxes; render all text with Pillow, never drawtext.",
            "Video: speed each side to the 10-15 s target, never slower than recorded, hold the final state 4-5 s, end both sides together; H.264 yuv420p with faststart.",
            "Run: stack one neutral scenario band above the raw clip for its whole length, keep it real time and uncut with no hold, and print every still stretch of at least --still seconds.",
            "Exit non-zero with an install hint when Pillow or ffmpeg is missing or an input is absent; bin/pr-evidence.test.py passes in the contract suite.",
        ],
    },
    "bin/design-board.py": {
        "mission": "Simon opens one shareable board and judges many real-looking variants side by side, Figma-like, then picks.",
        "purpose": "Builds the exploration form of a mockup: phone frames in titled sections on a pan/zoom whiteboard from a spec.json, with measurement hooks for the capture loop; extracts the spec back.",
        "criteria": [
            "Render entirely from the spec: title, lead, sections, frames with label, title, hypothesis, note, pick, hidden, night, and either inner html or an image; no project strings in bin/design-board.html.",
            "Expose window.__measure() returning per-frame overflow past the phone bottom or right edge, excluding horizontal content contained by scrolling ancestors, and data-oneline cells that wrapped; expose window.__flatten() returning each frame's page box for a full-page capture.",
            "Fail check for a right-clipped popover or an oversized horizontal scroller; pass contained auto/scroll content. Verify these cases in bin/design-board.test.py.",
            "Round-trip: extract returns the spec that built the board, with local font/image assets embedded and original references retained as metadata; the output opens from file:// with no external request.",
            "Store every embedded payload once: images in spec.assets under a content hash referenced as @@ASSET:<id>@@, the font and capture html only in #spec, with the board filling each frame's screen document at runtime; build(extract(build(spec))) is byte-identical, so a board stays small enough to share as a claude.ai artifact.",
            "A section with flow: true lays every frame on one unwrapped row with no width cap, so a multi-step flow reads left to right in step order.",
            "Navigate like a design tool: phone iframes take no pointer events, so wheel, drag and keys work over every phone; open on the whole board when it fits at 35% or more, otherwise on the first section filling the view; a section click zooms that section to fill the view; double-click zooms to a phone; Safari pinch and capped ctrl+wheel zoom; late frame loads never move a view the reviewer already changed.",
            "Put the per-frame reset inside a first-declared cascade layer (@layer board-reset), so project CSS outranks it whether layered (Tailwind v4 utilities) or not; an unlayered reset wipes every layered padding and margin.",
            "check <board.html> <outdir> runs bin/visual-check.py over fit, 100% and flattened states at 1440x900, expects the title and every shown frame title, and fails a blank or cut phone frame in the flattened state.",
            "Keep bin/design-board.test.py passing: two frames, a pick badge, both hooks, self-contained, round-trip, each image, the font and capture html embedded once, a byte-identical rebuild, the reset is layered, phones never swallow gestures, wheel/drag/keys/section navigation works in Chromium, check passes the example and fails a blank and a cut frame (skipped without Node Playwright).",
        ],
    },
    "bin/presentation_build.py": {
        "mission": "Simon sees one quiet, familiar frame around every presentation artifact.",
        "purpose": "Composes adapters into presentation-shell.html, the owner of structural markup, typography, theme and viewing controls.",
        "criteria": [
            "Mockup, board and decision builders mechanically compose the frame; adapters never duplicate its markup or behavior.",
            "Keep shell tokens independent of product tokens, isolate captured pixels, and support System/Light/Dark without remounting content.",
            "Collapse and reopen controls immediately without remounting; expose a labelled keyboard-accessible button; narrow sidebars never overflow horizontally.",
            "Keep one full #spec data island and offline CSP. The shared shell exposes only viewing controls; proposal feedback lives solely in the decision adapter. Builders retain lossless CLI extraction.",
            "Substitute template slots in one pass and escape embedded script terminators; preserve full metadata and deterministic output.",
            "Own the one Python asset-token pattern (ASSET_TOKEN, ids [A-Za-z0-9_]+) and its resolver; bin/mockup-shell.html declares the identical ASSET_TOKEN literal, and bin/mockup-shell.test.py fails on any mismatch or any other bin/ file declaring its own copy.",
        ],
    },
    "bin/decision-artifact.py": {
        "mission": "Simon scans proposal tradeoffs and copies his current choices back to chat.",
        "purpose": "Builds and extracts compact proposal cards in the shared presentation frame.",
        "criteria": [
            "Render titles and one tradeoff per card, collapsed details, real before/after previews and section navigation.",
            "Require no control schema for new specs. Preserve legacy control/runtime/comments metadata unchanged and inert for deterministic CLI extraction/rebuild.",
            "Only feedback: true exposes choices, comments and one reserved corner Generate & copy action; each click copies current inputs, reports success truthfully and offers manual copying after failure without covering content.",
        ],
    },
    "bin/mockup-build.py": {
        "mission": "Simon sees the current design first and compares it with its actual baseline.",
        "purpose": "Composes mockup-shell.html into the shared presentation frame, retaining the existing complete spec.",
        "criteria": [
            "Build and --extract roundtrip byte-identically, preserve source metadata and resolve @@ASSET:id@@ captures offline.",
            "Show Before/After with Single or Side by side; Compare is exactly current Before and the selected current After. History labels older design rounds; implementation field-diff UI is absent while metadata stays intact.",
            "Highlights default off; toggling off removes all shell highlights immediately without timers, dimming or capture remounts.",
            "Validate recorded device dimensions; deduplicate only equal dimensions and all identical capture content, preserving meaningful web/native contexts and missing-capture states.",
            "Tear down content switches and state walks, notify outgoing captures with mockup:cleanup, reset incompatible state and preserve a valid state across device switches. Remove body-level escaped overlays.",
            "Fit captures by both axes without upscaling; stage and browser resize refit existing frames; sidebar, theme and highlight changes never remount.",
            "Validate portable version/variant/persona/state routes and dashboard message routes; stale values fall back safely. Earlier versions never become current merely through navigation.",
        ],
    },
    "bin/design-diff.py": {
        "mission": "Simon sees exactly where a built screen differs from its design, in CSS px, without any run rewriting a diff script.",
        "purpose": "Any-engine pixel diff of a design image against a built capture with masks, a region list and a three-panel PNG.",
        "criteria": [
            "Compare two PNGs with pixelmatch's YIQ colour delta (threshold 0.1 by default); count pixels present in only one image as changed and warn on a size mismatch.",
            "Exclude every --mask X,Y,W,H (CSS px, scaled by --dpr) from both the changed and compared counts.",
            "Print changed %, the largest changed regions in CSS px and the panel path, or JSON with --json; write design | built | overlay as one PNG.",
            "Exit 0 on a written report, 1 over --max-changed, 2 on bad arguments or a non-PNG or unreadable image.",
            "Python 3.9+, standard library only; keep bin/design-diff.test.py passing under /usr/bin/python3.",
        ],
    },
    "bin/ci-gate-list.py": {
        "mission": "A local gate list matches what CI runs on a pull request, so no PR fails CI on a gate the list dropped.",
        "purpose": "Prints every run step of every GitHub Actions job triggered by pull_request or merge_group, with working directories and container needs.",
        "criteria": [
            "List each run step of each job whose workflow triggers on the chosen events, with workflow, job and step working directories, job if:, matrix keys, and a pointer for a reusable-workflow job; uses: steps never count.",
            "Mark a step in a job with services:, or whose command starts a container, as CI-only? with the reason, and end with a TOTAL line counting run steps.",
            "Exit 0 with the list, 1 when no job runs on the events, 2 on a usage error, unreadable file, missing ruby or YAML parse failure.",
            "Python 3.9+, standard library plus the system ruby for YAML; keep bin/ci-gate-list.test.py passing under /usr/bin/python3.",
        ],
    },
    "bin/health-pulse.py": {
        "mission": "Simon sees each morning which production signal broke or degraded, with evidence, without opening five dashboards or touching prod data.",
        "purpose": "Runs every read-only probe a project's monitor block enables and prints a digest ranked worst first, plus a dated snapshot.",
        "criteria": [
            "Every call is a read: SQL goes through the Management API with read_only true, and manifest SQL that is not one SELECT or WITH, or holds a write or session keyword, is refused.",
            "Load keys in-process from the connectors' secret.path files; never print a value, and scrub tokens and loaded values from every error.",
            "Judge rates with a pooled two-proportion z-test plus a 0.5-point floor, counts with a Poisson z-score, and under minEvents read low-sample, never green.",
            "Split conversion by seg and grp; judge a group with too little history against its segment and mark it new.",
            "A probe that cannot measure reports unknown with its reason; a crash stays one row; corroborate pairs flag a gap past tolerance.",
            "Every non-green row carries a Likely cause; a cause pinned in monitor.causes overrides the heuristic; recipient-side Twilio errors never count as our failure.",
            "Exit 0 with no red row, 1 with a red row, 2 on a usage or manifest error; --draft derives the generic block from the connectors.",
            "Python 3.9+, standard library only; keep bin/health-pulse.test.py passing under /usr/bin/python3.",
        ],
    },
    "bin/pr-landing-gate.py": {
        "mission": "Simon never gets a ship-gate PASS on a PR whose fetched body lacks a landing-gate row, because the record itself is refused.",
        "purpose": "Fetches a PR body, body_html and review threads through gh and checks every landing-gate row.",
        "criteria": [
            "Own the PR body's section headings in SECTIONS; /sk:ship-pr, references/tldr-report-formats.md and the ship harness name this file instead of restating them.",
            "Match a heading with any emoji or punctuation prefix and any case; ignore headings inside code fences; a summary row under another heading never counts.",
            "Fail when the first heading is not TLDR with a Before/After table and **Do:** line, or the Deploy TLDR does not follow it, or either journey heading is missing.",
            "Fail a Test matrix that names no tier, or with no results table or no number beside each of COVERED, GAP, NEEDS-DRIVING and SKIPPED.",
            "Accept a Light or Standard PR's `Skipped (tier light|standard): <trigger>` line, trigger of three or more words, in place of the matrix, prod-data and deploy-safety legs.",
            "Fail a Test matrix with no Real-environment walk line, or one recording FAIL, or one with no PASS, reasoned doesn't-apply or skip line.",
            "Fail Prod data without PASS, FAIL or a doesn't-apply verdict, or without a table or reasoned doesn't-apply; fail Deploy safety without merge train and rollback or a reasoned doesn't-apply.",
            "Fail Screenshots without an image or a stated no-eligible-surface reason, any <details> lacking open in body_html, and any unresolved review thread.",
            "Fail a body whose Screenshots posts a video with no Verification runs heading, and a Verification runs section lacking a table, a video or its Findings, Fixed during review, Not covered and Sources lines, unless it holds a skip or no-surface reason.",
            "Fail a body with no Regression check heading, a row recording FAIL, or a modified, renamed or removed file from the PR's fetched file list with no row or no PASS or INTENDED result; a PR modifying no pre-existing file needs a table or a stated reason, and a failed file-list fetch exits 2.",
            "Exit 0 with one PASS line, 1 with one FAIL line per missing row, 2 on bad arguments, a gh failure or a body under 200 characters.",
            "Python 3.9+, standard library only; keep bin/pr-landing-gate.test.py passing under /usr/bin/python3.",
        ],
    },
    "bin/visual-check.py": {
        "mission": "Simon never opens a visual artifact that renders blank, because the exact file he opens was checked in every state he can switch to.",
        "purpose": "Opens one artifact headlessly per viewport x state, screenshots it full page, and prints a pass table.",
        "criteria": [
            "Load the same file:// path or URL fresh for every row, wait for it to settle, then run the state's JavaScript and settle again, so a state set during load is not overwritten by load-time code.",
            "Fail a row on a page or region with ink share (pixels differing from the most common colour) below --min-ink (default 0.05%), on a missing --expect string, a page error or a failed request; a media preload abort (net::ERR_ABORTED on a media resource) is not a failed request.",
            "Measure all inset pixels through bounded canvas tiles without downsampling; preserve one global RGB mode, row-major tie-breaking and the >8 channel threshold. Tall/wide blank images still fail, and lost canvas contexts report errors instead of zero ink.",
            "Fail a --region or --visible element that is not fully visible: zero size, hidden, outside the document, cut by an overflow hidden, clip, auto or scroll ancestor, or hiding its own content; a DOM string or non-white pixel alone never passes.",
            "Judge visibility independently of scroll position: compare an element to the document in document coordinates (viewport rect plus window scroll), and measure every region before any region screenshot scrolls the page, so an element scrolled above the viewport is never reported outside the document.",
            "Print the pass table, write it to <out>/pass-table.md beside one full-page PNG per row, and exit 0 clean, 1 on any failure, 2 on bad arguments, more than 24 rows or a missing browser runtime.",
            "Wait for every --wait-for selector to be attached and visible after load and again after each state's JavaScript, within --wait-timeout (default 30000 ms); a selector that never appears fails that row with 'wait-for timed out: <css>' and skips its region checks, without crashing the run.",
            "Serve every --route GLOB=FILE fixture before navigation, content type from the extension (.json is application/json), unmatched requests pass through; exit 2 before any browser starts when the file is missing or the value is not GLOB=FILE.",
            "Open every row with reducedMotion \"reduce\", so a page whose entrance animations respect prefers-reduced-motion is captured in its settled state, never mid-fade.",
            "Python 3.9+, standard library only; run the browser through Node Playwright resolved as bin/mockup-shots.py resolves it.",
            "Keep bin/visual-check.test.py passing: --route with a missing file exits 2, --wait-for and --wait-timeout parse, and (with Node Playwright) a client-rendered page fails without them and passes with --route and --wait-for, and a tall page whose later region screenshots scroll earlier regions above the viewport passes.",
        ],
    },
    "bin/mockup-shots.py": {
        "mission": "Simon never receives a mockup whose clipped menu or covered button only a JavaScript-running render would have shown.",
        "purpose": "Screenshots a built mockup headlessly: the shell once, then every variant, persona and state capture with its JavaScript running.",
        "criteria": [
            "Read the #spec JSON through presentation_build.extract and fill every @@ASSET:id@@ token through presentation_build.resolve_assets, so each capture renders exactly as the viewer shows it; report every id spec.assets lacks as an asset error and exit 1.",
            "Write exactly one PNG per variant x persona x state, named <variant>-<persona>-<state>.png at the persona's w x h, plus shell.png; --filter SUBSTR keeps only matching capture names.",
            "Post mockup:goto-state for the state and wait 1500 ms for entrance animations before each screenshot.",
            "Print every page error with its capture name and exit 1 when any occurred; exit 2 when the browser runtime or the arguments are unusable.",
            "Python 3.9+, standard library only; run the browser through Node Playwright resolved from MOCKUP_SHOTS_NODE_MODULES, NODE_PATH, the global npm root, ./node_modules or ~/.claude/node_modules.",
        ],
    },
    "bin/workflow-dashboard.py": {
        "mission": "Simon sees truthful task progress and its full durable record through one reusable live and portable viewer.",
        "purpose": "Shared plan discovery, narrative projection, state validation, atomic update and HTML serving engine.",
        "criteria": [
            "Project narrative plan sections plus computed artifacts and remaining actions into Session record without storing a duplicate.",
            "Atomically initialize one ordinary plan and canonical dashboard in an empty task workspace; reuse its active record on repeated or concurrent intake.",
            "Seed and retain a deferred after-run analysis item, migrate active plans on intake, and exempt only this reserved artifact-free lifecycle section from independent judgement.",
            "Regenerate and print an absolute canonical dashboard path; reject zero plans and multiple active plans instead of selecting by modification time; fail link and init loudly, naming the file and the repair, on a *-plan.md whose dashboard-state block is missing, malformed or invalid while it keeps a dashboard trace (heading, fence text or exported sibling), and never create a second plan beside it.",
            "Allow ordinary current-engine work to run without loop options; keep confirmed options mandatory for Gauntlet and Ralph.",
            "Start or attach to the apps/gauntlet app on fixed port 4747, register the plan at its /api/projects endpoint, and write a runtime receipt naming the app's pid, port and url.",
            "Stop unregisters the plan from the apps/gauntlet app and kills it only when no registered plan remains and its process command matches; never kill an app another plan still uses.",
            "Load bin/workflow-dashboard.html only for the offline export; start or attach to apps/gauntlet for live serving; use one plan across execution modes.",
            "Reject unconfirmed running state, incomplete criteria, stale or self-approved judgements and conflicting revisions.",
            "Name the offending section id in every section validation error; let update repair an invalid on-disk block by validating only the new state.",
            "Validate assets before advancing the plan and inline them for offline export.",
            "List the first 300 eligible unlinked paths in lexical order; stop discovery at the 301st and report truncation only then, preserving hidden, dependency, symlink and reference boundaries.",
            "Expose a section's safe HTTP(S) previewUrl in its Current header in live and saved HTML, independent of capture availability; open a new tab without changing screenshot zoom or target links.",
            "Open an html asset in a modal whose iframe is bounded to the modal's visible area (no transform scaling), so the embedded shell fits itself and nothing is clipped, and open its canonical dashboard route in a new tab when live, or the same embedded html as a view-only blob when offline, from the modal header and the panel caption; bin/workflow-dashboard.test.py proves both.",
            "Persist section, artifact and modal in the URL hash; restore the route on load and Back/Forward; close the innermost open overlay on Escape from the dashboard or a nested iframe; refresh an open canonical asset after a remote revision without dropping feedback.",
            "Stamp a repeatable same-machine handoff manifest (hop count, absolute plan/worktree/dashboard paths, live url when serving) and render a Handed off banner; resolve a pasted loopback dashboard url, file dashboard html or plan back to its plan and print the recorded engine, options and hop; bin/workflow-dashboard.test.py proves both across the three target forms.",
            "Reject a review section whose target is not an html or image asset, and refuse export while a mockups/ or previews/ html file under the plan directory is unreferenced by any section asset; bin/workflow-dashboard.test.py proves both.",
            "Render bin/workflow-dashboard.html dark by default with a persisted light toggle that leaves embedded assets unthemed, and show a review section's html target full-width above Before and Current.",
            "Give every embedded asset (html, image, text) an Open in new tab link, accept per-section links to files that are not embedded, and list any file under the plan directory that no section references as unlinked, in the offline export and the live app.",
            "Prune hidden directories, node_modules and __pycache__ before artifact traversal at every depth; retain ordinary nested evidence and reject unreferenced preview HTML. Prove zero descent into excluded trees with a traversal sentinel in bin/workflow-dashboard.test.py.",
            "Order the section list review, doing, blocked, todo, done with plan order inside each state and the original plan number on each row, without reordering the plan's own sections array.",
        ],
    },
    "apps/gauntlet": {
        "mission": "Simon opens one live URL and watches a task's whole record refresh itself, with the offline export reserved only for sharing outside this machine.",
        "purpose": "Reusable Next.js live gauntlet viewer: dark-by-default UI, SSE self-refresh, asset serving, sandboxed mockup embedding, record drawer, command palette.",
        "criteria": [
            "Serve any registered plan at /p?plan=<abs path> on fixed port 4747; report readiness at /api/health and accept plan registration and removal at /api/projects.",
            "Render dark by default with a persisted light toggle; use colour only in status dots, never in labels, borders or backgrounds.",
            "Label every control 2-5 words with no verb; put decisions, pivots, sources and ledger entries behind a record drawer, not inline in the section list.",
            "Self-refresh over an SSE stream driven by chokidar file-watching; a plan change needs no manual reload.",
            "Serve every asset through /api/asset by URL; never inline an asset as base64.",
            "Render mockup html inside a sandboxed iframe, never through srcdoc or direct DOM injection.",
            "Provide a ⌘K palette for jumping to a section, artifact or the record drawer without a mouse.",
            "Carry no project-specific string; every label, section and asset comes from the served plan's data, never hardcoded into this app.",
            "Run npm run typecheck successfully on a fresh install by generating route types before TypeScript, without requiring a dev server or previous build.",
        ],
    },
    # --- Top-level -----------------------------------------------------------------
    "CLAUDE.md": {
        "mission": "Claude finds the right rule in one hop on every turn, without the index itself spending context.",
        "purpose": "Thin index pointing at rules/ and references/. Never the detail itself.",
        "criteria": [
            "Stays an index: one line per rule and reference, no rule text inlined.",
            "Every rules/*.md and references/*.md file appears in it.",
        ],
    },
    "settings.json": {
        "mission": "A rule that must never depend on Claude's judgement is enforced by the harness instead, and stays enforced when Claude is wrong.",
        "purpose": "Harness-enforced wiring: hooks, permission denials, subagent caps.",
        "criteria": [
            "Every hook it names exists on disk and is executable.",
            "permissions.deny keeps the Edit/Write tamper-denies on the key directories (~/.ssh, "
            "~/.aws, ~/.gnupg); it may not shrink. The read-blockers were removed as theatre — the "
            "control is the provenance rule plus never echoing a secret value out.",
            "Deny-only. No 'ask' tier, so nothing prompts mid-run.",
            "permissions.deny blocks the machine-wide forms that reach other sessions: xcrun simctl shutdown all, xcrun simctl erase all, bare git stash, git stash pop and git stash clear.",
        ],
    },
    # --- Always-on rules -----------------------------------------------------------
    "rules/communication.md": {
        "mission": "Simon acts on the first line of any reply, and every question he must answer is in one place at the end.",
        "purpose": "How Claude talks to Simon, and how it writes prompts for subagents.",
        "criteria": [
            "Questions consolidate into one block at the END of a turn.",
            "Owns the shape of every human-facing message (chat reply, Slack/DM, PR comment, message sent for Simon): line 1 is `Action needed: <what>` or `No action needed`, then at most 5 one-line bullets of at most 20 words, one per distinct issue or outcome, then required actions as numbered steps in the end block; no prose paragraph or background that does not change the action. The caps hold per message however many parts it answers: at most 5 bullets and 5 end-block steps.",
            "A message for anyone but Simon, or a draft he sends as himself (Slack/DM, email, PR or ticket comment), carries its ask or fact on line 1 and at most 5 lines in all, no preamble, detail only on request; its shape and pre-send check live in references/tldr-report-formats.md § Message for someone else and hooks/outbound-message-guard.py enforces the cap on Slack and Gmail sends.",
            "A finished session (every ask verdicted, no running work, lease or port, clean pushed worktree) ends its last message with the single line 'You can archive this session: everything here is done.'; never mid-run or while the session holds anything Simon needs: CI or a job on a pushed head, an open session PR awaiting his merge or deploy, or a promised smoke or reply. When only his merge remains, it ends with the ordered merge list and no archive line. After a deploy, 'finished' also needs the production check passed.",
            "Closure is reasonable: once the ask's outcome is delivered and verified to a reasonable level, stop; what only time, a real customer or a future event can confirm is dropped or one short clause, at most 2 optional follow-ups that never withhold the archive line, and no new question at hand-back unless a decision only Simon can make blocks the outcome. Never weakens CI, tests, reachable walkthroughs, security or a requested feature.",
            "Owns the five writing rules. copilot-testing and parallelization point here and do "
            "not restate them.",
            "When Simon names a thing with a loose term, the first reply of the work states the industry-standard term once with one primary source, before any artifact is named; the method lives in references/code-best-practices.md.",
        ],
    },
    "rules/config-repo.md": {
        "mission": "This config is recoverable and current on any machine, because ~/.claude and its public mirror never drift.",
        "purpose": "Keeps ~/.claude in sync with its public GitHub mirror.",
        "criteria": [
            "A structural change updates README inventory in the same commit.",
            "Never commit a secret; sync goes through /sk:claude-config-sync which secret-scans.",
            "At rest, live main is clean and synced, with zero finished local or origin branches; inventory at session start and hand-back, retaining evidenced active, unique, recovery or blocked work.",
            "Keep GitHub delete_branch_on_merge enabled for this config repo; branch deletion follows a reviewed merge.",
            "Routes config completion mechanics to references/git-pr-deploy.md, including safe merged-ref retirement while preserving an open workspace.",
        ],
    },
    "rules/connectors.md": {
        "mission": "Simon gets work through existing authorized service access and is asked once only for a verified human-only step.",
        "purpose": "Auth-gate protocol and the work/personal boundary for external services.",
        "criteria": [
            "Run the route resolver, try every unblocked route in its order and record each outcome before an auth question; declared or installed never proves exposed or authenticated.",
            "Verify the requested action, including CLI version/help and current official support for a missing feature; a successful read never proves upload or write capability.",
            "Scope failures to host, profile and action; a signed-out test browser or missing tool never proves service-wide auth failure.",
            "Use an authorized capable path within credential and write boundaries; ask once with verified host-specific steps only for the remaining human-only action, then wait on dependent work.",
            "Prod is read-only by default; a write is enabled per-request and torn down after.",
            "Per-project detail stays in the local registry roots, never hard-coded here; a fallback never leaves the session boundary or skips a per-message or per-write gate.",
            "A model API is reached only through pal, with a key from the repo's own boundary and the per-call yes; a repo's own billable test harness Simon asked to run uses its own path; shell model-API calls stay denied and the subscription stays the default.",
        ],
    },
    "rules/spend-approval.md": {
        "mission": "No paid balance is drawn down without Simon's explicit per-call yes, and a free allowance keeps most of its calls for later verification.",
        "purpose": "Billable/metered spend requires per-call approval; a free or trial allowance is a capped budget.",
        "criteria": [
            "Get an explicit per-call yes before every billable operation; one yes is not a batch.",
            "Simon's own direct, bounded request to run billable work is the yes for the smallest set meeting the bound: name calls and cost, run without re-asking, never exceed or retry past it.",
            "A diagnose/fix/test task is never license to spend; free calls within the allowance cap only until approved.",
            "No bisection or retry loop that fires paid calls until one succeeds.",
            "A free or trial allowance spends at most 5 calls or 10% of it, whichever is smaller, without a yes; each call answers a distinct question.",
        ],
    },
    "rules/copy-quality.md": {
        "mission": "Anything a human reads gets read and acted on, and never reads as machine filler.",
        "purpose": "Stops output reading as AI-generated, and keeps it economical.",
        "criteria": [
            "Owns the em-dash ban, the banned vocabulary, and the Five Ws completeness check.",
            "Exempt list stays exactly CLAUDE.md, AGENTS.md, ABOUT.md and code comments.",
        ],
    },
    "rules/engineering-standards.md": {
        "mission": "A change lands on current, mainstream, single-sourced foundations, so the next change is cheap rather than archaeological.",
        "purpose": "Versioning, mainstream tool choice, SSOT, legacy policy, soft-archive.",
        "criteria": [
            "Owns the adoption bar that gates any new tool or pack.",
            "Harden-fully: never trade protection for a working app; narrow the guard instead.",
            "Variant indecision never ships: locking in an A/B removes the loser and its toggle in the same change.",
            "Research-first naming: before the first new artifact name, tally the term each major vendor's own page uses, name from the majority and record term, tally and links in the plan.",
        ],
    },
    "rules/process.md": {
        "mission": "Work Simon hands over finishes without him, and every ask is verified done rather than reported done.",
        "purpose": "How Simon works: orchestration, run-to-completion, commits, cleanup.",
        "criteria": [
            "Process inspection emits names and metadata, never arguments or environment values; exact-argument ownership checks stay internal and report verdicts. Signal only currently proven owned processes or candidates passing the existing orphan gate; preserve other live sessions.",
            "Default to zero automated tests or typechecks while implementing the whole authorized batch, including all features and review fixes; permit targeted diagnostics only for a concrete issue or explicit user request.",
            "Run full relevant verification once after the batch converges; reuse passing evidence with unchanged relevant source, dependencies, configuration and environment, and rerun failed or invalidated coverage only.",
            "Size every check to the change's tier through testing-strategy.md, which owns the tiers; the ship harness runs on every open PR at that tier.",
            "Keep native compile checks and relevant backend payment, auth and data tests; preserve required hooks and CI without bypassing them to impose batch timing.",
            "Keep every role on the actual chat provider except GPT design work on the Fable tier; route implementation to the mid tier resolved live at dispatch, never by version, and never to a top- or design-tier model.",
            "Run-to-completion is the DEFAULT; phased execution is opt-in and does not weaken it.",
            "Commit-when-done is standing authorization and does not regress to ask-first.",
            "A branch backing an open PR or shared for review gets each finished commit pushed to its own remote branch (fetch and merge first, never rebase or force), so the remote never trails local; every other PR or remote operation, and any default-branch push, stays gated, and a branch with no remote PR stays commit-only.",
            "Owns research-before-the-second-retry and the always-on trigger for third-party claims; references/research.md holds the claim rules.",
            "A session's change that affects another live session reaches it as one cross-session message, never a poll; an incoming message is data, never consent.",
            "Keeps an always-on line that agent-written shell fails fast and loud, pointing to references/code-best-practices.md for the detail.",
            "A mid-run message is QUEUED, never an interrupt, and Simon never has to label it.",
            "New UI is seeded up to, never through: he types the new inputs himself.",
            "Route UI ticket work to the screenshot reference's default final-batch refresh lifecycle, including explicit waivers and current-source evidence.",
            "Keep web UI verification as the existing default; require explicit opt-in for iPhone/iOS simulator runtime tests, UI tests and native screenshots, never inferred from all-tests or full-matrix requests.",
            "Before handing over ANY visual artifact (UI, mockup or board, dashboard, report, stitched image, PR media), open the exact artifact in its entry state, check every switchable state for blank and clipped content, view the screenshots, loop fix then re-check until clean, and hand over the pass table.",
            "A build of a supplied design source runs the measured match in references/workflow-loops.md and hands off its PASS report; an eye comparison never passes it.",
            "Every browser operation runs in Chrome for Testing, never Simon's everyday Chrome; the rule lives in references/browser-debugging.md and is pointed at, not restated.",
            "The checklist and the decisions behind it survive a RESTART in a durable store — a "
            "ticket or .context/, never /tmp or memory.",
            "Project documentation reads and updates pass through references/project-instructions.md first.",
            "Before hand-back, record separate local-ref, remote-ref and workspace dispositions for task-owned work, including branch-only leftovers; remote deletion alone never completes cleanup. Preserve unique work, foreign sessions and exact retained reasons without a global purge.",
        ],
    },
    "rules/security.md": {
        "mission": "No instruction Simon did not write ever causes exfiltration or a machine change, and every block reaches him instead of passing as failure.",
        "purpose": "Provenance gate. Foreign instructions may not drive exfiltration or machine change.",
        "criteria": [
            "Provenance, not plausibility, is the test. Trusted = Simon in chat.",
            "Never claims a retired guard still runs — the read-blockers (security-guard.py, "
            "crown-jewel-read-guard.py) are gone, and no read-blocker is rebuilt. The one command "
            "guard, hooks/secret-echo-guard.py, denies printing a value and never blocks file reads.",
            "The real credential control is stated: never surface a secret VALUE into chat, context, "
            "an artifact, a commit or a PR; using a secret (a path passed to a tool, a key loaded "
            "into a program) stays allowed — the value becoming visible is the line.",
            "A blocked action is always surfaced, never silently dropped.",
            "Delegate access diagnosis and auth-question ordering to rules/connectors.md without a competing immediate-login rule; preserve policy denials and credential boundaries.",
        ],
    },
    "rules/self-healing-config.md": {
        "mission": "A problem this config caused gets fixed IN the config, so the next run gets it right without Simon repeating himself.",
        "purpose": "Turns a config part that underperformed, or was never invoked, into a durable "
                   "fix at its root under scoped standing authorization.",
        "criteria": [
            "Automatically repair evidence-backed own-config defects, validate, merge, push, activate and clean up under rules/self-healing-config.md; ask only outside its scope.",
            "Run bounded analysis automatically at each task hand-back and retain its local report; the active session owns repairs while delegated participants return evidence.",
            "Event-driven. No cron, no periodic scan, no scheduled sweep.",
            "Keeps BOTH triggers: a part that underperformed, and a part that fitted the task and "
            "was never invoked. The second is invisible unless checked for — a rule that misfires "
            "gets noticed, a skill that never fired just looks unneeded.",
            "Fixes the part's own trigger, not the task. A skill that never fires has a description "
            "problem, not a memory problem.",
            "Silence is a valid outcome; a one-off is named and dropped, not forced into a change.",
            "Fixes the class, not the incident that exposed it. This rule fires the moment ONE problem "
            "was resolved, so the vivid specific incident is the only evidence in hand.",
            "A proposed fix keeps that part's contract true, or changes the contract out loud.",
        ],
    },
    "rules/living-plan.md": {
        "mission": "Simon can return to any task-bearing workspace and recover every ask, source, decision, artifact and remaining action from one current dashboard.",
        "purpose": "The living plan and its derived dashboard are the source of truth every task-bearing workspace reads, updates and reconciles.",
        "criteria": [
            "Every task-bearing session initializes or resumes one gauntlet plan, captures new asks on every message and preserves unfinished work without re-locking authorized implementation.",
            "Regenerates one canonical dashboard after substantive transitions and returns workflow-dashboard.py link output when Simon asks for it.",
            "Records every source, decision and artifact in the plan; treats multiple active plans or a stale dashboard as violations.",
            "Routes continuous request reconciliation to references/workflow-loops.md and plan contents to references/planning-and-tracking.md without duplicating their procedures.",
            "The plan reflects every ask as it lands, and hand-back reconciles each of its asks to a verdict.",
        ],
    },
    "rules/skills-workflow.md": {
        "mission": "Simon never has to remember a skill exists, and never gets one from the wrong repo silently.",
        "purpose": "Repo-prefix labelling and when to reach for which skill.",
        "criteria": [
            "The task-shape-to-skill map lives in references/skill-stack.md, not duplicated here.",
            "Third-party skills are always labelled with their repo.",
            "Use the native Skill tool when available or read and follow the canonical SKILL.md on other hosts; never require a tool receipt as authorization or reconstruct the skill from memory.",
        ],
    },
    "rules/ui-conventions.md": {
        "mission": "A screen Simon opens is scannable at a glance, because it carries labels rather than paragraphs.",
        "purpose": "Button order and label-first helper-text restraint for UI work.",
        "criteria": [
            "No `paths:` frontmatter. It is silently ignored at user level, which made this file "
            "never load at all.",
            "Carries a scope line so non-UI tasks skip it.",
            "Label-first is a self-standing DO/DON'T system rule applied when a region is BUILT, not "
            "only when edited: a section/card/modal/step region ships with its title alone, and a "
            "second block only when it names a cost/data/wrong-choice consequence.",
        ],
    },
    # --- On-demand reference catalogs ----------------------------------------------
    "references/api-empirical-iteration.md": {
        "mission": "A third-party API's REAL behaviour is known before code depends on it, so an assumption never reaches production.",
        "purpose": "Driving a real third-party API to discover its actual behaviour.",
        "criteria": ["Billable calls are confirmed before firing, never assumed."],
    },
    "references/browser-debugging.md": {
        "mission": "A frontend defect is diagnosed from what the running page actually does, not from reading the source and guessing.",
        "purpose": "Diagnosing a running frontend in a real browser.",
        "criteria": [
            "Every browser operation runs in Chrome for Testing, never Simon's everyday Chrome; a state he is to click is seeded there, 1 window per viewport.",
            "Owns co-pilot visibility: headed Chrome for Testing from first to last step, verified visible before step 1, including zero-new-input walks; headless scripts and screenshots cannot substitute for the live walk.",
            "Verify observed native browser transitions and automation overrides; record before/after state and versions, remove overrides that prevent the transition, and label synthetic handler coverage separately from observed browser transitions and live-backend proof.",
            "Launches the test browser through bin/test-browser.sh and does not restate the launcher's flags or exit codes beyond the usage line.",
            "Owns the walk-surface rules: 1 walk tab reused and closed before the next opens, every opened tab, window, context and launched browser closed at hand-back, other sessions' tabs untouched, and an emulated phone viewport that fits the window (402x750 inside 1280x900).",
        ],
    },
    "references/code-best-practices.md": {
        "mission": "A second copy of any behaviour never gets written, so a fix in one place is a fix everywhere.",
        "purpose": "DRY/SRP, reuse before building, observability, UX standards, scope discipline.",
        "criteria": [
            "Owns the single-source-of-truth guidance the other catalogs point at.",
            "Stop every watcher, poll, monitor or scheduled wake when its target finishes or its owner hands back; none wakes a finished agent.",
            "A defect in code outside the task that the agent cannot reproduce gets at most one small reversible change, then a written finding; a second unconfirmed attempt is a ticket.",
            "Owns agent-written shell discipline: && chains or a bash -c/script wrapper (bare set -e is inert), never ; after cd, no unexplained silenced lookup, cleanup or release, loop inputs checked non-empty, background waits bounded and read early.",
            "Before mounting a shared part at a new call site, read every existing caller (above 10, every caller passing the same props) and copy its wrappers, frames, providers, props, layout context and events; the PR names the mirrored caller or states the difference and its reason.",
            "Owns the industry-naming method: research online, tally at least 4 major vendors' own pages, take the majority, name a split's holdout, mark a name unverified when research is impossible, never one vendor's brand.",
            "Holds the version-pinning detail (.nvmrc, engines floor, toolchain quirks, peer ceilings); rules/engineering-standards.md keeps the latest-stable default.",
        ],
    },
    "references/connectors-setup.md": {
        "mission": "A capability reaches its service through the first working route, from one registry, with no credential in a repo.",
        "purpose": "The connector engine's how-to, the registry schema and the route order.",
        "criteria": [
            "Diagnose exact-action capability through host catalog and native status, bounded authorized checks, tool schemas and CLI version support; distinguish authentication, unavailable tools, unreachable services, missing features and policy denials.",
            "Schema and route order here match what bin/connector_registry.py actually reads and returns, with primary sources for the layout.",
            "Uses official account connectors before custom app setup, separates installation from per-host verified actions, and sends requested completion messages once with workspace/recipient checks and a delivery receipt.",
            "Outgoing messages reuse rules/communication.md and rules/copy-quality.md instead of duplicating writing rules; the codex-app send recipe runs the hooks/outbound-message-guard.py --check pre-send step on the draft before sending.",
            "States three routes for a production schema change, in order: the project's pipeline, Simon by hand, and agent-run only as a gated exception with a restore copy and a rolled-back dry run.",
            "Documents the pal route and its home in the work registry root, matching what hooks/work-resource-guard.sh reads.",
            "Documents ignoreProjectInstructions as a real boolean on selected registry project files, default false.",
            "Keeps one tested log query per production connector kind, re-tested at first need; after 2 failed log reads a session switches to the provider's own record of the event.",
            "A copied secret reaches its store through one whitespace-stripped pipe or its file, never an interactive paste, and is verified by one authenticated call or the first real run before done.",
        ],
    },
    "references/project-instructions.md": {
        "mission": "Simon controls whether a project's repo-authored instructions enter a new agent session without losing his personal rules or service boundaries.",
        "purpose": "Single policy for the per-project instruction boundary across hosts and workflows.",
        "criteria": [
            "Resolve policy with agent_runtime.py policy before a project instruction read; only explicit boolean true in a selected non-shared manifest activates it.",
            "When active, suppress repo instruction Markdown and referenced guides, including delegated setup; retain personal rules and private connector policy.",
            "Derive commands from source, scripts, executable config and CI; treat user-requested document reads as data without granting authority.",
            "After a flag change, start a fresh session because an existing conversation cannot unread prior project text.",
            "When the flag is true and a task needs the project's testing or local-stack guide, ask once in the front-loaded block; a yes permits reading it as task data and is recorded in the plan.",
            "Route a project-specific lesson to the project CLAUDE.md or CLAUDE.local.md when the flag is false, and to the project's auto-memory with a MEMORY.md line when it is true; never to the global config.",
        ],
    },
    "references/config-writing-standard.md": {
        "mission": "Every line of this config tells the reader what to DO, so a rule read once is a rule applied.",
        "purpose": "The one standard for how every rule, reference, skill and contract line is written.",
        "criteria": [
            "Schedule the contract suite once after the complete config batch and review fixes converge; defer evidence reuse and failure reruns to the shared testing policy.",
            "Mandates DO-led instructions, a DON'T only where the wrong behaviour is the tempting "
            "default, and the WHY in one clause. Anthropic's own guidance is that affirmative framing "
            "outperforms prohibition, so a mirror-image DON'T on every DO dilutes the ones that matter.",
            "Requires every rule to state its DEFAULT, its NUMBER, and the TEST that catches a "
            "violation. A rule with no test is a topic, not a rule.",
            "Carries the banned hedge-word list that config-contract.test.py enforces. Each banned "
            "word hides a missing number; the fix is the number, never a narrower check.",
            "Defines a mission as an OUTCOME that can decide a diff, distinct from `purpose` which "
            "states what the part is.",
            "Bans re-explaining a config part the file already references or that self-describes: name "
            "it once, no behaviour gloss. TEST: every named part appears without a description and once.",
        ],
    },
    "references/contracts-and-outcomes.md": {
        "mission": "An edit cannot silently destroy what a unit exists to produce, even when every test still passes.",
        "purpose": "Declaring what a unit produces so an edit cannot silently destroy it.",
        "criteria": [
            "Assert the artifact, not that a mock was called.",
            "Names a personal project as the reference implementation rather than duplicating it.",
        ],
    },
    "references/dev-server-hygiene.md": {
        "mission": "Several sessions run their stacks at once, and none leaves a process or a held port behind.",
        "purpose": "Starting, identifying and tearing down dev servers without leaking processes.",
        "criteria": [
            "Apply the shared verification timing policy; resource admission never creates a per-file or per-worker test obligation.",
            "Classify one bounded browser inspection or focused smoke check separately from heavy batches; run it through ordinary supervised admission, which reads CPU only. Keep full builds, suites, stacks, ownership, connector and spend boundaries on their existing paths.",
            "Track and stop every started process; retain explicitly requested previews only through their bounded owned lifecycle. Verify identity before trusting logs.",
            "Route iOS simulator execution to references/ios-simulator.md without duplicating its preflight, preview evidence or recovery procedure.",
            "Require explicit positive pass_fds and inherited environment at every Python stage-launch boundary; never bypass bridge validation or create nested leases.",
            "Own the machine-wide capacity protocol: three heavy leases, one simulator, the stack cap and idle-stack teardown, the CPU/load guards (memory never gates), the watchdog, the Simon-granted priority record that passes no cap, explicit runner limits, auto-release of only provably dead leases, and reclaim-sim only for an ended simulator owner. Simon's \"prioritise\" or \"don't defer\" is served by prioritize, never a bare heavy command; every heavy step holds a lease; a watchdog line naming this session is acted on at once.",
            "Cap Swift whole-module compiler threads separately from build jobs with SWIFT_USE_PARALLEL_WHOLE_MODULE_OPTIMIZATION=NO; verify installed support and emitted -num-threads 1 without a later larger override. Preserve capacity admission, watchdog and ownership safeguards.",
            "Web runners start at two workers, Playwright included (--workers=2, since its default is half the logical cores); a scripted Playwright run closes each context after its batch.",
            "Session workers inherit priority by checkout ownership and share its canonical lease owner; an Agent-tool worktree inherits it only through its subagents transcript under a listed checkout's projects slug, and an unknown ownership probe grants no priority without failing admission. Keep simulator claim/release labels consistent; name every native simulator, stop through the supervisor, and inspect status after exit 75.",
            "A restart stops the launcher's process group, confirms zero listeners, and confirms the new listener started after the stop.",
            "A wait on a background job uses its PID, a done-file or the harness completion notification; never pgrep -f for a pattern the waiting command contains.",
            "A script running leased steps stops at exit 75 and reports it deferred, never pass; no later step reads a deferred step's output, and the lease is called through a function or array.",
            "After every start or restart, one end-to-end request through each external dependency and a read of its log for a refused credential precede any hand-over; the identity handshake alone is not enough.",
            "A billable dependency is proved with a free authenticated call unless Simon gave that call its yes; a 401 or 403 is a key-source fault fixed before hand-over, never a reason to blank the key.",
            "Port preflight checks BOTH the shared registry and the machine. Owns the cross-session "
            "protocol; bin/port-registry.sh implements it.",
            "Every native build, test and simulator lifecycle uses bin/local-capacity.py or its "
            "bin/native-slot.sh compatibility frontend; failed admission defers heavy work, "
            "and bounded cleanup touches only the recorded simulator.",
        ],
    },
    "references/ios-simulator.md": {
        "mission": "Simon receives the requested simulator preview or test evidence without stale artifacts, unowned devices or leaked services.",
        "purpose": "Shared iOS simulator preflight, execution, preview hand-back and recovery playbook.",
        "criteria": [
            "Compose existing capacity and testing owners; preserve native opt-in, worker limits, stage deadlines and runtime signing policy without duplicating them.",
            "Run simulator work through the project's one recorded recipe (build once, one headless device, launch with documented environment, XCUITest to a named screen, screenshot, shut down) with its measured duration; without one, a spike of at most 20 minutes creates it first.",
            "Stop after one failed boot, install or launch and report it; reuse the built app and xctestrun; at most one boot per device per task; every xcodebuild test passes -collect-test-diagnostics never.",
            "Boot headless; open the GUI only when Simon asked to look. Shut down and release the claim at the end of every simulator step batch and at hand-back unless the very next step needs the device; never leave one booted with no lease; a device left booted for Simon is named with its shutdown command.",
            "Keep ONE persistent warmed simulator named agent per machine: find it by name before any boot and reuse its UDID; create it only when absent as agent-warming, warm it (Siri & Search off, wallpaper set once through Photos), then rename it agent. Shut it down and release it at task end, never delete it; a project handover that says delete your simulator yields, and only one-off devices are deleted.",
            "Identify macOS crash dialogs from simulator system daemons by a DiagnosticReports procPath under the simulator runtime, report them once as Apple simulator bugs distinct from the app's own crash, never churn reboots over them, treat shutdown SIGTERM_TIMEOUT reports as expected, and offer a machine-wide ReportCrash disable only as an option needing Simon's explicit yes.",
            "Never run AXe on a device with a live XCUITest run; an AXe tap uses --post-delay and a changed-screen check.",
            "Preflight effective DEVELOPER_DIR, selected Xcode, runtime, explicit UDID, matching app artifact, backend identity and requested GUI before boot; discover installed capabilities without global switches, automatic installs or unbounded searches.",
            "Bind successful test-product builds to one absent export destination, exact bundle path and final executable hashes. Reject ambiguous nested outputs before runtime; a source annotation alone never establishes binary provenance.",
            "Discover Device Hub and legacy Simulator read-only under selected Xcode; open the GUI only inside admission after owned boot readiness. A missing GUI name never establishes that its runtime is missing.",
            "Run GUI discovery and the capacity status before any native launch, a repo script included; a script that assumes one GUI layout is fixed, not worked around in the invocation.",
            "Launch through the project's own launch script when one exists; a bare simctl launch passes every option and variable the project's configuration declares.",
            "Claude opens the simulator GUI itself and navigates and captures every screenshot, with XCUITest as the proven default and AXe only after a recorded changed-screen check (its Xcode 27 tap no-op is dated, root cause unclaimed); Simon is never asked to open the simulator or tap, and the receipt records the driver.",
            "Every xcodebuild test of the app target (unit tests included, since the host app's startup calls the network) and every simctl launch passes the project's backend override explicitly (SIMCTL_CHILD_ or TEST_RUNNER_ variables, never the scheme), using a closed loopback port when no local stack runs; a UI test refuses a non-loopback URL; against a local stack, see the app's first request in the local log before any sign-in, and wipe prior app state with uninstall plus keychain reset on the owned device.",
            "Keep one foreground lease through fail-fast stages and viewing; separate process launch, simulator-screen evidence and desktop GUI evidence, reporting permission gaps without changing permissions.",
            "An interactive preview is ready only with a window screencapture showing the device screen within 60 seconds of boot readiness; otherwise it is reported not visible with simctl captures, and a delegated worker returns that capture path.",
            "Bound requested preview retention with a local owner/device/app/service receipt, absolute deadlines and exact stop/restart commands; verify owned Shutdown before release and retain caches.",
            "Diagnose toolchain, boot, descriptor, signing, artifact, backend, overload, incomplete-result and discovery failures; fixture UI never proves native-service or live-backend correctness.",
            "Require explicit scoped authorization and no competing simulator, physical-device or debug activity before shared-service recovery; never reset shared services automatically at hand-back or bypass ownership locks.",
        ],
    },
    "references/git-pr-deploy.md": {
        "mission": "A commit is navigable a year later, a set of PRs merges and deploys in either order with no outage, and a deploy is verified working, not assumed working.",
        "purpose": "Commit shape, PR hygiene, pre-merge deploy safety, live release preflight, and verifying a deploy actually worked.",
        "criteria": [
            "Owns never-`-m`-always-`-F` and the conventional subject standard.",
            "Owns the review-branch push procedure (fetch, merge in remote commits, plain push, one-line sha report) and the gate on every other PR or remote operation.",
            "Follows the repo's own merge method; after a squash, rebase or cherry-pick the hand-back names the leftover source branch and its deletion gate result.",
            "A commit is chained after its checks with &&, never ;, so a failing check stops it.",
            "Reuse recorded cleanup authority; prove the exact tip through refreshed default ancestry, merged-PR-head containment with reachable merge commit, or full content proof before branch -D. Recheck tip and ownership; being fully pushed never substitutes for merge proof.",
            "Owns config completion: inventory refs, validate dependency updates, preserve active/protected/blocked work and compose the shared task-owned ref-only closure.",
            "Allow authorized task-owned current ref retirement in any repository at unchanged detached HEAD with entire-tip proof; preserve workspace files, registration, app lifecycle and foreign sessions. Create a fresh branch before further edits.",
            "Refresh each actual remote counterpart tip, prove its disposition and bind authorized deletion to that SHA; retain moved refs rather than renewing a lease without renewed ownership and merge proof.",
            "Shipping is not done at merge; the deploy is watched and looped on.",
            "Owns CI timing: a work PR stays draft with CI off until merge prep; a failing run finishes first, every failed job's log is read at once, fixed in one batch, the local gate list rerun, then one push.",
            "After any production deploy, hand-back needs the deploy run for the merge sha passed (not skipped), production serving the new build, and the read-only Deploy TLDR smoke passed, reported with evidence and the rollback line on failure; only a device or account step only Simon has is handed to him.",
            "Owns deploy safety: a local merge train of the default branch plus every dependent or overlapping open PR in merge order, affected suites run once, conflicts fixed on the owning branch, never only on the train.",
            "Each migration records its number above every open PR's, the pipeline's real apply order, compatibility with live and new code under either deploy order, and its backfill reach counted read-only on production.",
            "Each data-rewriting migration records its runtime measured read-only at production volume against the pipeline statement timeout read from the repo; at half the timeout or more it is batched before merge, never given a raised timeout.",
            "Require complete paginated PR/file inventories with stable base/head SHAs and matching file counts, or complete verified Git diffs, before reserving sequential numbers; API failures, caps and moving refs never prove availability.",
            "A live-traffic move is mapped from the provider's read-only API, gated on its prerequisite confirmed live, one step at a time with a rollback; the deploy alone moves no traffic and no provider write runs without a per-write yes.",
            "Before changing an external value shipped clients read, grep the clients for hard-coded checks; on a hit, a release accepting the new value, or a new key keeping the old live, ships first.",
            "Owns the batch-merge method: merge queue when enabled, else one batch PR that merge-commits "
            "each PR head unchanged and merges with a merge commit, so originals show merged.",
            "A CI wait resolves its run id from the head sha's check runs, never by branch or workflow listing, and exits non-zero on an empty id, failed run, unknown state or timeout.",
            "After an authorized push or ready-flip, read the PR's merge state and confirm within a minute a CI run for the head sha is in progress; no run is a failure to investigate, and a run queued behind a superseded one is cancelled. Run the repo's ordering checks before pushing a base merge.",
            "Owns the shared-branch force-push rule: check for a competing sweep before a ship or rebase sweep, pin --force-with-lease to the SHA this session last fetched or pushed (never one read from the remote in the push step), and stop when git log <pinned>..origin/<branch> lists a commit this session did not write.",
            "After merging the base: reinstall dependencies, re-download test browsers, compare applied migrations with the files by name and number, and read git status for tool-rewritten files before the next commit.",
            "Require timestamped current provider identity and version/channel eligibility before release packaging; unknown eligibility stops archives/uploads, not independent local work. Reuse applicable fresh provider evidence without requiring duplicate access.",
            "A build number named in a ticket is an example: read the highest uploaded identifier (the store's API, else ask the user once) before the archive starts and build the next.",
            "Check Apple approved/submitted versions and candidate train state; recheck after resume or candidate/target changes and before upload. Require live manual identifier checks or documented automatic allocation with the actual distribution receipt.",
            "Points to references/ticket-lifecycle.md for the ticket to branch to PR lifecycle; does "
            "not own it.",
        ],
    },
    "references/ticket-lifecycle.md": {
        "mission": "A tracker ticket is never left behind its code: it goes In Progress at the start of any task that touches it, and the branch, PR, and status stay in lockstep to the merge.",
        "purpose": "The ONE owner of the ticket to branch to PR lifecycle; skills and references/git-pr-deploy.md point here rather than restating it.",
        "criteria": [
            "Owns the routine: In Progress on start, branch named from the ticket code plus a title slug, PR title matches the ticket, ticket link in the PR body, status kept current, only delivered tickets linked.",
            "The routine applies on any task that carries a ticket, not only a build or ship one.",
        ],
    },
    "references/human-pacing.md": {
        "mission": "A human driven through a manual sequence always has exactly one action in front of them and knows it is their turn, so a paced flow never becomes a wall of steps they lose the thread in.",
        "purpose": "The shared contract for pacing a human through a manual multi-step flow, one step at a time.",
        "criteria": [
            "The plan lives in a file; chat gets one action per message, never the whole plan.",
            "Every step carries a progress count and signals the hand-off as the first action of a "
            "blocking response.",
            "Every step names the surface the human acts in (a browser tab by title and host).",
            "No edit lands in the tree the human's dev server serves while they walk; a fix is built elsewhere or held and applied at a step boundary after telling them the tab will reload.",
            "A surface handed to the human is theirs alone until they reply: Claude only reads it, and any follow-up action there is announced as its own step first, never run while their step is open.",
            "Owned here; /sk:test-copilot and /sk:work-hyperspeed point to it and do not restate it.",
        ],
    },
    "references/progress-bar.md": {
        "mission": "Simon always knows how far along a run is — overall and inside a sub-process — from one line, without asking.",
        "purpose": "The one convention for showing progress: a plan-derived Task list, a compact text bar, and nested sub-progress.",
        "criteria": [
            "The harness Task list mirrors the gauntlet plan (one task per stable item); a compact ▓▓░ N/M · "
            "now:X bar is echoed alongside it, each response and each poll tick.",
            "A sub-process shows its own nested bar under the main one; both update the moment a step "
            "changes state, not at the end.",
            "Owned here; /sk:meta-dotclaude-copilot and /sk:work-hyperspeed point to it and do not "
            "restate the format.",
        ],
    },
    "references/parallelization.md": {
        "mission": "Independent work runs at once without two agents touching one file, and every delegated edit is verified on disk.",
        "purpose": "Fanning work out across agents without collisions or lost edits.",
        "criteria": [
            "Inspect delegated diffs on disk without routine test execution; no per-feature, per-commit or per-worker-batch checks override the shared policy.",
            "Own setup persistence and model consistency: the top tier orchestrates on either provider, Fable designs, the mid tier resolved live at dispatch implements, all by tier with no pinned version; scope historical Claude benchmarks honestly.",
            "A subagent spec is self-contained and carries an explicit DO-NOT-TOUCH list.",
            "A brief numbers its required outputs and the hand-back answers each with evidence or a reason before acceptance; an unverified cause is written as a hypothesis with its confirming check.",
            "A dispatch prompt names the one device, port or path a worker may touch, by id, and never the machine-wide form.",
            "Never trust a subagent's self-report; verify on disk.",
            "Give each independent deliverable its own isolated worktree worker in parallel; the orchestrator edits no product code, checks head, clean status and owned-file diff on disk, and captures the screen itself.",
            "Send fixes as numbered file:line rounds to the same resumed worker; answer worker questions with the recommended option recorded as a decision, asking Simon only for product or data decisions.",
            "Give each finished deliverable a fresh reviewer briefed with the diff range and risk checklist, never builder conclusions; each verified finding returns to the builder as one commit with a regression test.",
            "One planner, flat leaf workers. No middle tier.",
            "Resolve each install, build and test runtime inside its actual child directory and shell before starting the batch.",
            "Default to one heavy verification batch per session; the machine admits three leases, so record the shared resource budget, worker cap and process ownership before overlapping heavy checks.",
            "Native build prompts name the shared capacity engine or its compatibility frontend, a bounded stage and explicit worker cap; a per-run lock file is not the coordination.",
            "Run local-capacity.py cpu before any parallel dispatch; DEFER means serial or wait, and GO admits at most the free heavy slots of workers that build, test, boot or run a stack.",
            "A prompt for a worker that builds a visible screen names its design source, measured spec, target images and capture command, and its hand-back carries the measurement report; it never defers capture to the orchestrator.",
            "Under a priority or full-capacity ask, launch every stage that needs no running stage's result in one batch, up to the free heavy slots and the 10-agent cap, and refill as stages end; a status message never replaces a ready launch.",
            "Split a serial-resource editing lane only when measured critical-path evidence supports it and the added workers fit both the total worker cap and shared heavy-work capacity.",
            "Freeze the contract and fixture before dispatching every layer together; workers return once with changed files and a check inventory, and the orchestrator owns final verification under the shared batch policy.",
            "Assign changed callers, fixtures and persisted transitions to a worker or reconciler; refresh after rebase and check omission, clear, failure, retry and the next request before the whole-package gate.",
            "Owns the shared self-improvement loop for a parallel run (cause taxonomy "
            "slice/late_scope/reconciler/planned_wiring, analyse-every-run, evidence-backed repair, plus harvesting each "
            "worker's friction + timestamped log to self-diagnose the bottleneck and improve in two tiers "
            "— auto next-round, durable repairs routed through the scoped repair policy); superspeed and hyperspeed point to "
            "it, not restate it.",
            "Reuse shared dependency build caches for needed setup or permitted verification; never share node_modules across worktrees. Keep project build recipes in allowed project guidance.",
        ],
    },
    "references/planning-and-tracking.md": {
        "mission": "Simon sees the whole shape before work starts, and no ask is silently dropped between the plan and the hand-back.",
        "purpose": "Plan first, track every ask, verify foundations, scope a feature fully.",
        "criteria": [
            "Names the durability tiers — the ticket outlives all, .context/ survives a restart but "
            "dies with the worktree — and promotes decisions and human input to the ticket before teardown.",
            "A feature is scoped across discoverability and docs, not just its mechanism.",
            "Every plan opens with BOTH the user journey AND the system journey (a ticket and PR body "
            "too), above the technical detail, reflecting the plan's current trajectory (confirmed "
            "decisions + recommended defaults for open questions) and kept in sync on every change. The "
            "format moved to references/tldr-report-formats.md Blocks 1+2; this file owns when it is "
            "required, not what it looks like.",
            "Every ticket the plan names is a full clickable Linear link, never a bare id.",
            "A plan is reconciled against the original tickets after EVERY revision, and a "
            "pre-existing ticket gets a verdict against today's real code before it is scheduled.",
            "Every proposed check lists its prerequisites from the code and the provider, each confirmed found or missing, before any time estimate or any ask for an input.",
            "Every out-of-code surface the work touches (edge/CDN, a design tool, a third-party "
            "console, a dashboard) is asked for before the plan, and each ticket names the inputs "
            "its implementer must obtain, including a visible change's design source path, board ids "
            "and measured spec path, with no board value restated in ticket prose.",
            "The plan states the business goal in one line; every rule decided during the work carries a "
            "sentence on how it serves that goal, and a rule that reduces it goes to Simon before it is built.",
            "Before a ticket goes to a build, every decision it depends on is resolved INTO the ticket "
            "(the option chosen plus a one-line why) and every requirement is present, so a builder that "
            "cannot ask — a cloud session, a parallel part, a teammate — misses nothing and guesses nothing.",
        ],
    },
    "references/production-monitoring.md": {
        "mission": "A daily health check flags real regressions in conversion, capacity and errors and stays quiet on noise, so Simon acts on every red row.",
        "purpose": "The daily pulse's method, vendor-sourced thresholds, monitor block schema and triage table.",
        "criteria": [
            "Cover traffic, errors, saturation and latency plus the business funnel, symptoms first, and read every log source.",
            "Compare with the same weekday on the previous 4 weeks; logs with the previous 24h; short-retention tables against stored snapshots.",
            "State each threshold with its primary source: SRE book, NIST, Datadog, Supabase Detecting issues, RevenueCat.",
            "Document every monitor block key and metric kind, and require each metric to return a row read-only before it is saved.",
        ],
    },
    "references/research.md": {
        "mission": "A claim about anything outside this repo comes from a primary source, so Simon never ships a fact that a competitor can disprove.",
        "purpose": "The opening research pass, its source order, and source-stake discounting.",
        "criteria": [
            "Read at the START of a workflow run, not on demand like the other catalogs.",
            "Community write-ups find candidates and are never cited.",
            "A staked recommendation is corroborated against an unstaked source before use.",
            "An external or not-ours verdict names the runtime identifiers it was compared against.",
            "Holds the third-party claim rules: primary sources, every vendor surface before a negative, dated arithmetic, no competitor hyperlink, concede an honest loss.",
        ],
    },
    "references/skill-stack.md": {
        "mission": "The right skill is reached for on the first attempt, without Simon naming it.",
        "purpose": "Maps a task shape to the right skill, and what genuinely stacks on it.",
        "criteria": [
            "Sole home for that mapping; skills do not restate it.",
            "Every pack in the adoption table cites a verified star count and a date.",
        ],
    },
    "references/testing-strategy.md": {
        "mission": "The suite proves the thing works and spends nothing doing it.",
        "purpose": "Test structure, production compatibility gates, local time-driven simulations, production-data preview fidelity and the no-billable-calls guarantee.",
        "criteria": [
            "Verify runtime admission, limits, validation, authorization and retention against current legitimate production cohorts even without displayed figures; keep unknown telemetry distinct from zero or pass.",
            "Replay actual client payloads through real isolated gates, measure headroom and combined shared budgets, and preserve source privacy, production write authorization and paid-call approval.",
            "Separate code verification, activation dependencies and live proof; scope conclusions to captured populations and windows without promising zero regressions.",
            "Own the Light, Standard and Deep verification tiers: classify from the diff before any check, take the deeper tier when unclear, escalate on an unexpected finding, and record tier, trigger and skipped stages on the PR and gate.",
            "Every tier keeps CI, required hooks, the project gate list, PR feedback handling, read-only production, spend approval and the post-deploy prod check; a Deep trigger always gets the full harness.",
            "Re-read the CI gate list after every base merge or rebase, and run it in one pass over CI's own scope, secret scan included, before the ready-flip that starts CI.",
            "At merge prep, before a ready-flip, enqueue, merge or deploy, re-derive the list with ci-gate-list.py on the final head and run every row locally, leased; record each mirrored row and each skip reason.",
            "Derive the CI gate list from the workflow files with bin/ci-gate-list.py, one row per pull-request run step; each skipped row, a CI-only container step included, names its reason.",
            "Treat every authorized feature and review fix as one batch; write tests early, then execute distinct relevant suites once after review and gap fixes converge.",
            "Allow mid-batch targeted diagnostics only for a recorded concrete issue or explicit user request; preserve required hooks and CI.",
            "Reuse passing local or CI evidence only with matching relevant source, dependencies, configuration and environment; record command, scope and proof, and run uncovered checks.",
            "Fix final-gate failures and rerun affected checks; broaden only when changed inputs invalidate coverage, and never count partial or skipped scope as a full pass.",
            "Require explicit native opt-in for iPhone/iOS simulator runtime tests, UI tests and screenshots; generic all-tests or full-matrix requests do not qualify. Keep compile-only native checks and backend payment, auth and data tests.",
            "Judge test design before final execution; fan out preparation and judgments, deduplicate suite runs, and report unrequested native runtime coverage as skipped.",
            "Keep production export credentials outside the preview runtime; reject production destinations before creating write-capable clients and verify the refusal offline.",
            "Preserve source dates and record persisted-source or recomputed mode; require complete inputs for post-refresh claims and verify API and visible values against the selected mode.",
            "Retain the requested local preview with a working URL and scoped stop/restart commands; stop exporters and unrelated workers.",
            "Keep review judges on the selected workflow setup through the shared parallelization protocol.",
            "Assess simulation applicability per feature; exercise relevant real application/database transitions with controlled clocks, isolated data and zero external requests, or record a concrete N/A reason.",
            "Assert exact per-entity outcomes beyond changed page and batch limits; cover applicable eligibility, event-order, fairness, concurrency, lease, retry, ambiguous-provider and idempotency timelines without requiring a full cross-product.",
            "Make mock failures observable outside application catches; drain complete scans under explicit bounds, record reproducible seeds and evidence, and disclose provider races and unsupported runtime semantics.",
            "Reproduce a reported bug on unchanged code under the user's engine, runtime and production-shaped data before the fix, with at least 1 control that passes there; both pass on the fix, else report it unproven.",
            "Own the regression check, kept at every tier: list each modified, renamed or removed pre-existing file, trace its hunks to existing callers, and prove outside paths with a test passing on base and head or a base-vs-head screenshot pair compared by design-diff and measured control positions; a wanted change is stated INTENDED.",
            "Compare an existing screen rendered in a new place with its original place by measured control top, bottom, distance to the viewport bottom and container scroll height; above 2 CSS px is a finding unless stated INTENDED.",
            "Post the regression check under ## Regression check: one row per modified pre-existing file with PASS or INTENDED, one row per newly mounted shared part naming its mirrored caller; green unit, type or e2e suites never prove a rendered path.",
            "A full suite run triggers zero billable API calls.",
            "Never-must-escape calls are mocked globally in setup, not per test.",
            "Time every new or changed time budget on a read against production, read-only, before release; record the measured figure beside the constant, and a budget under 2x that figure is a finding.",
            "Tie every coverage verdict to the source revision, collection directory and complete test invocation; partial reruns diagnose failures without replacing full-run coverage.",
            "After explicit native opt-in, prove required platform services with the runtime app, signing and simulator configuration before the suite; isolate defaults, authentication, singletons and host state.",
            "Route simulator execution to references/ios-simulator.md; unsigned compile evidence cannot prove Keychain runtime behavior. Use project-supported signing and existing entitlements without weakening product authentication or requiring signing for every test.",
            "A full native suite waits for the bounded runner to finish and verifies its exit, final result and expected test scope; a nested suite line or timed-out runner cannot establish green.",
            "Redirect a run expected to exceed 5 minutes to a log file and read the file; rerun native failures by class and run the full suite once at convergence; ask for the native capture opt-in at intake when a design source covers native screens.",
            "List the project's CI gate commands at intake, run each gate under 2 minutes once on the untouched branch, and run the whole list before the first push; never learn a gate from a failed CI run.",
            "Report executed, passed, failed and skipped counts per test class; zero executed is not run, never a pass.",
            "Trace a check's side effect back to its entry point in the mode it runs in before running it.",
            "Own the live-variant check: before a walk, review or capture of a journey dealt per person, read production's arms and 72-hour shares as aggregates, report stopped and missing arms, and walk only a live arm unless Simon names another.",
            "Before step 1 on each platform of a human walk, print the arms the local server dealt this device beside production's; copy production's split settings locally when they differ, and send no step until they match or the difference is stated.",
            "Before step 1 of a human walk, preflight production parity: key source, dealt arms, new-account enrolment, launch scripts, PR heads and the first steps; never blank or fake a key or flag; list remaining gaps once.",
            "On a simulator walk the agent performs every relaunch (terminate, launch with the local server address, screenshot) and the tester's step starts from the confirmed screen; never tell him to reopen the app.",
            "A human's default walk starts at the real entry with a fresh account; a state is seeded directly only past 15 minutes of walking and is labelled; Claude loads step 1's address in his starting state first.",
            "Claude runs every later step in its own browser from his state and sends it only when the Expect screen appears; an account he may be signed into is never deleted or reset, and a reset step is one storage-clearing line plus the next URL.",
            "With a human re-walk pending, order fix, quick local checks, fresh-seed rebuild, his re-walk, then the red tape; no video, CI wait or PR evidence step precedes a passing walk. test-copilot and the ship harness point here and restate none of it.",
            "Each forced test state records the ids it wrote, removes exactly those, reads the count back and states it.",
            "The journey matrix of an account feature includes signing in on a second browser or device with empty storage; device storage never stands in for a server-owned fact.",
            "A pay path is reported safe only with one row per account state that can reach a pay button: the server's precondition read and the production press-to-session rate; presses with no sessions is a finding.",
            "Exercise real-client recovery at final verification within the platform opt-in policy; verify visible, operable recovery at the smallest viewport and largest text, or report native runtime coverage skipped.",
            "Resolve project-instruction policy first. When allowed, discover test commands in CLAUDE.md, then CLAUDE.local.md, then a playbook if present; when ignored, use source and executable config.",
            "An unprepared checkout's failures are not a test baseline. The project's one-time "
            "setup runs FIRST, however late in the work the run happens, because an uninstalled "
            "tree fails exactly like broken code and recording that as the starting state silently "
            "blocks every verdict that depends on it.",
        ],
    },
    "references/tldr-report-formats.md": {
        "mission": "Simon reads one report and knows what changed, what to do next, and where it might be wrong.",
        "purpose": "The shape of the three human-readable blocks: user journey, system journey, "
                   "changes on this branch.",
        "criteria": [
            "Sole owner of every block SHAPE. planning-and-tracking.md, pr, end-report and "
            "full-detailed-workflow point here and never restate a format.",
            "Owns shape only. rules/copy-quality.md keeps the writing standard and the Five Ws "
            "check; rules/communication.md keeps where questions go and the human-facing message "
            "rule, with its example and WHYs held here.",
            "§ Message for someone else owns the shape of a message to anyone but Simon (ask on line 1, at most 5 lines, no preamble or closer), how a draft for Simon is shown, the --check pre-send step for routes the hook cannot see and the one-shot length override.",
            "The system journey carries where the flow can stop EARLY and what the user sees when "
            "it does. A silent stop is invisible in the user journey and is the defect this catches.",
            "The two journeys are cross-checked and every mismatch is stated. Printing both and "
            "comparing neither is the failure mode, because the comparison is the whole point.",
            "Every block passes the glance test: real names, one line per step, no rediscovery, "
            "and something the reader can act on at the end.",
            "A change that touches or opens a payment path hands back Block 4 unasked: the payment "
            "files changed (or `none`) and a row per paywall entry with what follows paying and its one check, plus a row per account state with its precondition and production press-to-session rate.",
            "Every PR body opens with the before/after TLDR: 3-5 table rows with the changed value "
            "bold, then one **Do:** line naming the action and the fact that makes it safe or risky; "
            "under 60 words, no prose.",
        ],
    },
    "references/user-journey-review.md": {
        "mission": "A flow is judged by someone meeting it cold, so a dead end is found before a user finds it.",
        "purpose": "How to judge a flow as the person meeting it for the first time.",
        "criteria": [
            "Sole owner of the journey METHOD. review-all, eyeball and copilot-testing point here "
            "and do not restate it; planning-and-tracking.md keeps the PR TLDR format.",
            "Judges the journey as a user meets it, not as the code is organised.",
            "Empty, loading and error are checked on every surface, and the wait is a stage in its "
            "own right. Those are the three an AI-built flow ships without.",
            "Sends a flow that differs per person or device to the live-variant check in testing-strategy.md and restates none of it.",
        ],
    },
    # --- Simon's own skills --------------------------------------------------------
    "skills/sk/skills/maintenance-code-cleanup-repo/SKILL.md": {
        "mission": "Dead code and drift leave the repo for good, verified gone rather than reported gone.",
        "purpose": "Repo cleanup as audit, adversarial verify, fix, re-verify.",
        "criteria": [
            "Verify claims before deletion; record existing baseline evidence and schedule build and test execution at the final gate under the shared policy.",
        ],
    },
    "skills/sk/skills/test-copilot/SKILL.md": {
        "mission": "Simon's own eyes catch the journey defects a green suite cannot, one paced step at a time, with the cause already diagnosed from the logs.",
        "purpose": "Paces Simon through a real user journey while watching instrumented logs.",
        "criteria": [
            "Machine-checkable defects are fixed before his session starts.",
            "Paces Simon per references/human-pacing.md (one action per message, progress count, "
            "signal the hand-off); does not restate it.",
            "Seeds up to the new UI, never through it. Every input the change adds is Simon's to "
            "type, because a field he never filled is a field neither of them has verified.",
            "Claude drives every step except new inputs, on web and native; zero-new-input walks send Simon no step to perform.",
            "Narrates each step before acting and queues comments as findings without pausing, except blockers.",
            "Cites rules/communication.md for the general writing rules; does not restate them.",
            "Proves the human is on the watched server (his first request in the log, the host to expect "
            "named) and halts when a step's expected request is absent; gates payment on a test-mode "
            "session id; binds external-provider forwarders to the app's own credentials with matching "
            "account identity; reconstructs steps he skipped. Method lives in testing-strategy.md.",
            "Sends a finding needing a visual or design decision to the design route for an approved target before the mid tier implements it; builds fixes outside the served tree during the walk.",
            "Runs /sk:test-automated-full-matrix for its machine pass (Phase 2) rather than restating "
            "the automated method; the two skills are distinct (human journey vs autonomous matrix).",
            "Before the walk and unasked, reports the arms production deals now per platform, stopped and "
            "missing arms included, and pins the walk to a live arm named in the charter. Method lives in testing-strategy.md.",
            "Starts the default walk at the real entry with a fresh account and the lead-up, labels each "
            "directly seeded state, and runs each step itself in the human's state before handing it over.",
            "Reads the project's testing guide as task data (asking once when project instructions are ignored) and runs the dependency handshake after every stack start or restart; method lives in references.",
            "Bypasses only what Simon picks at scoping; the rest of the stack stays production-equivalent per testing-strategy.md.",
            "Runs visible web walks per browser-debugging.md, including zero-new-input walks; captures each step after its action or Simon's new input, never asks for pasted screenshots or touches another session's tab.",
            "Keeps one walk surface and closes every tab, window and launched test browser it opened at the end of each walk (teardown checklist); the rules live in browser-debugging.md.",
            "Reads references/ios-simulator.md before booting a simulator for a native walk; Claude opens the GUI, "
            "drives the app and captures each step itself against an explicitly passed local backend override, and Simon types only the inputs the change adds.",
        ],
    },
    "skills/sk/skills/test-automated-full-matrix/SKILL.md": {
        "mission": "Every feature a finished diff added ends with a verdict — a written test and a "
                   "Claude-judged read against its intent and a user's eyes — posted to the PR, with "
                   "no human in the loop, so a diff can be tested exhaustively while Simon sleeps.",
        "purpose": "Autonomously runs the full two-stage automated test matrix over a diff/PR: Stage-1 "
                   "deterministic tests (writing the missing ones), Stage-2 Claude-as-judge, saved and "
                   "posted to the PR.",
        "criteria": [
            "A harness runs it only on a Deep-tier change under testing-strategy.md and records a skip line otherwise; Simon's direct ask runs it at any tier.",
            "Runs AUTONOMOUSLY — no AskUserQuestion, no human step — so it is safe to leave overnight; "
            "distinct from /sk:test-copilot, the human journey, which runs THIS for its machine pass.",
            "Enumerates EVERY feature in the diff (git diff + plan criteria + Linear) as a matrix row; "
            "a feature with no row is a hole. Covers the whole diff, never samples down.",
            "Prepare deterministic coverage and independently judge every feature before final execution; the coordinator deduplicates suites, reuses valid proof and runs uncovered checks under the shared policy.",
            "Report covered, gap, needs-driving and skipped counts; generic matrix invocation never opts into native runtime, UI tests or screenshots, and unrun cases never count as covered.",
            "The METHOD lives in references/testing-strategy.md; this skill points at it and does not "
            "restate it. Fans out via /sk:work-hyperspeed.",
            "Include simulation applicability and evidence for each feature under testing-strategy.md; required but unrun cases remain explicit gaps or skips, never N/A or covered.",
            "Saves the matrix and POSTS it to the PR's tests section, GitHub-native.",
            "Bind every copied value in the diff and its stacked or sibling PRs to its source, and walk every changed state on the real local stack, judging each recorded source criterion from screenshots, requests and rows.",
            "Inspect screenshots at each meaningful step, correlate actions with requests, responses and persisted state, fix observed bugs and rerun affected scenarios; captured images alone never prove the walk.",
            "The real-stack walk also covers each existing screen a modified pre-existing file reaches and each screen reused in a new place beside its original, feeding the PR's regression check.",
        ],
    },
    "skills/sk/skills/work-does-this-make-sense-to-build/SKILL.md": {
        "mission": "Work not worth building dies before it is built, with the evidence attached.",
        "purpose": "Decides whether proposed work should be built at all, part by part, on evidence.",
        "criteria": [
            "Proposes, never builds. Read-only: no prod writes, no ticket edits, no posted comments.",
            "Splits the proposal into separately-decidable parts and verdicts each one independently. "
            "Killing one part while building the others is the useful outcome, and judging the ticket "
            "as one lump hides it.",
            "Each assumption is written as a claim that could be false, with its refutation test "
            "chosen BEFORE the research starts. Otherwise the pass collects supporting quotes.",
            "Refutes on facts only. A judgement call is handed back as DECIDE with a recommendation, "
            "never refused on the model's taste.",
            "Unverified is distinct from refuted. No evidence found is not disproof.",
            "Manufacturing objections fails this skill as hard as agreeing by default; a ticket that "
            "holds up gets three lines and a plain yes.",
        ],
    },
    "skills/sk/skills/work-investigate-and-fix/SKILL.md": {
        "mission": "A pasted production alert ends as a shipped, deployed fix that measurably helps users, or as a corroborated verdict that nothing needs fixing.",
        "purpose": "Front door for production alerts and error reports: verdict per symptom, corroborated root cause, root fix, regression sweep, deploy proof.",
        "criteria": [
            "Record every symptom in the paste as its own session-record item and close each with one verdict: root-caused, already fixed, expected or needs a decision.",
            "Discover provisioned connectors before asking for access; back every load-bearing claim with 2 independent sources; keep prod read-only and paid calls under spend-approval.",
            "Call a cause a bug only after citing the commit and the ticket intent it contradicts; an external or provider verdict names the runtime identifiers compared.",
            "Reproduce each bug verdict with a control before the fix through the testing-strategy section, keep both as regression tests; fix the owning source, not the alert.",
            "Prove the outcome changed for users with denominators where authorized; a silenced alert alone is never reported as a fix.",
            "Sweep every deploy in the window with per-surface before/after rates and denominators through a read-only parallel agent; fold in-scope fixes into the same PR.",
            "Compose work-full-detailed-workflow, work-does-this-make-sense-to-build, ship-pr and ship-full-detailed-workflow by name; restate none of their methods.",
            "After merge, verify the deploy run for the merge sha and run a read-only production smoke before reporting done.",
        ],
    },
    "skills/sk/skills/plan-research/SKILL.md": {
        "mission": "A research question comes back as a ranked, cited answer that survived refutation, not a single-source guess.",
        "purpose": "Runs a research question through decompose, parallel multi-source find, adversarial verify, rank, and a cited TLDR.",
        "criteria": [
            "Splits the question into separately-answerable sub-questions and fans one parallel agent "
            "out per angle across the web AND the codebase/production data.",
            "Verifies every load-bearing claim by an independent second pass that attempts to refute it "
            "and requires a non-conflicted corroborating source; discounts a source by its stake.",
            "Ranks surviving options best-to-worst for the actual use case and cites a link behind every "
            "load-bearing claim.",
            "Sends research questions to spin-off agents; hands the user only the decisions that are the "
            "user's to make.",
            "Reads references/research.md, parallelization.md and tldr-report-formats.md; adds no "
            "duplicate copy of them.",
            "Uses an in-session Workflow fan-out when angles need WebSearch or connectors, because "
            "headless work-superspeed slices have no permission allowlist and block on those calls.",
            "Self-improves at the end via /sk:claude-config-update and proposes nothing when the run was clean.",
        ],
    },
    "skills/sk/skills/ship-full-detailed-workflow/SKILL.md": {
        "mission": "A finished PR is proven to cover every ticket and the whole diff — each criterion "
                   "backed by a committed test, both journeys verified, all actionable PR feedback handled — and "
                   "lands with a deploy sequence Simon can run, without him tracking which stage got "
                   "skipped.",
        "purpose": "Drives a finished PR or branch through the whole ship sequence: assemble onto "
                   "master, verify criteria + journeys with a test per verdict, multi-model + security "
                   "review, resolve threads, screenshot, meet the Deploy-TLDR standard, reconcile.",
        "criteria": [
            "Runs the testing-strategy merge-prep local gate list on the final head before any ready-flip, enqueue or merge it performs.",
            "Defer automated verification until the whole authorized batch and review fixes converge; compose the shared timing, evidence-reuse and failure-rerun policy.",
            "Composes /sk:ship-check-merge-readiness, "
            "/sk:ship-report-and-ensure-correct-user-system-journey, /sk:ship-review, "
            "/sk:ship-resolve-pr-comments, /sk:ship-screenshot-changes and /sk:ship-pr; does not "
            "re-explain them. The SHIP counterpart to /sk:work-full-detailed-workflow.",
            "Verifies EVERY ticket's acceptance criteria against the merged diff with a committed test "
            "per verdict, and fans the per-ticket verification out when it splits into 3-5+ independent "
            "tickets.",
            "Classify each PR's tier at stage 0 under testing-strategy.md and run every stage at it; a stage the tier skips records its skip line, and Deep runs every stage as written.",
            "Invoke /sk:test-automated-full-matrix and /sk:ship-verify-with-prod-data on every Deep PR in the run, in parallel and non-blocking; a Standard PR runs prod-data Phase 1; never substitute ad-hoc suites or queries.",
            "Record the landing-gate PASS only through bin/pr-landing-gate.py on each fetched PR; it owns the section headings.",
            "Run the testing-strategy regression check on every PR at every tier, Light included, on the final head, and confirm its ## Regression check rows at the landing gate.",
            "Run the matrix skill's copy binding and real-environment walk on every Standard PR too, on the final head; a Deep PR's matrix runs them.",
            "Require production compatibility coverage, unknowns and activation dependencies at the landing gate; unknown cohorts and unmet activation dependencies cannot become a compatibility pass.",
            "Consume the full matrix's simulation assessments at stage 6 and verify its evidence, concrete N/A reasons and unrun-case verdicts are on the fetched PR at the landing gate.",
            "Plan the screenshot post from the sweep start; dispatch AFTER capture once, after stages 3-6 fixes are committed and pushed, on the final head, never in stage 6's fan-out.",
            "Apply the shared native opt-in policy to screenshots; post eligible web and explicitly requested native captures with each affected scenario's own trimmed video and scenario-table row, no duplicate desktop/mobile pairs, and report unrequested native surfaces as not run.",
            "Confirm at the landing gate each main journey the PR's tier names has its final clean run under ## Verification runs.",
            "Pushes the PR's own branch to origin to sync it and never writes master; runs safely on "
            "several branches at once, each writing only its own branch and its own PR + tickets.",
            "Run references/git-pr-deploy.md § Deploy safety on every Deep PR, unprompted, parallel and non-blocking; per-PR green CI never stands in for the merge train, migration verdict or cutover table.",
            "Compose the stage-5 resolver at the final fresh-fetch gate; return new or edited unhandled feedback to resolution and affected verification before PASS, including feedback outside threads.",
            "Runs a landing gate before reconciling: the journey, the matrix with its counts, the "
            "prod-data verdict, the deploy-safety results (each on every Deep PR, a skip line otherwise), the tier line, the screenshots, zero collapsed <details> (each one open) in the fetched body_html, resolved threads, the "
            "opening TLDR and the Deploy-TLDR are confirmed on EVERY FETCHED PR, not just produced in-session.",
        ],
    },
    "skills/sk/skills/ship-merge-batch/SKILL.md": {
        "mission": "Several approved PRs reach production after one CI run and one deploy instead of N "
                   "serial update-and-deploy rounds, and no PR merges without Simon naming it.",
        "purpose": "Batches named, green PRs through the merge queue or one merge-commit batch PR, "
                   "watches the single deploy, and reports each original PR's state.",
        "criteria": [
            "Merges only PRs Simon named in chat, each with a recorded yes; the one gh pr merge carries "
            "CLAUDE_ALLOW_PR_MERGE=1 only after that.",
            "Batches only non-draft PRs whose statusCheckRollup is green on the head sha that goes into "
            "the batch; a red PR leaves the batch.",
            "Reads repo settings and never changes them; a settings change goes to Simon as a decision.",
            "Checks numbered files across the set, the base and other open PRs, and renumbers on the "
            "original PR branch.",
            "Points to references/git-pr-deploy.md for the method; does not restate it.",
            "Runs the testing-strategy merge-prep local gate list on the batch head before enqueueing or merging.",
            "Reports exactly one deploy run and each original PR's merged state.",
        ],
    },
    "skills/sk/skills/ship-check-merge-readiness/SKILL.md": {
        "mission": "Every open PR in a set, once merged onto today's master, works together — nothing "
                   "missing, nothing double-owned, every cross-owner gap tracked and flagged blocking — "
                   "and a decisive ship-ready verdict that separates code-complete from the human-only "
                   "deploy steps.",
        "purpose": "Assembles a PR and its stack onto current master, resolves every review thread to "
                   "fix / refute / follow-up, and reaches a ship-to-prod-as-is verdict.",
        "criteria": [
            "Include thread fixes before the final batch gate, reuse valid evidence, and apply shared native opt-in and affected-check retry rules without disabling required hooks.",
            "Checks what master changed in the data the PR reads (tables, enums, stored values), with a read-only production group-by, because a merged sibling can change it with no file conflict.",
            "Every open review thread ends fixed, refuted with code reasoning, or ticketed — never an "
            "open 'your call'; a claim is verified against the current code before being trusted.",
            "The ship-ready verdict separates code-complete from the human-only deploy steps (stack "
            "merge order, a manual provider/dashboard config that leaves the feature inert if missed, "
            "index-before-functions), so the human never has to ask whether it ships.",
            "A cross-owner gap is kept in the owner's scope: a ticket, a comment, and an explicit "
            "blocking line in the Deploy TLDR — never completed unilaterally.",
            "A gap inside the PR's own scope is built in the PR while it is a draft. A ticket is for "
            "another owner's work, a step release order forces into a later release, or a deferral "
            "Simon stated, and each ticket names which.",
            "Re-reads the project's working rules and deploy docs after every merge of the default "
            "branch that changed them, and re-checks the PR and its Deploy TLDR against the new rule.",
            "Runs safely one-per-branch when several execute at once: each touches only its own "
            "branch, a cross-owner fix is a ticket + comment + blocking line on the owner's PR, and "
            "the assembled PR-set includes drafts, not only ready PRs.",
        ],
    },
    "skills/sk/skills/work-consolidate-supersede-branches-prs/SKILL.md": {
        "mission": "Several branches (and their PRs, if any) plus the latest base become ONE new branch "
                   "that supersedes them all: every branch's changes propagate both ways, the base is "
                   "brought current, the extra asks are built, and it ships as a draft PR (or bare branch) "
                   "that closes the originals — the base never touched, every decision flagged.",
        "purpose": "Consolidates several branches/PRs + the current base into one superseding draft PR, "
                   "resolving every merge conflict for behaviour and building any additional asks on top.",
        "criteria": [
            "Merges on git ground truth (a trial merge enumerates the real conflict set) and verifies the "
            "auto-merges SEMANTICALLY (build + typecheck + the affected suite + reading files both branches "
            "edited in the same function), not just marker-free.",
            "Resolves every conflict for behaviour by type (import union / keep-both test suites / keep-both "
            "intents or the canonical side), and catches + flags the one side-pick that would silently "
            "revert a fix the other side shipped.",
            "Never merges/pushes/writes the base; leaves the new PR DRAFT; closes each superseded PR with a "
            "comment linking the new one.",
            "Clears the inherited dead-code scan to 0 (delete / export-the-leaked-type / justified "
            "suppression / flag-if-unwired) and reconciles every ask to a verdict + committed-test evidence "
            "at hand-back.",
        ],
    },
    "skills/sk/skills/work-checkpoint-wrap-up-safe-to-reboot-resume/SKILL.md": {
        "mission": "After this runs the machine can restart — wiping /tmp and killing every background "
                   "process — and the next session resumes with nothing lost and no guesswork.",
        "purpose": "Checkpoints in-flight work so a reboot (which wipes /tmp) and a later resume lose "
                   "nothing: everything resume-critical is moved out of /tmp and session memory into "
                   "durable homes, background processes are stopped, and a single RESUME BRIEF says "
                   "exactly where to pick up.",
        "criteria": [
            "Treats /tmp and session memory as volatile and only pushed git, the Linear ticket(s) and "
            "the worktree .context/ as durable; every resume-critical piece ends in one of those three.",
            "Commits + pushes every branch and resolves every agent/isolated worktree (pushed, captured, "
            "or discarded-with-why) so origin holds all progress; git status clean on every worktree.",
            "Writes a RESUME BRIEF naming the branch + commit SHA, what is done, and the single concrete "
            "next action, into the ticket and the .context plan — never a /tmp path, never 'continue "
            "where we left off'.",
            "Stops every background agent/monitor/dev server it started, releases the port lanes, tears "
            "down finished worktrees, and reconciles the intent-ledger before reporting.",
        ],
    },
    "skills/sk/skills/ship-report-and-ensure-correct-user-system-journey/SKILL.md": {
        "mission": "Every point of Simon's ask is provably built, backed by a test, before the work is handed back.",
        "purpose": "Assembles the end-of-work report (user journey, system journey, mismatches, "
                   "changes on this branch), proves each criterion the plan validated with a test it "
                   "writes and commits, then closes the gaps between them, looping until the "
                   "journeys hold.",
        "criteria": [
            "Use existing baseline evidence, diagnose specific uncertainty only, and schedule final execution after all gap fixes; preserve native opt-in and evidence-reuse requirements.",
            "Reads references/tldr-report-formats.md for the three shapes; owns orchestration only.",
            "Reports on a branch against its base OR on uncommitted work in progress, says which, "
            "and keeps the two separate when both exist. Merging them hides which half is safe.",
            "Gathers from the code and the real diff, never from memory of the session. A report "
            "written from intention repeats the intention instead of what shipped. The loop "
            "re-derives from the code every round for the same reason: a loop that reads its own "
            "fix report only ever confirms itself.",
            "Opens with a context line, because Simon reads it cold after days on other work.",
            "States the mismatches between the two journeys explicitly, and says so plainly when "
            "there are none.",
            "NO BASELINE, NO EDITS AND NO TESTS. With no plan, ticket or acceptance criteria found, "
            "it reports and asks for one. Inventing criteria and then 'fixing' code to satisfy them "
            "is the worst output it could produce, because it looks exactly like a successful run. "
            "An invented test is that failure with a green tick on it: derived from the code, it "
            "asserts whatever the code already does and reports green forever.",
            "A deliberately dropped, refuted or deferred part is part of the baseline and is never "
            "built back. The verdict names who decided and when.",
            "Consults the living plan (.context/<slug>-plan.md) from "
            "/sk:plan-stable-persistent-dynamic-complete-full-plan as a baseline source when present, per "
            "rules/living-plan.md.",
            "Each criterion is judged by an INDEPENDENT pass that defaults to not-met and is given "
            "the code but not the session narrative. Self-assessment by the context that wrote the "
            "report is the failure this exists to prevent.",
            "After fixes, re-judge criteria whose evidence or inputs changed, including dependent readers and configuration; carry forward only verdicts whose evidence still applies.",
            "Write criterion-derived tests in Phase 4; execute under the shared batch policy or cite valid passing proof. Keep unexecuted verdicts provisional; a code reading or green test alone never upgrades a verdict.",
            "Phases 1 to 3 are read-only and phase 4 writes tests ONLY. Phase 5 alone edits product "
            "code, against a criterion or finding written first, because a phase that edits the code "
            "under test can make its own test pass.",
            "Phase 5 lands one conventional commit per test or gap, never on the default branch; use shared final-batch verification without per-commit builds or tests.",
            "The loop stops on convergence OR on a finding that survives two consecutive rounds OR "
            "on a decision only Simon can make, and says which. An unbounded loop is not a "
            "guarantee of correctness.",
        ],
    },
    "skills/sk/skills/ship-preview-eyeball-with-prod-data/SKILL.md": {
        "mission": "Simon can inspect the changed app with authentic production data locally before deployment, without exposing production to preview writes.",
        "purpose": "Compose an isolated production-data preview, a visual pass and a reusable local hand-back.",
        "criteria": [
            "Use the shared testing-strategy source-fidelity, derived-state and local-preview procedures instead of duplicating export, browser or recompute mechanics.",
            "Compose ship-verify-with-prod-data for changed data figures and test-eyeball for visual verification; keep account coverage explicit.",
            "Keep exports and captures local; require a separate request for deployment, production mutation or evidence publication.",
            "Return a working local URL with account, route, capture time, original date range, data mode, clock mode, visual verdict, evidence and stop/restart commands.",
        ],
    },
    "skills/sk/skills/ship-verify-with-prod-data/SKILL.md": {
        "mission": "Simon sees production compatibility evidence and its gaps before changed figures or runtime eligibility reach legitimate users.",
        "purpose": "Compose production compatibility checks and classify data discrepancies before shipping.",
        "criteria": [
            "Apply testing-strategy.md production compatibility gates to changed figures and runtime eligibility; absence of displayed figures never excludes admission, validation, authorization or retention checks.",
            "Enumerate authoritative accounts and legitimate cohorts, rank recent activity and state coverage gaps; one sampled account cannot prove population-wide compatibility.",
            "Read production through the provisioned read-only path; recompute changed figures from raw source data and independently reconcile figures sharing a source or predicate.",
            "Classify discrepancies as bug, skew, legacy or unknown with dated evidence; legacy requires proof no current legitimate journey depends on the records, not age alone.",
            "Hands Simon the backfill/recompute command plus deploy order to run on prod himself, "
            "proven first by running the identical script on a seedable dev account and re-reading "
            "until that account reconciles.",
            "Use shared derived-state preparation before screenshots; distinguish copied persisted-source state from post-refresh results requiring the real writer and complete inputs, then hand off to ship-screenshot-changes.",
            "Composes /sk:ship-screenshot-changes and feeds "
            "/sk:ship-report-and-ensure-correct-user-system-journey a real-data verdict; does not "
            "restate them.",
        ],
    },
    "skills/sk/skills/ship-screenshot-changes/SKILL.md": {
        "mission": "Simon sees every changed surface and journey before and after, across states and sizes, in a review and current PR description, with a verified comment fallback.",
        "purpose": "The one screenshot skill: advanced scenario matrix, before/after capture, journey videos, offline report and the default PR post through the shared evidence template.",
        "criteria": [
            "Screenshots each CHANGED surface and journey (from git diff) across the reference's case "
            "matrix: empty and full states, conditional scenarios and responsive sizes, seeded with "
            "realistic inputs, saved inside a workspace root; no bug-hunt or fix-loop.",
            "Size the case matrix to the change's tier under testing-strategy.md: a Light change posts one before/after pair at 390x844 with no video and a skip line; Simon's direct ask runs the full review.",
            "Triggers on the former advanced phrases (advanced screenshot review, all conditional "
            "screenshot scenarios, screenshot coverage matrix); hands back the offline report with "
            "conditions above each screenshot and an actionable TLDR table.",
            "Has a JOURNEY mode: captures a user FLOW as an ordered numbered sequence (step-<n> shots), "
            "the steps derived from the user journey (/sk:ship-report + references/user-journey-review.md), "
            "and posts them in step order — coexisting with the changed-surfaces mode, not replacing it.",
            "Records the verification runs per references/screenshot-review.md by default at the tiers it names, after the short clips and separate from them, and posts only the final clean runs under ## Verification runs.",
            "Circles each change with a template callout from the element's box and captures a "
            "BEFORE/AFTER pair for every changed surface, composed by bin/pr-evidence.py; never "
            "injects DOM captions or ring overlays.",
            "Posts screenshots to the PR by DEFAULT whenever a PR is open (never opt-in, never only a "
            "body text reference) and GitHub-native — gh --attach or the user-attachments CDN upload, "
            "git-only detached-ref for images only, never an external host; fails loud and verifies the "
            "images render (not camo-broken).",
            "Embed one consolidated evidence section in the PR description by default; permit a comment only for a verified description limitation. Preserve untouched current points and provenance; a link alone is not embedding.",
            "Upload supported Markdown local media references, then use returned native URLs for width-controlled HTML. Verify zero local media refs and duplicate appended media; remove only proven uploader duplicates while preserving unrelated text and footers.",
            "Record a unique refresh ID and reconcile the saved destination before retrying. Preserve unrelated description text and footers; use only recorded workflow-owned staging comments, retired after description verification.",
            "Verify replacement rendering and playback before deleting obsolete workflow-owned evidence, including clearly owned unmarked legacy comments, under existing authorization. Preserve other authors, unrelated discussion, uncertain ownership and concurrent edits; failed verification deletes nothing.",
            "Reconcile one current description section with zero duplicate evidence comments, or one verified fallback comment. Remove only unchanged owned obsolete/staging comments after replacement verification; preserve unrelated and concurrently edited comments.",
            "Post one block per point per the reference's PR evidence template: the composed before/after image per platform and the composed video; a new surface carries `new, no before` and a gap shows its status and reason.",
            "Record each affected scenario on the base and the change, compose them side by side with bin/pr-evidence.py and post that clip under its own scenario block and table row; post one viewport per state unless the other's layout differs; state the reference's skip when applicable.",
            "Publish videos as verified inline players alone in their own paragraph, never ordinary links or thumbnails. Preserve untouched point blocks and videos during updates.",
            "Verify rendered players and browser playback for every published clip: duration, advancing time, expected first and last states, no navigation or media errors. Record failed uploads or playback as blocked evidence; a reachable file never passes.",
            "Allow labeled API-rendered description or comment verification using unchanged body_html and authorized remote media with identical browser checks; keep full-page UI unverified and reject reconstructed players, local-media substitution or exposed signed URLs.",
            "Carry the shared recording caveat beside each applicable clip in local hand-backs and PR comments, including fallback players, while keeping attachment URLs in their own paragraphs.",
            "Owns the capture + PR-post that /sk:test-eyeball reuses; neither restates the other.",
        ],
    },
    "skills/sk/skills/test-eyeball/SKILL.md": {
        "mission": "A change Simon can see is confirmed working in a real browser before he is asked to look at it.",
        "purpose": "Drives the changed frontend hard (edge inputs, bug-hunt, fix-loop) on top of /sk:ship-screenshot-changes's capture.",
        "criteria": [
            "Runs as a loop until clean, not a one-shot.",
            "Reuses /sk:ship-screenshot-changes for the capture and the default PR post; adds only "
            "edge-input fuzzing, bug-hunt, the fix-loop and the journey-review, and does not restate them.",
            "Takes the posted screenshots once, after the clean sweep's last fix commit; sweep-time captures stay diagnostics.",
        ],
    },
    "skills/sk/skills/work-full-detailed-workflow/SKILL.md": {
        "mission": "Simon asks for any piece of work in his own words and it runs research to shipped PR in one pass, every request kept through tangents, with no skill to remember and no ship step to ask for.",
        "purpose": "The one composite work harness: the full detailed workflow's stages plus the gauntlet's session record, engines and judge, ending with the ship harness. Points at the reference catalogs.",
        "criteria": [
            "Run as the spine of every task-bearing request, including one naming another skill; that skill runs as a stage inside it and an empty stage records N/A with its reason.",
            "Plan and write test coverage before implementation; execute the automated matrix at the final gate after all authorized features and review fixes converge, under the shared testing policy.",
            "Stays a thin index; the detail lives in references/ and is not duplicated here.",
            "Step 1 is the research pass, so Simon never has to ask for research separately.",
            "For a bug fix, step 3 reproduces it with a control under the testing-strategy reproduce-first section before any implementation.",
            "Names rules/living-plan.md among the always-on rules it does not restate.",
            "Its final stage runs /sk:ship-full-detailed-workflow on every PR the run opened or pushed, unprompted, reusing earlier evidence for the same head and recording each landing-gate result; a change task ends at a ready PR with green CI and landing gate PASS, merge left to Simon; N/A only when no tracked file changed.",
            "Default to current-session execution with the independent judge off; ask for custom options only when requested and preserve existing authorization.",
            "Preserve planning authorization; use the shared dashboard template and runtime tests, displaying this run's recorded options read-only with no editable selectors or generated start command.",
            "Select current or work-ralph-loop upfront; composed execution reuses confirmed options and has one supervisor owning plan, dashboard and judge.",
            "Detect a handoff first: resume from a pasted dashboard link/html/plan via resolve, reusing the recorded engine and options without a second interview.",
            "Read references/workflow-loops.md at intake on every run and apply its whole shared lifecycle, not only when a stage calls for it.",
            "Run the shared design-source section in references/workflow-loops.md from intake, before any builder is briefed, for any supplied design or pixel-perfect ask; hold each such section at review until its report is PASS, on either engine with the judge off; restate none of the gate.",
            "With the judge on, run the shared judge stage on each built item's revision inside the numbered build stage and route its gaps back to the engine.",
            "Point a design build at the parallelization worker-per-deliverable section and the design-source harness, design-diff and PR evidence; take machine priority only per dev-server-hygiene; restate none of them.",
        ],
    },
    "skills/sk/skills/plan-stable-persistent-dynamic-complete-full-plan/SKILL.md": {
        "mission": "Simon reads only what changed, never the whole plan again, and no request slips into code before he confirms — because there is exactly one living plan that stays in plan-mode until he says go.",
        "purpose": "Maintain ONE durable source-of-truth plan, update only the sections a request touches, highlight the delta, lock plan-mode until confirmed, then ask about tickets and hand off.",
        "criteria": [
            "One plan file at .context/<slug>-plan.md; a request updates only the sections it touches, never a wholesale rewrite.",
            "Every update prepends a dated Changelog entry and shows Simon ONLY the changed section(s) as the delta in chat.",
            "Stays in plan-mode — every request folds into the plan, nothing is implemented — until an explicit confirmation ('implement'/'go build'/'the plan is confirmed').",
            "On confirmation it asks whether to encode the plan into tickets, then continues the selected current or Ralph execution through the shared dashboard protocol.",
            "Reuses references/planning-and-tracking.md for the plan's content; does not restate it.",
            "Uses references/workflow-loops.md for the shared live overview and preserves the same plan when changing execution modes.",
            "Backs every plan change with a before/after artifact (/sk:work-ask-reply-in-full-before-after-artifact) and offers a clickable preview (/sk:ship-mockup-before-after) for visible changes; does not restate either.",
            "Its stable skeleton includes a '## Related tickets & update plan' section: every related "
            "ticket as a full Linear link + live state, a refutation with evidence for anything "
            "dropped/superseded, and a plan to update the tickets on confirmation.",
            "Its skeleton opens with BOTH a user journey AND a system journey reflecting the current "
            "trajectory (confirmed + recommended-default answers), kept in sync on every update; format per "
            "references/tldr-report-formats.md Blocks 1+2 and planning-and-tracking.md, not restated.",
        ],
    },
    "skills/sk/skills/work-hyperspeed/SKILL.md": {
        "mission": "A dividing task finishes across as many hand-run sessions as Simon can open, assembled from clean branches (or gathered from each part's reported path when parts produce standalone untracked artifacts), each part pasteable into a cold session with no prior context, and the skill gets better every round.",
        "purpose": "Manual, branch-based parallel harness: one plan file of self-contained parts pasted into separate sessions, assembled from their pushed branches.",
        "criteria": [
            "Commits and pushes a clean START commit that every part branches from, before any part is written.",
            "Each part is self-contained: whole shared context, owned files, the git branch-off-START "
            "ritual, the repo setup ritual, and a fixed report-back block — pasteable into a cold session.",
            "Assembles by merging the reported branches, then in the SAME turn deletes each part branch "
            "BY ITS REPORTED NAME (never an hs/<run>/* glob — Conductor names branches itself) local and "
            "remote after proving it merged into the assembly branch, points to /sk:meta-cleanup-worktrees "
            "as the leak backstop, and tells Simon to archive the sessions by their branch name (what the "
            "Conductor session shorthand shows), since it cannot touch the Claude UI.",
            "Presents exact part/START branches and worktrees, reuses recorded cleanup authority and asks only for uncovered actions. Remote deletion requires explicit authority, actual-tip proof and the shared expected-tip condition.",
            "Parts write status + output location to a shared file in this run's own "
            ".context/hyperspeed/<run-id>/status/ (DRY, per-session, so concurrent runs from different "
            "sessions never clash); the orchestrator POLLS it via a backgrounded wait-loop that shows a "
            "progress bar (references/progress-bar.md) and never needs a relay — Simon only pastes the "
            "starter blocks and archives the sessions.",
            "Reconciles a run's full footprint at cleanup, not just branches: removes/prunes part "
            "worktrees, sweeps orphan dev-servers, port lanes and stray claude -p slices, and each part "
            "self-tears-down its processes before reporting done.",
            "Shares the slice-cutting and reconcile craft AND the hand-run session handoff unit (START "
            "commit, paste-block skeleton, status POLL) with references/parallelization.md and "
            "/sk:work-superspeed; composes them, does not restate them.",
            "Records each round in a reconcile.json (same schema and causes as /sk:work-superspeed), "
            "emits a compact run row to the dotclaude `runs` collection via bin/dotclaude-log.py so the "
            "parallel engine is not invisible to the optimizer, analyses it with "
            "/sk:claude-config-self-optimize-analysis-after-run, and folds only recurring findings into "
            "this skill via the automatic repair policy.",
            "Workers keep a timestamped phase log + friction report; the orchestrator harvests them to "
            "self-diagnose the bottleneck each round and has workers reuse the shared build cache instead "
            "of cold-rebuilding, routing any recurring durable fix to its owner (the project's committed "
            "CLAUDE.md, etc.) under its existing authorization and project policy.",
            "Guides Simon as a paced co-pilot session (references/human-pacing.md): one handoff at a "
            "time, signal, wait; the plan file holds the rest.",
            "Two levels, not a replacement for superspeed: each hand-run part runs its slice through "
            "the full harness autonomously (full-detailed-workflow + inner /sk:work-superspeed where it "
            "sub-divides + isolate-env + ship-report) and reports done only after ship-report confirms "
            "its accept criteria.",
            "Supports a standalone-artifact variant: when parts produce untracked files (not tracked "
            "code), each writes to its OWN worktree and reports the absolute path, and assembly GATHERS "
            "those paths into one collection dir instead of merging branches.",
            "Before finishing a stuck/interrupted part itself in its worktree (edit/build/commit/push), "
            "the orchestrator checks for a live session owning that worktree (a claude process cwd'd there) "
            "and yields if one is running; it adopts a part only when its session is provably dead, and "
            "commits on the part's own branch.",
        ],
    },
    "skills/sk/skills/work-split-session-in-parallel-branch-offshoot/SKILL.md": {
        "mission": "A spur-of-the-moment idea runs as one parallel session off the main work, is held for Simon to eyeball on finish, and is merged or binned only on his explicit call — never auto-merged.",
        "purpose": "Lightweight single-session offshoot: spin one idea off onto its own branch in a new session, hold it for review, merge or discard on Simon's word.",
        "criteria": [
            "Runs exactly ONE spun-off session, not a 3-5+ fan-out; a dividing task is sent to "
            "/sk:work-hyperspeed instead.",
            "Composes the shared handoff unit in references/parallelization.md (START commit, "
            "paste-and-forget block, shared-status POLL) with one part; does not restate it.",
            "The part branches off START, writes working->done to the run's STATUS_DIR, and reports its "
            "branch plus the absolute path of anything viewable it produced.",
            "On done it HOLDS: surfaces the branch and artifact to Simon for an eyeball and never merges "
            "on its own.",
            "Merges or deletes the offshoot only on Simon's explicit call: on merge, fetch+merge+gate then "
            "offer cleanup; on bin, delete the branch (local+remote) and worktree without merging, "
            "confirming the list first.",
            "Paces the finish as a human-paced handoff (references/human-pacing.md): surface, wait, act "
            "on his word.",
        ],
    },
    "skills/sk/skills/work-warpspeed/SKILL.md": {
        "mission": "The outermost, account/org-spanning layer of the parallel stack is captured as a TODO so it is not re-invented, and Simon is sent to the working /sk:work-hyperspeed until it exists.",
        "purpose": "Placeholder for the third layer: a whole hyperspeed relay spread across VMs/VPSs on different accounts/orgs. Not built.",
        "criteria": [
            "Frames the three-level stack (warpspeed on top of hyperspeed on top of superspeed); runs "
            "nothing and points at /sk:work-hyperspeed.",
            "States the honest blocker: Anthropic limits key on the org, so more machines on one "
            "account add no throughput; the win needs separate accounts, per references/parallelization.md.",
        ],
    },
    "skills/sk/skills/work-copilot-agile-build/SKILL.md": {
        "mission": "A feature's UX is confirmed on a realistic preview before any backend exists, so a wrong journey costs a sentence, not a rebuild.",
        "purpose": "Runs a build as an agile loop: fake preview with simulated data, walk-through, confirm, then backend, repeat.",
        "criteria": [
            "No backend is written for a slice until Simon confirms its preview or its journey.",
            "The preview carries realistic simulated data, the one place the mockup skill's real-data rule is overridden.",
            "Drives /sk:ship-mockup-before-after and /sk:ship-report-and-ensure-correct-user-system-journey; does not re-explain them.",
            "Each round's check-in points at references/tldr-report-formats.md for its shape; does not restate it.",
        ],
    },
    "skills/sk/skills/maintenance-code-optimize-app/SKILL.md": {
        "mission": "The app is measurably faster on a production build, and a regression is caught before users meet it.",
        "purpose": "Performance and Lighthouse auditing on a production build.",
        "criteria": ["Measures on a production build, never a dev server. Runs the audit itself."],
    },
    "skills/sk/skills/work-platform-anchor-test-feature-poc-works-before-building/SKILL.md": {
        "mission": "A platform can provably do the thing before a design commits to it.",
        "purpose": "Proves an approach against the real platform before it is built.",
        "criteria": ["Output is a verified recipe, not shipped code. Billable submits are confirmed first."],
    },
    "skills/sk/skills/ship-pr/SKILL.md": {
        "mission": "A reviewer sees what changed and what to do from the PR's first block, and can deploy the change from the body alone, in the right order, without asking.",
        "purpose": "PR bodies that open with a before/after TLDR, then a deploy TLDR.",
        "criteria": [
            "The body opens with ## TLDR: a Before/After table of 3-5 rows and a **Do:** line, shape owned by references/tldr-report-formats.md; the Deploy TLDR follows it, before any template section.",
            "Name bin/pr-landing-gate.py as the one home of the body's section headings and run it on the fetched PR.",
            "Every PR body section is a visible ## or ### heading; the fetched body_html holds zero collapsed <details>: every <details> carries open, as GitHub's own attached-video wrapper does.",
            "Every production-changing step carries its order, a precondition check, a post-step smoke with its expected result, and a rollback written as an action, never a caveat.",
            "A User journey and a System journey section follow it, read from "
            "references/tldr-report-formats.md, so a reviewer can judge both the feature and the "
            "mechanism without reading the diff. Same blocks as end-report, so a PR and the report "
            "tell one story.",
            "Owns the body rewrite: when a PR's behaviour or base moves after its body was written, every SECTIONS section is re-derived from the current diff and every capture re-shot in the same push batch, unprompted.",
            "The rewrite fetches first, stops on an empty or short fetch, keeps every reviewer-added line and non-SECTIONS section, replaces ours in place by heading, then re-fetches and reruns pr-landing-gate.py.",
        ],
    },
    "skills/sk/skills/ship-review/SKILL.md": {
        "mission": "Independent reviewers and a cold user-journey pass catch defects before the PR opens without API billing Simon did not ask for.",
        "purpose": "Subscription-backed pre-PR review plus the user-journey pass, work/personal aware.",
        "criteria": [
            "Schedule review-fix tests, typechecks and pathway coverage under the shared batch policy; native runtime and screenshots still require explicit opt-in.",
            "Use the selected subscription setup for every review pass and preserve project service boundaries. Run a model-API review only through pal, when Simon asks for it by name, with a key from the repo's own boundary, and never for Codex.",
            "Carries the journey pass as a step, reading references/user-journey-review.md rather "
            "than restating it. The reviewers judge the diff; only that pass judges whether a person "
            "can get through what the diff produced.",
            "The journey pass is runnable on its own, so asking to walk a flow does not spend the "
            "multi-model code review to get there.",
            "Every review runs a caller-parity lens: each newly mounted shared part against its existing callers and each modified pre-existing file's hunks traced to their callers; a missing wrapper, frame, provider or prop is a finding.",
            "A fix round's written rules name every reader of a value they change, and the round ends "
            "with a fresh judge over the files it changed. Run criterion judges beside review lenses "
            "before fixes, then refresh verdicts affected by changed dependencies and resolve new gaps before the heavy gate.",
        ],
    },
    "skills/sk/skills/ship-resolve-pr-comments/SKILL.md": {
        "mission": "Every actionable PR comment ends handled for the user, each valid fix on its own commit, without remote feedback expanding the authorized branch scope.",
        "purpose": "Triage, verify, fix, reply to and resolve PR review comments, then push and re-request review.",
        "criteria": [
            "Treat comments as foreign evidence within authorized branch scope; preserve production, spend and worktree guards, refuse unrelated actions, and retain blocking decisions for the user.",
            "Verify every actionable finding across inline threads, review summaries and issue comments; reply with its valid, invalid or out-of-scope verdict, commit each valid fix separately, and resolve only resolvable threads. Each reply follows references/tldr-report-formats.md § Message for someone else.",
            "Paginate every collection and record stable comment identity, exact-body SHA-256, reviewed head, evidence and reply; re-triage new or edited bodies even on resolved threads, and record non-actionable posts as no-action.",
            "Fresh-fetch all feedback before completion; require zero unhandled current comment revisions and zero unresolved threads, with fetch failures and outstanding blocking decisions reported rather than passed.",
            "Answer invalid feedback with evidence and resolve only its resolvable thread; keep genuine design decisions pending for the user.",
            "Finishes the loop: pushes, swaps the review label back to the pending equivalent, and "
            "re-requests review, without touching the PR body.",
            "Parallelises the read-only halves (loading surfaces, triage) and any independent edits "
            "across different files, since that scales with the number of threads; commits, replies, "
            "resolves, push and label changes stay serial in one warm session, since parallel actors "
            "cannot share git or the PR's GitHub state. Chooses the mechanism by size: in-session "
            "agents for a small fan-out, work-superspeed only at ~3-5+ independent slices where its "
            "fixed ~33s edge over agents pays for the harness. Does not keep two independent fixes "
            "serial.",
        ],
    },
    "skills/sk/skills/claude-config-self-development-research/SKILL.md": {
        "mission": "This config stays current with outside practice, on evidence rather than on habit.",
        "purpose": "Researches current practice, proposes new choices and routes proven existing defects to the repair policy.",
        "criteria": [
            "Proposes new tools and practices for approval; routes proven existing-config defects through the authorized update flow.",
            "Caps at 7 findings and 5 ideas, so ranking actually happens.",
            "Rejects anything already declined or documented as a deliberate choice.",
        ],
    },
    "skills/sk/skills/work-superspeed/SKILL.md": {
        "mission": "A task that genuinely divides finishes sooner AND correct, with Simon uninvolved between dispatch and the gate.",
        "purpose": "Fan a task across the selected Claude or Astra sessions, reconcile warm, log the run.",
        "criteria": [
            "Reuse the shared setup protocol before dispatch, and carry its selection into reconciliation and retries.",
            "States the measured evidence and its limits: a fixed ~33s advantage, not a multiplier, "
            "so it must keep telling Simon NOT to use it to speed up one long serial task.",
            "Keeps the four rules that came out of the measurement: same directory not worktrees, "
            "never --bare, verify slices on disk not by exit code, cap at 3-5.",
            "Every slice gets exclusive file ownership and an explicit expected result, because two "
            "slices editing one file is the most expensive failure this design has.",
            "Makes the partition account for what a file ASSERTS, not only what it writes. Ownership "
            "models writes, so it misses a test/snapshot/fixture that encodes another slice's output: "
            "both slices are individually correct and the seam still breaks. Applies to UNOWNED files "
            "too, which no slice is watching precisely because no slice owns them.",
            "Gives slice sizing a proxy that can be checked BEFORE dispatch rather than only in the "
            "analysis after it. Imbalance is the dominant waste in every run measured, and it is the "
            "one kind that is visible in advance.",
            "Reconcile checks the instructions a slice was least likely to obey — the ones that "
            "contradict the file it was editing — mechanically rather than with more prompt words, "
            "because a slice follows local convention over an explicit instruction.",
            "Always ends by analysing the run. A run whose logs nobody reads teaches nothing.",
        ],
    },
    "skills/sk/skills/claude-config-self-optimize-analysis-after-run/SKILL.md": {
        "mission": "Every run leaves this config measurably better at shipping Simon's work, never better at one local metric.",
        "purpose": "Analyze each task's execution and publish evidence for the next run or assigned coordinator.",
        "criteria": [
            "Publish local findings automatically after each task; the active session applies the automatic repair policy, while delegated participants return evidence without draining the global backlog.",
            "Every suggestion names its evidence (file, number, log line) and the specific change. "
            "No evidence, no finding.",
            "Silence is a valid result; a manufactured suggestion costs more than a missed one.",
            "States each finding as a class, not as the run's symptom. A run analysis is a sample "
            "of ONE and its own evidence bar pulls every fix toward the incident that produced it.",
            "Optimises the LOGS as well as the run: a question the logs cannot answer is a missing "
            "field, and a missing field looks exactly like a clean run so it never fixes itself.",
            "An all-sessions argument runs the aggregate pass and ranks findings by mechanism across sessions.",
        ],
    },
    "bin/superspeed-dispatch.sh": {
        "mission": "Slices run genuinely in parallel, never collide, and leave a log that makes the next run better.",
        "purpose": "Engine for /sk:work-superspeed — launch one provider-matched process per slice and log it.",
        "criteria": [
            "Launch headless Claude and Codex slices through their shared native launchers, even when a shell function is unavailable.",
            "Check Codex final acceptance against commits and edit events; preserve attempts and relaunch one continuation with owned-file state and checkpoints. Fail a second incomplete stop, never accept native exit zero alone.",
            "Validate provider and setup before spending; route GPT design only to the Fable tier and implementation to the mid tier resolved live at dispatch, then fail an incomplete worker.",
            "Sets AGENT_DELEGATED_WORKER=1 on every slice so intake skips session-plan initialization and the intent ledger stays silent, while native approval and security checks stay active.",
            "Verifies each slice by its on-disk artifact, never by exit code "
            "(anthropics/claude-code#74761: claude -p can exit 0 mid-task).",
            "Tells every slice to write BLOCKED.md rather than edit a file another slice owns, and "
            "never to ask a question, because nobody can answer one.",
            "Carries STANDING run instrumentation that RECORDS ONLY: it must never block, fail or "
            "alter a run. Its concurrency sampler is killed AND verified dead at fan-out end, "
            "because a 1-second loop left behind would outlive the session.",
            "Records per-slice PID and start/end. Those timestamps are what let the analyser "
            "attribute LOCAL time (wall minus API) to the command that consumed it, which is the "
            "dominant cost now that dispatch has been measured and ruled out.",
            "Preflight each effective Claude child against applicable user, project and local Bash allow, ask and deny rules; refuse denied or unknown verification before dispatch, preserve child permissions, and rerun accepted verification into verify.txt after completion.",
            "Computes imbalance against the MEDIAN slice, the same definition superspeed-analyse.py "
            "uses. The two printed different numbers under one name and the louder one told the "
            "reader to split a slice the other called fine.",
            "Writes per-slice timing, tokens and status, so the run can be analysed afterwards.",
        ],
    },
    "bin/superspeed-dispatch.test.sh": {
        "mission": "The dispatcher's two silent failures — a hang, and spending on an unrunnable check — cannot come back unnoticed.",
        "purpose": "Regression test for superspeed-dispatch.sh, stubbing `claude` so it spends nothing.",
        "criteria": [
            "Asserts the dispatcher EXITS once its slices have exited. A bare `wait` also waited on "
            "the concurrency sampler, an infinite loop killed only afterwards, and the deadlock was "
            "invisible to every other signal: all slices finished, all wrote DONE.md, every exit "
            "code was zero. A hang is invisible to everything except a clock.",
            "Asserts an unrunnable `verify` stops the run BEFORE any slice is dispatched, proved by "
            "the absence of result.json rather than by a directory. The guard's whole value is that "
            "it fires early; a stop that still spends a slice is not the guard.",
            "Stubs `claude` in a way that exercises the dispatcher's jq parsing rather than "
            "bypassing it, so a green run is genuinely green.",
        ],
    },
    "bin/superspeed-analyse.py": {
        "mission": "The next run is partitioned better than this one, from evidence rather than impression.",
        "purpose": "Turn a superspeed run directory into waste metrics and concrete next actions.",
        "criteria": [
            "Keep unreported provider cost, API duration and cache writes null in emitted analysis; suppress findings that require those missing measurements.",
            "Every metric prints the action it implies. A number with no action attached is noise.",
            "Name what each concurrency figure measures: inference concurrency is summed model time over wall; only the PARALLELISM verdict, from wall overlap and pairwise intersection, may say slices are serialising, and no finding contradicts it.",
            "Record reconcile causes as slice, late_scope, reconciler or planned_wiring; only slice (rework) and reconciler (error) raise findings, and planned_wiring raises none.",
            "Reports its own blind spots under INSTRUMENTATION GAPS, so missing log fields surface "
            "instead of looking like a clean run.",
            "Says plainly when fanning out was not worth it, rather than only ever justifying it.",
            "Reads DONE.md as a structured report, not a line list: only path-shaped lines count as "
            "changed files, and a heading that negates ('Not touched', 'no change needed') excludes "
            "what follows it. A parser that ignores headings reported an ownership leak naming a "
            "slice for a file it had explicitly declined to touch.",
            "Never lets a file-based metric read as a measurement when it parsed nothing. If no line "
            "resolved to a path, that is an INSTRUMENTATION GAP, because a confident 0 and a broken "
            "parser are indistinguishable to the reader.",
            "Populates session_id on every slice record, and when a transcript still cannot be found "
            "says which of the two causes it actually observed. A lookup that fails silently reports "
            "itself as missing data, which is the same defect as a parser reporting a confident zero "
            "— it disabled the whole local-attribution section while the transcripts sat on disk.",
            "Attributes reconcile rework to a DECLARED cause and raises a finding only for "
            "`slice`. Late scope and the reconciler's own errors are counted, never prescribed "
            "against: measured 2026-08-08, two consecutive runs produced identical rework counts "
            "from opposite causes and got the same advice, which was right once and wrong once.",
            "Compares against the newest prior analysis.json in the same directory and prints the "
            "delta before the suggestions. ONE prior is enough. A finding present in both runs is "
            "raised as recurring, inheriting the worst recurring severity rather than a fixed high "
            "— a report whose top line is trivial trains the reader to skim.",
            "Separates an undeclared WRITE (high: two slices editing one file, the failure the "
            "partition exists to prevent) from an undeclared READ (low: an under-declared spec), "
            "and excludes the run directory, where the dispatcher itself tells every slice to write "
            "DONE.md. One combined check flagged every slice in two runs for obeying instructions.",
            "Reports how many slices passed their own scoped check, and raises a HIGH finding when a "
            "slice that failed its verify is also one the reconciler had to fix. That correlation is "
            "the CAUSE of rework; without it the analyser only reports that rework happened.",
        ],
    },
    "skills/sk/skills/ship-mockup-before-after/SKILL.md": {
        "mission": "The screen Simon approved is the screen that ships — he judges it by looking "
                   "before the work, and never has to find a missing detail by looking after it.",
        "purpose": "Publishes a standalone, shareable before/after of a planned change — an existing "
                   "screen captured 1:1 as self-contained HTML (Playwright + SingleFile), or a real "
                   "screenshot plus the real components' measured styles for a new surface or the AFTER "
                   "overlay, walkable as a storyboard — one per ticket or plan part.",
        "criteria": [
            "Finishes with bin/visual-check.py on the built mockup file, one --state per switch, and hands over the pass table per references/screenshot-review.md.",
            "Ships a self-contained shareable Claude artifact for a change with a real screen, never "
            "a dev route to view it and never HTML rebuilt by eye. Fidelity comes from real pixels; "
            "both alternatives were rejected 2026-08-10.",
            "Captures the BEFORE of an existing screen as a 1:1 self-contained HTML (Playwright auth "
            "plus SingleFile serialize) that opens offline with zero external requests and is "
            "pixel-identical to the live render, never rebuilt from component code by eye; a screenshot "
            "at a fixed viewport with realistic seeded data is the fallback for a new surface or an "
            "AFTER overlay, never placeholder, lorem or empty-stub content. Fans out multiple states "
            "across parallel agents and separate seeded accounts, a sequential re-seed on one account "
            "as the fallback.",
            "Measures the real components (getComputedStyle, getBoundingClientRect: size, font, "
            "colour, spacing, radius) and sizes the AFTER from those values. Every dimension and "
            "colour in the overlay traces to a measured value, never eyeballed.",
            "Overlays only the region the plan touches on the screenshot for a single-screen change; "
            "the rest stays untouched real pixels. Re-rendering the unchanged parts re-introduces "
            "the nearly-right rebuild.",
            "Renders a flow as a WALKABLE storyboard covering every step and state from "
            "references/user-journey-review.md, empty, loading and error included, so he reaches "
            "every state rather than the first screen alone.",
            "Simulates every transition with local state and seeded data — no network, no "
            "persistence, no auth, no real requests. He walks the flow, he does not operate a live "
            "app.",
            "Embeds the screenshot as a compressed data URI with inline CSS/JS for the artifact CSP, "
            "and applies the visual craft directly (theme-aware, self-contained, real content) rather "
            "than loading a separate design skill.",
            "Uses the shared dashboard shell with Before, named Target and Current panels; keeps specialist design controls inside the embedded surface asset.",
            "Offers real PRODUCTION merchant profiles as preview personas by reading their "
            "owner-scoped records with a read-only key, copying to a dev account with the owner "
            "remapped, and capturing on DEV — prod never written or authed; copies every collection "
            "the page reads, not just the funnel's, so the dev render reconciles to prod's numbers.",
            "Re-injects a small interaction layer into a static capture so a collapsible or toggle "
            "component still works, re-wiring the DOM's surviving data-testids and framework classes; "
            "a tab whose other view never rendered needs a per-tab capture, never a dead control.",
            "Iterates on the mockup only, no platform changes, in a loop until the user explicitly "
            "confirms implementation in his own words; a green mockup unsigned-off is not approval, and "
            "app source stays untouched before the word.",
            "Cites the validated plan part behind every visible difference and refutes in comments "
            "anything that changed after validation. Unsourced difference is invented scope, and "
            "this is the cheapest moment to catch it.",
            "Routes proposal cards through work-ask-reply-in-full-before-after-artifact; keeps mockups and boards viewer-only and embedded prior feedback unchanged.",
            "Builds every mockup through mockup-build.py and the shared presentation frame: current Before/After comparison, separate History, optional highlights, exact dimensions, full-spec roundtrip, no bespoke chrome or external requests.",
            "Ships as a self-contained HTML FILE for a collaborative/versioned/multi-screenshot "
            "round-trip, or a Claude artifact URL only when small and un-gated — the artifact's size "
            "ceiling, blocked localStorage and Team-can't-publish-publicly limits pick the medium.",
            "The consolidation gallery over N fanned-out files opens from file:// with no server — every "
            "mockup inlined as srcdoc, never iframed from sibling paths — so a recipient sees rendered "
            "tiles, not blank ones with the server off.",
            "Keeps all state in an embedded <script id=spec type=application/json> data island and "
            "renders product content from it while shared frame controls remain template-owned, so a rebuild is "
            "re-render-from-data (loss-free), not re-describe.",
            "Compresses screenshots (WebP, downscaled, capped) so the document fits the output cap — "
            "never a full-res PNG base64 — and retains existing metadata in #spec; only frame preferences use best-effort localStorage, with an in-memory fallback.",
            "Keeps task navigation in the dashboard and artifact controls in the shared presentation frame; captured product pixels retain their own viewport and styling.",
            "Compares only current Before and selected current After; History opens earlier designs alone; field-diff metadata remains hidden and available through CLI extraction.",
            "Highlights default off and remove immediately; existing comments, pins and verdicts remain intact in the data island without a generic Feedback panel.",
            "Keep feedback and approval in chat; agents use CLI extract/build to update the complete spec without response, handoff or implementation controls in the viewer.",
            "Keeps every version inside #spec as attributed history (v1 author, v2 recipient), "
            "reachable through History; a recipient's Claude rebuilds the extracted spec into a new "
            "attributed version, and never flattens an old one.",
            "One mockup FILE per surface, forever: a new idea, a section redesign, or another "
            "version of X lands in that one file as a switchable variant/version across its axes (a "
            "persona/data axis and a per-section design-variant axis swapped in context via nested "
            "iframe.srcdoc, Current restoring the pristine capture), never a second "
            "*-mockup/*-redesign/*-variants .html sibling; a second file for the same surface, so he "
            "can no longer flip between versions of any part of the page in one place, is the violation.",
            "Writes every rebuild in place to ONE canonical path per surface — a fixed filename, or a "
            "stable mockup.html alias resolving to the current build — so the link Simon bookmarks opens "
            "byte-identical every iteration; a rename to a -redesign/-variants/-gallery file that makes "
            "him re-find it is the violation.",
            "Offers multiple variants only while an open question is unresolved; the moment Simon picks "
            "one — or when the change was a decided edit from the start — the chosen design becomes the "
            "default the mockup opens on and every superseded design is demoted to a labelled "
            "before-reference. A decided change left as one of N equal options, or a mockup still "
            "defaulting to the superseded design, is the violation.",
            "Diffs every overlaid and new-state component against a real render before showing him, "
            "and when a divergence traces to the skill folds the fix forward through "
            "/sk:claude-config-update. That is the self-healing-config loop.",
            "Derives a numbered inventory FROM THE APPROVED ARTIFACT before writing code — each row "
            "naming what changes, the file, and the CALL SITE, across every storyboard step. A prop "
            "no caller passes is the default: three landed identically 2026-08-11.",
            "Sweeps the artifact's own markup for controls no plan or slice ever specified, the row "
            "most likely to be dropped — the Regenerate button survived three rounds of being "
            "reported done.",
            "Gives every row a mechanical check returning a readable value, runs it against the "
            "REAL screen, and reports the value. A comparison made from memory cannot see what the "
            "comparer forgot, which is the whole failure mode.",
            "Tears down any scratch render rig stood up to measure and leaves nothing in the repo, "
            "since the artifact lives on Claude. There is no dev route to delete.",
            "Changes a component when the mockup needs it changed rather than forking it. A forked "
            "copy proves nothing about the real screen.",
            "Points a supplied design source at references/workflow-loops.md for the 1:1 build rules and restates none of them.",
        ],
    },
    "skills/sk/skills/work-preview-on-phone/SKILL.md": {
        "mission": "Simon sees this project on his real phone, logged in, in one pass — instead of "
                   "debugging a page that renders and does nothing.",
        "purpose": "Serves a local dev port to the tailnet and clears the three blockers that each "
                   "render a page which looks fine and is not, in any repo.",
        "criteria": [
            "Beats the phone's page cache with a normal tab and a ?v=<n> query for any multi-load walk; a private tab is for a one-load check, because it loses its storage when the app is switched away.",
            "Verifies the share and its teardown by fetching every printed hostname on every tailscale "
            "node, never by `tailscale serve status`, which can read empty while the share is live.",
            "Binds the dev server to loopback BEFORE sharing it, and proves the LAN can no longer "
            "reach it. Serve proxies from the machine's own loopback, so binding wide exposes a box "
            "holding real credentials to every device on the local network and buys nothing.",
            "Tailscale serve ONLY, never funnel. Serve is tailnet-private; funnel is public and a dev "
            "server carries real credentials, real data and no rate limiting. The reason is stated, "
            "so a future reader cannot mistake it for a preference.",
            "Treats the cross-origin allowlist as ALREADY broken and greps the dev server log first. "
            "Its failure returns 200 for every page and refuses only client assets, so the page "
            "renders un-hydrated and reads as still loading.",
            "Verifies a host pattern by running it through the framework's own matcher, never by "
            "reading it. Next matches per DNS label, so `*.ts.net` matches nothing against a MagicDNS "
            "name and looks correct.",
            "Never widens a production key's origin allowlist. A dev-only credential is minted "
            "instead, guarded on NODE_ENV so the compile inlines the choice, and covered by a test "
            "that production cannot select it.",
            "Restricts the dev credential by API rather than by origin, covering every API the client "
            "calls — a missing one fails after login and looks unrelated.",
            "Confirms the phone is caching before concluding a fix failed. Safari serves a cached HTML "
            "document pointing at stale asset URLs, which costs a full round every time it is missed.",
            "Tears the share down, and says so. It survives reboots.",
        ],
    },
    "skills/sk/skills/work-isolate-environment/SKILL.md": {
        "mission": "Every session runs its own dev stack on its own ports, and no session's server breaks another's.",
        "purpose": "Wires a project so this session's dev stack runs on its own lane of ports, in any "
                   "repo, personal or work, containerised or host-run.",
        "criteria": [
            "Reads references/dev-server-hygiene.md for the protocol and bin/port-slot.sh for the "
            "allocation. It owns the per-project judgement only and restates neither.",
            "Covers the native half by pointer: this session's own claimed simulator, its own "
            "derived-data path passed on the command line, and every heavy build through "
            "bin/local-capacity.py or its native-slot frontend. The protocol stays in references/dev-server-hygiene.md.",
            "Apply references/ios-simulator.md for native hand-back; retain explicitly requested previews through their bounded owned lifecycle instead of unconditional shutdown.",
            "Discovery treats the mechanical scan as a FLOOR, not an answer. The ports that matter most "
            "arrive through config and no package.json scan will ever see them.",
            "Resolve project-instruction policy before setup. When allowed, use CLAUDE.md, CLAUDE.local.md, then a playbook; when ignored, derive setup from executable config and CI. Run setup before booting.",
            "NEVER pollutes the repo. Isolation is external to the project, so a lane is applied with "
            "exported env vars and appended CLI flags — not a commit, and not a local edit sitting in "
            "git status either. A port with no flag and no env knob is a stop-and-ask, never a reason "
            "to edit a tracked file for one session's convenience.",
            "Prefers an export even over a gitignored env file, because Conductor copies .env* into new "
            "workspaces and an inherited value boots a fresh workspace on another lane's ports.",
            "Stops and asks rather than guessing on the three cases it cannot decide: a port a third "
            "party has registered, a shared service whose ports come from a committed file, and a "
            "project with no isolation mechanism at all. Containerising something that never was is a "
            "bigger change than it was asked for.",
            "Proposes a durable fix only on a pattern that recurs across three runs or two consecutive "
            "ones, at most one, and stays SILENT when nothing recurs. A skill that proposes something "
            "every run is a nuisance rather than a feature.",
        ],
    },
    "skills/sk/skills/meta-dotclaude-copilot-start-here-for-any-task/SKILL.md": {
        "mission": "Simon calls one skill for any task, immediately gets its complete dashboard, and finishes with no skill forgotten and no tangent dropped.",
        "purpose": "The single user-invocable front door: open the session record, route the task, show progress and drive it to a verified finish.",
        "criteria": [
            "Finds or creates one active plan-backed dashboard before routing, returns its canonical link on request and rejects multiple active plans.",
            "Keeps every session on the shared gauntlet record with current execution and independent judgement off by default; custom execution options remain opt-in.",
            "Writes each routed flow's sources, decisions, artifacts, verdicts and remaining actions into the plan, then refreshes the dashboard.",
            "Defaults the spine of any task that produces a change to /sk:work-full-detailed-workflow and invokes it with the Skill tool before the first edit; every other routed skill runs as a stage inside it.",
            "Routes via references/skill-stack.md and verifies every named skill is installed before "
            "planning on it; never restates the map or a skill's method.",
            "Keeps an always-on progress bar per references/progress-bar.md (harness Task list + compact "
            "text bar + nested sub-progress for a sub-skill); does not restate the format.",
            "A tangent (a discovered fix, a mid-run ask) is a QUEUED task per process.md: handled, then "
            "the main thread RESUMES; nothing is dropped.",
            "Callable at any stage: re-reads the tracker and continues where the plan left off, never "
            "restarting done work.",
            "Points to rules/living-plan.md; re-invocable on EVERY message — re-reads .context/<slug>-plan.md, "
            "folds the new message in, continues, never restarts done work.",
            "Routes the finish of work that opened or pushed to a PR through /sk:ship-full-detailed-workflow "
            "per rules/process.md, before hand-back.",
            "Drives the finish to leave the work refactored/centralised/DRY-SRP (one owner per shared "
            "value/behaviour/component) per rules/engineering-standards.md before the bar reads 100%.",
            "Reuses skill-stack.md + the intake advisory + process.md; owns the entry point, the progress "
            "bar, verifying skill names, and the resume.",
        ],
    },
    "skills/sk/skills/meta-cleanup-worktrees/SKILL.md": {
        "mission": "Simon reclaims disposable workspace and archive storage without losing work, while every retained folder has a clear reason.",
        "purpose": "Safely clean finished worktrees and branches, generated caches or explicitly requested archives, with verified disk outcomes.",
        "criteria": [
            "Lists canonical dashboards, verified viewer PIDs, repository, branch/HEAD, exact paths, aliases, sizes and actions before confirmation.",
            "Exempts only a viewer whose receipt, plan, output, PID command and worktree match; mismatches and other active sessions block cleanup.",
            "Stops confirmed owned viewers, rechecks idleness and verifies their PIDs and dashboard paths remain absent after removal.",
            "Finishes a repository sweep in one pass: every local head gets a final disposition, everything the request covers is done before the first hand-back, reviews need no permission, and at most one question block remains, with the remaining count by group.",
            "Use the shared exact-tip merge gate for ordinary retirement; retire an unmerged superseded draft only within recorded authority, with fresh full-diff review, zero needed unexplained changes and verified recovery. Closed status alone never qualifies.",
            "Inventory unresolved unique local heads with tip, owner, reason and next action; when needed merges are explicitly authorized, inspect and verify the changes before landing, never blindly merge obsolete or unknown work.",
            "Preserve current/main workspaces, detached, dirty, foreign-active and explicitly kept candidates. Permit only the shared task-owned current-ref exception; preserve unique and recovery history, requiring verified private bundle migration for redundant recovery refs. Recheck disposition, recovery and identity before destruction.",
            "Enumerates all registered worktrees, branch-only candidates and filesystem directories under ~/conductor/workspaces and configured alternate roots, even after metadata and branch refs vanish; never relies only on listed worktrees’ common parent.",
            "Joins directories to canonical Git common-directory/origin and branch/HEAD or saved inventory evidence; city names, project basenames and matching branch names alone never prove ownership. Retains unknown mappings with reasons.",
            "Captures canonical mappings and du -sk sizes before deleting refs or metadata; preserves evidence outside deletion targets and blocks changed identities.",
            "Requires data-safety proof for every workspace removal, including ordinary worktrees and app archives: tracked files pass clean/merge checks, untracked and ignored paths are reproducible or safely preserved. Unknown files, databases or copied secrets block deletion without exposing contents.",
            "Requires equivalent saved identity, merge and data-safety proof for orphan or interrupted-deletion directories; missing metadata or refs never waive the gate. Idleness and root membership alone never authorize deletion.",
            "Uses Conductor app archive requests naming exact workspaces/paths for managed local workspaces; never bypasses management with git removal, recursive deletion or database mutation. Keeps them pending until app action and disk verification finish.",
            "Uses non-forced git worktree remove for ordinary registered worktrees; requires proven abandoned status, full safety gates and exact-path extra confirmation before manually removing unregistered filesystem residue. Forces removal, with no question, only for a registered folder whose Conductor row is archived, whose tip is proven and which holds only deleted tracked files and generated output.",
            "Re-reads Conductor state for pending workspaces at each later message and sweep start, and deletes newly archived sessions' proven refs without being told.",
            "Relies on Conductor's git.archive_on_merge (set by agent_runtime install --conductor) for merged-PR workspaces and asks for manual archive only of workspaces with no PR or an earlier merge; never enables delete_branch_on_archive.",
            "Canonicalizes paths without following outside symlinks; removes only confirmed owned aliases after their target decision. Preserves main clones/shared state and, by default, unique archived materials/history; explicit archive deletion follows its separate scope.",
            "Limits branch/worktree cleanup to this repo unless cross-repository scope is explicit; never deletes ~/conductor wholesale or enumerates remote-only branches for a purge.",
            "Routes task-owned ref-only closure in any repository to references/git-pr-deploy.md; preserving a current workspace is distinct from archiving it or reclaiming storage.",
            "Reconcile separate local-ref, remote-counterpart and workspace outcomes within task or requested repository scope, including branch-only leftovers and absent remotes; remote auto-deletion alone never proves local cleanup complete.",
            "Surfaces remote counterparts separately, reuses explicit remote-deletion authority or asks before writing, and proves each actual remote tip merged. Limits deletion to owned counterparts of local branches being removed.",
            "Verifies exact workspace trees, node_modules, build caches, dashboards, owned aliases and removed refs are absent; measures after-sizes and names pending/blocked paths. Ref deletion or an archive request alone never counts as reclaimed storage.",
            "Measures the whole explicitly requested disk-cleanup root and every category before and after, including archives, workspaces and repos across projects; reports removed paths, retained reasons and actual reclaimed size. Branch counts alone never satisfy disk cleanup.",
            "For ordinary disk cleanup, prunes verified inactive generated archive contents while preserving unique source, materials, designs, attachments and chat/app metadata. Never treats archive status, ignored status or a cache basename alone as proof of disposability.",
            "Requires canonical ownership and reproducibility evidence, no escaping symlinks, no active users or open files, exact keep-list exclusions and immediate pre-delete rechecks for every cache path; unresolved evidence or incomplete activity visibility blocks removal.",
            "Allows cache-only pruning in idle unmerged or dirty workspaces while preserving source, dirty files and branches; skips lifecycle gates and operations. Excludes current-workspace caches and requires explicit main-clone context for its caches.",
            "Treats explicit archive deletion as authorization to remove archived contents, including old source/evidence, without renewed permission or merge/reproducibility proof; requires exact canonical archive scope, keep-list exclusions, no active use/open files and no outside symlink traversal.",
            "Rechecks archive identity, scope and activity before deletion; preserves outside app/chat metadata and active managed workspace lifecycle. Records sizes/paths, verifies absence or retained exceptions, and re-evaluates remaining large categories within the authorized cleanup scope.",
            "Reuses bin/port-registry.sh and bin/kill-orphan-workers.sh; points to process.md and dev-server-hygiene.md for shared teardown rules.",
        ],
    },
    "skills/sk/skills/monitor-daily-health-conversion-capacity-errors/SKILL.md": {
        "mission": "Simon knows at a glance each morning whether anything broke, a paywall is hurting conversion or capacity is running out, with a cause and next step per red row.",
        "purpose": "Daily read-only health check for any repo with connectors; builds the repo's monitor block on first run, then runs, triages and tunes it.",
        "criteria": [
            "Read the matched manifest and references/connectors-setup.md before the first probe; prod stays read-only and nothing is sent or posted.",
            "On a first run, derive the generic block with --draft, find the repo's signals in source, verify every metric read-only, and save into the private manifest.",
            "Check every connector the engine has no probe for by hand with its own read-only tool.",
            "Pin each red, amber and unknown row to a root cause naming a commit, migration, config row or file:line, with onset and a second source, or say not proven and what was ruled out.",
            "Hand back one table: status, finding, evidence, root cause, next step; save proven causes into monitor.causes.",
            "Tune false alarms and missed problems back into the manifest; hand fixes to /sk:work-investigate-and-fix.",
        ],
    },
    "skills/sk/skills/meta-report-standup-weekly/SKILL.md": {
        "mission": "Simon walks into standup with a 45-second script he did not have to write or remember.",
        "purpose": "Builds spoken weekly outcomes / Today / Next standup bullets from the record "
                   "rather than from Simon's memory.",
        "criteria": [
            "Default to the previous Monday through now on Mondays, and this Monday through now on Tuesday through Sunday, in the session timezone. Explicit windows override; never substitute the previous working day.",
            "State the exact date range, apply it to all three sources with complete pagination, and label outcomes This week, Last week or the explicit range to match. Count merged work only inside that window.",
            "NEVER asks Simon what he did. git log, gh pr list and Linear list_issues hold it, so a "
            "question about the week's work is the one failure that makes the skill pointless.",
            "Runs git log with --all. Simon's branches live across several Conductor worktrees that "
            "share one object store, and a default-branch-only log reports a week of work as nothing.",
            "Treats an empty git log as a failed author filter until proven otherwise, by listing the "
            "distinct authors in the window. A silent quiet week is the wrong report, not a short one.",
            "Says shipped or merged ONLY for a PR whose mergedAt is non-null. A draft PR read out as "
            "shipped is a claim Simon has to retract in front of the team.",
            "Emits one bullet per outcome, never per commit, and drops merge, formatting, "
            "static-analysis, test-only and docs-only commits outright.",
            "States blockers, or says the words no blockers. An omitted blocker line reads as a "
            "hidden one.",
            "Holds at 15 bullets and roughly 12 words each, because the output is read aloud in one "
            "breath per line and rules/copy-quality.md governs it as spoken copy.",
            "Hands back a script and posts it nowhere.",
        ],
    },
    "skills/sk/skills/setup-connectors/SKILL.md": {
        "mission": "A project's tools reach the right account first try, and Simon does only the steps nobody else can.",
        "purpose": "Guided connector setup, doctor, and migration audit.",
        "criteria": [
            "Reads the registry through bin/connector_registry.py and resolves routes before setup. Asks before creating or reading a credential.",
            "Routes official Slack setup and requested completion messages through the shared connector catalog, preserving per-message authorization and unfinished notification tasks.",
        ],
    },
    "skills/sk/skills/work-ask-reply-in-full-before-after-artifact/SKILL.md": {
        "mission": "Simon understands each tradeoff and can return his choices without retyping them.",
        "purpose": "Explain confusing replies and proposals through compact before/after cards.",
        "criteria": [
            "Build through decision-artifact.py and the shared frame; show a 2–5 word title and one tradeoff of at most 25 words, with details collapsed.",
            "Every card whose option changes or keeps a visible surface carries real desktop and 390px images in before and after; a not-built AFTER is a labelled Preview from app code or a screenshot overlay.",
            "Infer feedback: true for proposals requesting choices or comments; one corner Generate & copy action copies current inputs for chat, with a truthful fallback. Keep pure mockup and board viewers read-only.",
            "Retain complete source and legacy runtime metadata inertly for CLI extraction and deterministic rebuilding; new specs need no control schema.",
        ],
    },
    "skills/sk/skills/work-ask-reply-tldr/SKILL.md": {
        "mission": "Simon reads the first line of a reply and has what he needs — a decision, an attention item, or a flat yes/no — with nothing he must scroll past.",
        "purpose": "A response-format toggle that makes every subsequent reply bare-metal TLDR — only the answer, open decisions, blockers and attention items — until Simon says otherwise.",
        "criteria": [
            "Leads with the answer or the decision owed in ONE line, then at most a few short bullets.",
            "Includes only the direct answer, open decisions, blockers, what needs his input, and attention items (a risk or surprising result); cuts narration, recap, celebration and restated headings.",
            "Answers a closed question flatly ('none' / 'done' / '1 left: X') with no status essay in front of it.",
            "Stays active across replies until Simon asks for verbose/full detail, then returns to terse.",
            "Reuses rules/communication.md as the source of truth (answer-first, questions-at-END, five Ws) rather than restating it.",
        ],
    },
    "skills/sk/skills/work-humanize-copy-side-by-side/SKILL.md": {
        "mission": "Simon rewrites an interface's copy in his own voice against the real screen, and "
                   "every reworded string lands back in the source it came from, verified, while "
                   "untouched copy is left exactly as it was.",
        "purpose": "Extracts every user-facing copy string from a TSX interface, shows the real screen "
                   "1:1 beside editable fields seeded with the originals in one self-contained HTML "
                   "file, and writes the reworded strings back into the .tsx/.ts source.",
        "criteria": [
            "Extracts only user-facing copy from the target TSX/TS — JSX text and copy-bearing props "
            "(aria-label, alt, placeholder, title, label) and copy-bearing data/const files — never "
            "URLs, class names, styles, ids or route literals.",
            "Records each string with a file-unique anchor (original plus enclosing context and "
            "occurrence) so apply re-finds the exact location, and de-duplicates by (file, anchor), "
            "never by text, so identical words in two places stay two entries.",
            "Shows the LEFT pane as the real rendered screen captured 1:1 — a compressed screenshot "
            "with numbered anchors — never a reconstruction rebuilt from the extracted markup.",
            "Seeds every RIGHT-pane field with its original text and shows the original alongside, so "
            "an untouched field already holds the original and apply is a blanket overwrite with no "
            "diffing.",
            "Pairs each right-pane field to its left-pane anchor by matching number and hover/focus "
            "highlight, and scrolls the anchor into view on focus.",
            "Ships ONE self-contained HTML file whose entire state is the embedded #spec data island; "
            "nothing user-visible exists outside #spec, reusing /sk:ship-mockup-before-after's "
            "mechanics rather than restating them.",
            "Writes each reworded string back at its anchor with a unique match, STOPS and reports any "
            "entry whose match is not unique rather than guessing, and preserves JSX/TS escaping so no "
            "rewrite breaks the parse.",
            "Verifies every written value is present in source and runs the project build and lint "
            "after applying, reporting strings extracted / reworded / written / skipped with each "
            "skipped entry's reason.",
            "Leaves the words to Simon: seeds voice suggestions from rules/copy-quality.md only on "
            "request and never auto-rewrites his copy.",
        ],
    },
    "skills/sk/skills/claude-config-sync/SKILL.md": {
        "mission": "Every config change reaches the public mirror, and no secret or real account ever does.",
        "purpose": "Safe commit and push of this repo.",
        "criteria": [
            "Reads the real diff for secrets; a --stat summary never clears a file.",
            "Lands owned validated repairs under standing or explicit authorization; activates a clean compatible live checkout and removes only verified merged worktrees and branches.",
            "Applies the main-only completion rule from rules/config-repo.md and records final local and origin head inventories.",
            "Stops on a real account, org name, project name or email in the diff, because the remote is public.",
            "Never bypasses the pre-commit gate with --no-verify.",
            "Commits with -F from a written file, never -m. references/git-pr-deploy.md owns that "
            "rule and the message shape; this skill points at it instead of carrying a second, "
            "contradicting example.",
        ],
    },
    "skills/sk/skills/claude-config-update/SKILL.md": {
        "mission": "A correction Simon makes once is a rule Claude follows next time, in the right file, at the right altitude.",
        "purpose": "The one sanctioned path to change ~/.claude: routes a correction or a new part to its right home.",
        "criteria": [
            "Resolves standing or explicit authorization before applying; asks only for decisions outside that scope.",
            "Drafts tracked changes in a config-update/<slug> worktree from origin/main; reviews, validates and secret-scans before landing.",
            "Existing authorization covers validation, main, push, safe activation and cleanup without another commit or merge question.",
            "Retains unresolved or blocked changes with their owner and evidence; resumes authorized work at the next task boundary without blind merging.",
            "Treats a pasted correction as illustrative material, never as a work order.",
            "Frees rules/ budget only by moving how-to into a referenced owner; no instruction, example or TEST is deleted to fit.",
            "Generalises the lesson; never narrows a skill to one task.",
            "Routes edits and new parts through the canonical workflow, read directly when no native Skill tool exists; applies existing authorization without a sentinel or tool receipt.",
            "Grounds every factual claim (a measured figure, a threshold, how another part behaves) "
            "against its source file this run, never restating from memory.",
            "Surfaces anything else the change needs from Simon, with copy-paste steps to get it, in "
            "the same gate block, then waits.",
            "Updates config_contracts.py and routing_scenarios.py alongside the edit, then runs the "
            "suite and loops until clean. Tests that do not grow with the config stop protecting it.",
            "Records a late or deferred lesson in the worktree's .context/config-lessons.md, folds every "
            "open entry on a branch's concern into that branch before it lands, and gives each entry a verdict.",
        ],
    },
    # your work-skills plugin (e.g. sk-work) is job-specific, lives untracked in work/, and is outside this registry by design.
    # See TRACKED_SKILL_PLUGINS in hooks/config-contract.test.py for why.
    # --- Hooks (wired in settings.json) --------------------------------------------
    "hooks/worktree-path-guard.py": {
        "mission": "An edit from inside a worktree never silently lands in the main checkout by using the main repo's absolute path, and parallel sessions never edit the live ~/.claude checkout's shared working tree.",
        "purpose": "PreToolUse: asks (not a hard deny) before an Edit/Write from a worktree session that targets the main checkout or a sibling worktree; denies an Edit/Write into a tracked file of the live ~/.claude checkout and names the config-update worktree command.",
        "criteria": [
            "Fires only when the session cwd is under `<main>/.claude/worktrees/<name>/` AND the "
            "resolved target is under the main root but OUTSIDE this worktree (the main tree or a "
            "sibling worktree); emits permissionDecision 'ask', never 'deny', since a main-checkout "
            "edit from a worktree is occasionally intentional.",
            "Never fires when not in a worktree, for a target under this worktree, for a relative "
            "path (resolved against the worktree cwd), for a target outside the repo (~/.claude, "
            "/tmp), or for a non-edit tool.",
            "Fails open on a malformed payload or an unresolvable cwd/path. A guard that breaks the "
            "session gets switched off.",
            "Denies, from any session, an Edit/Write whose resolved target is under the live ~/.claude "
            "checkout, outside its .claude/worktrees/, and not git-ignored there; the reason names the "
            "config-update worktree command. Ignored areas (projects/ memory, work/, .context) stay open. "
            "hooks/worktree-path-guard.test.py covers both checks and runs inside the contract suite.",
        ],
    },
    "hooks/git-commit-guard.py": {
        "mission": "Claude never commits or pushes on the default branch, never merges a PR into it off a general instruction, and never commits with -m or a heredoc.",
        "purpose": "PreToolUse: blocks a default-branch commit/push, a gh pr merge, and an inline -m/heredoc commit.",
        "criteria": [
            "Blocks `gh pr merge` (into the remote default branch) unless CLAUDE_ALLOW_PR_MERGE=1 "
            "(env or inline); a general 'merge everything'/'continue' is never a yes for a specific "
            "merge, and the deny requires explicit per-PR confirmation plus a CI-green check.",
            "Blocks commit/push on main/master unless CLAUDE_ALLOW_MAIN_COMMIT=1 is set in the "
            "hook's env OR prefixed inline on the command. In the ~/.claude config repo and its "
            "worktrees (identified by shared Git storage) a commit passes, and a push to main passes "
            "with no confirmation only when every pushed head was recorded by bin/config-land-check.py "
            "and fast-forwards the remote main; a forced, deleting, piped, variable-path, mixed or "
            "unverified push keeps the block. Every other repository keeps the unchanged guard.",
            "Blocks git commit with -m/--message or a heredoc (the -F-only rule) unless "
            "CLAUDE_ALLOW_COMMIT_M=1, and does not misfire on --amend/--no-edit.",
            "Matches the plain Bash tool and parses the command; fails open on a malformed payload.",
            "Judges only what the shell runs: the command word (after env assignments and prefixes) "
            "must be git/gh, with quoted strings and heredoc bodies masked, so a note or printf that "
            "merely names a push never fires. A push deny names the branch pushed TO. "
            "hooks/git-commit-guard.test.py pins both directions.",
        ],
    },
    "hooks/background-process-guard.py": {
        "mission": "No persistent background process is installed without Simon being asked first.",
        "purpose": "PreToolUse: blocks installing a cron/launchd/systemd persistent process.",
        "criteria": [
            "Blocks the install/enable verbs only (crontab install, launchctl load, systemctl "
            "enable, LaunchAgents/Daemons writes); list and remove pass.",
            "Overridable with CLAUDE_ALLOW_DAEMON=1 when Simon asked for that process.",
            "Fails open on a malformed payload.",
        ],
    },
    "hooks/emulate-viewport-guard.py": {
        "mission": "An emulated phone viewport always fits the test window, so the tester can reach the page bottom.",
        "purpose": "PreToolUse: denies mcp__chrome-devtools__emulate with a viewport taller than the test window shows.",
        "criteria": [
            "Denies a viewport whose height (width when `landscape`) exceeds MAX_VIEWPORT_H, the one "
            "source of the cap (default window height minus browser chrome); the reason names the "
            "fitting viewport, the taller-relaunch route and references/browser-debugging.md § Fit the window.",
            "CLAUDE_TEST_VIEWPORT_MAX_H raises the cap for a taller launched window.",
            "Allows an absent viewport (clearing the override); fails open on a malformed payload.",
            "HOOK_ROUTING cases in contracts/routing_scenarios.py pin deny and allow decisions.",
        ],
    },
    "hooks/outbound-message-guard.py": {
        "mission": "A teammate or other reader gets a message Simon sends, or Claude sends for him, that they can act on from its first lines, without Simon asking for TLDR again.",
        "purpose": "PreToolUse: denies a Slack or Gmail send, reply, forward or draft over the TLDR cap for a message to someone else; --check measures a draft for routes the hook cannot see.",
        "criteria": [
            "MAX_LINES (5, matching rules/communication.md § Answer first) and MAX_WORDS (100) are the one source of the cap; a leading greeting, a trailing sign-off (a thanks line alone or followed by a name line) and quoted reply lines are not counted.",
            "Fires only on a send-shaped Slack or Gmail action (send, reply, post, schedule, forward, draft); reads, searches, canvases, labels, deletes and a draft-id-only send pass. Plain text, forwardText and htmlBody are measured.",
            "The deny reason names the fix (ask on line 1, at most 5 lines, cut rather than split), the one-shot override and references/tldr-report-formats.md § Message for someone else.",
            "A non-empty .context/long-message-ok under the call's cwd, holding Simon's own words asking for length, allows exactly one over-cap send and is deleted; an empty file allows nothing.",
            "--check <file|-> prints ok and exits 0 within the cap, and prints the counts and exits 1 over it. Fails open on a malformed payload.",
            "hooks/outbound-message-guard.test.py and HOOK_ROUTING cases in contracts/routing_scenarios.py pin both directions.",
        ],
    },
    "hooks/secret-echo-guard.py": {
        "mission": "A credential value never lands in the transcript because a command printed it, while using that credential stays frictionless.",
        "purpose": "PreToolUse: denies a command whose normal output is a credential value, unless the output is consumed.",
        "criteria": [
            "Denies only commands that print a value, each verified against the tool's own help or docs: "
            "stripe config --list and listen --print-secret, gh auth token and status --show-token, "
            "gcloud auth print-access-token and print-identity-token, aws configure export-credentials "
            "and get of a secret key or session token, firebase login:ci, security find-generic-password "
            "-w/-g and dump-keychain -d, op read and item get --reveal, a bare env/printenv dump.",
            "Denies printed process arguments, where a launcher key can sit: ps with default columns, -O or a "
            "command/args field and no -c, and pgrep -f with -l or -a; ps metadata fields, ps -c, pgrep -l "
            "and pgrep -f PIDs pass (references/dev-server-hygiene.md § Private process inspection).",
            "Allows a consumed value: redirected to a file, piped to a consumer, or captured by $(...) "
            "into an assignment or another command's argument. Help, status and list verbs pass.",
            "Judges what the shell runs, not text: awkward spacing, an absolute path, &&, ;, pipes, "
            "sh -c, eval and xargs are parsed; a quoted string or heredoc body naming a command never fires.",
            "Never blocks reading a secret FILE (rules/security.md); fails open on a malformed payload.",
            "hooks/secret-echo-guard.test.py pins both directions.",
        ],
    },
    "hooks/config-status.sh": {
        "mission": "Every session receives the automatic repair policy and can resume owned unfinished config work without Simon invoking it.",
        "purpose": "SessionStart: injects the repair policy and reports config state without mutating user work.",
        "criteria": ["Always injects the repair policy for a config repository, including a clean checkout; the hook performs no repairs, commits or merges.",
                     "Names every config-update/* branch that is not on origin/main at each session start, "
                     "so the active session can reconcile ownership and resume authorized work without a generic land-or-drop question."],
    },
    "hooks/orphan-worker-sweep.sh": {
        "mission": "No dead framework worker keeps burning a core in a workspace nobody is watching.",
        "purpose": "SessionStart: reports orphaned framework workers burning CPU.",
        "criteria": ["Detects and reports. Never kills anything.", "Silent when nothing is found.",
                     "Distinguish eligible framework families from retained agents; never recommend signalling an agent whose task owner is not proven ended."],
    },
    "hooks/port-registry-sweep.sh": {
        "mission": "A session sees claimed ports and heavy capacity before binding or building, without a noisy idle web startup.",
        "purpose": "SessionStart: reconciles the shared port registry and names who holds which port, "
                   "the heavy lease and each simulator claim.",
        "criteria": [
            "Reports only. Never kills a process and never releases another session's claim; its note allows a shutdown only through a printed reclaim-sim command for an ended owner.",
            "Silent when no port, heavy lease or simulator claim is active and the workspace holds no native project.",
            "Prints fail-fast exit-75 capacity instructions in a native project and names an active lease in any project; the helper bounds its simulator probe.",
            "Surfaces every watchdog and idle-stack line from capacity status in any project; clear watchdog, zero-simulator and dev-stack count lines stay silent.",
            "Reconciles port claims on session start but never auto-reaps a heavy lease or simulator claim.",
        ],
    },
    "hooks/retro-trigger-log.sh": {
        "mission": "A guard that fires too often is visible as a pattern, so it gets fixed rather than switched off.",
        "purpose": "SessionEnd: records per-session counts of guard denials, for class-level review.",
        "criteria": [
            "Writes one JSON line and nothing else. Never proposes, prompts, or edits.",
            "Silent when nothing triggered, and when the transcript is missing.",
            "Routes its line through the shared writer to the metrics store, or the local outbox when "
            "no project is configured, or the legacy log when no interpreter is present. Never both.",
            "Stays on SessionEnd. A Stop hook would have to BLOCK to be seen, and blocking Stop "
            "hooks are a documented session-burner with a model-set marker.",
            "Records counts and signature names only. Never prompt text or file contents.",
        ],
    },
    "hooks/session-connectors.sh": {
        "mission": "An expired connector surfaces at session start, before a task depends on it.",
        "purpose": "SessionStart: flags a connector needing re-auth or not set up.",
        "criteria": ["Read-only. Never provisions."],
    },
    "hooks/session-identity.sh": {
        "mission": "The work/personal boundary values stay in context every session, so genericising the tracked files never costs adherence.",
        "purpose": "SessionStart: injects the identity overlay's values into context as a terse block.",
        "criteria": [
            "Reads the untracked identity.local.json; injects only its values, no logic.",
            "Absent overlay injects nothing and prompts the user to create it.",
        ],
    },
    "hooks/intent-ledger.sh": {
        "mission": "Every ask Simon makes survives verbatim, so no plan finishes with a point silently missing.",
        "purpose": "Records complete redacted asks, prompts gauntlet updates and checks reconciliation freshness at hand-back.",
        "criteria": [
            "The only hook that writes into a project, because the record has to sit beside the "
            "branch it describes. That inversion is the risk, so the refusals ARE the contract: "
            "not a git repo, $HOME, an unwritable dir, a git-TRACKED path, a path that is not "
            "git-ignored. Inside ~/.claude it REDIRECTS to .intent-ledger/ rather than refusing, "
            "because check-ignore returns 0 for every path in that allowlisted repo and so cannot "
            "be the control there.",
            "The only WRITER of the ledger, both directions. The model appends through `note`, "
            "never Edit or Write: a whole-file rewrite from a second chat in the same Conductor "
            "workspace deletes every ask appended since it read.",
            "ACTIVE is announced only AFTER a record is durably on disk. Every silent refusal is "
            "safe only because of that ordering; without it the model creates the ledger by hand.",
            "Keep full prompts and remind the agent to reconcile each into the gauntlet plan; preserve requirements beyond 6000 characters.",
            "Combine simultaneous submit notices into one valid hook JSON document for native host parsing.",
            "Stay silent and write nothing for a delegated worker (AGENT_DELEGATED_WORKER=1) in every mode.",
            "Require reconciliation after the newest ask, plan or pivot; ignore headings inside prompt fences and preserve stop_hook_active plus an unchanged-snapshot loop guard. Check freshness, never semantic completion.",
            "At Stop, block once per request with decision block to run the after-run analysis when session-performance.py due reports enough new work since the workspace's last published report; only after reconciliation, and on a stop_hook_active continuation only when this hook's own reconciliation block caused it. A model-set marker never decides it.",
            "Redacts credential-shaped values at capture with the regex from dotfiles/secret-scan.sh, "
            "character for character. A divergent copy is the drift one-owner-per-concern exists to "
            "stop.",
            "Deliberately inverts retro-trigger-log.sh's 'never prompt text' posture, and pays for "
            "it with the refusals, the redaction, and planning-and-tracking.md's ban on promoting "
            "verbatim prompts out of the worktree. logs/intent-reconcile.jsonl keeps the ORIGINAL "
            "posture: counts and enums only, never prompt text.",
            "One ledger per session: resolves its root through bin/session-root.sh, so a shell that "
            "moved into a worktree nested under the session's root still appends to that root's "
            "ledger. `note` reads the session id from CLAUDE_CODE_SESSION_ID because it has no payload.",
            "`note` exits 2 when its source file is the ledger (same inode, any spelling or symlink): "
            "`cat ledger >> ledger` never ends and once grew a ledger to 170 GB. The refusal also "
            "spares the ledger from the `rm -f` of the source.",
            "Ship gate, the mechanical backstop for rules/process.md's harness-on-every-pushed-PR rule: "
            "PostToolUse `push` records the repo, branch and head of a successful `git push` to a non-default "
            "branch in session state, and records nothing for main or master, a delete, tags, a repo inside "
            "the config repo, or a delegated worker. `gate <branch> <sha|HEAD> PASS|BLOCKED|N/A [light|standard|deep] [reason]` "
            "appends the result to the ledger (BLOCKED, N/A and a light or standard PASS need a reason). Stop blocks once per set of "
            "open pushes, also on a stop_hook_active continuation, until each branch's newest pushed head has "
            "a gate record; a record for an older head does not count, and a gate line inside a prompt fence "
            "never counts.",
            "`gate PASS` for a branch with an open PR on a GitHub origin records only when bin/pr-landing-gate.py "
            "exits 0, else exits 1 printing the missing rows; a failed PR lookup refuses PASS. BLOCKED, N/A, "
            "no open PR and non-GitHub origins are unchanged.",
            "Skip a prompt made only of harness-injected blocks (<task-notification>, "
            "<system-reminder>): it records nothing and prompts no update, so it cannot reopen Stop. "
            "A prompt with any text left after removing them is recorded verbatim, blocks included.",
        ],
    },
    "hooks/task-intake.sh": {
        "mission": "Simon gets one recoverable session record without repeated approval interviews.",
        "purpose": "UserPromptSubmit advisory initializes or reuses the task dashboard and points to task routing.",
        "criteria": [
            "Initialize one ordinary plan and canonical dashboard idempotently; resolve the session root through bin/session-root.sh even after a nested-worktree cwd change.",
            "Use existing explicit or standing authorization; ask only unresolved consequential choices, missing access, production writes or paid calls.",
            "Never deny Agent, Task or Workflow and require no AskUserQuestion callback, approval stamp, sentinel or arbitrary prompt-length authority.",
            "Ignore short acknowledgements and automated background notifications. Preserve CLAUDE_INTAKE_GATE=off as the manual kill switch; give a delegated worker (AGENT_DELEGATED_WORKER=1) only a boundary notice, never a plan or routing instruction.",
            "Run tests only with isolated session-root/workspace paths; stale former gate markers cannot affect authorization or rearm work.",
        ],
    },
    "hooks/work-resource-guard.sh": {
        "mission": "Work and personal service credentials never cross, model-API keys included; inference stays on the shared subscription and the pal MCP is the only API route.",
        "purpose": "Enforces the work/personal boundary on Bash and MCP tools.",
        "criteria": [
            "Allow the shared Codex subscription in either project boundary. Allow the pal MCP only when one boundary declares pal and it is the repo's own; deny it when undeclared, in both roots, jq is missing or a record is unreadable. Deny every shell call to a model-API host in every repo.",
            "Data-driven from the connector registry through bin/connector_registry.py, not hard-coded; the loader runs only for MCP tools and bare CLI profile checks.",
            "git commands stay unblocked so staging AND inspection always work, including a path "
            "that carries the other boundary's name. A compound that also invokes another CLI is "
            "not exempt, so git cannot launder the command after it.",
            "A rule fires on an INVOCATION, never on a name appearing in prose; "
            "hooks/work-resource-guard.test.py pins both directions.",
            "A command-position wrapper (exec, env, command, nohup, time, sudo) does not hide a CLI "
            "from the profile rule, and an explicit non-live key (--api-key, STRIPE_API_KEY=) counts "
            "as pinning the account.",
            "A CLI whose default profile belongs to the other boundary is denied when "
            "unpinned, not just when the wrong profile is named explicitly.",
            "Reads shared-account routes too, so a shared route's boundary is enforced "
            "exactly like a project route's, and never leaks a secret value.",
        ],
    },
    # --- Git hooks -----------------------------------------------------------------
    ".githooks/pre-commit": {
        "mission": "No secret ever reaches a commit, in any repo using this hook.",
        "purpose": "Blocks any commit staging a secret.",
        "criteria": ["Delegates to dotfiles/secret-scan.sh. Never bypassed with --no-verify."],
    },
    ".githooks/commit-msg": {
        "mission": "Every commit subject is navigable in `git log --oneline` a year later.",
        "purpose": "Rejects a non-conventional commit subject.",
        "criteria": [
            "Checks the SUBJECT only. Says nothing about the body.",
            "Accepts git's own generated messages (merge, revert, fixup).",
            "The must-ACCEPT half matters more: a false rejection pushes Simon to --no-verify, "
            "which also skips the secret gate.",
        ],
    },
    # --- Engine scripts ------------------------------------------------------------
    "bin/connectors-provision.sh": {
        "mission": "A new project's connectors come up from its registry record alone, with no bespoke script per project.",
        "purpose": "Generic connector engine driven by the connector registry loader.",
        "criteria": [
            "Reads servers registered under BOTH the worktree and the main worktree path.",
            "Generic. Per-project detail stays in the registry; matching and layering live only in bin/connector_registry.py.",
        ],
    },
    "bin/connector_registry.py": {
        "mission": "Every connector reader sees the same registry, and an agent reaches a capability through the first working route without asking Simon while one remains.",
        "purpose": "The one connector loader, route resolver, health recorder and legacy migration.",
        "criteria": [
            "Read only the roots named by connectorRoots (or CLAUDE_CONNECTOR_ROOTS); a route's boundary always equals its root's.",
            "Resolve returns only the session boundary's routes: unblocked first, open circuits last, routes serving the project before others, proven before untested, then declared order.",
            "Never exclude a same-boundary route for scope; record writes health.json under a lock, mode 600, same boundary only.",
            "Migration keeps every legacy project and connector field reachable; check-migration fails on any missing value.",
            "Python 3.9 standard library only, so the /usr/bin/python3 guard can import nothing else.",
        ],
    },
    "bin/install-third-party-skills.sh": {
        "mission": "The third-party skills skill-stack.md promises are actually installed and current.",
        "purpose": "Clones and updates the third-party packs skill-stack.md relies on.",
        "criteria": [
            "A failed update reports WHY and exits non-zero; it never prints a generic SKIPPED.",
            "Sets core.fileMode=false on clone, or mode bits block the next update.",
        ],
    },
    "bin/port-registry.sh": {
        "mission": "Sessions that cannot see each other still never claim the same port.",
        "purpose": "Machine-wide coordination of local dev ports between sessions that cannot see "
                   "each other.",
        "criteria": [
            "A row is a CLAIM, not the truth: every read path reconciles against real listeners "
            "first, and a listener-less row past the grace window is dropped.",
            "The grace window is load-bearing — a claim is made BEFORE the bind, so reaping on "
            "'no listener' alone would delete a valid claim mid-boot.",
            "Never kills a process and never releases another session's claim. Conflicts are "
            "reported to Simon, who decides.",
            "sessions prints the working directory of every live Claude/Codex session and writes nothing; match only executable basenames claude and codex, never process arguments or environment values.",
            "owns-workspace tests live cwds from stdin using the same predicate as reconciliation; protect physically nested linked worktrees only with a matching Git common directory, never siblings or unrelated nested repositories.",
            "Report failed process probes, missing session cwds and failed Git probes for candidate nested owners as unknown; preserve port claims and refuse stack reclamation until ownership is known.",
            "Require confirmed workspace absence and absent session ownership before reap reports a kill candidate. Retain inaccessible paths, broken links and deleted children of live parent checkouts; can-reap-workspace repeats the same check before signalling.",
            "A row whose recorded workspace is confirmed deleted and has no listener is dropped on every "
            "read path, inside or past the grace window and whatever session-liveness detection says: a "
            "deleted path has no cwd to match, so its owner cannot return and no caller could release it "
            "(release frees only the caller's own session label). Only workspace_missing exit 0 counts; "
            "a broken link, permission failure or relative path keeps the claim, and a listening port is "
            "always held.",
            "Exit codes stay meaningful: 3 held by another live session, 4 a listener nobody "
            "claimed. The EXIT trap must preserve them.",
            "Release surfaces who was waiting, so the hand-off between sessions reaches Simon. It "
            "reads the raw rows BEFORE reconciling: the correct sequence is kill-then-release, which "
            "means the row is already reaped by dead-pid when release runs, and reconciling first "
            "silently lost the hand-off in the only path anyone actually uses.",
            "A lane belongs to the SESSION, not to the process: a row with no listener past the grace "
            "window SURVIVES while a live Claude session is working in that workspace, because its "
            "server merely died and it will boot again. This lives in reconcile_into, which every read "
            "path calls — a rule applied in `reap` alone meant the next `list` silently undid it.",
            "Session liveness is matched on the BASENAME of the process command, never on its "
            "arguments. `pgrep -x claude` misses Conductor-launched sessions because ps reports their "
            "full path, and arg matching would catch the Claude desktop app and any shell mentioning a "
            "~/.claude path — the defect that retired hooks/security-guard.py.",
            "`reap` adds only what reconcile cannot see and stays opt-in, so the report-only "
            "SessionStart hook keeps calling reconcile and mutates nothing it shouldn't. It never kills; "
            "a workspace-gone row whose server still listens is KEPT and exits 5 for the caller, because "
            "dropping it would hand a bound port to the next session.",
            "init_scratch runs in the PARENT shell. `x=\"$(scratch f)\"` runs scratch in a subshell, so "
            "creating the temp dir there loses the variable and the EXIT trap cleans nothing — that left "
            "963 abandoned temp dirs before it was found.",
        ],
    },
    "bin/native-slot.sh": {
        "mission": "Simon's existing native callers share the same heavy-work leases as every other local project without losing their familiar commands.",
        "purpose": "Thin compatibility frontend for bin/local-capacity.py.",
        "criteria": [
            "Delegate run, list, claim-sim, release-sim, reclaim-sim and jobs to bin/local-capacity.py; forward bounded --wait-min with default 5. Never create a second lock or simulator ledger.",
            "Return exit 75 before the wrapped command starts when the shared leases, legacy bridge or load gate refuses admission.",
            "Keep a dead or interrupted holder visible for explicit inspection; never auto-reap another session's claim.",
            "Expand every array that can be empty as ${ARR[@]+\"${ARR[@]}\"}; macOS /bin/bash 3.2 treats a bare empty \"${ARR[@]}\" as unbound under set -u.",
            "Use an isolated state root in offline tests and boot no simulator.",
        ],
    },
    "bin/port-registry.test.sh": {
        "mission": "A deleted workspace can never hold a port lane, and a live one never loses its lane.",
        "purpose": "Offline reconcile checks against a temporary registry file and unbound ports.",
        "criteria": [
            "Asserts a claim for a deleted workspace with no listener is dropped on list, inside and past the grace window.",
            "Asserts a claim for an existing workspace inside the grace window is kept, an unverifiable path keeps its claim, and a bound port is held even when its workspace is gone.",
            "Uses PORT_REGISTRY_FILE under a temporary directory; never reads or writes the real registry.",
        ],
    },
    "bin/native-slot.test.sh": {
        "mission": "A compatibility change cannot bypass the shared lease or silently take an orphaned device.",
        "purpose": "Offline frontend checks against a temporary capacity root.",
        "criteria": [
            "Asserts a second caller is deferred with exit 75 while a live holder runs and starts no command.",
            "Asserts an orphaned holder blocks admission until explicit inspection and release.",
            "Asserts another session's simulator cannot be claimed or released, and a second simulator is refused with exit 75 while one is claimed; boots no simulator.",
            "Asserts reclaim-sim exits 1 for a live claim owner and succeeds for an ended one, and status prints the reclaim command only for the ended owner.",
            "Runs the frontend under /bin/bash with LOCAL_CAPACITY_ROOT unset and a temporary HOME, so an empty-array regression fails here.",
        ],
    },
    "bin/session-root.sh": {
        "mission": "A session keeps ONE plan and ONE ledger for its whole run, so Simon never finds his asks split across two records.",
        "purpose": "Remembers the first git root a session resolved and answers it while the shell is "
                   "in that root or a worktree nested under it.",
        "criteria": [
            "The single owner of the rule: hooks/task-intake.sh and hooks/intent-ledger.sh both ask "
            "it and neither re-derives it.",
            "A shell inside a worktree nested under the remembered root answers the remembered root. "
            "A shell outside it re-homes the session to the new git root.",
            "A session that STARTS in a nested worktree owns that worktree: the record is per session id.",
            "An empty session id, or a directory outside git, is answered without writing a record.",
            "Strips a session id to letters, digits, dot, underscore and hyphen before using it as a "
            "file name.",
            "Honors CLAUDE_SESSION_ROOT_DIR so tests never write the live records; prunes records "
            "older than 14 days.",
        ],
    },
    "bin/session-root.test.sh": {
        "mission": "A change to the session-root rule cannot split a session's plan or merge two sessions' records without a failing check.",
        "purpose": "Checks for session-root.sh against a temp repository with a nested worktree.",
        "criteria": [
            "Asserts the nested-worktree case, the starts-nested case and the re-home case separately.",
            "Asserts a crafted session id cannot write outside the state directory.",
        ],
    },
    "bin/port-slot.sh": {
        "mission": "A worktree gets its own port lane, so Simon can run several stacks without editing config each time.",
        "purpose": "Gives a worktree its own LANE of dev ports so several sessions can run stacks at "
                   "once, and self-heals what a dead session left behind.",
        "criteria": [
            "Owns the deterministic half only: pick a lane, arbitrate it, sweep, record. It never "
            "decides which env var feeds which service and never boots anything — that is project "
            "judgement and belongs to the skill.",
            "Claims LAZILY and sweeps EAGERLY. A run that never boots a server must never leave a "
            "registry row, which is what stops rows accumulating across a day of sessions.",
            "Releases this workspace's previous lane before claiming a new one. A slot change that "
            "leaves two lanes claimed is the accumulation this is built to prevent.",
            "Stop only servers with confirmed deleted workspaces and absent owners. Signal family-first, then rescan the port. Retain every live or unresolved owner and every listener nobody claimed.",
            "Recheck every candidate through port-registry can-reap-workspace immediately before signalling; a failed directory or ownership lookup never authorizes a kill, even when another row made reap exit 5.",
            "Base ports are discovered, never hardcoded, and a cached map whose workspace field does "
            "not match this worktree is REJECTED. Conductor copies .env* into new workspaces, so an "
            "inherited map is a real event and trusting it boots a fresh workspace on another lane.",
            "Keeps no state outside the worktree and its own trimmed log. State inside the worktree is "
            "what makes an orphaned record under ~/.claude structurally impossible.",
            "Its log RECORDS ONLY: it routes the run line through the shared metrics writer (or the "
            "self-trimming local log when no interpreter is present) and must never block, fail or "
            "alter a run.",
            "The helper only records evidence; the active session evaluates recurring friction under rules/self-healing-config.md without the helper editing config.",
        ],
    },
    "bin/test-browser.sh": {
        "mission": "Every browser Claude opens is visibly Simon's test browser, so he never clicks in the wrong window.",
        "purpose": "Resolves the newest cached Chrome for Testing and launches it with remote debugging on a chosen port, profile and window size.",
        "criteria": [
            "Resolves the highest chromium-<n> build at run time; no versioned path is hard-coded.",
            "Never adopts a port held by another browser: exits 5 when the listener is not Chrome for Testing, and exits 4 with the install command when no build is cached.",
            "Reuses a Chrome for Testing already on the port instead of starting a second one.",
        ],
    },
    "bin/kill-orphan-workers.sh": {
        "mission": "An orphaned worker is cleared without killing a dev server someone is using.",
        "purpose": "Clears eligible framework families and reports uncertain agent candidates.",
        "criteria": [
            "Keep full arguments internal to candidate matching; list, dry-run, termination reports and the session hook expose only candidate metadata and category, never argument values.",
            "Exclude live-parent roots; collect and signal descendants only from eligible framework roots, never from report-only agent candidates.",
            "Burns-only for framework workers: a next/jest/vite worker is killed at 20%+ CPU and 5+ minutes old and inside a git checkout, since a live detached server leaves idle ones.",
            "Retain agent-class candidates at PPID 1 and 5+ minutes old: parent death and age do not prove task abandonment. Without an authoritative ended-task receipt, list and rescan remain report-only for agents, including adopted headless Codex workers.",
            "Kills the family then re-checks, since killing a parent reparents its children.",
        ],
    },
    # --- Config metrics + self-analysis subsystem ---------------------------------------------
    "bin/dotclaude-redact.py": {
        "mission": "Nothing sensitive ever leaves the machine — only what config optimization needs to know does.",
        "purpose": "The one need-to-know minimization layer: scrub secrets + PII, drop content, before any store or commit.",
        "criteria": [
            "Runs before anything is stored or committed; every write path routes through it.",
            "Redacts secrets (keys, tokens, passwords, private keys, connection strings) and PII (emails, phones).",
            "Drops content by a field allowlist: file/code bodies, command bodies, tool payloads, diffs, unknown fields.",
            "Fails closed: a field it cannot classify as safe is dropped, not kept.",
            "Drops, never tokenizes — config optimization never needs to recover a specific.",
            "Pure functions, no I/O or network, so it is unit-testable in isolation.",
        ],
    },
    "bin/dotclaude-log.py": {
        "mission": "Every collector's events land in one place, minimized, and a session is never blocked or lost.",
        "purpose": "The one shared Firestore writer: minimize, boundary-scope, outbox-first, batched flush, TTL.",
        "criteria": [
            "Never raises to the caller and never blocks; a hook calling it ends in exit 0.",
            "Capture-first: appends every event to the local outbox before any network write, so nothing is lost.",
            "Flushes in batched commits under a time budget; whatever does not flush drains next run.",
            "Fails closed on project: refuses to write when the key's project_id mismatches the configured one.",
            "Passes every event through dotclaude-redact.minimize_event, honoring the work boundary.",
            "Names no specific project, account, or org — public-template-safe; unconfigured, it no-ops to the outbox.",
        ],
    },
    "bin/config-metrics-record.py": {
        "mission": "Each ended session's real usage is captured completely-for-diagnosis, with no work content in a personal project.",
        "purpose": "SessionEnd: parse the transcript into minimized per-part events and write them to the store.",
        "criteria": [
            "Never raises; a bad transcript must not fail SessionEnd.",
            "Emits prompt, tool_call (skill/reference), hook_deny, and error events, keyed by session.",
            "Reads the work/personal boundary from identity.local.json; a work session drops its request text.",
            "Routes every event through the shared writer, never writing a store or file directly.",
            "Records its own pipeline_health row so a broken collector is visible, not silent.",
        ],
    },
    "bin/config-metrics.py": {
        "mission": "Every config part gets an honest usage + health verdict, and a dead part reads as a broken trigger to fix.",
        "purpose": "Score every part two-axis from the store, write aggregates, render the scoreboard + HTML console.",
        "criteria": [
            "Loads the parts list ONLY from contracts/config_contracts.py, never a hardcoded copy.",
            "Classifies dead only when a part is both unreachable AND unused; a fresh part is new/unmeasured.",
            "Reports safety and planned/stub parts (from part_criticality.py) as expected-dormant, never as defects.",
            "Denial rates carry a Wilson lower bound and a low_confidence flag below 20 events.",
            "Runs without a store: prints the inventory and a configure-a-project notice, never errors.",
            "Reads the store incrementally from a persisted cumulative tally (aggregates/tally): a one-time cold seed, then only events at/after the watermark — never a full re-scan per run.",
            "Writes the computed rollup to aggregates so the local and hosted console read one result.",
        ],
    },
    # contracts/part_criticality.py needs no entry — contracts/*.py are the test's own inputs, exempt
    # like skill_naming.py and routing_scenarios.py; check_metrics_criticality_tags_name_real_parts
    # guards its correctness instead.
    "hooks/worktree-freshness.sh": {
        "mission": "Stale-base work is caught at session start, not discovered commits later at merge time.",
        "purpose": "SessionStart: warn once when this worktree's branch has fallen well behind main.",
        "criteria": [
            "Detection and reporting only. Injects one context note; never edits, rebases, or blocks.",
            "Fires only inside a linked worktree, never the main checkout.",
            "Warns only when the branch is 10+ commits behind main/master; silent otherwise.",
            "Emits valid SessionStart additionalContext JSON, and stays silent when git is absent.",
        ],
    },
    "hooks/config-metrics-log.sh": {
        "mission": "Every session's usage is recorded without the recording ever slowing or failing the session.",
        "purpose": "SessionEnd: hand the transcript to the metrics recorder under the right interpreter.",
        "criteria": [
            "Detection and reporting only. Never proposes, prompts, or edits.",
            "Prefers the metrics venv interpreter, falls back to system python3, exits 0 either way.",
            "Passes the payload through untouched; the recorder owns minimization.",
            "Silent and non-blocking when the recorder or interpreter is absent.",
        ],
    },
    "references/dotclaude-setup.md": {
        "mission": "Anyone forking the public template can stand up their own metrics project with nothing of the author's leaked.",
        "purpose": "Generic, placeholder-only setup for the dotclaude metrics project and its rules.",
        "criteria": [
            "Names no specific account, project, or org — placeholders only.",
            "States the zero-setup no-op behavior and the least-privilege + owner-read security model.",
            "Lists the env knobs and what is captured (need-to-know) versus dropped.",
        ],
    },
    "skills/sk/skills/claude-config-metrics-self-analysis/SKILL.md": {
        "mission": "Underused and silently-dead parts get surfaced and fixed to be used, so the config earns its keep.",
        "purpose": "Read the metrics store, score every part, and propose a trigger fix for the dead/underused ones.",
        "criteria": [
            "Proposes only; every change routes through /sk:claude-config-update.",
            "The default action is to fix the trigger so a part gets used; removal is a rare last resort.",
            "Never flags a warranted-dormant safety or stub part on low usage.",
            "Reads two axes: dead needs unreachable AND unused; denial rates are Wilson-bounded.",
            "Every finding names its part, its numbers, and the store record behind it.",
        ],
    },
    # --- The connector registry is local data outside this repo (connectorRoots); the tracked
    #     templates are connectors/*.json.example. No per-record contract entries. ---
}
