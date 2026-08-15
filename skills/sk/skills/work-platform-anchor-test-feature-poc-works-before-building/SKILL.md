---
name: work-platform-anchor-test-feature-poc-works-before-building
description: Simon's live experiment harness — prove a feature or fix works by iterating against the REAL platform pipeline (real endpoints, real session/prod data, run in localhost as production would) BEFORE implementing it. User-driven loop: change only what's specified, show every asset + the exact payload and confirm before each billable/outward submit, read the real result, iterate to success, capture the working recipe, then tear down the scaffolding. Use for "let me test this before I build it", debugging why a real request fails, or dialing in a third-party API's behaviour.
argument-hint: "[what to prove / the real scenario to anchor to]"
---

# Platform-Anchored Spike — prove it before building

Prove an approach against the real platform before building it into the product. This is an
experiment, not an implementation — the output is a verified recipe and the confidence to build it,
not shipped code. Pairs with `full-detailed-workflow`'s "Verify foundation pillars" spike and
`~/.claude/references/api-empirical-iteration.md` — this is the interactive, user-driven version of that.

## Anchor to the real platform and real data
- Reproduce the ACTUAL scenario: run the platform's own code path / service functions and real
  endpoints, on real session or production data, in localhost exactly as production would run it.
  No mocks or stubs for the thing under test — a spike against an approximation proves nothing.
- **Take a lane before that localhost binds anything.** `~/.claude/bin/port-slot.sh` gives this worktree
  its own ports so the spike cannot attach to a neighbouring session's stack and prove the wrong thing;
  protocol in `~/.claude/references/dev-server-hygiene.md`.
- Pin the scenario to a concrete real case (e.g. a specific failing session id) and keep every input
  identical to the real request except the one thing being tested.
- Use the project's OWN keys/env the way the app loads them (its dotenv/config), scoped to THIS
  project only — never hand-roll a client or borrow another project's key.

## The user drives; change ONLY what they specify
- Simon runs the loop: he says what to try next, you make that ONE adjustment and nothing else.
- Touch only the exact inputs he names (e.g. "modify only this image"). Everything else stays
  byte-identical to the real request — treat the rest as an explicit DO-NOT-TOUCH list.
- Don't invent variations or "improve" adjacent inputs. One controlled change per iteration so the
  result is attributable to that change.

## Confirm before every billable / outward submit
- Before each real submission, show ALL of it: every asset that will be sent AND the exact payload
  (the full request body), so nothing goes out unseen.
- Temp-download any modified artifact (image, file) and surface it so Simon can eyeball it before
  it's sent; wait for an explicit yes.
- Say what the call is and its cost order-of-magnitude. Never submit on assumption. (Entering
  credentials/keys is still his to do — see the safety rules.)

## Iterate to success, logged
- Loop: Simon picks the change → apply it → show assets + payload → confirm → submit → read the REAL
  result (the actual API response/output, not a guess) → report plainly what happened → repeat.
- Keep a running log of each attempt: what changed, what was sent, what came back. It's the record
  of how the behaviour was cracked and the seed of the recipe.
- Read real outputs honestly — if it still fails, say so with the actual error; don't declare
  success until the real result proves it.

## Keep it a spike — don't build yet
- Do NOT fold changes into the product during the spike. The goal is to PROVE the recipe (exact
  inputs, params, order, transforms), not to ship it.
- Use clearly-marked throwaway scaffolding (a dev-only bridge, a scratch script) — never wire an
  experimental hack into a real code path.
- When it works, write the working recipe down precisely, then hand off to implementation as a
  SEPARATE step (a plan/ticket, or `full-detailed-workflow`).

## Tear down
- Remove all scaffolding when done: scratch scripts, temp downloads, dev-only bridges, any
  experimental env flag. Leave the repo and product exactly as clean as you found it.
- Call out explicitly anything that must NOT ship (a dev bridge, a debug flag) so it can't leak to
  production.

Extra context for this run (if any): $ARGUMENTS
