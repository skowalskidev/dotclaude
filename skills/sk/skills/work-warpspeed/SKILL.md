---
name: work-warpspeed
description: TODO — not built yet. The next evolution of /sk:work-hyperspeed: run the self-contained parts on different VMs or VPSs instead of local Conductor workspaces, so parts run on separate machines. Placeholder only — invoking it explains the plan and sends you to /sk:work-hyperspeed for the working version. Use for "warpspeed", "run the parts on different VMs", "run this across VPSs".
argument-hint: "[the task you'd eventually spread across machines]"
---

# Warpspeed — TODO (not built)

This is a placeholder for the VM/VPS evolution of `/sk:work-hyperspeed`. It runs nothing. Do not
partition or dispatch anything from here.

## What it will do

Same hand-relay parallelism as `/sk:work-hyperspeed` — a clean START commit, one plan file of
self-contained parts, branch-per-part, assemble-and-clean — but each part runs on its OWN VM or VPS
instead of a local Conductor workspace, so the parts run on genuinely separate machines.

## Why it is not built yet, honestly

Per `references/parallelization.md`, Anthropic's rate limits key on the ORGANIZATION, not the machine
or IP. So spreading parts across more machines on ONE account adds ZERO throughput — the requests share
one rate pool. The real win of VMs/VPSs is running on DIFFERENT accounts/orgs, or genuine machine/OS
isolation, and that needs the account, billing, provisioning and secret-distribution design worked out
first. Building it before that design exists would spend effort on machines that do not go faster.

## Until then

Use `/sk:work-hyperspeed` — local Conductor workspaces give the parallelism and the branch-based
assembly today. When this is built, the spec is: provision one VM/VPS per part, ship the START commit +
the part's self-contained instructions to each, collect the pushed branches, then assemble and clean up
exactly as hyperspeed does.
