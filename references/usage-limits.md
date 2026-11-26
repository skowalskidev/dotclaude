# Usage limits: read the plan meter and pace the work

Claude plans carry a rolling session limit and a weekly limit, shared across claude.ai, Claude Code
and mobile ([limit resets](https://support.claude.com/en/articles/17007452-about-limit-resets),
[usage and length limits](https://support.claude.com/en/articles/11647753-usage-and-length-limits),
researched 2026-11-24). Settings > Usage shows both as progress bars with their reset times. This
page replaces an hourly watchdog: the agent reads the meter itself and stops before the limit.

## Read the meter

DO read it through the Claude in Chrome tools on Simon's personal Chrome profile: `navigate` to
`https://claude.ai/settings/usage`, then `find` or `read_page` on the Usage dialog. Capture "Current
session" percent and its "Resets at" time, "This week" percent and its reset day, and any "Heads up"
pace warning. Take a screenshot only when Simon asks to see it.
DON'T click "Reset for free", "Buy usage credits" or turn on usage credits: a reset is a scarce
allowance and buying is spend (`rules/spend-approval.md`).

## When to check, and what to do

DEFAULT: check at every task boundary, before launching any heavy agent or walk, and every 30 to 60
minutes of agent work.
NUMBER: at 90 to 95 percent of the current session, stop launching work, send each running agent
"PAUSE" with `SendMessage`, and wait until the shown reset time, then tell each to resume. Wait with
one background wait to that time, never a poll loop.
Treat the weekly meter the same way, and narrow scope as it climbs; the "Heads up" warning counts as
90 percent.
TEST: every long run records its last reading (percent, reset time, UTC time of the read); no agent
is launched at 90 percent or more; no click on a reset or credits control.

## No longer automatic

A session stopped by a crash or a network error is no longer resumed hourly. Simon resumes it, or
restarts the session by hand. Nothing in this config replaces that.
