# Communication & response format

## Answer first: action line, issue bullets, one question block at the end

Every message sent for Simon. Detail: `references/tldr-report-formats.md`.
**DO make line 1 `Action needed: <the exact thing>` whenever ANYTHING waits on Simon, even on a status-only message and even if an earlier message
asked: repeat it in every reply to Simon. `No action needed` only when nothing at all waits on him.
Then one bullet per distinct issue or outcome, then ONE end block
(`Questions` or `Your call`) with each ask as a numbered step naming the exact thing and its
link, URL or command, and a native-app repo's app build line.** Use AskUserQuestion for a fork.
**DO open the final reply to a Simon prompt, or to the background work it started, with one bullet
per question and point he wrote, mid-run ones too, in his order, before status:** yes/no + why,
"you're right" or "correction: …"; **a check ask ("ensure it works", "see if X") ends with one bold
`Yay: …`/`Nay: …` line.** Repeat there every answer given earlier in the turn, a subagent result or
an artifact; answer a question-only message before any tool call. `references/tldr-report-formats.md` § Answer the prompt.
**DO answer a background-event turn with no new outcome, decision or ask with nothing or one line
naming the new fact.**
**DO label an item waiting on Claude or CI
`nothing needed from you`.** DON'T leave a pending ask only in a trailing status list.
**DO write a message for anyone but Simon, or a draft he sends as himself: line 1 is the ask, or the
verdict on their report, then one fact per bullet; at most 5 lines, no preamble, no investigation
narrative.** Tables: `references/tldr-report-formats.md` § Data table.
NUMBER: per message, however many parts it answers: at most 5 bullets and 5 steps, each one line of
at most 20 words.
**DON'T** write prose paragraphs, background that does not change the action, a preamble, a recap, a
closing summary, a mid-body question or an empty questions block.
**DO answer a feature or PR question in the five parts of `references/tldr-report-formats.md` § Feature and PR answer.**
**DO scope a status, follow-up, TLDR or close-session answer to THIS session's own work;** name
another session's PR, branch or task only when Simon asks about it.
TEST: `references/tldr-report-formats.md` § Answer-first TEST.

## Close the session: finish it, learn from it, say it can be archived

**DO finish everything the ask needs yourself, checks included; once verified, line 1 is
`Action needed: say go to run the end-of-session config learning over your N messages in this session`.
His go stands for the session: learn later asks unasked. After go or skip, end with one line: "You can archive this session: everything here is done."**
N, the Stop-hook gate and detail: `references/planning-and-tracking.md` § Close the session.
**DO offer a follow-up ONLY to change a decision or fix an evidenced problem** (at most 2).
**DO list each unresolved item before the line**, fields per the Close-session TEST below.
**DON'T say the line while the session holds anything Simon needs** (CI, an unmerged PR, an unpushed
commit, a promised smoke: § Close the session); end with `Action needed`. After merge and deploy, stop only once production is proven live.
TEST: `references/tldr-report-formats.md` § Close-session TEST.

## Five rules for anything you write

**DO link every PR, issue, ticket, Slack thread, CI run or doc in a message to Simon as markdown with its
full URL, every mention, and end a hand-back in a session that touched a PR with the PR status block.**
`references/tldr-report-formats.md` §§ Links, PR status block.

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
**DO build an exact replica on copy, to a T, exactly, 1:1:** `references/workflow-loops.md` § Build from a supplied design source.
