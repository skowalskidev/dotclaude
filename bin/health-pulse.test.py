#!/usr/bin/env python3
"""Offline regression tests for bin/health-pulse.py. Standard library only; no network, no keys.

Each scenario is a failure the daily pulse exists to catch, or a false alarm it must not raise:
a new paywall that tanks conversion, a share that is statistically but not practically worse, a
webhook dropping payments, a secret leaking into an error, a write slipping into manifest SQL.
"""
import datetime as dt
import importlib.util
import io
import json
import os
import re
import sys
import tempfile
from contextlib import redirect_stdout
from pathlib import Path

HERE = Path(__file__).resolve().parent
spec = importlib.util.spec_from_file_location("health_pulse", HERE / "health-pulse.py")
hp = importlib.util.module_from_spec(spec)
spec.loader.exec_module(hp)

FAILS = []
CFG = dict(hp.DEFAULTS)
NOW = dt.datetime(2026, 11, 6, 7, 0, tzinfo=dt.timezone.utc)


def expect(cond, msg):
    if not cond:
        FAILS.append(msg)


def ctx_for(monitor, state_dir, env=None, connectors=()):
    manifest = {"project": "demo", "connectors": list(connectors), "monitor": monitor}
    ctx = hp.Context(manifest, 24, NOW, state_dir)
    ctx.env.update(env or {})
    return ctx


class FakeSupabase:
    """Answers manifest SQL by the window it was rendered for: current window first, then baselines."""

    def __init__(self, by_week):
        self.by_week = by_week  # list of row lists, index 0 = current window

    def sql(self, query):
        m = re.search(r"'(\d{4}-\d\d-\d\dT[^']+)'::timestamptz", query)
        start = dt.datetime.fromisoformat(m.group(1))
        week = round((NOW - dt.timedelta(hours=24) - start).total_seconds() / (7 * 86400))
        return self.by_week[week] if week < len(self.by_week) else []


# ---------------------------------------------------------------- statistics

z, p = hp.two_proportion(10, 100, 20, 100)
expect(abs(z + 1.98) < 0.02 and abs(p - 0.0477) < 0.002, f"two-proportion z-test drifted: z={z:.3f} p={p:.4f}")
expect(hp.two_proportion(0, 0, 5, 10) == (0.0, 1.0), "empty sample must not divide by zero")

status, _ = hp.judge_rate(20, 500, 400, 4000, CFG)              # 4% vs 10%
expect(status == "crit", f"a conversion drop from 10% to 4% on 500 views must be crit, got {status}")
status, _ = hp.judge_rate(46, 500, 400, 4000, CFG)              # 9.2% vs 10%: noise
expect(status == "ok", f"a 0.8-point dip inside noise must stay green, got {status}")
status, why = hp.judge_rate(1, 3, 400, 4000, CFG)
expect(status == "low-sample", f"three views must read low-sample, not green or red: {status} {why}")
status, why = hp.judge_rate(2209, 490000, 1241, 461000, CFG, better="lower")  # 0.45% vs 0.27% 5xx
expect(status == "ok" and "points" in why,
       f"a 0.2-point rise on half a million requests is significant but not practical: {status} {why}")
status, _ = hp.judge_rate(6, 20, 11, 198, CFG, better="lower")  # a sender failing 30% vs 5.6%
expect(status == "crit", f"a sender jumping to 30% failures must be crit, got {status}")
status, _ = hp.judge_rate(3, 20, 0, 200, CFG, better="lower")
expect(status == "ok", f"fewer failures than minEvents must not alarm, got {status}")

expect(hp.judge_count(60, 10, CFG)[0] == "crit", "errors going 10 → 60 must be crit")
expect(hp.judge_count(12, 10, CFG)[0] == "ok", "errors going 10 → 12 must stay green")
expect(hp.judge_count(5, 22.8, CFG, better="higher")[0] == "crit", "trials going 23/day → 5 must be crit")
expect(hp.judge_count(1, 2, CFG, better="higher")[0] == "ok", "a drop smaller than minEvents must stay green")
expect(hp.judge_count(3, None, CFG)[0] == "low-sample", "no baseline must read low-sample")

