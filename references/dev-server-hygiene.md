# Dev-server hygiene — prove you're watching the RIGHT server

Reference catalog for any workflow where Claude boots a dev server or stack and then trusts
what it sees: `/sk:test-copilot`, `/sk:test-eyeball`, `/sk:maintenance-code-optimize-app`, any live debugging.

**The failure this exists to prevent:** a leaked server process from an earlier run of
*different code* is still bound to the port. A naive readiness check (`curl` the port, got a
response, "it's up") is satisfied by the impostor. Everything after that — every log line,
every screenshot, every conclusion — describes code that isn't running. The whole session
produces confident nonsense, and nothing about it looks wrong.

"Something answered on the port" is NOT "my server is up."

## The three guards. Use all of them; each catches what the others miss.

### 1. Port preflight — before booting anything
Check every port the stack needs in **two** places: the shared registry (which session claims it)
and the machine itself (what is actually listening).

**Then take a different lane rather than failing.** A contested port is the normal case on a machine
running several sessions, not an error, and the answer is `bin/port-slot.sh` moving this worktree to
the next free lane (see Slots, below). **Fail fast and name the squatter** — pid, command, cwd, or the
session holding the claim — only when the port cannot move: one a third party has registered, or one
Simon named explicitly.

- **Any listener is a failure, even one from your own checkout.** Before boot, nothing from
  this run exists yet, so even a same-directory process is a stale leak that may be running
  old code. The checkout path changes the *label* and the remediation hint, never the verdict.
- **Report, don't kill, by default.** Killing a human's unrelated server is worse than
  failing. Require an explicit opt-in to sweep.
- "Port in use, I'll just reuse it" is still the bug. Taking your own lane is not reusing theirs.

#### The shared port registry — how parallel sessions stay out of each other's way

Several sessions run at once in different worktrees, all wanting the same `:3000` and `:4000`, and
none of them can see the others. `~/.claude/port-registry.md` is the machine-wide record of who holds
what. It sits at the top level because ports are a machine-wide resource, and it is deliberately
untracked: the config knows the path and the protocol, the contents are local state. Drive it with
`~/.claude/bin/port-registry.sh` — never by hand-editing it while sessions are live.

- **`claim <port>… --for "<what>"` before binding.** It reconciles first, then claims. Exit 3 means
  another live session holds it: tell Simon who holds it, what for, and how long, add yourself with
  `wait <port>`, and stop. Do not silently pick a different port, and do not kill their server.
- **`release` at the same moment you kill the process**, not later. It prints any session that was
  waiting on those ports; surface that to Simon so he can go and unblock them.
- **The record is a claim, not the truth.** `reconcile` drops any row whose port has no listener and
  is past the grace window, so a session that died without releasing cannot block anyone tomorrow. It
  runs at session start and inside every `claim` and `check`, which is what keeps the file honest. The
  grace window is why a claim made just before boot is not immediately reaped.
- **A live session keeps its lane even with nothing listening.** The one exception to the rule above:
  a lane belongs to the SESSION, not to the process that happened to bind it. If a Claude or Codex session is
  still working in that workspace, its server has died or not booted yet and it will boot again, so
  handing the lane to a neighbour just moves the `EADDRINUSE` one session over.
- **A listener with no row is the interesting case** — something is bound that no session admitted to.
  `claim` reports its real pid, command and cwd. Tell Simon; never assume it is abandoned.
- **`reap` is `reconcile` plus the two signals it cannot see** (below). Use it when you want the file
  honest before acting on it; `bin/port-slot.sh` runs it on every invocation.

#### Slots — take a lane instead of arguing over :3000

A **slot** is 0..9. Slot N means `base + N*10` for every base port the project uses, so slot 1 of a
`{web 3000, api 4000}` project is `{3010, 4010}`. The slot is derived from the worktree path, so it is
stable across restarts without anything being stored, and then arbitrated by the registry: if that
lane is held, probe the next one. `~/.claude/bin/port-slot.sh` is the only thing that should compute
this. `/sk:work-isolate-environment` is the skill that drives it and decides the per-project wiring.

**Why 10 and not 100.** `3000/3100/3200` reads better and was the first design. It walks into ports
real projects have already spoken for: in one work monorepo 3100 is `LANDING_URL`'s dev
default and both 3100 and 3200 are in `scripts/kill_ports.sh`, so four of ten lanes were broken before
anyone used one. A 10 step collided with nothing there, is the increment the parallel-worktree
write-ups converge on, and matches Conductor, which documents "ten ports to each workspace:
`CONDUCTOR_PORT` through `CONDUCTOR_PORT+9`". `CONDUCTOR_PORT` is the last-resort lane when all ten
slots are held: its uniqueness is documented, but no port column exists in Conductor's own database,
so the number is derived per launch and makes a poor bookmark.

**Offset the HOST side only.** In a containerised project the container-internal port never changes
(`ports: ["${API_PORT:-4000}:4000"]`), which is what lets app config hardcoding `localhost:4000` keep
working. Ports a third party has registered — OAuth and webhook redirect URIs — cannot move at all, so
those flows only work on the lane whose port matches, and that is worth saying out loud rather than
silently breaking a login.

**A lane must not pollute the repo — not a commit, not even a local edit.** Isolation is external to
the project: nobody else on the team needs this session's ports, so it belongs in exported env and CLI
flags, never in a tracked file. Three hatches make that practical, all verified on 2026-08-07:
a **later CLI flag beats an earlier one** (`next dev -p 3011 --port 3012` binds 3012, so appending
`--port` to an existing script reuses it verbatim); a task runner's env filtering has a flag
(`turbo dev --env-mode=loose` instead of editing `turbo.json`); and an env var the project already
reads is free, provided no loader overrides it from a file (env-cmd 10.x is file-wins, so check the
key is absent from that file). A port with no flag and no env knob is a **stop and ask**, not a reason
to edit a shared file.

