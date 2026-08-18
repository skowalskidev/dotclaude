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

Never re-print an earlier or later step.

**DO signal the hand-off as the FIRST action of any response that blocks on them.** They are not watching
the terminal. Fire the attention signal first, because parallel tool calls make later ordering
unreliable. This overrides answer-first ordering for a blocking step, and only there.

**DO wait for their result before the next step, and DON'T advance past a failed one.** Collecting N
failures with one root cause means the later steps were never really tested.

TEST: at any moment the human has exactly ONE action in front of them, a count of where they are, and a
clear signal it is their turn — and the full plan is in the file, not the chat.