expect(hp.judge_threshold(95, {"warnAbove": 90, "critAbove": 100})[0] == "warn", "gauge between warn and crit")
expect(hp.judge_threshold(101, {"warnAbove": 90, "critAbove": 100})[0] == "crit", "gauge past crit")
expect(hp.judge_pct(99.2, 99, 95, higher_is_worse=False) == "ok", "cache hit above 99% is green")
expect(hp.judge_pct(97, 99, 95, higher_is_worse=False) == "warn", "cache hit 97% is amber")

wins = hp.windows(NOW, 24, 4, lag_hours=24)
expect(len(wins) == 5 and wins[0][1] == NOW - dt.timedelta(hours=24) and
       wins[4][0] == NOW - dt.timedelta(hours=48, weeks=4), "windows must lag and step back whole weeks")

# ---------------------------------------------------------------- SQL guard (never a write)

sql = hp.render_sql("select count(*) as n from t where at >= {start} and at < {end}", wins[0][0], wins[0][1])
expect("'2026-11-04T07:00:00+00:00'::timestamptz" in sql, "render_sql must fill {start} with a literal")
for bad in ("delete from t", "select 1; drop table t", "with x as (delete from t returning *) select 1",
            "update t set a = 1", "select set_config('a', 'b', false)"[:0] + "set role postgres",
            "select 1 -- ok\n; insert into t values (1)"):
    try:
        hp.render_sql(bad, NOW, NOW)
        FAILS.append(f"render_sql accepted a write: {bad!r}")
    except hp.ProbeError:
        pass
expect("drop" in hp.render_sql("select 'drop' as word from t", NOW, NOW), "a keyword inside a string literal is data")

# ---------------------------------------------------------------- log signatures

sig = hp.normalize_signature("route_lookup for JFK: 57014 canceling statement 123456 for 3f2b1c9a-1111-2222-3333-444455556666")
expect("57014" in sig and "JFK" not in sig and ":id" in sig and "123456" not in sig,
       f"normalize must keep SQLSTATEs and collapse codes, numbers and ids: {sig}")
expect(hp.normalize_signature("500 POST /rest/v1/rpc/run_query").startswith("500 POST"), "HTTP status must survive")
merged = hp.merge_signatures([("for JFK: timeout", 5), ("for EWR: timeout", 7), ("other", 1)])
expect(merged[0] == ("for X: timeout", 12), f"variants of one failure must merge: {merged}")
expect("statement timeout" in (hp.sqlstate_hint("ERROR 57014 canceling statement") or ""), "57014 needs its hint")

# ---------------------------------------------------------------- secrets never leave the process

token = "sbp_" + "a1b2c3d4e5" * 4
text = hp.scrub(f"HTTP 401: invalid token {token} Bearer abc.def", ())
expect(token not in text and "abc.def" not in text, f"scrub must redact tokens: {text}")
expect("hunter2-long-value" not in hp.scrub("echoed hunter2-long-value back", ("hunter2-long-value",)),
       "scrub must redact any loaded key value")

with tempfile.TemporaryDirectory() as tmp:
    env_file = Path(tmp) / "keys.env"
    env_file.write_text("export A_TOKEN='quoted value'\n# B=commented\nC=plain\n")
    env = hp.load_env([env_file, Path(tmp) / "missing.env"])
    expect(env == {"A_TOKEN": "quoted value", "C": "plain"}, f"load_env parsed {env}")
    paths = hp.env_paths({"connectors": [{"secret": {"path": str(env_file)}}, {"secret": {"path": str(env_file)}}],
                          "monitor": {"env": ["~/x.env"]}})
    expect(len(paths) == 2, "key files come from connector secret paths, deduplicated, plus monitor.env")

# ---------------------------------------------------------------- the paywall scenario