**The three signals a sweep needs.** "Is anything listening" cannot see two real orphan classes, so
`reap` adds "does the workspace still exist" and "is there a live Claude session whose cwd is that
workspace". DO use `port-registry.sh owns-workspace <workspace>` with live cwds on stdin for ownership.
A session also protects linked worktrees physically nested under its checkout with the same Git common
directory. TEST: a sibling worktree or unrelated nested repository stays reclaimable.
DO preserve claims and stop reclamation on an unknown probe (exit 2); a failed process/Git lookup is
not evidence that its owner ended.
DO recheck a port cleanup candidate with `port-registry.sh can-reap-workspace <workspace>` before
signalling. TEST: only exit 0 permits cleanup; inaccessible paths, broken links and deleted children
of live parent checkouts remain held.
The session check matches only `claude` and `codex` process NAME basenames, never arguments: `pgrep -x
claude` misses Conductor-launched sessions because `ps -o comm=` reports their full path, and `pgrep -f
claude` matches the Claude desktop app and any shell whose argv mentions a `~/.claude` path.

| Workspace exists | Listener | Live session | Verdict |
|---|---|---|---|
| no | yes | n/a | Orphaned server. Auto-kill the family, then release |
| no | no | n/a | Release |
| yes | no | no, past grace | Release. Stale claim from a dead session |
| yes | no | yes | Keep. Its server died or has not booted; the session owns the lane |
| yes | yes | yes | Live. Keep |
| yes | yes | no | **Report only, never kill.** May be a server Simon started himself |

Auto-kill is confined to the one unambiguous row: the code is deleted, so nobody can be using it.
Everything else keeps report-never-kill.

**Release your own previous lane before claiming a new one**, or a slot change leaves two lanes claimed
and rows accumulate across a day of sessions.

### 2. Identity handshake — not a liveness probe
Stamp three things into the server's environment at boot and have a dev-only health endpoint
echo them back:

- the **git SHA** of the launching checkout — catches stale code
- a **random per-invocation run id** — catches a same-SHA process from a previous run
- the server's own **`process.cwd()`** — catches a same-SHA server from another worktree

Poll until it answers, then assert all three match before trusting anything. Each field rules
out a distinct impostor, which is why all three are needed.

- **A missing fingerprint is an impostor**, not a pass. It means pre-handshake code or a
  production build that gates the field out. Either way it isn't the server you just booted.
- The endpoint must be **dev/CI only** and must never expose this in production.
- Use distinct exit codes for verified / impostor / died / timeout so failures are diagnosable.

This is cheap to implement and eliminates an entire class of phantom results. It is the single
highest-value guard here.

### Dependency handshake — after every start and restart

An identity-verified server can still run with a rejected key.

**DO send one end-to-end request through each external dependency the journey uses (a model call, a
search, a payment sandbox) and read that service's log for a refused credential, before anyone else
touches the stack.** Where that request is billable, prove the key with a free authenticated call (a
model-list or account endpoint) unless Simon gave that one call its yes (`rules/spend-approval.md`).
Treat a 401 or 403 as a key-source fault and fix it before handing over; never blank or fake the key
instead. When an env file and the managed secret store both hold a key and the file wins,
start with that variable emptied for the one command (`<KEY_VAR>= <start command>`).
**DON'T hand the stack to a tester on the strength of the identity handshake alone.**
TEST: after each start or restart the log holds one successful request per dependency and no refused
credential (the fix for a restart that read a stale key from an env file, so every ask fell back to its
intake question).

### 3. Process-group teardown
The classic leak: you launch through a package-manager wrapper, kill the wrapper's pid, the
wrapper dies, and the actual server **grandchild survives** and keeps squatting the port.

- Launch each service in its **own process group** and kill the whole **group**, so no
  descendant outlives the orchestrator.
- Never `kill $PID` on something you launched through a wrapper.
- **A restart is a teardown plus a start.** Stop the launcher's group, confirm zero listeners on the port,
  start the new server, then confirm the listener's start time is newer than the stop. A launcher that
  outlives the kill respawns its own server with the old settings, and the new one dies on "address in
  use" while the port still looks healthy. TEST: after every restart the port has one listener and it
  started after the stop (the fix for a restart whose old launcher had already respawned a server with
  the old settings).

## Signal and trap discipline (hard-won specifics)

- Register cleanup on **EXIT only**; have signal handlers exit explicitly. The naive
  `trap cleanup EXIT INT TERM` runs cleanup on the signal *and* again on exit, and keeps
  executing in between.
- **Block further signals during teardown.** A second Ctrl-C mid-cleanup abandons the job
  half-killed: one service swept, another leaked.
- **Trap HUP too.** "Terminal window closed mid-run" otherwise kills the shell without running
  the EXIT trap, leaking exactly as in the original incident.
- Know the limits and say them honestly: shell traps are deferred until the current foreground
  command finishes (a build can run for minutes), and SIGKILL never runs traps. For those paths
  the recovery is the *next* run's preflight and handshake. Cleanup can't be perfect, so guard
  at both ends.

## Boot order, stated once

DO use `references/ios-simulator.md` for iOS simulator work.

One entrypoint, not five terminals for the human. Write the order in the script header so a
failure is locatable:

`setup → env → infra → seed → build shared libraries → boot server + verify identity → build frontend → run`

- **`setup` is DISCOVERED, never hardcoded.** Apply `references/project-instructions.md` first. When allowed, read that
  project's `CLAUDE.md`, then `CLAUDE.local.md`, then a playbook if one exists, and run what they say. When ignored, derive setup from source, executable config and CI.
  This is the step whose absence is most often misdiagnosed: a missing install, an unbuilt workspace
  package, an uncompiled native binary a dev script shells out to, or the wrong runtime version each
  produce a server that will not boot, and none of them is a port fault. `references/testing-strategy.md`
  owns the rule and the discovery order.

