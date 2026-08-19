---
name: test-eyeball
description: Drive the changed frontend HARD in a real debug browser — fuzz edge inputs, hunt and FIX bugs, loop until a clean pass — on top of /sk:ship-screenshot-changes, which it REUSES for the capture (debug-browser login, port lane, figuring out what changed, seeding the state, screenshotting each surface with realistic inputs, the hand-back, and the opt-in GitHub-native PR post). Use for "go eyeball / QA / check my UI change in the browser". For a quick screenshot pass with no bug-hunt, use /sk:ship-screenshot-changes directly.
argument-hint: [optional focus, e.g. "the RR SMS preview"]
---

# Go eyeball — the QA loop on top of the capture

Go and eyeball and FIX bugs using the debug browser, loop until you find no more, then hand back
screenshots with example inputs. Do it as a loop, not a one-shot.

**REUSE `/sk:ship-screenshot-changes` for the capture** — the debug-browser login (its Step 0), the port
lane, figuring out what changed (Step 1), seeding the account into the state the change is seen in (Step
2), screenshotting each surface with realistic inputs (Step 3), the hand-back + open-in-Finder (Step 4),
and the opt-in GitHub-native PR post (Step 5). Follow that skill for all of it; do NOT restate it here.
This skill adds ONLY the QA a documentation pass skips:

## Drive each surface with EDGE inputs too, hunting bugs

On top of the realistic pass (`/sk:ship-screenshot-changes` Step 3), also drive each changed surface with
EDGE inputs — empty, very long, special/typographic chars (accents, em dash `—`, quotes, `& ( ) + . @`),
boundary values, and the not-yet-configured states. These are where the real bugs hide (regex breaks,
overflow, wrapping, NaN, XSS, wrong gating). Verify behavior with `evaluate_script` (read the
DOM/computed styles/pill spans, not just eyeball), and check `list_console_messages({types:["error"]})`
for feature-related errors (ignore pre-existing unrelated noise).

Judge each surface against `~/.claude/references/user-journey-review.md` — the empty/loading/error
states, a lock with no stated reason, a step with no way on. A surface that renders perfectly and
dead-ends is a bug you're driving straight past.

## Fix what you find, then LOOP

For each real bug: fix it, add/extend a test that fails without the fix, rerun the unit tests + `tsc`,
and re-drive that surface in the browser to confirm. Then sweep again. Keep looping until a full pass
turns up NOTHING new (aim for one clean sweep after the last fix). Commit each fix as its own logical unit.

## Report

When a sweep is clean, tell Simon plainly: "no more bugs found." List what you tested (realistic + edge)
and the bugs you fixed with commit refs. The screenshots, the hand-back-and-open, and the opt-in PR post
are `/sk:ship-screenshot-changes`'s job — done via that skill, not restated here.
