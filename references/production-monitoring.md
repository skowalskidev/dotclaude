# Production monitoring: the daily health pulse

How `/sk:monitor-daily-health-conversion-capacity-errors` judges a project, and the `monitor` block
it reads. The engine is `bin/health-pulse.py`; its docstring lists every probe and flag.

## What a daily pulse checks

**DO cover the four golden signals plus the business funnel, symptoms first.** Traffic, errors,
saturation (capacity) and latency from the
[Google SRE book](https://sre.google/sre-book/monitoring-distributed-systems/); RED (rate, errors,
duration) for request paths and USE (utilization, saturation, errors) for Postgres; then signups,
paywall conversion, trials, payments and refunds. A cause (a slow query) is detail under the
symptom it produces (API 5xx, statement timeouts).
**DON'T stop at the provider's status page.** Every service can be green while a webhook drops
payments or a paywall converts at half its rate.
TEST: a project's digest has at least one row in each of Traffic, Errors, Capacity and, when it
sells anything, Conversion and Revenue.

**DO read every log source, not one.** The engine counts failures in the API gateway, Postgres,
Edge Functions (status and logged errors), auth, every other service, and Edge Function shutdowns
at a CPU, memory or wall-clock limit, each with its top merged signatures and a cause hint per
Postgres SQLSTATE (`SQLSTATE_HINTS` in the engine).
TEST: an `Errors` row exists per log source, or the row says why it could not run.

**DO corroborate one fact across two sources wherever two exist.** A payment provider's successful
charges against the app's payment ledger for the same window; auth users against the app's signup
table. A gap past tolerance means a webhook or writer is dropping events.
TEST: a project with a payment connector and a ledger table has a `corroborate` pair for them.

## Baselines and when a change counts