- **Rebuild shared workspace libraries before booting consumers.** In a monorepo the server
  consumes a library's *built output*, so a change is invisible until it's rebuilt. This is the
  classic "my change has no effect" hour-waster.
- Boot only the infra the run actually needs; each extra component is boot time plus a failure
  surface.
- Wrapping the run in the infra tool's own `exec` wrapper guarantees teardown and a non-zero
  exit on failure.

## Make the harness logic testable

Extract preflight and fingerprint decisions as **pure functions with injected observations**,
so they're unit-testable without binding real ports. Run those tests on randomized high ports
so they're safe to run while a live stack is up. Test infrastructure needs tests, and those
tests must not fight the thing they test.

## Symptom → cause mapping (write these down in the project)

Map the confusing symptom back to its environmental cause; it saves enormous time:

- opaque generic network error in the browser → two stacks fighting over the same port
- "exit 127" from a dev script → an unbuilt native/submodule binary it shells out to
- a change that appears to have no effect → shared library not rebuilt
- a query that works locally and fails only at runtime in production → a missing declared
  composite index (no build-time warning exists for this class)

## Machine-wide capacity

DO admit each heavy build, full test suite, browser batch and simulator lifecycle through
`bin/local-capacity.py`. It admits at most three leases (`HEAVY_SLOTS`) across local projects and
worktrees, one per owner, so three sessions run heavy work at once; model calls, small reads, edits and
scoped lightweight checks continue while all are held. This is cooperative admission, not an OS CPU
ceiling. DON'T create a per-repository gate or nest another lease inside one already held: `run` and
`acquire` inside a leased run on the same root exit 1 (not 75) and name `stage`, the way in. A
same-owner 75 names its own holder; act on it (move a server to `stack-acquire`, run the step as a
`stage`, or wait) instead of retrying blind. TEST: a fourth owner gets exit 75 naming all three holders,
the same owner asking twice gets exit 75 naming `stage`, and a nested `run` exits 1.

```sh
python3 ~/.claude/bin/local-capacity.py status
python3 ~/.claude/bin/local-capacity.py run --owner <session-id> -- <foreground-command>
```

DO read `status` first: it prints `heavy slot 1 of 3` through `heavy slot 3 of 3`, each free or its holder,
then `simulators in use`, the `watchdog:` lines and `dev stacks`.
DO put EVERY heavy step under a lease, a priority session's included: wrap the command itself, e.g.
`run --owner <session-id> --simulator <udid> -- xcodebuild test-without-building ...` or
`run --owner <session-id> -- next build`. `run` takes any single foreground command, so no heavy step
needs to run bare. For one step that spans several tool calls, `acquire --owner <session-id> --pid <pid of
a process that lives the whole step> [--simulator <udid>]` prints a token; `release --token <token>` drops it
when the step ends. A claim without a lease does not count as admission. WHY: a booted simulator driven
outside any lease reads "unavailable (booted simulator without a lease)" on every heavy slot, deferring
every other session and the session's own sub-agents for hours (the fix for a prioritised session that ran
`xcodebuild test-without-building` bare). TEST: while a heavy command or booted simulator is running,
`status` shows its owner on a heavy slot; a `watchdog:` line "booted simulator without a lease" never
names this session's owner.
DO let foreground `run` retry admission automatically every 10 seconds for up to 5 minutes
(`--wait-min`, 0 for immediate refusal, maximum 60 (`MAX_WAIT_MIN`); a larger value exits 1 naming the cap
before admission). For a longer wait, rerun the same command at the next task boundary. It launches the command once after admission;
it never retries a started command. On exit 75, record the holder and next task-boundary retry in the
living plan, keep independent work moving, and resume without asking Simon to say continue. Ordinary admission (`acquire`, `run`, `claim-sim`,
`stack-acquire`) defers while current CPU idle is below 20% (`MIN_IDLE_PERCENT`, the second
`iostat -d -C -n 0 -c 2 -w 1` sample), the 1-minute load exceeds 1.5 x logical cores (`LOAD_PER_CORE`) while
CPU idle is also below 35% (`LOAD_CONFIRM_IDLE_PERCENT`), or the OS reports memory pressure at warning or worse (`kern.memorystatus_vm_pressure_level` >= 2 via `sysctl -n`;
1 normal, 2 warning, 4 critical, the `NOTE_MEMORYSTATUS_PRESSURE_*` values in XNU `event_private.h`);
the exit-75 reason carries the reading. Only if that sysctl is unavailable, the fallback defers when the
compressor holds more than 40% of RAM (`MAX_COMPRESSED_SHARE`). DON'T gate on a fixed compressed-GiB
figure: macOS compresses opportunistically, so 8 GiB compressed on a 24 GB machine reads level 1 and
starved agents for hours. DON'T gate on load alone: macOS counts threads blocked in uninterruptible I/O,
Spotlight and mobileassetd bursts and zombies, so load read 118 to 208 on 8 cores at 51 to 66% idle and
refused every heavy step, the prioritized one included, for hours. Use the session-priority allowance below for a prioritized foreground command, a
simulator run included; stack starts retain these thresholds. WHY: load is
a lagging one-minute average that reads low while the CPU is pegged and high long after, so idle is the
saturation measure and load only adds a signal while idle confirms it. TEST: load 200 at 57% idle with
normal memory prints `GO`; load 200 at 10% idle prints `DEFER`. Simulator admission additionally defers when any device is Booted, Booting or
Shutting Down outside the lease. A failed CPU, load or memory probe is unknown, never permission to
proceed, and exits 75 like every other deferral. TEST:
a rejected command has not started and the small work remains runnable.

DO sample CPU, load and memory once per admission attempt; evaluate ordinary and priority decisions
from that snapshot. Use the second one-second `iostat` CPU sample, require its CPU-only header and
two valid rows, and bound the probe to 5 seconds; discard the first uptime average. Read the classified CPU failure (timeout, process exit or malformed sample)
before retrying; unknown still defers. TEST: pressured admission invokes each probe once.

