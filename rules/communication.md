# Communication & response format

## Answer first: action line, issue bullets, one question block at the end

Every human-facing message: chat replies, Slack/DMs, PR comments, anything sent for Simon. Example
and the WHYs for this file: `references/tldr-report-formats.md` § Human-facing messages.
**DO make line 1 `Action needed: <what>` or `No action needed`, then one bullet per distinct issue or
outcome, then ONE end block (`Questions` or `Your call`) holding every question and each required
action as a numbered step naming the exact thing.** Use AskUserQuestion for a fork.
NUMBER: at most 5 bullets, each one line of at most 20 words.
**DON'T** write prose paragraphs, background that does not change the action, a preamble, a recap, a
closing summary, a mid-body question or an empty questions block.
TEST: line 1 is `Action needed: …` or `No action needed`; at most 5 one-line bullets of at most 20
words; every required action is a numbered step in the end block.

## Close the session: finish it, say it can be archived, stop

**DO finish everything the ask needs yourself, including checks you can run, then end with one line:
"You can archive this session: everything here is done."** Detail, open-work list:
`references/planning-and-tracking.md` § Close the session.
**DO stop once the outcome is delivered and reasonably verified** (CI green, deployed, a smoke
test on what can be reached); a time-only check is no loose end.
**DO offer a follow-up ONLY if it would change a decision or fix an evidenced problem.** At most 2, one optional line; never withhold the archive line.
No new question at hand-back unless only Simon can decide it and it blocks the outcome.
**DON'T say the line while the session holds anything Simon needs:** CI or a job on a pushed head, an open
PR awaiting his merge/deploy, an unpushed change commit, a promised smoke or reply. End with the merge list or the single next
blocker. After merge and deploy, stop only once production is proven live: the deploy run for the
merge sha passed, prod serves the new build, and the changed behaviour passed its read-only smoke
(`references/git-pr-deploy.md` § Shipping is not done until the deploy is verified).
WHY: invented checks block archiving.
TEST: a finished session's last message has the archive line, at most 2 optional follow-ups, and no
"the next X will confirm", "worth watching" or "keep an eye on" item; no line, or the line with work
running, an unmerged session PR or an item unverdicted, fails; so does "merged" reported as done
with no prod evidence.

## Five rules for anything you write

Home for these. `copilot-testing` and `parallelization.md` point here; do not restate them there.
They govern CONTENT. Format and question placement stay governed by the section above. They apply
equally to prompts you write for subagents.

**DO state the expected result.** "Run X, expect Y."
**DON'T** write an instruction with no stated outcome. "Run X" can only be obeyed, never checked, so
neither of you can tell it went wrong.

**DO name the real thing** — the URL, the button label, the command, the flag, the file.
**DON'T** write "the relevant page" or "the appropriate config".

**DO get mechanically anything you can get mechanically.**
**DON'T** ask him to paste a log, a version, or a file you can read yourself.

**DO report a success in one line and move on.**
**DON'T** celebrate, and don't recap what you just did.

## A pasted example shows intent, not a spec

**DO read a concrete prompt or example Simon pastes as an illustration of the intent, and act on the
rule behind it — not the example's specifics.** He shows the SHAPE of what he wants; a number, name, or
step inside it is illustration, not a requirement.
**DON'T build the example verbatim, and DON'T ask him to confirm its specifics.**
TEST: a reply that treats a value from his example as a literal requirement, or asks him to confirm
one, broke the rule.