**DO compare the last 24h with the same 24h on each of the previous 4 weeks.** Same-weekday
history cancels weekly seasonality; [Datadog's weekly seasonality](https://docs.datadoghq.com/monitors/types/anomaly/)
needs at least 3 weeks and uses up to 6. Logs keep about 7 days, so log rows compare with the
previous 24h; a short-retention table uses `trend: true` (the stored snapshots are its baseline).

**DO judge a rate with a pooled two-proportion z-test and a count with a Poisson z-score.** The
[NIST handbook](https://www.itl.nist.gov/div898/handbook/prc/section3/prc33.htm) gives the test.
Amber needs p < 0.05 and a 10% relative change; red needs p < 0.01 and 20%. Counts: amber at
z ≥ 2.33 and +50%, red at z ≥ 3.09 and +100% (a drop of a "higher is better" count: 20% and 40%).
**DON'T flag a move that is significant but not practical.** A rate must also move 0.5 percentage
points (`rateMinDeltaPts`): on half a million requests a 0.1-point rise is "significant" noise.
**DON'T call thin data green.** Under 5 events (`minEvents`) a row reads low-sample;
[peeking at thin data](https://www.evanmiller.org/how-not-to-run-an-ab-test.html) inflates false alarms.
TEST: `bin/health-pulse.test.py` holds a 4%-vs-10% paywall drop at red, a 9.2%-vs-10% dip at green
and a 0.2-point 5xx rise on 490k requests at green.

**DO measure conversion on a matured window.** Set `lagHours` to the conversion delay and count a
conversion only inside a fixed interval after the view (`purchase_at < viewed_at + interval '24 hours'`),
so the current and baseline cohorts had equal time to convert. RevenueCat warns that recent trial
cohorts read low until trials end ([experiment results](https://www.revenuecat.com/docs/tools/experiments-v1/experiments-results-v1)).
Pair it with a 1h-lag fast detector so a broken paywall shows the same day.

**DO split a conversion by platform (`seg`) and by paywall arm or variant (`grp`).** A new arm with
under `minBaselineEvents` (20) of history is judged against its platform's baseline and marked new;
an arm under `minEvents` goes in its platform's detail instead of a row.
TEST: the paywall scenario in the test file shows a new arm at 1% against its segment's 10% as its
own red row.

**DO use vendor thresholds for capacity.** Connections amber at 80% of `max_connections` and
sessions active over 30s, per Supabase [Detecting issues](https://supabase.com/docs/guides/observability/detecting.md);
disk, CPU and IOPS amber at 70% and red at 85%; memory (excluding cache) at 85% and 95%; cache hit
amber under 99%; disk also amber when growth fills it to 85% within 21 days.

## Presentation

**DO give every non-green row a cause.** The engine fills Likely cause from the top log signature
and its SQLSTATE hint, the metric's `hint`, a corroborate pair's `hint`, or the sender-side Twilio code;
a cause pinned in `monitor.causes` overrides it.

**DO rank worst first: red, amber, unknown, acknowledged, low-sample, green; a row that was green
in the previous snapshot is marked NEW and ranks first within its colour.** An unknown row always
carries the reason it could not measure.
**DO keep a known, accepted issue visible but muted** with an `acknowledge` entry that has an
`until` date; it returns to red or amber on the day after.
TEST: no acknowledgement lacks an `until` date and a reason.

## The `monitor` block

Lives in the project's private registry record (`<root>/projects/<project>.json`, `references/connectors-setup.md`), never in a repo: it names tables and
project ids. `health-pulse.py --draft` writes the generic part from the manifest's connectors.

| Key | Holds |
|---|---|
| `supabase` | `ref`, `tokenEnv` (management token), `metricsKeyEnv` (optional service or secret key for the privileged metrics endpoint; without it metrics come from the Management API through `tokenEnv`); `infrastructure`, `logs`, `authUsers` set false to skip |
| `revenuecat` | `projectId`, `keyEnv` (v2 key with `charts_metrics:overview:read`) |
| `stripe` | `keyEnv` (restricted read-only key, read over HTTPS; wins over the CLI) or `profile` (CLI project name), `account` (the expected `acct_…`, checked first) |
| `twilio` | env names for the account SID and API key; `messagingServiceSids` to scope a shared account |
| `metrics` | project SQL rows, below |
| `corroborate` | `{label, a, b, tolerancePct, minGap, hint}`; `a`/`b` are `stripe:charge.succeeded`, `metric:<id>`, `logs:<id>` or `revenuecat:<id>` |
| `acknowledge` | `{id, until, why}` per muted check |
| `causes` | `{<check id>: {cause, found, fix}}`, root causes triage proved; shown in the digest's Likely cause column |
| `thresholds` | overrides for any `DEFAULTS` key in the engine |
| `env` | extra key files beyond the connectors' `secret.path` entries |
| `notes` | repo-specific triage context the skill reads first (known causes, owners, dashboards) |

A metric is `{id, label, area, kind, sql, better, lagHours, hint}`:

- `kind: "rate"` returns rows of `num`, `den` and optional `seg`, `grp`.
- `kind: "count"` returns one row with `n`; `better` is `lower` (errors) or `higher` (signups).
- `kind: "value"` returns one row with `n` (a gauge, e.g. projected quota %) plus any detail columns;
  it takes `warnAbove`, `critAbove`, `warnBelow`, `critBelow`, `unit`, or `trend: true`.

**DO write each `sql` as one SELECT or WITH with `{start}` and `{end}` as the window bounds.** The
engine fills them, runs the query through the Management API with `read_only: true` (as
`supabase_read_only_user`), and refuses any write or session keyword.
TEST: every metric returns a row in a `--only metrics` run before the block is saved.

## Triage hints

| Signal | Usual cause | First read |
|---|---|---|
| Postgres 57014 with API 5xx on the same RPC | a query slower than the role's `statement_timeout` | the slow-queries row; `explain` the RPC read-only |
| 42501, 42703, 42883 after a migration | code and schema drifted | the Changes row; the migration's grants |
| Auth "unavailable due to hook" | an auth hook function failing | the hook's function logs |
| Edge Function WallClockTime shutdowns | a function waiting on a slow upstream | that function's logged errors |
| Stripe charges above ledger payments | the payment webhook is failing or skipping | the webhook-delivery row; the webhook function's logs |
| A sender with 30034 | US A2P 10DLC registration missing for that number | Twilio's error page linked in the row |
| Trials or conversions down with no error rise | an experiment arm, offering or price changed | experiment arms in the data; recent merges |
| A "stuck" or "never sent" row with a click time | the table also stores click-only rows; not a send | the code that inserts that row |
| Twilio 63024, 30005, 30006 | the recipient: not on WhatsApp, number gone, landline ([Twilio errors](https://www.twilio.com/docs/api/errors/63024)) | counted as undeliverable, never as our failure |
| Failures from a sender outside the project's services | another app on a shared provider account | scope with `messagingServiceSids`; report it to that app's owner |