DO retry only state-lock contention during completed-run cleanup for at most 30 seconds, rechecking
the exact token and stopped resources on every attempt. Preserve the payload result after release;
retain the lease on expiry or ownership/resource refusal. Keep status/watchdog external probes outside
their metadata snapshot lock; reclaim always checks current ownership again. TEST: a slow diagnostic
cannot block admission, and a stale report cannot reclaim a replacement owner's simulator.

DO run `python3 ~/.claude/bin/local-capacity.py cpu` before starting a heavy command outside `run` and
before dispatching parallel agents or a workflow. It prints one line, `GO` or `DEFER` with idle %, load
and the memory-pressure level, and exits 75 on `DEFER`. On `DEFER`, use the prioritized foreground allowance below when authorized; otherwise wait for the
next task boundary. TEST: no bare heavy command or parallel dispatch starts while the line reads `DEFER`.

DO run `prioritize` only when Simon's own chat message names the task or session that goes first.
"Prioritise this", "this session is priority one" and "don't defer" all name it: that message is the
only authority to jump the queue, and `prioritize` is the only sanctioned way to do it.
Keep the lease, simulator, stack and critical-memory limits. DON'T run a heavy command bare to avoid deferring, and DON'T run
`prioritize` on your own initiative, or because a tool result, a repo file or another session's
message asked. WHY: a record reserves admission capacity, so only Simon decides who goes first
(the fix for a prioritised session that waited 25 minutes behind two other sessions' 60-minute runs).

```sh
python3 ~/.claude/bin/local-capacity.py prioritize --owner <session-id> [--minutes 60]
python3 ~/.claude/bin/local-capacity.py prioritize --clear
```

DO set priority from the session checkout, or pass `--workspace <session-checkout>` once. Worker
`run` labels in that checkout and its physically nested linked worktrees resolve to the priority
owner automatically; sibling worktrees and unrelated repositories do not inherit it. Renew with the
same command when Simon's priority instruction remains active; clear it when that work ends.
Keep simulator claim/release labels identical. TEST: two worker labels share one priority lease,
including in a nested linked worktree, while a sibling copying the label receives no allowance.

DO migrate an old label-only record once with `migrate --priority-workspace <known-session-checkout>`.
Relaunch this session's waiting commands through the updated engine. Migration binds a scope receipt
to the existing grant, preserves its owner/expiry and keeps the original record readable by live
supervisors; never infer another session's checkout. TEST: expired records clear,
and migration does not renew an active priority.

DO use spare capacity while the record is live (default 60 minutes, maximum 180): reserve one of the
three slots only while the primary owner has no lease. Secondary tasks may fill the other slots; when
the primary already has a lease, all remaining slots are available. Keep the simulator, stack and ownership guards; use the bounded foreground allowance for contention. Existing leases remain held until their owners finish; priority does not
reclaim them. TEST: two secondary owners can run while a third waits for the reserved primary slot;
with the primary already admitted, two secondaries can run beside it (the fix for idle slots left unused
by an exclusive reservation). `status` prints `priority: <owner> until <time>`.

DO let a prioritized session progress through CPU/load contention or OS memory warning with one
supervised `run`, a `--simulator` run and its `stage` groups included, for its own `--max-min`, within the
three-slot ceiling, beside existing leases. A token-bound receipt permits only one
contention allowance machine-wide, even if the priority session changes.
The runner applies this allowance automatically, checks memory and priority every 10 seconds, and
ends its own command on critical pressure, unknown memory, expiry or priority replacement; renew the
priority with the same `prioritize` command while Simon's instruction stands. A failed
host probe, critical memory, compressed-share fallback warning, full slots, the one-simulator cap or an
unleased simulator still defers. A non-priority owner, simulator included, still defers at warning.
WHY: a prioritized simulator preview Simon was waiting on deferred 30 minutes at warning with all three
slots free, and a 5-minute allowance cap killed a 120-minute `--max-min` run.
DO read the exit-75 line: it names the real blocker and the next step (not the priority session; memory
critical; allowance held by `holder=`; use foreground `run`). TEST: a prioritized `--simulator` run is
admitted at warning and refused at critical; a non-priority one defers at warning.
DO retry a transient priority-state lock collision within that heartbeat and the command deadline,
checking memory before every attempt. TEST: a brief lock collision preserves a live payload;
critical or unknown memory during that retry ends only its owned group.
DO prove checkout ownership once at admission and bind it to that supervisor's exact working
directory identity. Heartbeats check the live grant and directory identity without repeating Git
or port-registry subprocesses. Same-scope renewal remains valid; expiry, replacement or unknown
identity ends the allowance. TEST: a later ownership-probe timeout cannot interrupt a proven run.
DO verify the unreaped child's PID, parent, start and private process group before teardown signals.
Keep its leader unreaped until live descendants stop. Accept a signal permission error only when
the group is proven zombie-only; otherwise retain its lease without retrying teardown.
TEST: reaped or foreign children receive no signal, and a live signal refusal preserves evidence.
Keep explicit runner worker limits.
Use serial phases and resume admission automatically; do not ask Simon to close apps for ordinary
contention. Never kill another live owner's job, steal a lease or bypass `run`.
TEST: warning plus 2% CPU idle admits exactly one priority command, a secondary waits, critical memory
starts no payload, and escalation stops only the owned group and releases its verified lease.

DO keep `run` for commands that finish: builds, test suites, simulator lifecycles, browser batches.
Pass `--max-min` covering the whole command (default 60, no upper cap); the runner honours it,
priority allowance included, and on expiry exits 124 naming the `--max-min` limit. DON'T wrap a
long-lived dev server (`next dev`, `npm run local:web`) in `run`: it holds the session's one lease for
hours, and that owner's next build or simulator run then exits 75 with "one owner holds at most one
lease". Boot the server on its claimed port lane (`bin/port-slot.sh`) and its Docker stack under
`stack-acquire`; lease its separate build and test steps. TEST: `status` shows no heavy slot held by
a dev server while its session runs a simulator preview.

DO treat a legacy bridge lock (`bridge.json` `lockPaths`) as held only by a live process. The runner
samples the host before taking it, so a waiting supervisor holds it only for its millisecond state
check, and polls up to 3 seconds (`LEGACY_LOCK_GRACE_SECONDS`) before refusing. flock is released
when its last holder exits, so a lock still held is never stale: the refusal names each holder's PID
and command name from `lsof -t`. Wait for it; never signal it. WHY: waiters holding the lock through a
one-second CPU probe made each other's attempts read "legacy native lock is held" with no build
running. TEST: a lock held 0.5 seconds is waited out; one held past the grace names its holder PID.

DO default to yielding between commands: wrap each separate build/test phase in its own `run`, so
admission automatically waits and resumes at that safe boundary. For an isolated CPU command that
retains no shared locks or services and tolerates wall-clock pauses, add `--pause-safe`. Its supervisor
checks every 10 seconds while a different primary is named, stops only its recorded PID/start/private
process group under pressure or failed probes, and resumes after two consecutive healthy samples.
Without a primary, full CPU utilization alone does not suspend ongoing work. TEST: primary contention
pauses only the opted-in secondary; recovery resumes it without another user message.

DO retain the paused job's lease and account for its memory and locks: SIGSTOP frees CPU, not memory.
A pause lasting 5 minutes ends that owned command with exit 75; it is never automatically restarted.
`--max-min` (default 60) includes paused wall time, separately from admission waiting. Cancellation
and timeout send TERM then CONT to the verified stopped group for graceful cleanup, then KILL after
2 seconds if needed. Recheck PID/start/PGID ownership before every cooperative signal. TEST: timeout
while stopped leaves no owned running group, or retains the lease with an explicit inspection error.

DO use `run --resource compute` for isolated backend tests/builds that use no native toolchain,
simulator or shared service. When one legacy bridge or old `slot.d` exists, compute reserves the first heavy
slot for the native lane even if an unregistered native job holds its mutex; compute uses only the
other two slots and never acquires that mutex. A registered first-slot native lease counts once. Multiple bridge locks, or a bridge plus
an old slot directory, defer compute sharing until their ambiguous occupancy is reconciled.
CPU, memory and unleased-simulator guards still apply. Default `--resource native` retains the legacy
bridge protocol. TEST: an unknown native lock holder and two compute owners exhaust capacity;
a third compute owner waits, and no native job bypasses its existing lock guard.

DO keep simulator runs, shared servers, wall-clock-sensitive tests and separate `stage` groups out of
pause-safe mode. Compute runs reject native stages and `--simulator`; compute with `--pause-safe`
can pause without holding a legacy mutex. Native runs with a configured bridge reject pause-safe.
Use separate ordinary `run` phases with automatic admission retries for unsafe workloads. The resource
label is an explicit cooperative assertion, not an OS sandbox; never relabel a native job as compute.
No daemon, unknown-process signal, lease stealing or persistent queue is installed.
TEST: pause-safe rejects native simulator/bridge/stage combinations before their payload runs.
DO run `prioritize --clear` the moment the priority step ends. TEST: after the clear, `status`
shows no `priority:` line and another owner is admitted when a slot is free.

DO run at most ONE simulator machine-wide, across every session (`MAX_BOOTED_SIMULATORS = 1` in
`bin/local-capacity.py`). A device counts while it is claimed, leased or not Shutdown, including a
booted device nobody leased. `claim-sim` and `run --simulator` exit 75 naming the holder while another
counts, the same owner's second device included. A before/after on iOS stages ONE device and switches
its backend between the two runs. WHY: one booted device's SpringBoard ran at 300-480% CPU, and two
took about 790% of an 8-core machine. TEST: a second `claim-sim` or `run --simulator` for a different
UDID exits 75 while the first is claimed or booted.

DO keep simulator boot, bootstatus, install, test and shutdown under ONE lease. Claim an owned UDID
with `claim-sim --udid <udid> --owner <session-id>` and use
`run --owner <session-id> --simulator <udid> -- <foreground-script>`. The helper never boots a
device; after the command group stops, the runner also attempts bounded shutdown of only its
recorded UDID on normal exit, failure or timeout. In the script, run each
`stage --timeout-seconds <n> -- <command>`
under the owned runner. Bound `simctl boot` to 60 seconds, `simctl bootstatus` to 120 seconds and
install to 120 seconds. Stop immediately when boot fails; do not enter bootstatus or the suite after
that failure. `stage` returns 124 after stopping only its own command group on timeout. Never use an
ambiguous `booted` destination, `shutdown all`, a foreign UDID or a foreign derived-data directory.
Release the owned simulator claim only after verifying Shutdown; retain the lease and a cleanup
action if the bounded shutdown attempt fails. Use a foreground script with fail-fast stages and a
shutdown trap; the runner checks shutdown again before release:

```sh
python3 ~/.claude/bin/local-capacity.py claim-sim --udid "$UDID" --owner "$SESSION_ID"
python3 ~/.claude/bin/local-capacity.py run --owner "$SESSION_ID" --simulator "$UDID" -- sh -eu -c '
  udid=$1; app=$2
  cleanup() { python3 ~/.claude/bin/local-capacity.py stage --timeout-seconds 60 -- xcrun simctl shutdown "$udid" || true; }  # harmless: the runner re-checks Shutdown before release
  trap cleanup EXIT
  python3 ~/.claude/bin/local-capacity.py stage --timeout-seconds 60 -- xcrun simctl boot "$udid"
  python3 ~/.claude/bin/local-capacity.py stage --timeout-seconds 120 -- xcrun simctl bootstatus "$udid"
  python3 ~/.claude/bin/local-capacity.py stage --timeout-seconds 120 -- xcrun simctl install "$udid" "$app"
  # Run the scoped native test here, with an explicit job cap and its own bounded stage.
' _ "$UDID" "$APP"
```

DO name the simulator on EVERY `run` whose command can boot one, including an `xcodebuild test` with a
simulator destination and a script that never calls `simctl boot`. Without `--simulator`, `run` cannot
release while a device is Booted: it retains the lease, and every later `run` exits 75. DO read `status`
at the first 75 (the `holder=` line and `booted simulators:`) instead of retrying; shut down the booted
owned UDID, then use the inspected release below. TEST: every native `run` line carries `--simulator <udid>`, and no 75
is retried before `status` was read.

DO verify the exact UDID is Shutdown before `release-sim --udid "$UDID" --owner "$SESSION_ID"`,
including when `run` deferred before boot and the claim was the only operation.
TEST: a failed boot starts zero subsequent stages, and any non-Shutdown device blocks lease release.

DO give a foreground `run` at most 60 minutes by default (`--max-min 60`). Raise `--max-min` only
for a justified full suite with measured duration; a prior 39-minute suite fits the default. Let
the runner's own supervisor cancel at its deadline; a runner timeout retains uncertain resources for
inspection. Treat PID death, PID reuse and an interrupted command as ownership questions, not proof
of cleanup. Inspect the saved receipt and process tree before an explicit
`release --token <token> --orphan-inspected`; a live owner, recorded child group or booted simulator
still refuses release.
DO let `acquire`, `run`, `status` and `watchdog` auto-release a provably dead lease: owner PID gone or
reused, its recorded command and stage groups empty, no simulator, and no live priority session.
Each release prints `auto-released heavy slot <n> of 3: holder=<owner>` and writes a `telemetry.jsonl`
event. TEST: a lease with a running group member, a simulator, a pending launch, no recorded group or a
failed probe stays held. Keep shut-down simulators, derived data and caches for the next scoped run.
If an older lease schema is reported, run `python3 ~/.claude/bin/local-capacity.py migrate` to
upgrade that receipt under lock before any new admission; the owner and child identity remain held.

DO stop a native run by sending SIGTERM to its `run` supervisor, the `pid=` on `status`'s `holder=` line:
it terminates its own command group. DON'T kill only the wrapper scripts or the parent of `xcodebuild`;
the build process reparents, keeps running with no parent and keeps the lease. When the holder reads
`orphan / PID reused` with `command_group=<pgid> (running)`, list the group with `pgrep -g <pgid> -l`,
stop its build process, and confirm `status` no longer shows `(running)` before the inspected release
above. A mid-run message to a worker says "let it finish" or names the process to stop, never only "do
not rerun". TEST: after a stop, `status` shows no running command group; inspect the recorded group
with `pgrep -g <pgid> -l` and verify its owned members stopped, preserving other live runs.

DO cap native runner parallelism inside the lease: `xcodebuild -jobs 4
-parallel-testing-enabled NO -maximum-concurrent-test-simulator-destinations 1` on hosts with at
least 8 logical cores, or at most half the cores (minimum 1) on smaller hosts. Apply explicit worker
limits to Gradle and other runners. Apply `rules/process.md` § Fan out verification to scheduling;
use `test-without-building` only for matching artifacts. For
web suites, start at two workers (`vitest --maxWorkers=2`, `node --test --test-concurrency=2` or
`playwright test --workers=2`) after confirming the installed CLI accepts that flag. Playwright's
`workers` defaults to "half of the number of logical CPU cores" (TestConfig docs), so pass
`--workers=2` explicitly.
In a scripted Playwright run, close each browser context when its batch ends and the browser when the
run ends. Treat
failures under machine overload as inconclusive and rerun the affected scoped check when the load
clears. Record any skipped gate as unverified, never passed. One failed boot left
a slot idle for 51 minutes. Another observed run had 12 concurrent `xcodebuild` processes and load
155–597 on 8 cores; its full suite took 39 minutes while scoped checks took seconds. A separate
web run's full suite rose from 80 to 408 seconds while load was 213–436, with Vitest timeouts
observed when load reached 600–995. Record elapsed time, contention and coverage before changing
these caps. TEST: no worker repeats the full suite, and no overloaded failure is treated as a
clean pass.

DO read every `watchdog:` line on `status`, or `local-capacity.py watchdog` alone; the SessionStart
capacity report (`hooks/port-registry-sweep.sh`) surfaces them too. It flags, read-only: any process at
or above 200% `ps` CPU (`HOT_CPU_PERCENT`; `ps` %cpu is "a decaying average over up to a minute") that
has run at least 120 s (`HOT_MIN_SECONDS`; younger is boot or startup); a simulator booted with no lease;
an idle simulator claim; more than one Chrome for Testing instance (`MAX_TEST_BROWSERS`). A hot process
inside a simulator names its UDID and owner. The owner stops its own process or device with the command
the line prints; DON'T stop another session's simulator or process from a watchdog line.
DO treat a `watchdog:` line that names THIS session's owner as an action item the moment you read it, at
session start, at every check-in and after every heavy step: run the printed shutdown and `release-sim`, or
take the missing lease (above), before the next tool call that is not that fix. DON'T carry it to hand-back.
TEST: the first reply after a `watchdog:` line naming this session's owner runs the fix, and a session
handing back with such a line broke the rule.

DO reclaim a simulator whose claim owner has ended with the command the line prints, and only then:
`python3 ~/.claude/bin/local-capacity.py reclaim-sim --udid <udid>` (also `native-slot.sh reclaim-sim <udid>`).
The engine prints it on the `watchdog:` lines, the `run`/`claim-sim` simulator refusals and `status` only
when the recorded claim workspace has no live owner and no lease holds the device. New claims record their
checkout and use the shared workspace ownership check, including live parents of nested linked worktrees.
DO retain older label-only claims while any session is live; an unmatched label cannot prove an ended owner.
TEST: a live parent prevents reclaim, while a known independent workspace or an empty session snapshot permits it.
It shuts the device down, drops the claim and
logs the action in `telemetry.jsonl`; it never deletes the device. It exits 1 naming the owner when that owner
is live, a lease holds the device, no claim exists, the claim is a legacy one or the session probe fails.
DON'T shut down a live owner's simulator, run `xcrun simctl shutdown` by hand on another owner's device, or
reclaim without the printed command. WHY: a booted simulator with no lease blocks every heavy slot, and an
ended owner can never run its own release-sim (the fix for a claim left by an ended session that deferred
builds machine-wide for 1.5 hours). TEST: `reclaim-sim` exits 1 for a live owner or a leased device and exits 0
for an ended owner with no lease; the printed command never appears for a live owner.

DO take a stack lease before starting any local Docker dev stack (`supabase start`, `docker compose up`)
and release it after stopping the stack:

```sh
python3 ~/.claude/bin/local-capacity.py stack-acquire --owner <session-id> --workspace "$(git rev-parse --show-toplevel)"
python3 ~/.claude/bin/local-capacity.py stack-release --workspace "$(git rev-parse --show-toplevel)"
```

At most `max_stacks()` stacks run at once: floor(Docker VM GiB / 3) (`STACK_GIB_EACH`), at least 1 and
at most 2 (`STACK_CEILING`); an unknown VM size admits 1. Running stacks are read from container labels
(`com.supabase.cli.workdir`, `com.docker.compose.project.working_dir`), so an unleased stack still
counts; a lease counts for 15 minutes (`STACK_START_GRACE_MIN`) before its containers appear. Start
Supabase with `-x` excluding every service the task does not use. WHY: the `supabase start` docs (supabase/cli
`docs/supabase/start.md`) recommend "at least 7GB of RAM to start all services". TEST: a third `stack-acquire` exits 75 naming the two running
stacks.

DO stop idle stacks on events only, never on a timer. `stack-acquire` first stops every idle Supabase
stack: one whose workspace has no live Claude session (`bin/port-registry.sh sessions`) and no commit,
index or changed file for 60 minutes (`STACK_IDLE_MIN`). It runs what `supabase stop` runs without
`--no-backup`: stop the project's containers, then prune its containers and network by the
`com.supabase.cli.project` label, keeping data volumes (supabase/cli `stop/SIDE_EFFECTS.md`, read
2026-10-20). `stack-sweep` lists idle stacks and `stack-sweep --apply` stops them; the SessionStart
report only lists them. A compose stack without that label is reported, never stopped. WHY: Docker
Desktop's Resource Saver stops the VM only "when no containers are running for a period of time". TEST: a stack with a
live session or a change in the last 60 minutes is never stopped, and no data volume is removed.

DO use `bin/native-slot.sh` only as a compatibility frontend to this same engine. Its `run`, `list`,
`claim-sim`, `release-sim` and `jobs` commands share the local-capacity lease and claims; it owns no
second slot or simulator ledger. Its `--wait-min` delegates to the same bounded admission loop.
If an older project still uses file locks, write an untracked
`~/.claude/state/local-capacity/bridge.json` containing
`{"lockPaths":["/absolute/existing-lock-path"]}` so native `run` checks each BSD lock without
blocking inside an admission attempt. Keep project-specific lock paths out of git. A configured bridge makes `acquire` refuse,
since a separate multi-call lease cannot hold the legacy lock safely. A held legacy lock is passed
only when a different owner's run holds the first slot, and the passing run takes a free slot other than the first;
a lock held with no lease defers native admission; compute follows the reserved-lane protocol above.
Existing claims are never automatically reaped. TEST: unresolved native lock contention yields exit 75
after bounded waiting, before the command starts.

DO preserve the inherited environment and `LOCAL_CAPACITY_LEGACY_FDS` through EVERY intermediary
that launches a `stage`. Python closes nonstandard descriptors by default; explicitly pass the
positive descriptor tuple to `subprocess.run` or `Popen`:

```python
import os
import subprocess

legacy_fds = tuple(int(value) for value in
                   os.environ.get("LOCAL_CAPACITY_LEGACY_FDS", "").split(",") if value)
if any(fd <= 0 for fd in legacy_fds):
    raise ValueError("invalid inherited capacity descriptor")
env = os.environ.copy()
subprocess.run(stage_command, check=True, env=env, pass_fds=legacy_fds)
```

DO retain this contract at each wrapper boundary, including wrappers launched by another wrapper.
DON'T use `close_fds=False`, remove bridge validation, drop the inherited environment or acquire a
nested lease. The stage's fail-closed descriptor check is intentional. TEST: an offline
run → Python wrapper → stage succeeds with explicit inheritance, rejects omission before its payload,
and excludes a competing lock owner while held. Python's
[`subprocess` documentation](https://docs.python.org/3/library/subprocess.html#subprocess.Popen)
defines `pass_fds` and the default `close_fds` behavior (checked 2026-10-09).


## Track what you started

**DO keep a branch's build caches until the branch lands or is abandoned.** Stop its processes at
hand-back unless an explicitly requested preview remains under its bounded owned lifecycle; leave
the derived data and build output created for that branch; review fixes and the ship run reuse
them. DON'T delete them at an intermediate hand-back (the fix for derived data deleted after the
build, then rebuilt cold for review fixes). The shared warmed `agent` simulator is not branch
state: shut it down and release it, never delete it, and ignore a project's "delete your simulator"
handover (`references/ios-simulator.md` § One warmed agent device). TEST: re-entering the branch
reuses its build; workspace teardown removes it, and `agent` survives it.


**The RULE is owned by `~/.claude/rules/process.md` § "Clean up after yourself"**, which is always-on
and so already loaded: track every process you start, stop it when its authorized lifecycle ends,
verify it's gone by checking the port rather than by trusting the kill, and sweep orphaned framework AND agent-spawned workers
(`chrome-devtools-mcp`, `wrangler`/`workerd`, headless `codex exec`) machine-wide rather than only your
own. Not restated here.

**The MECHANICS live here**, because they are deep how-to and this file already owns process-group
teardown and signal discipline. They moved out of the always-on rule, which was at 69,993 bytes of a
70,000 ceiling and could not afford to carry them.

### Private process inspection

DO inspect processes with names and metadata only. Use `pgrep -l <name>` for discovery and
`ps -p <pid> -o pid=,ppid=,pgid=,comm=` for a known PID. Keep arguments and environment values out
of tool output, logs and artifacts, even for owned processes (e.g. a launcher argument can hold a key).
**DON'T print full command lines with `pgrep -fl`, `pgrep -af`, `ps aux`, or `ps` args/command fields.**
`hooks/secret-echo-guard.py` denies those unless the output is consumed (`| wc -l`, a file).
When exact arguments are required for an existing ownership check, capture them inside a local
checker and emit only the match verdict and safe metadata; never weaken that check to a name match.
Before signalling, verify the launch receipt, start time, parent/group and cwd against this task;
a name match alone proves neither ownership nor abandonment. Preserve other live sessions.
TEST: zero argument/environment values in inspection output; every stopped PID has current
ownership evidence or passes the existing orphan-cleanup gate.

### Waiting on a background job

**DO wait on a handle the job owns:** `wait $pid` in the same shell that launched it, a `kill -0 $pid`
poll on the PID recorded at launch, a done-file the job writes as its last step
(`cmd; echo $? > "$dir/done"`), or the harness's own completion notification for a `run_in_background`
task.
**DON'T poll `pgrep -f <pattern>` for a pattern the waiting command itself contains.** `pgrep -f`
matches whole command lines, so `until ! pgrep -f "ios-run.sh" >/dev/null; do sleep 5; done` finds its
own shell and never ends; the same bare pattern also matches other worktrees' jobs. (the fix for three
self-matching wait loops: the rebuild queued behind one never started, and two ran until the 30-minute
background limit killed them.)
TEST: every wait names a PID, a done-file path or a harness notification; none searches process
command lines for a string in its own argv.

