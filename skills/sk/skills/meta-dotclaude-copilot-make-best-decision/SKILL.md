---
name: meta-dotclaude-copilot-make-best-decision
description: Take any set of items (bot alerts, SRE bot threads, tickets, incidents, an open question), research the best-practice answer online, inventory what the code already does, verify against read-only prod data, then decide per item whether it needs no action, a step only Simon can take (a plan or setting change in a vendor console), a config change, a PR, or a re-architecture. Runs the full work and ship skills only on items where a PR is clearly right, and ends with Simon's action points. Use for "make the best decision", "research best practice and verify with prod data", "do I need to take action on these", "look at all the bot alerts and fix what needs fixing", "look at all the sre bot convos", "maybe it just needs a plan change", or /sk:meta-dotclaude-copilot-make-best-decision.
argument-hint: "[the items, a channel, or a thread link; default: every open SRE bot thread]"
---

# Make the best decision per item, then act only where action is clearly right

Not every alert needs a PR. Some need a plan upgrade, a setting, a vendor ticket, or nothing. This
skill decides which, on evidence, then does only what the decision calls for.

## Per item (one record each, run items in parallel)

1. **Capture.** List each item as its own row in the session plan (`rules/living-plan.md`): source link, symptom, owner. Source is a bot or alert thread: read the whole thread first.
2. **Research online.** Find the most popular, vendor-documented practice for this exact problem. Order, judges and the claims-about-third-parties rule: `references/research.md`. Name the mainstream option and the alternatives rejected (`rules/engineering-standards.md` § Choose mainstream).
3. **Inventory what we have.** Read the code, config and limits that own the behaviour today. Quote what you opened.
4. **Verify with prod data, read-only.** Use every connector that reaches the facts, Vault-backed routes included, via `rules/connectors.md`. Corroborate each load-bearing number from two sources. Run `/sk:ship-verify-with-prod-data`. Project reads follow the project's memory (for PointsGPT SRE: keep prod reads outside :20-:35 past the hour). Paid calls: `rules/spend-approval.md`.
5. **Decide** with `/sk:work-does-this-make-sense-to-build`. The verdict space is wider than build or not:
   - **No action** (expected, already fixed, noise): cite the evidence.
   - **Simon action** (plan or quota raise, a vendor setting, a secret only he holds): exact click path or command, plus the deadline from the measured usage trend.
   - **Config change** (threshold, alert tuning, env value).
   - **PR** (code is clearly the right fix).
   - **Re-architecture** (move or replace the store or service): cost, migration path, and why a smaller step fails. Always a DECIDE for Simon with a recommendation, never started unasked.
6. **Act only on the verdict.** A clear PR runs `/sk:work-full-detailed-workflow`, whose last stage runs `/sk:ship-full-detailed-workflow`. Everything else spawns no branch.
7. **Reply in the source thread** when the item came from a bot or alert thread (Simon's standing ask): verdict, evidence, link to the PR or the action point. Outbound message rules: `rules/communication.md`; a Slack send follows its connector route.

## Hand-back

Per `rules/communication.md`: line 1 `Action needed (N): ...` or `No action needed`, then one table row per item (verdict, evidence link, PR or none), then the numbered action points for Simon, each with its exact step, expected result and deadline. DON'T open a PR for an item whose verdict is Simon action, no action or re-architecture. TEST: every item has one verdict, one evidence line from two sources, and a thread reply where it came from a thread.
