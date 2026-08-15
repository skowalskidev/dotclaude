---
name: maintenance-code-optimize-app
description: Simon's web performance + Lighthouse audit harness — run Lighthouse yourself via the debug Chrome (never ask Simon to paste JSON), measure on a PRODUCTION build (never next dev), and apply the verified fixes for media payload, image optimization, lazy-loading, CSP, and accessibility audits. Use for any "make it faster", "run Lighthouse", "audit performance", "the page is slow", or Core Web Vitals task.
argument-hint: "[optional target, e.g. the landing page, a URL, or a specific audit]"
---

# Optimize App — performance & Lighthouse harness

Applies to any web app (Next.js assumed where specific). Run the audits yourself; report conclusions, not
raw JSON. The RULES are below; the exact commands + fix recipes live in two bundled references (read them
when the rule is in play):
- **How to measure** → `references/running-lighthouse.md` (prod build, debug Chrome, MCP perf trace,
  deployed-URL CLI pinned to Node 24, tool-artifact detection).
- **The fixes** → `references/verified-fixes.md` (video re-encode, `next/image` + `<picture>` art direction,
  media lazy-loading, a11y/agentic-browsing, CSP, the gotchas).

## Rule 0 — NEVER change colors

Simon has a standing instruction: **do not change the color palette, and do not "fix" `color-contrast`.**
It has been explicitly reverted before, twice. `color-contrast` scoring 0 is an accepted, deliberate state.
Never reapply contrast fixes, never touch the primary color, and don't re-raise it as a suggestion unless
Simon brings it up first.

## Rule 1 — Measure on a PRODUCTION build, never `next dev`

The single biggest source of false findings — a `next dev` Lighthouse run is worthless for performance
(real case: dev LCP 36,338 ms vs prod LCP 1,217 ms on the same code, ~30x). Always
`npm run build && npx next start -p 3100` and audit that. The dev-mode artifacts that mark a poisoned run,
and the exact commands, are in `references/running-lighthouse.md`.

**3100 is a placeholder, not a reservation.** Another session may already hold it, and in a work
monorepo it may be the landing app's own dev port. Take a lane first with `~/.claude/bin/port-slot.sh` and
audit the port it gives you; protocol in `~/.claude/references/dev-server-hygiene.md`. Auditing
someone else's server is a whole report about the wrong code.

## Rule 2 — Run Lighthouse yourself via the debug Chrome

Never ask Simon to paste a Lighthouse JSON report — drive it yourself. Launch a SEPARATE Chrome instance
(never kill Simon's everyday Chrome; he loses his tabs). `lighthouse_audit` EXCLUDES performance — run
`performance_start_trace` separately for perf. For a deployed URL with no MCP, run the Lighthouse CLI
**under Node 24** (`npx lighthouse` silently uses an old bundled Node and poisons the report). Full setup
+ command blocks + the errored-audit artifact check: `references/running-lighthouse.md`.

## Rule 3 — Lantern simulation ≠ what a user experiences

Lighthouse's Lantern simulates slow-4G + 4x CPU over the observed graph. A huge simulated LCP with a tiny
`observedLargestContentfulPaint` means the simulation is choking on payload, not that the page is broken.
Compare `observed*` vs simulated before believing a catastrophic number. (detail in
`references/running-lighthouse.md`)

## Rule 4 — Fix payload, not scheduling

Deferring a 45 MB payload still ships 45 MB. Re-encode / re-size FIRST; loading strategy is second-order.
The proven recipes — video (CRF 18, SSIM-verify), images (`next/image` + `getImageProps()`/`<picture>` art
direction), media lazy-loading (never above the fold) — are in `references/verified-fixes.md`.

## Rule 5 — Accessibility & agentic-browsing audits

`agentic-browsing` = `agent-accessibility-tree` + `cumulative-layout-shift` + `llms-txt` (one failure =
0.67). Common real fixes: swap Radix `Tabs` → `ToggleGroup type="single"` (kills a bogus `aria-controls`
failure); fix `heading-order` but **grep the CSS first** (it's often coupled to the tag name). Detail in
`references/verified-fixes.md`.

## Rule 6 — CSP

A CSP console error on every load also tanks Best Practices. Fix the CAUSE, don't widen the header — e.g.
`prefetch={false}` on cross-host `<Link>`s (a cross-origin prefetch is pure waste), and grep the WHOLE tree
for the pattern, not a hand-picked file list. Sentry's browser SDK needs `https://*.sentry.io` in
`connect-src`. Full detail + the empirical-proof step: `references/verified-fixes.md`.

## Workflow

1. Confirm scope + Rule 0 (no colors).
2. `npm run build && npx next start -p 3100`.
3. Launch the debug Chrome (separate profile, port 9222).
4. `lighthouse_audit` (a11y/BP/SEO/agentic) **and** `performance_start_trace` (perf) — mobile.
5. Parse the JSON; separate **real findings** from **dev-mode/Lantern artifacts**.
6. Research any fix online before applying it (Simon's standing rule: verify it's the popular, best-practice
   approach). Prefer the framework's *officially documented* pattern.
7. Delegate multi-file edits to **Sonnet 4.6** (`claude-sonnet-4-6`) with precise specs; keep
   planning/verification on the strong model. (Today's-landscape pin; the Agent `model` enum resolves
   the `sonnet` alias to Sonnet 5 — see `references/parallelization.md`.)
8. `npm run build && npm run test:run && npm run lint`.
9. **Re-run the audit to prove the fix**, and measure before/after in real bytes.
10. Commit **one logical unit per commit**, with the measured numbers in the message.
11. Update the project's `CLAUDE.md` + `ABOUT.md` (mandatory where the project requires it).
