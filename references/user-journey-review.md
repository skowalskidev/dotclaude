# User-journey review — judging a flow as the person meeting it for the first time

On-demand catalog. Read it when a change touches a user-facing flow: `/sk:ship-review` runs this as its
journey pass, and `/sk:test-eyeball` and `/sk:test-copilot` point here for what to look for while driving
the real app.

**Boundary.** This file owns how to JUDGE a journey. `references/planning-and-tracking.md` owns the
user-journey TLDR FORMAT that goes in a PR body (journey, the wait, how it works, assumptions). Don't
restate the format here, and don't restate this method there.

Reason from the running app, not from the code in the abstract. A diff review reads what was written; a
journey review asks whether the person on the other end can get through it.

## Walk it in order, as the first-time user

- Go through the flow end to end, step by step, in the order a new user hits it: first contact → set-up
  → trigger → the wait → the first meaningful result (the "aha"). Prefer walking the REAL app or
  preview. If none is running, ask before launching one (`rules/process.md` — don't auto-verify
  frontend in a browser).
- At every step note four things: what they DO, what they SEE, what they'd THINK, and where they could
  get STUCK. Drop-off happens where cognitive load spikes, where value isn't obvious, or where they
  feel lost.
- Enumerate every touchpoint. A step that silently assumes earlier state which was never set up is a
  gap, and it is invisible to anyone who already knows the feature.

## Every step present and connected — no dead ends

- Each step leads to the next with a clear action, and every state and item the flow surfaces is
  resolvable. A screen the user can reach but can't act from is a dead end. Flag it.
- Trace the whole chain. If the story jumps (a result appears with no path that produced it, a setting
  is required but never offered), a part is missing.

## The three states AI forgets — check EMPTY, LOADING, ERROR on every surface

AI-built flows overwhelmingly ship none of these (an NN/g review of 50 AI-built dashboards found ~92%
had no empty state, ~78% no error state, and 100% used a bare spinner). Check each surface for all three:

- **Empty** — before there's any data, the screen reassures nothing's broken, says what this is, and
  gives a clear next action. Never a blank panel. (e.g. "You haven't set up any X yet — [do the thing].")
- **Loading** — prefer a skeleton or real progress over a bare spinner, especially for long waits. Treat
  the WAIT as a first-class stage: show what's happening and roughly how long, so a slow result doesn't
  read as a hang. Time-to-first-useful-pixel matters.
- **Error** — every failure is surfaced with what went wrong and how to recover. Never a silent fail,
  never a dead end.

## First-run value

- The core value is reached fast, without a manual, and the happy path is obvious.
- Progressive disclosure: introduce things when they're relevant rather than dumping everything on the
  first screen. If the first session doesn't show the point, they don't come back.

## Edit, re-entry, and when NOT to allow editing

- They can come back and change what they set up. An abandoned or reopened flow restores sensibly
  rather than losing their input.
- Lock editing only where a change genuinely can't be allowed: already submitted or committed, a
  generation in flight, a plan-gated field, or a change that would break a downstream step or an
  irreversible/billable action. Don't disable a control just to steer flow if the user could still
  legitimately act.
- ALWAYS say WHY something is locked — an inline note, a tooltip, or a lock icon ("Locked while your ad
  generates", "Available on the Pro plan"). A silently dead or greyed control with no reason is a defect.

## Irreversible and destructive actions

- Confirm before an action that can't be undone or that costs the user time, money, or trust.
- Design for recovery: where possible offer an undo right after the commit (a toast or banner) instead
  of only a scary pre-confirm.

## Report it as a walkthrough

- Narrate the journey step by step. At each step call out what's missing, broken, confusing, or a dead
  end, ranked by how badly it hurts the user. Tie every finding to its step and give the fix.
- Reuse the project's existing patterns for the fixes (its skeleton loader, empty-state, confirm dialog,
  disabled/hidden conventions) rather than inventing new ones. Verify against the real app, not
  assumptions.
