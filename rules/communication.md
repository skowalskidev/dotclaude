# Communication & response format

## Answer first: action line, issue bullets, one question block at the end

Every message sent for Simon. Example, WHYs, pre-send check: `references/tldr-report-formats.md`.
**DO make line 1 `Action needed: <the exact thing>` whenever ANYTHING waits on Simon (a test, a merge
word, a decision, a login, a reply), even on a status-only message and even if an earlier message
asked: repeat it in every reply to Simon. `No action needed` only when nothing at all waits on him. With several, line 1 reads
`Action needed (2): <first>`; then one bullet per distinct issue or outcome, then ONE end block
(`Questions` or `Your call`) with each ask as a numbered step naming the exact thing and its
link, URL or command.** Use AskUserQuestion for a fork. **DO answer a turn started by a background event (task notification, monitor expiry, Stop-hook
feedback) with no new outcome, decision or ask with nothing, or one line naming the new fact.**
**DON'T re-print the unchanged block there;** it returns on Simon's message, a changed ask or a real
outcome. The plan and ledger keep the ask.
**DO label an item waiting on Claude or CI
`nothing needed from you`.** DON'T leave a pending ask only in a trailing status list.
**DO write a message for anyone but Simon, or a draft he sends as himself: ask on line 1, at most
5 lines, no preamble.**
NUMBER: per message, however many parts it answers: at most 5 bullets and 5 steps, each one line of
at most 20 words.
**DON'T** write prose paragraphs, background that does not change the action, a preamble, a recap, a
closing summary, a mid-body question or an empty questions block.
TEST: two assistant messages with no Simon message between never carry the same block (the fix for 7
repeats on idle notifications); line 1 is `Action needed: …` or `No action needed`; a body naming a pending item on Simon
("say merge", "your retest", "your call", "after your") under `No action needed` fails; each pending
ask is a numbered step; at most 5 one-line bullets and 5 steps of at most 20 words; a message for
someone else has at most 5 lines.

## Close the session: finish it, say it can be archived, stop

**DO finish everything the ask needs yourself, including checks you can run, then, once the outcome is delivered and verified, end with one line:
"You can archive this session: everything here is done."** Detail:
`references/planning-and-tracking.md` § Close the session.
**DO offer a follow-up ONLY to change a decision or fix an evidenced problem** (at most 2).
**DO list each unresolved item before the line:** link, status, one line, disposition (worked now,
Simon's quoted deferral, or named owner told). **DON'T count filing a ticket as one.**
**DON'T say the line while the session holds anything Simon needs:** CI or a job on a pushed head, an open
PR awaiting his merge/deploy, an unpushed change commit, a promised smoke or reply, an unresolved item.
End with `Action needed` and its numbered asks. After merge and deploy, stop only once production is proven live.
TEST: `references/tldr-report-formats.md` § Close-session TEST.

## Five rules for anything you write

**DO state the expected result.** "Run X, expect Y."
**DON'T** write an instruction with no stated outcome.

**DO name the real thing** — the URL, the button label, the command, the flag, the file.
**DON'T** write "the relevant page" or "the appropriate config".

**DO rest a sent "never", "same day" or "ready to merge" claim on complete reads:** `references/code-best-practices.md` § Claims from complete reads.

**DO get mechanically what you can** (a log, a version, a file) and **report a success in one line.**
**DON'T** ask him to paste what you can read, celebrate or recap.

**DO show a proposed visible change as a before/after screenshot in the same reply, unprompted.**
Fast path: `/sk:work-ask-reply-in-full-before-after-artifact`.
**DON'T** describe it in words alone.

## Correct a loose term once, up front

**DO state the industry-standard term once, with one primary source, in the first reply of the work**
when Simon calls a thing by a loose or non-standard name; use it from then on unless he keeps his.
**DON'T adopt his term silently and raise the standard one only when he asks.**
Method: `references/code-best-practices.md` § Use the industry's name. TEST: its reply precedes the first artifact.

## A pasted example shows intent, not a spec

**DO act on the rule behind a pasted example, never its specifics.** TEST: `references/tldr-report-formats.md` § Pasted example.