with tempfile.TemporaryDirectory() as tmp:
    ctx = ctx_for({"supabase": {"ref": "x"}}, tmp, {"SUPABASE_ACCESS_TOKEN": "t" * 20})
    base_week = [{"seg": "web", "grp": "control", "num": 30, "den": 300},
                 {"seg": "ios", "grp": "control", "num": 30, "den": 200}]
    current = [{"seg": "web", "grp": "control", "num": 15, "den": 150},
               {"seg": "web", "grp": "new_wall", "num": 2, "den": 200},     # 1% vs web's 10%
               {"seg": "web", "grp": "tiny_arm", "num": 0, "den": 2},
               {"seg": "ios", "grp": "control", "num": 30, "den": 200}]
    fake = FakeSupabase([current] + [base_week] * 4)
    rows = hp.rate_metric(ctx, fake, {"id": "pw", "label": "Paywall → purchase", "sql": "select 1 where {start} < {end}"})
    by_id = {r["id"]: r for r in rows}
    expect(by_id.get("pw:web · new_wall", {}).get("status") == "crit",
           f"a new paywall arm converting 1% against its segment's 10% must be its own crit row: {list(by_id)}")
    expect("new group" in by_id.get("pw:web · new_wall", {}).get("why", ""), "the new arm must say it is new")
    expect(by_id.get("pw:web", {}).get("status") in ("crit", "warn"), "the web segment must show the drop too")
    expect(by_id.get("pw:ios", {}).get("status") == "ok", "an untouched platform stays green")
    expect("pw:web · tiny_arm" not in by_id and any("tiny_arm" in d for d in by_id["pw:web"]["detail"]),
           "a two-view arm goes in the segment's detail, not its own row")
    expect(ctx.values.get("metric:pw") == 552, "the rate metric records its current denominator for corroboration")

# ---------------------------------------------------------------- full run: ranking, NEW, corroboration, exit code

with tempfile.TemporaryDirectory() as tmp:
    state = Path(tmp) / "demo"
    state.mkdir()
    (state / "2026-11-05.json").write_text(json.dumps({
        "at": (NOW - dt.timedelta(days=1)).isoformat(), "date": "2026-11-05", "values": {},
        "statuses": {"fake-errors": "ok", "fake-disk": "warn"}}))
    monitor = {"stripe": {"profile": "p"}, "corroborate": [
        {"label": "Charges vs ledger", "a": "stripe:charge.succeeded", "b": "metric:ledger", "tolerancePct": 20, "minGap": 3}]}
    ctx = ctx_for(monitor, tmp)

    def fake_stripe(c):
        c.values["stripe:charge.succeeded"] = 48
        c.values["metric:ledger"] = 20
        return [hp.check("Errors", "fake-errors", "Fake errors", "warn", "9", "1", "up"),
                hp.check("Capacity", "fake-disk", "Fake disk", "warn", "80%"),
                hp.check("Revenue", "fake-ok", "Fake ok", "ok", "1"),
                hp.check("Errors", "fake-unknown", "Fake unknown", "unknown", why="HTTP 403")]

    saved = dict(hp.PROBES)
    hp.PROBES.clear()
    hp.PROBES.update({"stripe": fake_stripe})
    try:
        checks = hp.run(ctx, set())
    finally:
        hp.PROBES.clear()
        hp.PROBES.update(saved)
    order = [c["id"] for c in checks]
    expect(order[0].startswith("corroborate-"), f"a 28-payment gap between Stripe and the ledger is crit and ranks first: {order}")
    expect(order.index("fake-errors") < order.index("fake-disk"), "a NEW amber ranks above a standing amber")
    expect(next(c for c in checks if c["id"] == "fake-errors")["new"], "green yesterday, amber today is NEW")
    expect(not next(c for c in checks if c["id"] == "fake-disk")["new"], "amber both days is not NEW")
    expect(order[-1] == "fake-ok", "green ranks last")
    md = hp.markdown(ctx, checks)
    expect("**NEW**" in md and "HTTP 403" in md, "the digest shows NEW and every unknown's reason")

# A probe that raises with a secret in its message never prints it, and a crash stays one row.
with tempfile.TemporaryDirectory() as tmp:
    secret = "sk_live_" + "Z" * 30
    ctx = ctx_for({"stripe": {"profile": "p"}, "twilio": {"maxPages": 1}}, tmp, {"STRIPE_KEY": secret})

    def leaky(c):
        raise hp.ProbeError(hp.scrub("auth failed for " + secret, c.secrets()))

    def crashing(c):
        raise KeyError(secret)

    saved = dict(hp.PROBES)
    hp.PROBES.clear()
    hp.PROBES.update({"stripe": leaky, "twilio": crashing})
    try:
        checks = hp.run(ctx, set())
    finally:
        hp.PROBES.clear()
        hp.PROBES.update(saved)
    dump = json.dumps(checks)
    expect(secret not in dump, "a key value reached the report")
    expect(len(checks) == 2 and all(c["status"] == "unknown" for c in checks), "each failed probe is one unknown row")

