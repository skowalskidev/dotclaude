# Pace a human through a manual multi-step flow

Reference catalog entry — load on demand. Used by `/sk:test-copilot` and `/sk:work-hyperspeed`.

When you drive a human through a manual sequence they can't see the internals of — a UI journey, a
paste-and-relay across sessions, a multi-step setup — the failure is dumping the whole plan and losing
them. Pace it. This builds on `rules/communication.md`'s five rules (always-on); these are the additions
pacing needs on top.

**DO keep the plan in a FILE and feed chat ONE action at a time.** The file holds progress and
observations (durable per `rules/process.md` — a ticket or `.context/`, never `/tmp`); chat never gets
the whole plan pasted again.

**DO show a one-line overview ONCE, then one action per message.** "12 steps, ~10 min" / "3 parts to
paste, then relay back". Unfamiliar effortful instructions overload at about FOUR chunks, so one action
per step is the ceiling.

**DO format every step Do / Expect / Then with the real target**, and carry:
- one action per step — three things is three steps;
- a progress count in the header ("Step 4 of 12", "Part 2 of 3") so they never wonder how much is left;
- under ~40 words — more means the step is too big;
- what you are watching or waiting for, so they know your side is covered.
- the surface they act in, named by what they can see: a browser tab by title and host, a window by
  its app name, a terminal by its directory. A browser walk follows `browser-debugging.md` § The test
  browser (one walk tab, closed when done).

Never re-print an earlier or later step.

**DO signal the hand-off as the FIRST action of any response that blocks on them.** They are not watching
the terminal. Fire the attention signal first, because parallel tool calls make later ordering
unreliable. This overrides answer-first ordering for a blocking step, and only there.

**DO record the finished step before you send the next one, and make that step the last thing you
say.** Append the step's result with `hooks/intent-ledger.sh note reconcile <scratch.md>` first. A
record written after the step message lets the Stop hook reopen the turn, and the human then gets a
second message after the step. (the fix for a 7-step walk where 6 steps were followed by "Step N is
recorded, waiting for you")

**DO end every step message with the hand-off line `Reply "done".`, and read the result yourself.**
On "done", capture the surface you can reach (the simulator per `ios-simulator.md`, the walk tab per
`browser-debugging.md`, the server log, the persisted state), judge it against the step's Expect line,
then send the next step or report the finding. A comment they volunteer is a finding.
**DON'T ask what they see, ask them to describe the screen, or ask for a screenshot of a surface you can
capture.** (the fix for a simulator walk whose every step ended "Reply 'done' or tell me what you see":
Simon pasted screenshots twice, then asked whether Claude could see it without them)
On a surface you cannot capture (a physical phone, another person's machine), keep `Reply "done".` and
name in that step the 1 capture the step's Expect line needs, e.g. "Reply "done" with a screenshot of
the receipt screen."; never a generic request.
TEST: every step message ends with `Reply "done".` or that line plus 1 named capture on an uncapturable
surface; zero step messages contain "what you see", "describe" or an unnamed screenshot request.

**DO wait for "done" before the next step, and DON'T advance past a failed one.** Collecting N
failures with one root cause means the later steps were never really tested.

**DO keep every edit out of the tree the human's dev server serves while they walk.** Build a fix in a
separate worktree or hold it, and apply it only at a step boundary, after telling them the tab will
reload and which step to redo. DON'T let a delegated worker commit into the served worktree: the dev
server hot-reloads the open tab and drops the state they built up. (the fix for a fix that landed mid-step
and reset the human's in-progress form twice)

**DO treat the surface you handed over as theirs alone until they explicitly release it.** Release is
"done", "your turn", "you do it", "stop" or "I'm out", nothing weaker. DO answer a question, an
ambiguous or partial message or a status line in chat and touch nothing: no navigation, reload,
recording stop, served-code swap or dev-server restart. Read it only (screenshot, DOM, console,
network, logs). Announce any action you take there as its own numbered step first. DON'T read any
reply as release, and DON'T drive it while their step is open: two drivers in one live tab replay
each other's actions. (the fix for a walk where "look let me pass" was read as quitting: Claude
stopped the recording, swapped the preview commit and reloaded the tab mid-step)

**DO queue every code refresh until the walk ends or the human releases it.** The served tree includes
the preview's checked-out commit and its server process, for the whole walk.

TEST: at any moment the human has exactly ONE action in front of them, a count of where they are, and a
clear signal it is their turn — and the full plan is in the file, not the chat. A step message is the
turn's last message. No file in the served tree, checked-out preview commit or server process changes while a walk is
open, and no click, keystroke, reload or navigation from Claude lands on their surface until an
explicit release; a question from them gets a chat answer and zero surface actions.
