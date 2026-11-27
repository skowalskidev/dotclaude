# KPIs: what this config optimizes

Three KPIs, in priority order. Every config change is judged against all three, and none is ever
dropped, renamed or traded away silently: `hooks/config-contract.test.py` fails when this file loses one.

1. **Ask coverage.** Every clause Simon asked for is checked against the result and built, without
   him asking twice or running a journey check himself.
2. **Quality of results.** The delivered work is right the first time: verified, no regression, no
   rework he has to request.
3. **Speed of delivery.** The same result reaches him in fewer model turns, tool calls and repeated
   checks, with no wait the work did not need.

DEFAULT: improve speed only while ask coverage and quality hold. A change that buys speed by lowering
either is a TRADE-OFF: it lands only with Simon's yes. A change that improves none is not a repair.

## Format

Each KPI is a set of indicators with a target, as Google SRE writes them: an SLI, "a carefully
defined quantitative measure", and an SLO, "a target value ... measured by an SLI", of the form
`SLI ≤ target` ([Google SRE book, Service Level Objectives](https://sre.google/sre-book/service-level-objectives/)).
Window: the last 14 days of sessions with 3 or more typed messages, compared with the 14 before
(`bin/kpi.py trend`). Delivery metrics follow DORA's pairing of throughput with instability, read
together ([DORA metrics](https://dora.dev/guides/dora-metrics-four-keys/)).

Wall-clock time swings with machine load (other sessions' builds and simulators share the CPU), so it
is reported beside the 1-minute load average and never decides. Counts and CPU seconds decide, as CI
benchmarking does for the same reason ([CodSpeed](https://codspeed.io/blog/benchmarks-in-ci-without-noise)).

| KPI | SLI | SLO | Enforced by |
|---|---|---|---|
| Ask coverage | Asks closed by a reconcile without their own verdict line | = 0 | `hooks/intent-ledger.sh note reconcile` refuses fewer verdict lines than asks |
| Ask coverage | Asks still open, not met or partly met when the archive line is given | = 0 | the intent-ledger Stop gate refuses the archive line until each is met, blocked on Simon or dropped by him |
| Quality | Rework rate: requests followed by a correction ("no", "you didn't", "still", "fix that") | ≤ 0.05 | `bin/kpi.py`; the end-of-session learning repairs the cause |
| Quality | Contract criteria failing on main | = 0 | `bin/config-land-check.py` |
| Speed | Model turns per request, median | ≤ 5 | `bin/kpi.py` |
| Speed | Stop-hook blocks per request | ≤ 0.3 | `hooks/intent-ledger.sh` skips paused turns |
| Speed | Polls of a background task's output | = 0 | `hooks/check-cache-guard.py` |
| Speed | Repeated identical checks (same command, same inputs) | = 0 | `hooks/check-cache-guard.py` (input-hash cache, as [Turborepo](https://turborepo.dev/docs/core-concepts/caching) and Nx do) |
| Speed | Subagents per small request (≤ 5 edits) | ≤ 0.1 | quick-path routing in `hooks/task-intake.sh` |
| Speed | Config suite CPU seconds per landing | down | runs once, at utility QoS (below task work), only in the land check |

Baseline (7 days to 2026-11-27, 947 requests): turns median 5, Stop blocks 0.98 per request, 79
polls, 0.38 subagents per small request. A transcript audit of 894 requests found background
verify/test subagents held 33% of active time and full-harness requests a 71-minute median.

## How the config steers toward them

- **Every landing names its KPI effect.** `bin/config-land-check.py` refuses a landing whose commits
  carry no `KPI:` line, e.g. `KPI: speed +, quality =, coverage = (one fewer Stop block per request)`.
- **The end-of-session learning measures, then repairs.** `bin/kpi.py session <sid> --record` appends
  the session to `state/kpi-history.jsonl`; `bin/kpi.py trend` shows each SLI against its SLO.
  `/sk:claude-config-self-optimize-analysis-after-run` ranks findings by KPI (coverage, then quality,
  then speed), repairs the SLO furthest from target first, and proposes nothing that worsens coverage
  or quality.
- **Size the work and the effort to the task.** A Light change or a follow-up takes the quick path:
  no spine skill, no subagent, one test run (`references/testing-strategy.md` § Quick path). Standard
  and Deep work runs the full harness; delegated checks run on the small model tier.
- **Verify once.** Checks run once on the converged head, never after every edit.
