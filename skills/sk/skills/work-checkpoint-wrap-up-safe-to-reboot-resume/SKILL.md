---
name: work-checkpoint-wrap-up-safe-to-reboot-resume
description: Checkpoint all in-flight work so a computer RESTART (which wipes /tmp) and a later resume lose nothing — everything resume-critical moved out of /tmp and session memory into durable homes (pushed git branches, the Linear ticket, the .context plan), background agents/monitors/servers stopped cleanly, and a single RESUME BRIEF written that says exactly where to pick up. Use when stopping for the day, resuming later (e.g. Monday), about to reboot or shut down, or handing a long task across a break. Triggers "I'm done for today", "resuming Monday/later", "I'll restart my computer", "wrap up so it's safe to reboot", "checkpoint this so I can resume", or the explicit /sk:work-checkpoint-wrap-up-safe-to-reboot-resume.
---

# Checkpoint & wrap up — safe to reboot, clean to resume

The guarantee: after this runs, the machine can restart — wiping `/tmp` and killing every background
process — and the next session resumes with nothing lost and no guesswork. Treat `/tmp` and this
session's memory as VOLATILE; only pushed git, the Linear ticket(s), and the worktree's `.context/`
survive a reboot. Everything resume-critical must end this run in one of those three.

## Step 1 · Inventory what's in flight

DO list it before touching anything: every running background agent/task/monitor and dev server (yours,
and what the machine-wide sweep shows), every branch and worktree carrying uncommitted or unpushed work
(the main checkout AND every agent/isolated worktree), and — the load-bearing set — everything the
resume depends on that currently lives ONLY in `/tmp` or in your own memory. Name that last set
explicitly; it is the whole reason this skill exists.
TEST: you can point to where each piece of in-flight state physically lives, and which pieces are volatile.

## Step 2 · Make every piece durable

DO commit + push every branch so origin holds all progress (`rules/process.md` commit-when-done: one
logical unit per commit, build/tests green first unless docs-only, branch off `main` first, never push
master without the explicit ask).
DO resolve every agent/isolated worktree: its work committed + pushed, OR captured onto a branch, OR
discarded with a one-line why — a re-runnable stage that restarts cleanly from a pushed point is a fine
discard, an hour of uncommitted edits is not.
DO move every resume-critical note OUT of `/tmp` and memory into a durable home: the Linear ticket(s)
and the worktree's `.context/<slug>-plan.md` (`rules/living-plan.md`, `references/planning-and-tracking.md`).
A scratch file under `/tmp` is gone on reboot — if the resume needs it, it is not saved until it lives
in git, the ticket, or `.context/`.
TEST: `git status` is clean on every worktree, every branch is pushed, and no resume step cites a `/tmp` path.

## Step 3 · Write the RESUME BRIEF

DO write one glanceable brief into the durable homes (the ticket, and the top of the `.context` plan):
the exact branch + commit SHA to check out, what is DONE, the single precise NEXT ACTION to take first,
where the plan and ticket live, and the reminder that `/tmp` is wiped so nothing there survives. The
test of a good brief is that a cold reader — you on Monday, or another session — resumes from it alone,
without reconstructing context from this transcript (which they will not have).
TEST: the brief names a branch, a SHA, and a concrete first command/action — never "continue where we left off".

## Step 4 · Stop and tear down cleanly

DO stop every background agent/monitor (TaskStop) and dev server (kill, then verify the port is actually
free), release this session's port lanes (`references/dev-server-hygiene.md`: `port-registry.sh release`),
and tear down every FINISHED isolated worktree whose work is on origin.
DON'T leave a burning or idle process holding a core over the break: a reboot kills them anyway, so
leaving them is only ever mess, never necessary.
TEST: `pgrep -fl 'next dev|next start|vitest|jest|next-router-worker'` lists nothing you started, and no
agent/monitor you launched is still live.

## Step 5 · Verify the guarantee, then hand back the brief

DO prove it before saying done: every branch pushed (name each with its tip SHA), the resume brief points
ONLY to durable locations, and nothing resume-critical lives only in `/tmp` or in memory. Reconcile the
worktree's `.context/intent-ledger.md` — one verdict per in-flight ask.
DO make the RESUME BRIEF the last message, so it is the first thing seen on return.
TEST: you can restate the whole resume as "check out `<branch>@<sha>`, read `<ticket/plan>`, do `<next
action>`" — all durable, zero `/tmp`, zero memory.
