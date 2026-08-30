# Ticket lifecycle — keep the tracker in lockstep

Reference catalog entry — the routine loads on demand; the always-on TRIGGER that fires it lives in
`rules/connectors.md`. This file is the ONE owner of the ticket → branch → PR lifecycle; skills and
`references/git-pr-deploy.md` point here rather than restating it.

When a task involves a project-tracker ticket — a pasted Linear/tracker link, or a ticket id like
`AD-39` — keep the ticket, the branch, and the PR in lockstep from the first action to the merge. Linear
is the example; the same routine holds for any tracker whose connector is set up (`rules/connectors.md`
+ `references/connectors-setup.md` own the ACCESS; this file owns the WORKFLOW).

## Read the whole ticket, in parallel, before you plan
DO fetch EVERY part of each ticket up front and in PARALLEL — the title, the full description, every
screenshot/attachment (embedded images AND attached files), the COMMENTS, and any linked/related issues
— firing one call per part in a single batch, before planning or writing code. A description read alone
is not the ticket: the build/refute/defer/scope decisions and the corrections live in the comments, and
the visual context lives in the screenshots (down them while the signed URLs are fresh). For a BATCH of
tickets, fetch all parts of all of them in one parallel wave, not one ticket at a time.
TEST: before the plan exists, every ticket has had its comments AND its attachments fetched, not just its
description. Reading only the description, and skipping the comments, is the miss this prevents.

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
DO update the tracker WITHOUT being asked — it is part of "done", never a closing question and never
bundled into the push/PR gate. At hand-back, post the outcome onto EACH delivered ticket (what was built
plus the acceptance-criterion verdict) and move its status as far as it honestly goes. Holding the PUSH
and the PR when unasked (`references/git-pr-deploy.md`) does NOT hold the ticket's verdict comment and
status move — those are a separate, ungated step that still lands. Parking "shall I update the tickets?"
as a question, or writing the verdicts only into a hand-back report while the tickets stay untouched, is
the miss (e.g. a whole batch judged Met but every ticket left in Backlog).
TEST: at hand-back every delivered ticket carries a verdict comment and a current status. A run that
lists verdicts but leaves the tracker untouched, or asks whether to update it, broke this.
DO link ONLY the tickets this PR actually delivers — a linked ticket's status flips with the PR, so an
unrelated link wrongly moves that ticket.
