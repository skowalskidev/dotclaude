---
name: ship-screenshot-changes-advanced
description: Produce an advanced screenshot review covering empty and full states, conditional scenarios, responsive screen sizes and complete journeys, with conditions above screenshots and an actionable TLDR table. Use for "advanced screenshot review", "all conditional screenshot scenarios", or "screenshot coverage matrix". Captures every changed surface and journey before and after, with a walkthrough video per changed journey, by default.
argument-hint: [changed routes or journeys; whole app only when requested]
---

# Advanced screenshot review

DO read `~/.claude/references/screenshot-review.md` and execute its procedure for the requested scope.
Keep one case per scenario × viewport × variant, including blocked and unrun requirements, and
present each point as a heading above its own table: web desktop, web mobile, iOS and their videos
side by side in fixed columns, with no Point or description column.
Record one verified walkthrough video per changed journey, and capture every changed surface and journey before and after (reference § Record useful walkthroughs).
Return the local report and an actionable TLDR with findings, gaps and next actions.
TEST: N points have N heading/table blocks with a cell for every column (a gap shows its status and reason), and each
case's conditions appear above its evidence.

DO keep this invocation local by default. Publication needs explicit authorization; invoking this skill
does not invoke `/sk:ship-screenshot-changes` or its PR-post behavior. Preserve independent QA gates.
