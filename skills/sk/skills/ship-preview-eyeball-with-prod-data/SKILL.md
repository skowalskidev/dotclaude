---
name: ship-preview-eyeball-with-prod-data
description: Show actual production account data in the changed app running locally before deployment, visually verify the affected screens, and leave a working local URL for review. Use for "preview locally with production data", "show real prod accounts on localhost", "eyeball production data before deploy", or "leave a local preview with real account data". Keep the source export read-only, isolate the preview runtime from production, and report source dates and any replay clock.
argument-hint: "[optional: account, route, or change to preview]"
---

# Preview the changed app with production data

Read `~/.claude/references/testing-strategy.md`, sections **Production source fidelity**,
**Prepare derived state before capture**, and **Local preview using production records**.
Run those sections against the current branch and the requested accounts and routes.

Compose `/sk:ship-verify-with-prod-data` when the diff changes stored-data figures, and
`/sk:test-eyeball` for the requested visual pass. Keep their results in the same preview evidence.
Do not restate their methods or claim fleet-wide coverage from the selected preview accounts.

Treat this invocation as authorization to prepare and visually inspect the local preview and leave
its required processes running for the user. Keep production exports and captures local; deployment,
production mutation, and publication of this evidence require a separate user request.

Hand back the working local URL, selected account and route, source capture time, original date range,
data mode, clock mode, visual verdict, and the exact stop/restart commands. Link the local evidence file.
TEST: the user can open the stated route after hand-back, trace its data to the recorded production
snapshot, and exercise the preview without any path to a production write.
