# Ticket lifecycle — keep the tracker in lockstep

Reference catalog entry — the routine loads on demand; the always-on TRIGGER that fires it lives in
`rules/connectors.md`. This file is the ONE owner of the ticket → branch → PR lifecycle; skills and
`references/git-pr-deploy.md` point here rather than restating it.

When a task involves a project-tracker ticket — a pasted Linear/tracker link, or a ticket id like
`AD-39` — keep the ticket, the branch, and the PR in lockstep from the first action to the merge. Linear
is the example; the same routine holds for any tracker whose connector is set up (`rules/connectors.md`
+ `references/connectors-setup.md` own the ACCESS; this file owns the WORKFLOW).

## Start it before writing code
DO assign the ticket to Simon and move it to In Progress the moment the task is identified, not at the
end. A ticket left in its old status while its code is being written is the failure this prevents.

## Name the branch and the PR from the ticket
DO name the branch with the ticket CODE plus a title slug, so the tracker auto-links it: `AD-39` →
`AD-39-audit-product-features-for-landing-page-messaging` (the bare code at minimum). The code in the
branch name is what links the branch to the ticket.
DO match the PR TITLE to the ticket title, and put the ticket LINK in the PR body.

## Keep the status current, not batched at the end
DO transition the ticket as the work does: In Progress at start → In Review when the PR opens; tick each
acceptance criterion as its work is verified, not all at the end.
DO link ONLY the tickets this PR actually delivers — a linked ticket's status flips with the PR, so an
unrelated link wrongly moves that ticket.
