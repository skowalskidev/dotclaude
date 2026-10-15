---
name: ship-screenshot-changes-advanced
description: Produce an advanced screenshot review covering empty and full states, conditional scenarios, responsive screen sizes and complete journeys, with conditions above screenshots and an actionable TLDR table. Use for "advanced screenshot review", "all conditional screenshot scenarios", or "screenshot coverage matrix". Include native walkthrough video when useful and already supported by the installed capture tool.
argument-hint: [changed routes or journeys; whole app only when requested]
---

# Advanced screenshot review

DO read `~/.claude/references/screenshot-review.md` and execute its procedure for the requested scope.
Keep one case per scenario × viewport × variant, including blocked and unrun requirements.
Return the local report and an actionable TLDR with findings, gaps and next actions.
TEST: every required case has a report row, and its conditions appear above its evidence.

DO keep this invocation local by default. Publication needs explicit authorization; invoking this skill
does not invoke `/sk:ship-screenshot-changes` or its PR-post behavior. Preserve independent QA gates.
