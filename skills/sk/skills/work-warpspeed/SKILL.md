---
name: work-warpspeed
description: TODO — not built yet. The THIRD and outermost layer of the parallel stack: /sk:work-warpspeed sits ON TOP OF /sk:work-hyperspeed, which sits on top of /sk:work-superspeed. Where hyperspeed runs many hand-run sessions on ONE machine/account, warpspeed spreads a whole hyperspeed relay across MULTIPLE VMs/VPSs on DIFFERENT accounts/orgs — the only thing that actually breaks the per-org rate ceiling. Each machine runs its own hyperspeed (many sessions, each superspeeding its slice). Placeholder only — invoking it explains the stack and sends you to /sk:work-hyperspeed for the working layer. Use for "warpspeed", "run the parts on different VMs", "run this across VPSs", "spread this across accounts".
argument-hint: "[the task you'd eventually spread across machines]"
---

# Warpspeed — TODO (the outermost of three layers, not built)

The parallel stack, innermost to outermost — each layer runs the one below it:

1. **`/sk:work-superspeed`** — automated `claude -p` fan-out WITHIN one session.
2. **`/sk:work-hyperspeed`** — many hand-run sessions on ONE machine/account, each running superspeed.
3. **`/sk:work-warpspeed`** (this, TODO) — many machines (VMs/VPSs) on DIFFERENT accounts/orgs, each
   running a full hyperspeed relay.

It runs nothing yet. Do not partition or dispatch from here.

## What it will do

Spread a `/sk:work-hyperspeed` relay across several VMs/VPSs — each its own machine, on its own
account/org — every one of which then runs hyperspeed (many sessions, each superspeeding its slice) on
its share of the work. Same START-commit + branch-per-part + assemble-and-clean shape, one level up: the
unit distributed is a whole hyperspeed run, not a single part.

## Why it is not built yet, and why it is the TOP layer

Per `references/parallelization.md`, Anthropic's rate limits key on the ORGANIZATION, not the machine or
IP. So more machines on ONE account add ZERO throughput — hyperspeed already saturates one org's rate
pool. The ONLY thing that raises the ceiling is running on DIFFERENT accounts/orgs, which is exactly why
warpspeed is the outermost layer: it is the account/org-spanning tier. It needs the account, billing, VM
provisioning and secret-distribution design worked out first — building it before that spends effort on
machines that do not go faster.

## Until then

Use `/sk:work-hyperspeed` — one machine's hand-run sessions (each superspeeding) give real parallelism
and branch-based assembly today. When this is built, the spec is: provision one VM/VPS per account/org,
run a hyperspeed relay on each, collect every relay's assembled branch, then assemble those and clean up
exactly as hyperspeed does one level down.
