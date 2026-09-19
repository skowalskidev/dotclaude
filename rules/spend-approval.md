# Billable spend needs approval — every time

**DO get an explicit per-call "yes" before ANY billable operation** — a paid model render/generation,
a credit-consuming API call, a metered external request. Name it and its rough cost, then WAIT. One
yes is ONE call, never a batch, a sweep, or a retry loop.
**DON'T treat a diagnose / fix / test / "find the cause" task as license to spend.** It authorizes
reading logs, code and data and running FREE calls (a provider that rejects an invalid request bills
nothing) — never a paid render to test a guess, and never a bisection that fires paid calls until one
works (each success is billed).
WHY: burned FAL render credits (~$4.54 each) bisecting a bug after being told not to spend.

TEST: every billable/metered call traces to an explicit per-call yes from Simon this session; a task
to "fix" or "find the cause" never counts as that yes.
