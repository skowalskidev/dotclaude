# Communication & response format

## Answer first: action line, issue bullets, one question block at the end

Every message sent for Simon. Example, WHYs, pre-send check: `references/tldr-report-formats.md`.
**DO make line 1 `Action needed: <the exact thing>` whenever ANYTHING waits on Simon, even on a status-only message and even if an earlier message
asked: repeat it in every reply to Simon. `No action needed` only when nothing at all waits on him. With several, line 1 reads
`Action needed (2): <first>`; then one bullet per distinct issue or outcome, then ONE end block
(`Questions` or `Your call`) with each ask as a numbered step naming the exact thing and its
link, URL or command.** Use AskUserQuestion for a fork.
**DO open the final reply to a Simon prompt, or to the background work it started, with one bullet
per question and point he wrote, mid-run ones too, in his order, before status:** yes/no + why,
"you're right" or "correction: …". `references/tldr-report-formats.md` § Answer the prompt.
**DO answer a background-event turn with no new outcome, decision or ask with nothing, or one line
naming the new fact; DON'T re-print the block.**
**DO label an item waiting on Claude or CI
`nothing needed from you`.** DON'T leave a pending ask only in a trailing status list.
**DO write a message for anyone but Simon, or a draft he sends as himself: line 1 is the ask, or the
verdict when it answers a report; at most 5 lines, no preamble, no investigation narrative.**
NUMBER: per message, however many parts it answers: at most 5 bullets and 5 steps, each one line of
at most 20 words.
**DON'T** write prose paragraphs, background that does not change the action, a preamble, a recap, a
closing summary, a mid-body question or an empty questions block.
**DO scope a status, follow-up, TLDR or close-session answer to THIS session's own work;** name
another session's PR, branch or task only when Simon asks about it. Send this session's impact on
another session's work to that session (`rules/process.md` § Tell the live session your change
affects), never onto his action list.
TEST: `references/tldr-report-formats.md` § Answer-first TEST.

## Close the session: finish it, say it can be archived, stop

**DO finish everything the ask needs yourself, including checks you can run, then, once the outcome is delivered and verified, end with one line:
"You can archive this session: everything here is done."** Detail:
`references/planning-and-tracking.md` § Close the session.
**DO offer a follow-up ONLY to change a decision or fix an evidenced problem** (at most 2).
**DO list each unresolved item before the line**, fields per the Close-session TEST below.
**DON'T say the line while the session holds anything Simon needs:** CI or a job on a pushed head, an open
PR awaiting his merge/deploy, an unpushed change commit, a promised smoke or reply, an unresolved item.
End with `Action needed` and its numbered asks. After merge and deploy, stop only once production is proven live.
TEST: `references/tldr-report-formats.md` § Close-session TEST.

## Five rules for anything you write

**DO link every PR, issue, ticket, Slack thread, CI run or doc in a message to Simon as markdown with its
full URL, every mention.** TEST: a bare "#123" or "POI-123" fails. `references/tldr-report-formats.md` § Links.

**DO state the expected result.** "Run X, expect Y."
**DON'T** write an instruction with no stated outcome.

**DO name the real thing:** the URL, the button label, the command, the flag, the file.
**DON'T** write "the relevant page" or "the appropriate config".

**DO rest a sent "never", "same day" or "ready to merge" claim on complete reads:** `references/code-best-practices.md` § Claims from complete reads.

**DO get mechanically what you can** (a log, a version, a file) and **report a success in one line.**
**DON'T** ask him to paste what you can read, celebrate or recap.

**DO show a proposed visible change as a before/after screenshot in the same reply, unprompted.**
Fast path: `/sk:work-ask-reply-in-full-before-after-artifact`.
**DON'T** describe it in words alone.

## Correct a loose term once, up front

**DO state the industry-standard term once, with one primary source, in the work's first reply**
when Simon uses a loose name. TEST: `references/tldr-report-formats.md` § Loose term.

## A pasted example shows intent, not a spec

**DO act on the rule behind a pasted example, never its specifics.** TEST: `references/tldr-report-formats.md` § Pasted example.
