---
name: monitor-daily-health-conversion-capacity-errors
description: Daily production health check for any repo with connectors. Reads every connector read-only (Supabase capacity, logs and errors, conversion and paywall variants from the app's own tables, RevenueCat, Stripe, Twilio), compares the last 24h with the same weekday on prior weeks, corroborates across sources, and hands back one at-a-glance digest ranked worst first, with a likely cause and next step per red row. On a repo's first run it builds that repo's monitor block from its connectors and source. Use for "daily health check", "monitor everything", "did anything break", "is the new paywall tanking conversion", "are we running out of capacity on supabase", "are users hitting errors", or a morning check.
argument-hint: "[optional: project name, --hours N, or a probe to focus on: supabase, metrics, revenuecat, stripe, twilio]"
---

# Daily health pulse: see the invisible problems at a glance

The engine is `bin/health-pulse.py`; the method, thresholds and `monitor` block schema are
`references/production-monitoring.md`. Read the reference once per session before step 2.
Prod stays read-only (`rules/connectors.md`): every probe is a read, SQL runs with `read_only`, and
no step writes, refunds, sends or posts.

## 1. Resolve the project and its connectors

- DO run `python3 ~/.claude/bin/agent_runtime.py policy --cwd .` in the project's workspace; it names
  the matched `connectors/<project>.json` and the `ignoreProjectInstructions` boundary. Apply
  `references/project-instructions.md` before reading any repo doc.
- DO read that manifest and `references/connectors-setup.md` before the first probe; a connector that
  needs auth goes through the auth gate in `rules/connectors.md`, asked once with every gap together.
  TEST: no probe runs before the manifest was read this session.

## 2. First run in a repo: build its monitor block

Run this when the manifest has no `monitor` block, or Simon asks to re-tune it.

1. `python3 ~/.claude/bin/health-pulse.py --project <name> --draft` prints the generic block (Supabase
   ref, keys, Stripe profile and account, RevenueCat project, Twilio) derived from the connectors.
2. Find the repo's own signals in SOURCE (migrations, schema, functions, app code), not its guides:
   signup and activation tables, the paywall view, checkout and purchase timestamps, the platform
   and paywall-arm or offering columns, trials, payments, refunds, rows the app stores as failed or
   stuck, and quota or budget tables. Delegate the scan to one Explore agent with the instruction
   boundary in its prompt.
3. Write each signal as a metric in the reference's shape: conversion as a `rate` with `seg`
   (platform) and `grp` (arm) and a matured `lagHours`, plus a 1h fast detector; volumes as `count`;
   quotas and stuck queues as `value`. Add a `corroborate` pair for every fact two sources hold.
4. Verify read-only: `health-pulse.py --manifest <draft.json> --only metrics --no-snapshot` until
   every metric returns a row and none reads unknown. Spot-check two numbers with an independent
   query or the provider's own figure.
5. Save the block into the private manifest (keep its `chmod 600`), with repo-specific triage
   context in `monitor.notes`.
   TEST: the saved block has no unknown metric row, and nothing was written to the repo.

## 3. Run the pulse

- DO run `python3 ~/.claude/bin/health-pulse.py --project <name> --json`; it also saves the digest
  and a snapshot to `~/.claude/monitor/<project>/<date>.md|json`. Exit 1 means a red row exists.
- DO check every connector listed under "Connectors with no probe" by hand with its own read-only
  tool (e.g. new urgent bugs in the issue tracker, error reporting in a cloud console), one row each.
  TEST: every connector in the manifest has a row or a stated reason.

## 4. Triage every red, amber and unknown row

For each, worst first, at most 10:

- DO read its detail lines, then corroborate with a second read-only source: the log signature
  behind an error count, the code path that writes a failing row, the provider's own number.
- DO find what changed: the Changes row, `git log --since=48.hours --oneline origin/<default>` in the
  repo, new experiment arms or offerings in the data. Tie the row to a change, or say none fits.
- DO state the likely cause and one next step with the real name: the RPC, function, migration,
  arm, sender or quota. Use the reference's triage table and `monitor.notes` first.
- DON'T call a row a problem from one source when a second disagrees; say which source and why.
  TEST: every non-green row in the hand-back has a cause line (or "cause unknown" plus what was ruled
  out) and a next step.

## 5. Tune, so tomorrow's digest is sharper

- DO fix a false alarm at its source in the manifest: a threshold under `thresholds`, a better metric
  SQL, or an `acknowledge` entry with `until` and `why` for an accepted standing issue.
- DO add a metric when triage found a problem no row flagged.
  TEST: a re-run after tuning keeps every real problem red or amber and drops each tuned false alarm.

## 6. Hand back

Line 1 is `Action needed: <the top red row>` or `No action needed`, per `rules/communication.md`.
Then a table of the red and amber rows only (status, check, now vs baseline, cause, next step),
then one line naming the green count and the saved digest path. A fix runs through
`/sk:work-investigate-and-fix` when Simon asks for it; this skill only reads.