# ---------------------------------------------------------------- CLI contract

with tempfile.TemporaryDirectory() as tmp:
    bare = Path(tmp) / "bare.json"
    bare.write_text(json.dumps({"project": "bare", "connectors": []}))
    buf = io.StringIO()
    with redirect_stdout(buf):
        code = hp.main(["--manifest", str(bare), "--state-dir", tmp])
    expect(code == 2, "a manifest with no monitor block exits 2 and points at the reference")
    expect(hp.main(["--manifest", str(bare), "--only", "nope", "--state-dir", tmp]) == 2, "unknown probe exits 2")

# The draft derives the generic probes from a manifest's connectors, with no project SQL.
draft = hp.draft_monitor({"project": "demo", "connectors": [
    {"name": "supabase", "mcp": {"url": "https://mcp.supabase.com/mcp?project_ref=abcdefghijklmnopqrst&read_only=true"}},
    {"name": "stripe", "cli": {"name": "stripe", "profile": "demo"}, "auth": {"how": "account acct_1ABCDEF is ours"}},
    {"name": "revenuecat", "auth": {"how": "project id proj1a2b3c4d here"}},
    {"name": "twilio-api", "secret": {"path": "~/k.env"}}]})
expect(draft.get("supabase", {}).get("ref") == "abcdefghijklmnopqrst", f"draft supabase ref: {draft}")
expect(draft.get("stripe") == {"profile": "demo", "account": "acct_1ABCDEF"}, f"draft stripe: {draft.get('stripe')}")
expect(draft.get("revenuecat", {}).get("projectId") == "proj1a2b3c4d", "draft revenuecat project")
expect("twilio" in draft and draft.get("metrics") == [], "draft has twilio and an empty metrics list to fill")

# A sandbox connector listed first must not win over prod; non-probe connectors are listed.
two = {"connectors": [{"name": "stripe-sandbox", "env": "test", "cli": {"profile": "sandbox"}},
                      {"name": "stripe-prod", "env": "production", "cli": {"profile": "live"}},
                      {"name": "linear", "env": "prod"}, {"name": "pal"}, {"name": "firebase-prod"}]}
expect(hp.draft_monitor(two)["stripe"]["profile"] == "live", "the draft must monitor the prod Stripe profile")
expect(hp.uncovered(two) == ["firebase-prod", "linear"], f"uncovered connectors: {hp.uncovered(two)}")

# An acknowledged amber reads 🔕 until its date, then comes back, and never sets the exit code.
with tempfile.TemporaryDirectory() as tmp:
    ctx = ctx_for({"acknowledge": [{"id": "a", "until": "2026-11-10", "why": "known"},
                                   {"id": "b", "until": "2026-11-01", "why": "expired"}]}, tmp)
    rows = [hp.check("Errors", "a", "A", "warn"), hp.check("Errors", "b", "B", "crit")]
    hp.acknowledge(ctx, rows)
    expect(rows[0]["status"] == "ack" and "known" in rows[0]["why"], "a live acknowledgement mutes the row")
    expect(rows[1]["status"] == "crit", "an expired acknowledgement no longer mutes")

# Cumulative counters average over the interval since the last run, and a reset reads as no history.
with tempfile.TemporaryDirectory() as tmp:
    state = Path(tmp) / "demo"
    state.mkdir()
    (state / "2026-11-05.json").write_text(json.dumps({"at": (NOW - dt.timedelta(hours=24)).isoformat(),
                                                        "date": "2026-11-05", "values": {"ops": 1000}}))
    ctx = ctx_for({}, tmp)
    delta, secs = hp.since_last_run(ctx, "ops", 87400)
    expect(delta == 86400 and abs(secs - 86400) < 1, f"since_last_run delta={delta} secs={secs}")
    expect(hp.since_last_run(ctx, "ops", 10) == (None, None), "a counter below its last value restarted")

if FAILS:
    print("FAIL health-pulse:\n- " + "\n- ".join(FAILS))
    sys.exit(1)
print("ok health-pulse")
