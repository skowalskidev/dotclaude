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
  a lane belongs to the SESSION, not to the process that happened to bind it. If a Claude session is
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
workspace". The session check matches the process NAME's basename, never its arguments: `pgrep -x
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

### 3. Process-group teardown
The classic leak: you launch through a package-manager wrapper, kill the wrapper's pid, the
wrapper dies, and the actual server **grandchild survives** and keeps squatting the port.

- Launch each service in its **own process group** and kill the whole **group**, so no
  descendant outlives the orchestrator.
- Never `kill $PID` on something you launched through a wrapper.

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

One entrypoint, not five terminals for the human. Write the order in the script header so a
failure is locatable:

`setup → env → infra → seed → build shared libraries → boot server + verify identity → build frontend → run`

- **`setup` is DISCOVERED, never hardcoded.** Every project prepares differently, so read that
  project's `CLAUDE.md`, then `CLAUDE.local.md`, then a playbook if one exists, and run what they say.
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

## Track what you started

**The RULE is owned by `~/.claude/rules/process.md` § "Clean up after yourself"**, which is always-on
and so already loaded: track every process you start, kill it at task end, verify it's gone by checking
the port rather than by trusting the kill, and sweep orphaned framework workers machine-wide rather
than only your own. Not restated here.

**The MECHANICS live here**, because they are deep how-to and this file already owns process-group
teardown and signal discipline. They moved out of the always-on rule, which was at 69,993 bytes of a
70,000 ceiling and could not afford to carry them.

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
- **Never kill a worker that still has a live parent dev server.** That's an active localhost someone
  is using. `bin/kill-orphan-workers.sh` enforces it by only ever signalling a PPID==1 root or a
  descendant reachable through one, so nothing it touches can have a live dev-server ancestor.

The process-group and signal-discipline sections above are what make any of this actually reach the
grandchild holding the port.