**DO launch a chain of capacity-gated commands detached when its worst case can exceed 2 hours**,
the harness cap for a `run_in_background` task. Worst case = steps x `--wait-min` plus runtime.
Run `nohup <chain> > <log> 2>&1 < /dev/null & disown`, record its PID as owned, have each stage
write its own receipt, poll the log in bounded foreground waits, and confirm the PID is gone at
hand-back. **DON'T** run such a chain as a `run_in_background` task: the cap kills it mid-queue and
the queued steps never start. (the fix for a five-stage gate chain, each step `--wait-min 60`,
killed at the 2-hour cap under machine contention.)
TEST: no `run_in_background` task wraps more than one capacity-gated step whose summed `--wait-min`
reaches 120.

### Where a tool's own listing lies to you

`rules/process.md` carries the rule (reconcile against the storage, not the listing). The cases it used
to carry, kept here because they are what makes it concrete:

- **`git worktree list` reports nothing** once a worktree's metadata is pruned, while gigabytes of stale
  checkouts sit on disk. Listing the parent directory finds them; the git command never will.
- The same gap hides **dangling container volumes**, **stale LaunchAgent plists**, and abandoned
  **`node_modules`** trees.
- Measured instance of the class: `bin/port-registry.sh` leaked one temp dir per invocation, 963 of
  them, and no command it offered would ever have shown that — the leak was outside everything it
  tracked.

### Killing an orphaned worker without minting a new one

A dead `next dev` / `jest` / `turbo dev` / `vite` run leaves child workers that reparent to PID 1 and
pin a core indefinitely. The classic offender is `next-router-worker`, also `jest-worker` and
`next-render-worker-pages`. One left in another checkout burned a full core for five hours before
anyone looked, which is why the sweep is machine-wide and not task-end-only.

DO retain **agent-class candidates** (`chrome-devtools-mcp`, `wrangler`/`workerd`, `codex exec`, `claude -p`)
when their task ownership is unresolved. `bin/kill-orphan-workers.sh` reports them at PPID 1 + 5+ min
but never admits those roots to its signal or rescan sets. A handed-off worker can still produce
results for a successor after its launcher exits; parent death, CPU use and log age prove no end state.
Use the owning task's launch identity and lifecycle records before its owner stops a proven ended run.
The generic sweep has no authoritative ended-task receipt, so uncertainty remains report-only.
TEST: an adopted old PPID-1 headless worker stays alive; framework CPU/age/git-cwd gates still apply,
and reports distinguish retained agents from eligible framework families without exposing arguments.

- **Capture the whole family BEFORE signalling anything.** A child's ppid changes the instant its
  parent dies, so a tree collected afterwards is already wrong.
- **Killing the parent REPARENTS its children rather than killing them**, so a naive parent-kill just
  mints a fresh orphan. Signal every pid in the family directly, not only the roots.
- **Re-scan after SIGTERM, then escalate.** A member can survive it (trapped, ignored,
  uninterruptible), and if only the root died its children have just become PID-1 orphans of their own.
  Re-run the same detector, SIGKILL the survivors, and verify empty.
- **Re-check against the observable that matters.** For a port holder that is "is the port still
  bound", not "is that pid alive": if only the parent died, a surviving child still holds the bind and
  the pid you were watching is gone.
- **Preserve live-parent exclusions and the framework gates.** Signal only an eligible framework
  PPID-1 root and its captured descendants. A root's parent death alone never licenses agent cleanup.

The process-group and signal-discipline sections above are what make any of this actually reach the
grandchild holding the port.
