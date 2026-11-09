#!/usr/bin/env python3
"""Daily production health pulse: one read-only sweep of every connector a project's manifest declares.

  health-pulse.py [--project NAME | --manifest PATH] [--json] [--only PROBE,...] [--hours 24]
                  [--state-dir DIR] [--no-snapshot]

Reads the `monitor` block of the project's record in the connector registry (bin/connector_registry.py;
resolved from the current directory's git origin when --project is omitted) and runs each probe it
enables:

  supabase   infrastructure (disk, memory, CPU, IOPS, connections, pooler queue) from the project's
             Prometheus endpoint; Postgres cache hit, long-running and slowest queries; service
             health; security and performance advisors; error logs from every log source (API
             gateway, Postgres, Edge Functions, auth, everything else) with the top signatures and a
             cause hint per Postgres error code; Edge Function limit hits; failed pg_cron runs; new
             auth users; and what changed (migrations, Edge Function deploys).
  metrics    project SQL declared in the manifest: rates (conversion, failure share), counts and
             gauges. Rates and counts run for the last --hours and for the same window on each of
             the previous `baselineWeeks` weeks, so weekday seasonality cancels. Rates use a pooled
             two-proportion z-test, counts a Poisson z-score, and anything under `minEvents` reads
             low-sample instead of green.
  revenuecat overview metrics against the stored snapshot about a week old.
  stripe     failed-charge share, failed invoices, disputes, events whose webhook delivery failed and
             disabled endpoints, through a restricted key over HTTPS (stripe.keyEnv) or the CLI
             profile, after checking it reads the expected account.
  twilio     failed or undelivered share per messaging service with top error codes, and debugger
             alerts. Aggregates only: no message body or phone number is read into the report.
  corroborate  pairs of counts from two sources for the same window (e.g. Stripe charges against
             the app's payment ledger); a gap past tolerance means a webhook or writer is dropping.

Every call is a read. SQL goes through the Supabase Management API with read_only set, and manifest
SQL that is not one SELECT or WITH statement is refused. Keys load in-process from the connectors'
`secret.path` files and are never printed; error text is scrubbed. A probe that cannot run reports
`unknown` with the reason instead of disappearing.

Output: a markdown digest ranked worst first, a check that was green in the previous snapshot is
marked NEW (or --json). A dated snapshot of plain numbers and the digest (.json + .md) go to
~/.claude/monitor/<project>/ (untracked) for growth, trend and new-since-yesterday baselines.
--draft prints the generic monitor block a first run derives from the manifest's connectors.
Exit 0: report written, nothing critical. Exit 1: at least one critical check. Exit 2: usage or
manifest error. Python 3.9+, standard library only.
"""

from __future__ import annotations

import argparse
import base64
import concurrent.futures
import datetime as dt
import json
import math
import os
import re
import shutil
import subprocess
import sys
import time
import urllib.error
import urllib.parse
import urllib.request
from pathlib import Path

HOME_CLAUDE = Path(os.environ.get("CLAUDE_HOME", Path.home() / ".claude"))
STATE_DIR = HOME_CLAUDE / "monitor"
SUPABASE_API = "https://api.supabase.com/v1"
RC_API = "https://api.revenuecat.com/v2"
STRIPE_API = "https://api.stripe.com"
TWILIO_API = "https://api.twilio.com/2010-04-01"
TWILIO_MONITOR = "https://monitor.twilio.com/v1"
TIMEOUT = 45

# crit first, so sorting by this ranks the digest worst first.
RANK = {"crit": 0, "warn": 1, "unknown": 2, "ack": 3, "low-sample": 4, "ok": 5}
ICON = {"crit": "🔴", "warn": "🟠", "unknown": "⚪", "ack": "🔕", "low-sample": "⚪", "ok": "🟢"}
DEFAULTS = {
    "baselineWeeks": 4,          # Datadog's weekly seasonality uses 3 to 6 weeks of same-weekday history.
    "capacityWarnPct": 70.0,     # disk, IOPS, CPU
    "capacityCritPct": 85.0,
    "memoryWarnPct": 85.0,
    "memoryCritPct": 95.0,
    "connectionsWarnPct": 80.0,  # Supabase "Detecting issues" alerts at 80% of max_connections.
    "connectionsCritPct": 90.0,
    "cacheHitWarnPct": 99.0,
    "cacheHitCritPct": 95.0,
    "rateWarnChangePct": 10.0,
    "rateCritChangePct": 20.0,
    "rateMinDeltaPts": 0.5,      # practical significance: a huge sample makes a 0.1-point move "significant"
    "countWarnChangePct": 50.0,
    "countCritChangePct": 100.0,
    "minEvents": 5,
    "minBaselineEvents": 20,     # a group with less history than this is judged against its segment
    "failShareWarnPct": 10.0,    # a delivery channel failing this share of sends is amber even if not new
    "failShareCritPct": 50.0,
    "longQuerySeconds": 30,      # Supabase "Detecting issues": active sessions older than 30 seconds.
    "slowQueryMs": 1000,
    "slowQueryMinCalls": 100,
    "daysToFullWarn": 21,
}
# What a Postgres SQLSTATE in the error logs usually means, so a red row carries its likely cause.
SQLSTATE_HINTS = {
    "57014": "statement timeout: a query is slower than the role's statement_timeout (missing index, lock wait or load)",
    "53300": "too many connections: the pool or max_connections is exhausted",
    "53100": "disk full",
    "53200": "out of memory",
    "40P01": "deadlock between concurrent writes",
    "40001": "serialization failure under concurrent writes",
    "55P03": "lock not available: a lock_timeout fired",
    "42501": "permission denied: a grant or RLS policy no longer matches the caller (check recent migrations)",
    "42703": "undefined column: code and schema disagree (a deploy or migration drifted)",
    "42883": "undefined function or operator: code and schema disagree",
    "42P01": "undefined table: code and schema disagree",
    "42601": "SQL syntax error in an application query",
    "23505": "unique violation: duplicate insert, usually a retry or race",
    "23503": "foreign key violation",
    "P0001": "raised by a PL/pgSQL function (RAISE EXCEPTION)",
    "57P01": "connection terminated by an administrator or restart",
    "57P03": "database starting up (a restart happened)",
    "08006": "connection failure",
}
# Connector-name prefixes the engine probes; any other data connector is listed for a manual check.
COVERED = ("supabase", "stripe", "revenuecat", "twilio")
NOT_DATA = ("pal", "slack")  # model and messaging tools, not production signal sources
# Twilio delivery errors the RECIPIENT causes (not on WhatsApp, number gone, landline), per Twilio's
# own error pages. They are listed but never count as our failure; 30034 (unregistered sender) does.
RECIPIENT_SIDE_ERRORS = {"63024", "30005", "30006"}
FUNCTION_LIMIT_REASONS = ("WallClockTime", "CPUTime", "Memory")
CAPS_KEEP = {"GET", "POST", "PUT", "PATCH", "DELETE", "HEAD", "ERROR", "FATAL", "PANIC", "LOG", "INFO",
             "WARN", "WARNING", "SQL", "API", "JWT", "RPC", "OTP", "SMS", "URL", "HTTP", "RLS", "UTC"}
SECRET_PATTERNS = re.compile(
    r"(sbp_[A-Za-z0-9]{8,}|sb_secret_[A-Za-z0-9_\-]{8,}|sk_(live|test)_[A-Za-z0-9]{8,}|"
    r"rk_(live|test)_[A-Za-z0-9]{8,}|eyJ[A-Za-z0-9_\-]{10,}\.[A-Za-z0-9_\-\.]+|Bearer\s+\S+|Basic\s+\S+)")


class ProbeError(Exception):
    """A probe could not measure; the message becomes the check's reason and must hold no secret."""


def scrub(text, secrets=()) -> str:
    text = SECRET_PATTERNS.sub("<redacted>", str(text))
    for value in secrets:
        if value and len(value) >= 6:
            text = text.replace(value, "<redacted>")
    return text[:400]


# ---------------------------------------------------------------- statistics (pure, unit-tested)

def two_proportion(x1, n1, x0, n0):
    """z and two-sided p for rate x1/n1 against x0/n0 (pooled two-proportion z-test, NIST 7.3.3)."""
    if n1 <= 0 or n0 <= 0:
        return 0.0, 1.0
    pooled = (x1 + x0) / (n1 + n0)
    se = math.sqrt(pooled * (1 - pooled) * (1 / n1 + 1 / n0))
    if se == 0:
        return 0.0, 1.0
    z = (x1 / n1 - x0 / n0) / se
    return z, math.erfc(abs(z) / math.sqrt(2))


def poisson_z(current, mean):
    """Normal approximation with continuity correction: how unusual `current` is for a Poisson mean."""
    step = -0.5 if current > mean else 0.5
    return (current + step - mean) / math.sqrt(max(mean, 1.0))


def judge_rate(x1, n1, x0, n0, cfg, better="higher"):
    """Status for a rate now (x1/n1) against its pooled baseline (x0/n0)."""
    if n0 <= 0:
        return "low-sample", "no baseline yet"
    p0 = x0 / n0
    expected = n1 * (p0 if better == "higher" else max(p0, 1 / max(n0, 1)))
    if n1 < cfg["minEvents"] or (better == "higher" and expected < cfg["minEvents"]):
        return "low-sample", f"too few events to judge (n={num(n1)})"
    p1 = x1 / n1
    _, p = two_proportion(x1, n1, x0, n0)
    change = ((p1 - p0) / p0 * 100) if p0 else (100.0 if p1 else 0.0)
    worse = change < 0 if better == "higher" else change > 0
    if better == "lower" and x1 < cfg["minEvents"]:
        worse = False  # a handful of failures is noise, not a regression
    text = f"{change:+.0f}% vs baseline, p={p:.3f}" if p < 0.05 else f"{change:+.0f}% vs baseline (noise, p={p:.2f})"
    if worse and abs(p1 - p0) * 100 < cfg["rateMinDeltaPts"]:
        return "ok", text + f"; under {cfg['rateMinDeltaPts']:g} points"
    if worse and p < 0.01 and abs(change) >= cfg["rateCritChangePct"]:
        return "crit", text
    if worse and p < 0.05 and abs(change) >= cfg["rateWarnChangePct"]:
        return "warn", text
    return "ok", text


def judge_count(current, baseline_mean, cfg, better="lower"):
    """Status for an event count now against the mean of its baseline windows."""
    if baseline_mean is None:
        return "low-sample", "no baseline yet"
    z = poisson_z(current, baseline_mean)
    change = ((current - baseline_mean) / baseline_mean * 100) if baseline_mean else (100.0 if current else 0.0)
    worse = (current > baseline_mean) if better == "lower" else (current < baseline_mean)
    text = f"{change:+.0f}% vs baseline (z={z:+.1f})"
    if not worse or abs(current - baseline_mean) < cfg["minEvents"]:
        return "ok", text
    if better == "higher" and baseline_mean < cfg["minEvents"]:
        return "low-sample", f"baseline too small to judge a drop ({baseline_mean:.1f})"
    crit = cfg["countCritChangePct"] if better == "lower" else cfg["rateCritChangePct"] * 2
    warn = cfg["countWarnChangePct"] if better == "lower" else cfg["rateCritChangePct"]
    if abs(z) >= 3.09 and abs(change) >= crit:
        return "crit", text
    if abs(z) >= 2.33 and abs(change) >= warn:
        return "warn", text
    return "ok", text


def judge_threshold(value, metric):
    """Status for a gauge against the manifest's critAbove/critBelow/warnAbove/warnBelow."""
    for key, status, above in (("critAbove", "crit", True), ("critBelow", "crit", False),
                               ("warnAbove", "warn", True), ("warnBelow", "warn", False)):
        limit = metric.get(key)
        if limit is not None and ((value > limit) if above else (value < limit)):
            return status, f"{'above' if above else 'below'} {limit:g}"
    return "ok", ""


def judge_pct(pct, warn, crit, higher_is_worse=True):
    if higher_is_worse:
        return "crit" if pct >= crit else "warn" if pct >= warn else "ok"
    return "crit" if pct < crit else "warn" if pct < warn else "ok"


def windows(now, hours, weeks, lag_hours=0.0):
    """The current window first, then the same window shifted back one week at a time."""
    end = now - dt.timedelta(hours=lag_hours)
    start = end - dt.timedelta(hours=hours)
    return [(start - dt.timedelta(weeks=k), end - dt.timedelta(weeks=k)) for k in range(weeks + 1)]


def render_sql(sql, start, end):
    """Fill {start}/{end} with engine-generated timestamptz literals; refuse anything but one read."""
    body = re.sub(r"--[^\n]*", "", sql).strip().rstrip(";").strip()
    if not re.match(r"(?is)^(select|with)\b", body) or ";" in body:
        raise ProbeError("manifest SQL must be one SELECT or WITH statement")
    if re.search(r"(?i)\b(insert|update|delete|truncate|alter|drop|create|grant|revoke|copy|call|do|"
                 r"vacuum|analyze|refresh|reindex|cluster|lock|set|reset|notify)\b",
                 re.sub(r"'[^']*'", "''", body)):
        raise ProbeError("manifest SQL contains a write or session keyword")
    literal = "'{}'::timestamptz"
    return body.replace("{start}", literal.format(start.isoformat())).replace("{end}", literal.format(end.isoformat()))


def normalize_signature(sig):
    """Collapse ids, numbers and short code-like tokens so one failure mode is one signature."""
    sig = re.sub(r"[0-9a-f]{8}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{12}", ":id", str(sig))
    sig = re.sub(r"\b\d+\b", lambda m: m.group(0) if len(m.group(0)) in (3, 5) else "N", sig)
    sig = re.sub(r"\b[A-Z]{2,5}\b", lambda m: m.group(0) if m.group(0) in CAPS_KEEP else "X", sig)
    sig = re.sub(r"'[^']{0,80}'", "'…'", sig)
    return re.sub(r"\s+", " ", sig).strip()[:160]


def merge_signatures(rows, limit=6):
    """[(sig, n)] -> top `limit` merged signatures, largest first."""
    merged = {}
    for sig, n in rows:
        key = normalize_signature(sig)
        merged[key] = merged.get(key, 0) + int(n)
    return sorted(merged.items(), key=lambda kv: -kv[1])[:limit]


def sqlstate_hint(sig):
    for code in re.findall(r"\b([0-9A-Z]{5})\b", sig):
        if any(ch.isdigit() for ch in code) and code in SQLSTATE_HINTS:
            return SQLSTATE_HINTS[code]
    return None


def check(area, cid, label, status, now="", baseline="", why="", detail=None, source="", cause=""):
    """One digest row. `why` is the statistic that judged it; `cause` the likely cause, which a cause
    pinned in the manifest's monitor.causes overrides."""
    return {"area": area, "id": cid, "label": label, "status": status, "now": now, "baseline": baseline,
            "why": why, "detail": detail or [], "source": source, "new": False, "cause": cause}


def num(x):
    """Whole counts as integers; a weekly-average baseline under 10 keeps one decimal so 0.2 never reads 0."""
    return f"{x:,.0f}" if float(x).is_integer() or abs(x) >= 10 else f"{x:.1f}"


def fmt_pct(x, n):
    return f"{(x / n * 100):.1f}% ({num(x)}/{num(n)})" if n else "n/a (0 events)"


def gb(b):
    return f"{b / 1024 ** 3:.2f} GB"


# ---------------------------------------------------------------- context: manifest, keys, HTTP, snapshots

class Context:
    def __init__(self, manifest, hours, now, state_dir):
        self.manifest = manifest
        self.project = manifest.get("project", "project")
        self.monitor = manifest.get("monitor") or {}
        self.cfg = {**DEFAULTS, **(self.monitor.get("thresholds") or {})}
        self.cfg["baselineWeeks"] = int(self.monitor.get("baselineWeeks", self.cfg["baselineWeeks"]))
        self.hours = hours
        self.now = now
        self.state_dir = Path(state_dir) / self.project
        self.env = load_env(env_paths(manifest))
        self.snapshot = {}   # plain numbers saved for tomorrow's baselines
        self.values = {}     # current-window counts other probes and corroborate rows read
        self._snapshots = None

    def secret(self, name):
        value = self.env.get(name) or os.environ.get(name, "")
        if not value:
            raise ProbeError(f"{name} is not set in the connector key files or the environment")
        return value

    def secrets(self):
        named = [os.environ.get(n, "") for n in self.secret_names()]
        return tuple(v for v in [*self.env.values(), *named] if len(v) >= 12)

    def secret_names(self):
        """Every env name the monitor block reads a key from, so scrub() also covers keys from os.environ."""
        names = []
        for conf in self.monitor.values():
            if isinstance(conf, dict):
                names += [v for k, v in conf.items() if k.endswith("Env") and isinstance(v, str)]
        return names

    def http(self, url, headers, data=None):
        body = json.dumps(data).encode() if data is not None else None
        req = urllib.request.Request(url, data=body, method="POST" if body else "GET", headers={
            "Accept": "application/json", "User-Agent": "health-pulse/1",
            **({"Content-Type": "application/json"} if body else {}), **headers})
        where = urllib.parse.urlsplit(url)
        for attempt in range(3):
            try:
                with urllib.request.urlopen(req, timeout=TIMEOUT) as resp:
                    raw = resp.read().decode()
                return json.loads(raw) if raw.strip() and raw.lstrip()[0] in "[{" else raw
            except urllib.error.HTTPError as e:
                detail = e.read().decode(errors="replace") if e.fp else ""
                if e.code == 429 and attempt < 2:
                    time.sleep(5 * (attempt + 1))  # documented rate limits; back off and retry the read
                    continue
                raise ProbeError(f"HTTP {e.code} from {where.netloc}{where.path}: "
                                 f"{scrub(detail, self.secrets())}") from None
            except (urllib.error.URLError, TimeoutError, OSError) as e:
                raise ProbeError(f"cannot reach {where.netloc}: {scrub(e, self.secrets())}") from None
        raise ProbeError(f"rate limited by {where.netloc}")

    def snapshots(self):
        if self._snapshots is None:
            self._snapshots = []
            for path in sorted(self.state_dir.glob("*.json")) if self.state_dir.is_dir() else []:
                try:
                    data = json.loads(path.read_text())
                    data["_age"] = (self.now - dt.datetime.fromisoformat(data["at"])).total_seconds() / 86400
                    self._snapshots.append(data)
                except (ValueError, KeyError, OSError):
                    continue
        return self._snapshots

    def previous_snapshot(self, min_age_days):
        """The newest stored snapshot at least min_age_days old."""
        ok = [s for s in self.snapshots() if s["_age"] >= min_age_days]
        return min(ok, key=lambda s: s["_age"]) if ok else None


def env_paths(manifest):
    """Key files come from the connectors' own secret.path entries (one source), plus monitor.env."""
    seen, paths = set(), []
    for raw in [*(c.get("secret", {}).get("path") for c in manifest.get("connectors", [])),
                *((manifest.get("monitor") or {}).get("env") or [])]:
        if raw and raw not in seen:
            seen.add(raw)
            paths.append(Path(os.path.expanduser(raw)))
    return paths


def load_env(paths):
    """KEY=VALUE lines into a private dict. Never exported, never printed."""
    env = {}
    for path in paths:
        if not path.is_file():
            continue
        for line in path.read_text(errors="replace").splitlines():
            m = re.match(r"\s*(?:export\s+)?([A-Za-z_][A-Za-z0-9_]*)\s*=\s*(.*)$", line)
            if m and not line.lstrip().startswith("#"):
                value = m.group(2).strip()
                if len(value) >= 2 and value[0] == value[-1] and value[0] in "'\"":
                    value = value[1:-1]
                env.setdefault(m.group(1), value)
    return env


def growth_per_day(ctx, key, value):
    """Change per day against the newest stored snapshot at least six days old."""
    old = ctx.previous_snapshot(min_age_days=6)
    if not old or key not in old.get("values", {}):
        return None
    return (value - float(old["values"][key])) / old["_age"]


# ---------------------------------------------------------------- Supabase

class Supabase:
    def __init__(self, ctx):
        conf = ctx.monitor.get("supabase") or {}
        self.ctx, self.ref, self.conf = ctx, conf.get("ref"), conf
        if not self.ref:
            raise ProbeError("monitor.supabase.ref is missing")
        self.headers = {"Authorization": "Bearer " + ctx.secret(conf.get("tokenEnv", "SUPABASE_ACCESS_TOKEN"))}

    def get(self, path, **params):
        query = ("?" + urllib.parse.urlencode(params)) if params else ""
        return self.ctx.http(f"{SUPABASE_API}/projects/{self.ref}{path}{query}", self.headers)

    def sql(self, query):
        rows = self.ctx.http(f"{SUPABASE_API}/projects/{self.ref}/database/query", self.headers,
                             {"query": query, "read_only": True})
        if isinstance(rows, dict) and "result" in rows:
            rows = rows["result"]
        if not isinstance(rows, list):
            raise ProbeError("unexpected query response: " + scrub(json.dumps(rows), self.ctx.secrets()))
        return rows

    def logs(self, sql, start, end):
        """ClickHouse SQL over the `logs` table (one row per event, `source` names the service)."""
        z = "%Y-%m-%dT%H:%M:%S.000Z"
        data = self.get("/analytics/endpoints/logs", sql=sql, iso_timestamp_start=start.strftime(z),
                        iso_timestamp_end=end.strftime(z))
        if isinstance(data, dict) and data.get("error"):
            raise ProbeError("logs query failed: " + scrub(json.dumps(data["error"]), self.ctx.secrets()))
        return (data or {}).get("result") or []

    def prometheus(self):
        """One scrape of the project's metrics endpoint as {name: [(labels, value)]}.

        With `metricsKeyEnv` it scrapes the privileged endpoint with the secret key; without it, the
        Management API's copy of the same Prometheus text, which a token with Logs Read can read.
        """
        if self.conf.get("metricsKeyEnv"):
            key = self.ctx.secret(self.conf["metricsKeyEnv"])
            auth = base64.b64encode(("service_role:" + key).encode()).decode()
            text = self.ctx.http(f"https://{self.ref}.supabase.co/customer/v1/privileged/metrics",
                                 {"Authorization": "Basic " + auth, "Accept": "text/plain"})
        else:
            text = self.ctx.http(f"{SUPABASE_API}/projects/{self.ref}/analytics/endpoints/metrics",
                                 {**self.headers, "Accept": "text/plain"})
        series = {}
        for line in str(text).splitlines():
            m = re.match(r"^([a-zA-Z_:][a-zA-Z0-9_:]*)(\{[^}]*\})?\s+(\S+)", line)
            if not m or line.startswith("#"):
                continue
            labels = dict(re.findall(r'(\w+)="([^"]*)"', m.group(2) or ""))
            try:
                series.setdefault(m.group(1), []).append((labels, float(m.group(3))))
            except ValueError:
                continue
        if not series:
            raise ProbeError("metrics endpoint returned no series")
        return series


def metric_sum(series, name, **match):
    return sum(v for labels, v in series.get(name, []) if all(labels.get(k) == w for k, w in match.items()))


def since_last_run(ctx, key, value):
    """(delta, seconds) of a cumulative counter against the newest snapshot at least an hour old."""
    ctx.snapshot[key] = value
    old = ctx.previous_snapshot(min_age_days=1 / 24)
    if not old or key not in old.get("values", {}) or value < float(old["values"][key]):
        return None, None  # no history, or the counter reset with a restart
    return value - float(old["values"][key]), old["_age"] * 86400


def probe_infrastructure(ctx, sb):
    """Disk, memory, CPU, IOPS, connections and pooler queue from the Prometheus endpoint.

    The endpoint serves a cached scrape, so rates come from the counters stored by the previous run:
    CPU and IOPS are averages since then, next to the 15-minute load right now.
    """
    cfg, out = ctx.cfg, []
    second = sb.prometheus()
    disk_conf = {}
    try:
        disk_conf = (sb.get("/config/disk") or {}).get("attributes") or {}
    except ProbeError:
        pass

    size = metric_sum(second, "node_filesystem_size_bytes", mountpoint="/data")
    avail = metric_sum(second, "node_filesystem_avail_bytes", mountpoint="/data")
    if size:
        used = size - avail
        pct = used / size * 100
        ctx.snapshot["disk_used_bytes"] = used
        growth = growth_per_day(ctx, "disk_used_bytes", used)
        status = judge_pct(pct, cfg["capacityWarnPct"], cfg["capacityCritPct"])
        why = "growth baseline starts today" if growth is None else f"{growth / 1024 ** 2:+.0f} MB/day"
        if growth and growth > 0:
            days = (size * cfg["capacityCritPct"] / 100 - used) / growth
            why += f"; {cfg['capacityCritPct']:.0f}% full in {max(days, 0):.0f} days"
            if days < cfg["daysToFullWarn"] and status == "ok":
                status = "warn"
        db = metric_sum(second, "pg_database_size_bytes", datname="postgres")
        out.append(check("Capacity", "disk", "Database disk used", status, f"{gb(used)} of {gb(size)} ({pct:.0f}%)",
                         "", why, [f"database {gb(db)}, WAL {metric_sum(second, 'pg_wal_size_mb'):,.0f} MB"] if db else [],
                         "supabase-metrics"))
    root_size = metric_sum(second, "node_filesystem_size_bytes", mountpoint="/")
    if root_size:
        root_pct = (1 - metric_sum(second, "node_filesystem_avail_bytes", mountpoint="/") / root_size) * 100
        if root_pct >= 90:
            out.append(check("Capacity", "disk-root", "System disk used", "crit" if root_pct >= 95 else "warn",
                             f"{root_pct:.0f}%", "", "Supabase-managed volume; open a support ticket if it keeps rising",
                             source="supabase-metrics"))

    total = metric_sum(second, "node_memory_MemTotal_bytes")
    if total:
        mem_pct = (1 - metric_sum(second, "node_memory_MemAvailable_bytes") / total) * 100
        swap_total = metric_sum(second, "node_memory_SwapTotal_bytes")
        swap_pct = (1 - metric_sum(second, "node_memory_SwapFree_bytes") / swap_total) * 100 if swap_total else 0
        status = judge_pct(mem_pct, cfg["memoryWarnPct"], cfg["memoryCritPct"])
        if swap_pct >= 50 and status == "ok":
            status = "warn"
        out.append(check("Capacity", "memory", "Memory used (excl. cache)", status,
                         f"{mem_pct:.0f}% of {gb(total)}, swap {swap_pct:.0f}%", "",
                         "swapping means the compute size is too small" if swap_pct >= 50 else "",
                         source="supabase-metrics"))

    cpus = second.get("node_cpu_seconds_total", [])
    cores = len({labels.get("cpu") for labels, _ in cpus}) or 1
    # A compute resize or restart is a change the digest names, and it resets the cumulative counters.
    compute = ""
    try:
        for addon in (sb.get("/billing/addons") or {}).get("selected_addons") or []:
            if addon.get("type") == "compute_instance":
                compute = (addon.get("variant") or {}).get("name") or ""
    except ProbeError:
        pass
    prior = (ctx.previous_snapshot(min_age_days=1 / 48) or {}).get("values", {})
    size_now = f"{compute or '?'} ({cores} cores, {total / 1024 ** 3:.0f} GB)" if total else compute
    ctx.snapshot["compute"] = size_now
    if prior.get("compute") and prior["compute"] != size_now:
        ctx.values.setdefault("_changes", []).append(f"compute changed from {prior['compute']} to {size_now}")
    boot = metric_sum(second, "node_boot_time_seconds")
    ctx.snapshot["boot_time"] = boot
    restarted = bool(boot and prior.get("boot_time") and abs(boot - float(prior["boot_time"])) > 60)
    if restarted:
        ctx.values.setdefault("_changes", []).append(
            "database host restarted at " + dt.datetime.fromtimestamp(boot, dt.timezone.utc).strftime("%m-%d %H:%M UTC"))
    busy, _ = since_last_run(ctx, "cpu_busy_seconds",
                             sum(v for labels, v in cpus if labels.get("mode") not in ("idle", "iowait")))
    spent, secs = since_last_run(ctx, "cpu_total_seconds", sum(v for _, v in cpus))
    if restarted:
        busy = spent = None  # counters started over on the new host
    load_pct = metric_sum(second, "node_load15") / cores * 100
    avg = busy / spent * 100 if busy is not None and spent else None
    status = judge_pct(max(load_pct, avg or 0), cfg["capacityWarnPct"], cfg["capacityCritPct"])
    out.append(check("Capacity", "cpu", "CPU: 15-min load per core / average since last run", status,
                     f"{load_pct:.0f}% / " + (f"{avg:.0f}%" if avg is not None else "n/a") + f" on {size_now or f'{cores} cores'}", "",
                     "" if avg is not None else ("host restarted; average restarts with the next run" if restarted
                                                 else "average starts with the next run"), source="supabase-metrics"))
    ops, secs = since_last_run(ctx, "disk_ops_total", metric_sum(second, "node_disk_reads_completed_total")
                               + metric_sum(second, "node_disk_writes_completed_total"))
    if disk_conf.get("iops") and ops is not None and secs and not restarted:
        iops = ops / secs
        pct = iops / float(disk_conf["iops"]) * 100
        out.append(check("Capacity", "iops", "Disk IOPS, average since last run",
                         judge_pct(pct, cfg["capacityWarnPct"], cfg["capacityCritPct"]),
                         f"{iops:,.0f} of {disk_conf['iops']} ({pct:.0f}%)", "",
                         "an average hides bursts; open the dashboard's IO chart if this is amber" if pct >= cfg["capacityWarnPct"] else "",
                         source="supabase-metrics"))

    max_conn = metric_sum(second, "max_connections_connection_count")
    conns = metric_sum(second, "connection_stats_connection_count")
    if max_conn:
        pct = conns / max_conn * 100
        out.append(check("Capacity", "connections", "Postgres connections", judge_pct(
            pct, cfg["connectionsWarnPct"], cfg["connectionsCritPct"]), f"{conns:.0f} of {max_conn:.0f} ({pct:.0f}%)",
            source="supabase-metrics"))
    waiting = metric_sum(second, "pgbouncer_pools_client_waiting_connections")
    out.append(check("Capacity", "pool-wait", "Clients waiting for a pooled connection", "warn" if waiting else "ok",
                     f"{waiting:.0f}", "0", "the pool is saturated" if waiting else "", source="supabase-metrics"))

    delta, _ = since_last_run(ctx, "deadlocks_total", metric_sum(second, "pg_stat_database_deadlocks_total"))
    if delta:
        out.append(check("Errors", "deadlocks", "Deadlocks since the last run", "warn", f"{delta:.0f}", "0",
                         SQLSTATE_HINTS["40P01"], source="supabase-metrics"))
    return out


CAPACITY_SQL = """
select pg_database_size(current_database()) as db_bytes,
  (select setting::int from pg_settings where name = 'max_connections') as max_conn,
  (select count(*) from pg_stat_activity where backend_type = 'client backend') as conns,
  (select round(100.0 * sum(heap_blks_hit) / nullif(sum(heap_blks_hit) + sum(heap_blks_read), 0), 2)
     from pg_statio_user_tables) as table_hit_pct,
  (select round(100.0 * sum(idx_blks_hit) / nullif(sum(idx_blks_hit) + sum(idx_blks_read), 0), 2)
     from pg_statio_user_indexes) as index_hit_pct
"""

LONG_SQL = """
select pid, state, round(extract(epoch from now() - coalesce(xact_start, query_start))) as secs,
       usename, left(regexp_replace(query, '\\s+', ' ', 'g'), 100) as q,
       cardinality(pg_blocking_pids(pid)) as blocked_by
from pg_stat_activity
where backend_type = 'client backend' and pid <> pg_backend_pid()
  and ((state = 'active' and now() - query_start > interval '{secs} seconds')
    or (state like 'idle in transaction%' and now() - state_change > interval '{secs} seconds'))
order by secs desc limit 8
"""

PGSS_SQL = """
select queryid::text as qid, calls, round(total_exec_time::numeric) as total_ms,
       coalesce(substring(query from '"public"\\."([A-Za-z0-9_]+)"'),
                left(regexp_replace(query, '\\s+', ' ', 'g'), 70)) as name
from extensions.pg_stat_statements order by total_exec_time desc limit 200
"""

TABLES_SQL = """
select schemaname || '.' || relname as tbl, pg_total_relation_size(relid) as bytes,
       n_live_tup as live, n_dead_tup as dead
from pg_stat_user_tables order by pg_total_relation_size(relid) desc limit 8
"""


def probe_postgres(ctx, sb):
    cfg, out = ctx.cfg, []
    cap = sb.sql(CAPACITY_SQL)[0]
    ctx.snapshot["db_bytes"] = float(cap["db_bytes"])
    growth = growth_per_day(ctx, "db_bytes", float(cap["db_bytes"]))
    if not any(c["id"] == "disk" for c in ctx.values.get("_infra", [])):
        out.append(check("Capacity", "db-size", "Database size", "ok", gb(float(cap["db_bytes"])), "",
                         "growth baseline starts today" if growth is None else f"{growth / 1024 ** 2:+.0f} MB/day",
                         source="supabase"))
    if not any(c["id"] == "connections" for c in ctx.values.get("_infra", [])) and cap.get("max_conn"):
        pct = cap["conns"] / cap["max_conn"] * 100
        out.append(check("Capacity", "connections", "Postgres connections", judge_pct(
            pct, cfg["connectionsWarnPct"], cfg["connectionsCritPct"]), f"{cap['conns']} of {cap['max_conn']} ({pct:.0f}%)",
            source="supabase"))
    hits = [float(h) for h in (cap.get("table_hit_pct"), cap.get("index_hit_pct")) if h is not None]
    if hits:
        worst = min(hits)
        out.append(check("Capacity", "cache-hit", "Cache hit ratio (table / index)", judge_pct(
            worst, cfg["cacheHitWarnPct"], cfg["cacheHitCritPct"], higher_is_worse=False),
            f"{cap.get('table_hit_pct')}% / {cap.get('index_hit_pct')}%", "99%+",
            "the working set no longer fits in memory" if worst < cfg["cacheHitWarnPct"] else "", source="supabase"))

    secs = int(cfg["longQuerySeconds"])
    long = sb.sql(LONG_SQL.replace("{secs}", str(secs)))
    blocked = [r for r in long if r.get("blocked_by")]
    out.append(check("Capacity", "long-queries", f"Sessions active or idle in a transaction > {secs}s",
                     "warn" if long else "ok", str(len(long)), "0",
                     f"{len(blocked)} blocked by another session" if blocked else "",
                     [f"{r['secs']}s {r['state']} {r['usename']}: {r['q']}" for r in long], "supabase"))

    try:
        rows = sb.sql(PGSS_SQL)
        current = {r["qid"]: (float(r["calls"]), float(r["total_ms"]), r["name"]) for r in rows}
        ctx.snapshot["pgss"] = {k: [v[0], v[1]] for k, v in current.items()}
        old = ctx.previous_snapshot(min_age_days=0.75)
        base = (old or {}).get("values", {}).get("pgss")
        span = "since stats reset"
        try:
            reset = sb.sql("select stats_reset::date::text as d from extensions.pg_stat_statements_info")[0]["d"]
            span = f"cumulative since the {reset} stats reset; 24h deltas start with the next run"
        except (ProbeError, IndexError, KeyError):
            pass
        if base:
            span = f"since {old.get('date')}"
            delta = {}
            for qid, (calls, total, name) in current.items():
                c0, t0 = base.get(qid, [0, 0])
                if calls >= c0 and total >= t0:  # a reset makes the delta meaningless; skip that query
                    delta[qid] = (calls - c0, total - t0, name)
            current = delta
        by_name = {}
        for calls, total, name in current.values():
            c, t = by_name.get(name, (0.0, 0.0))
            by_name[name] = (c + calls, t + total)
        top = sorted(((c, t, n) for n, (c, t) in by_name.items()), key=lambda v: -v[1])[:6]
        slow = [v for v in top if v[0] >= cfg["slowQueryMinCalls"] and v[1] / max(v[0], 1) >= cfg["slowQueryMs"]]
        out.append(check("Capacity", "slow-queries", f"Slowest queries by total DB time ({span})",
                         "warn" if slow else "ok", f"{len(slow)} averaging ≥ {cfg['slowQueryMs']:g} ms", "",
                         "frequent slow calls eat the CPU and trigger statement timeouts" if slow else "",
                         [f"{name}: {total / max(calls, 1):,.0f} ms mean × {calls:,.0f} calls = {total / 3.6e6:,.1f} h"
                          for calls, total, name in top], "supabase",
                         (f"{slow[0][2]} averages {slow[0][1] / max(slow[0][0], 1):,.0f} ms over {slow[0][0]:,.0f} calls"
                          if slow else "")))
    except ProbeError as e:
        out.append(check("Capacity", "slow-queries", "Slowest queries", "unknown",
                         why="pg_stat_statements unreadable: " + str(e)[:160], source="supabase"))

    try:
        tables = sb.sql(TABLES_SQL)
        bloated = [t for t in tables if t["dead"] and t["live"] and t["dead"] > 0.2 * t["live"] and t["dead"] > 10000]
        out.append(check("Capacity", "tables", "Largest tables / dead rows", "warn" if bloated else "ok",
                         f"{len(bloated)} over 20% dead rows", "", "autovacuum is falling behind" if bloated else "",
                         [f"{t['tbl']}: {t['bytes'] / 1024 ** 2:,.0f} MB, {t['live']:,} live, {t['dead']:,} dead" for t in tables],
                         "supabase"))
    except ProbeError as e:
        out.append(check("Capacity", "tables", "Largest tables", "unknown", why=str(e), source="supabase"))
    return out


# One entry per error stream in the `logs` table. `where` selects the failures, `sig` groups them,
# `den` (optional) selects the requests they are a share of.
LOG_SOURCES = [
    {"id": "api-5xx", "label": "API gateway 5xx", "den": "source = 'edge_logs'",
     "where": "source = 'edge_logs' and toInt32OrZero(log_attributes['response.status_code']) >= 500",
     "sig": "concat(log_attributes['response.status_code'], ' ', log_attributes['request.method'], ' ', "
            "replaceRegexpAll(log_attributes['request.path'], '[0-9a-f-]{8,}|[0-9]{2,}', ':id'))"},
    {"id": "postgres-errors", "label": "Postgres errors",
     "where": "source = 'postgres_logs' and severity_text in ('ERROR', 'FATAL', 'PANIC')",
     "sig": "concat(severity_text, ' ', log_attributes['parsed.sql_state_code'], ' ', substring(event_message, 1, 150))"},
    {"id": "function-5xx", "label": "Edge Function 5xx", "den": "source = 'function_edge_logs'",
     "where": "source = 'function_edge_logs' and toInt32OrZero(log_attributes['response.status_code']) >= 500",
     "sig": "concat(log_attributes['response.status_code'], ' ', log_attributes['request.pathname'])"},
    {"id": "function-errors", "label": "Edge Function logged errors",
     "where": "source = 'function_logs' and severity_text = 'ERROR'",
     "sig": "concat(log_attributes['function_id'], ' ', substring(event_message, 1, 150))"},
    {"id": "auth-errors", "label": "Auth errors",
     "where": "source = 'auth_logs' and severity_text in ('ERROR', 'FATAL')",
     "sig": "concat(log_attributes['error_code'], ' ', substring(coalesce(nullIf(log_attributes['error'], ''), "
            "nullIf(log_attributes['msg'], ''), event_message), 1, 150))"},
    {"id": "other-errors", "label": "Other services' errors (storage, realtime, pooler, PostgREST)",
     "where": "source not in ('edge_logs', 'postgres_logs', 'function_edge_logs', 'function_logs', 'auth_logs') "
              "and severity_text in ('ERROR', 'FATAL', 'PANIC')",
     "sig": "concat(source, ' ', substring(event_message, 1, 150))"},
    {"id": "function-limits", "label": "Edge Function shutdowns at a resource limit",
     "where": "source = 'function_logs' and log_attributes['event_type'] = 'Shutdown' and log_attributes['reason'] in "
              "(" + ", ".join(f"'{r}'" for r in FUNCTION_LIMIT_REASONS) + ")",
     "sig": "concat(log_attributes['reason'], ' ', log_attributes['function_id'])"},
]


def probe_logs(ctx, sb):
    """Every error stream: one countIf query per window for all totals, then one top-signature query each.

    The logs endpoint is rate limited and takes at most 24h per query, so totals share one call per
    window and signature queries run two at a time.
    """
    cur = (ctx.now - dt.timedelta(hours=ctx.hours), ctx.now)
    prev = (cur[0] - dt.timedelta(hours=ctx.hours), cur[0])
    try:
        slugs = {f["id"]: f["slug"] for f in sb.get("/functions")}
    except ProbeError:
        slugs = {}

    def name_functions(sig):
        return re.sub(r"[0-9a-f]{8}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{12}",
                      lambda m: slugs.get(m.group(0), m.group(0)[:8]), sig)

    exprs = []
    for src in LOG_SOURCES:
        exprs.append(f"countIf({src['where']}) as `{src['id']}`")
        if src.get("den"):
            exprs.append(f"countIf({src['den']}) as `{src['id']}__den`")
    totals_sql = "select " + ", ".join(exprs) + " from logs"
    now_totals = (sb.logs(totals_sql, *cur) or [{}])[0]
    try:
        before_totals = (sb.logs(totals_sql, *prev) or [{}])[0]
    except ProbeError:
        before_totals = None

    def top(src):
        try:
            return sb.logs(f"select {src['sig']} as sig, count(*) as n from logs where {src['where']} "
                           f"group by sig order by n desc limit 40", *cur), None
        except ProbeError as e:
            return [], str(e)

    with concurrent.futures.ThreadPoolExecutor(2) as pool:
        tops = list(pool.map(top, LOG_SOURCES))

    out = []
    for src, (rows, error) in zip(LOG_SOURCES, tops):
        total = int(now_totals.get(src["id"]) or 0)
        before = None if before_totals is None else int(before_totals.get(src["id"]) or 0)
        if src.get("den"):
            den_now = int(now_totals.get(src["id"] + "__den") or 0)
            den_before = 0 if before_totals is None else int(before_totals.get(src["id"] + "__den") or 0)
            status, why = judge_rate(total, den_now, before or 0, den_before, ctx.cfg, better="lower")
            if status == "ok" and before is not None:
                # The share can stay tiny on a busy service while the failures themselves jump.
                jump, jump_why = judge_count(total, before, ctx.cfg)
                if jump in ("crit", "warn"):
                    status, why = "warn", f"failures {jump_why}; share still small"
            now_text = fmt_pct(total, den_now)
            base_text = "" if before is None else fmt_pct(before, den_before)
        else:
            status, why = judge_count(total, before, ctx.cfg)
            now_text, base_text = f"{total:,}", "" if before is None else f"{before:,}"
        if before is None:
            status, why = ("warn" if total >= 20 else "ok"), "previous window unavailable"
        # A steady stream of real errors is a problem even when it is not new.
        if status == "ok" and total >= ctx.cfg.get("errorFloor", 100) and src["id"] != "function-limits":
            status, why = "warn", f"steady at {total:,} in {ctx.hours:g}h; " + why
        if src["id"] == "function-limits" and total >= ctx.cfg.get("errorFloor", 100) and status == "ok":
            status, why = "warn", "functions are being killed at a CPU, memory or wall-clock limit; " + why
        ctx.values["logs:" + src["id"]] = total
        detail = []
        sigs = merge_signatures([(name_functions(r.get("sig", "")), r.get("n", 0)) for r in rows])
        for sig, n in sigs:
            hint = sqlstate_hint(sig) if src["id"] == "postgres-errors" else None
            detail.append(f"{n:,}× {sig}" + (f" → {hint}" if hint else ""))
        if error:
            detail.append("signatures unavailable: " + error[:160])
        top_share = ""
        if sigs and total:  # a failed signature read leaves only its error line, which has no count
            top_share = f"{sigs[0][1] / total * 100:.0f}% are: " + detail[0].split("× ", 1)[1]
        out.append(check("Errors", "logs-" + src["id"], src["label"], status, now_text, base_text, why, detail,
                         "supabase-logs", top_share[:220]))
    requests = int(now_totals.get("api-5xx__den") or 0)
    before = None if before_totals is None else int(before_totals.get("api-5xx__den") or 0)
    status, why = judge_count(requests, before, ctx.cfg, better="higher") if before is not None else ("ok", "")
    out.append(check("Traffic", "requests", "API requests (previous 24h as baseline)", status, f"{requests:,}",
                     "" if before is None else f"{before:,}", why, source="supabase-logs"))
    return out


def probe_supabase(ctx):
    sb = Supabase(ctx)
    out = []

    def guarded(label, fn):
        try:
            return fn(ctx, sb)
        except ProbeError as e:
            return [check("Capacity", label, label, "unknown", why=str(e), source="supabase")]

    if sb.conf.get("infrastructure", True):
        infra = guarded("infrastructure", probe_infrastructure)
        ctx.values["_infra"] = infra
        out += infra
    out += guarded("postgres", probe_postgres)
    if sb.conf.get("logs", True):
        out += guarded("logs", probe_logs)

    try:
        services = sb.get("/health", services="auth,db,pooler,realtime,rest,storage")
        bad = [f"{s.get('name')}: {s.get('status')}" for s in services if not s.get("healthy")]
        out.append(check("Errors", "services", "Supabase services", "crit" if bad else "ok",
                         f"{len(services) - len(bad)}/{len(services)} healthy", "", "; ".join(bad), source="supabase"))
    except ProbeError as e:
        out.append(check("Errors", "services", "Supabase services", "unknown", why=str(e), source="supabase"))

    for kind in ("security", "performance"):
        try:
            lints = (sb.get(f"/advisors/{kind}") or {}).get("lints") or []
            levels = {}
            for x in lints:
                levels.setdefault(str(x.get("level", "")).upper(), {}).setdefault(x.get("title") or x.get("name"), 0)
                levels[str(x.get("level", "")).upper()][x.get("title") or x.get("name")] += 1
            errors, warns = levels.get("ERROR", {}), levels.get("WARN", {})
            key = f"advisor_{kind}_warnings"
            warn_count = sum(warns.values())
            ctx.snapshot[key] = warn_count
            prior = (ctx.previous_snapshot(min_age_days=0.5) or {}).get("values", {}).get(key)
            grew = prior is not None and warn_count > prior
            standing = "" if not warn_count else (f"{warn_count - prior:+.0f} warnings since the last run" if grew
                                                  else f"{warn_count} standing warnings, none new")
            if kind == "security":
                status = "crit" if errors else "warn" if grew else "ok"
            else:
                status = "warn" if errors or grew else "ok"
            detail = [f"{lvl} {n}× {title}" for lvl, group in (("ERROR", errors), ("WARN", warns))
                      for title, n in sorted(group.items(), key=lambda kv: -kv[1])][:8]
            out.append(check("Errors" if kind == "security" else "Capacity", f"advisor-{kind}",
                             f"Supabase {kind} advisor", status,
                             f"{sum(errors.values())} errors, {sum(warns.values())} warnings", "",
                             standing + (f"; https://supabase.com/dashboard/project/{sb.ref}/advisors/{kind}"
                                         if status != "ok" else ""), detail, "supabase"))
        except ProbeError as e:
            out.append(check("Errors", f"advisor-{kind}", f"Supabase {kind} advisor", "unknown", why=str(e), source="supabase"))

    cur = (ctx.now - dt.timedelta(hours=ctx.hours), ctx.now)
    try:
        if sb.sql("select to_regclass('cron.job_run_details') is not null as ok")[0]["ok"]:
            rows = sb.sql(render_sql("""
select coalesce(j.jobname, d.jobid::text) as job, count(*) as failed, max(d.return_message) as last_error
from cron.job_run_details d left join cron.job j on j.jobid = d.jobid
where d.status = 'failed' and d.start_time >= {start} and d.start_time < {end}
group by 1 order by failed desc limit 10""", *cur))
            out.append(check("Errors", "cron", "Failed pg_cron runs", "warn" if rows else "ok",
                             str(sum(int(r["failed"]) for r in rows)), "0",
                             detail=[f"{r['job']}: {r['failed']}× {str(r['last_error'])[:140]}" for r in rows], source="supabase"))
    except ProbeError as e:
        out.append(check("Errors", "cron", "Failed pg_cron runs", "unknown", why=str(e), source="supabase"))

    if sb.conf.get("authUsers", True):
        out.append(count_metric(ctx, sb, {"id": "auth-users", "area": "Traffic", "label": "New auth users",
                                          "better": "higher", "sql": "select count(*) as n from auth.users "
                                          "where created_at >= {start} and created_at < {end}"}))

    changes = []
    try:
        # Versions are not always timestamps, so "new" means absent from the last run's list.
        versions = sb.sql("select version, coalesce(name, '') as name from supabase_migrations.schema_migrations "
                          "order by version desc limit 30")
        ctx.snapshot["migrations"] = [r["version"] for r in versions]
        seen = (ctx.previous_snapshot(min_age_days=0.25) or {}).get("values", {}).get("migrations")
        if seen is not None:
            changes += [f"migration {r['version']} {r['name']} (applied since the last run)" for r in versions
                        if r["version"] not in seen]
    except ProbeError:
        pass  # projects that apply SQL by hand have no migrations table
    try:
        cutoff = (ctx.now - dt.timedelta(hours=48)).timestamp() * 1000
        deploys = {}
        for f in sb.get("/functions"):
            if (f.get("updated_at") or 0) >= cutoff:
                stamp = dt.datetime.fromtimestamp(f["updated_at"] / 1000, dt.timezone.utc).strftime("%m-%d %H:%M")
                deploys.setdefault(stamp, []).append(f["slug"])
        for stamp, slugs in sorted(deploys.items(), reverse=True):
            changes.append(f"{stamp} UTC deployed {len(slugs)} Edge Functions: " + ", ".join(sorted(slugs)[:8])
                           + (" …" if len(slugs) > 8 else ""))
    except ProbeError:
        pass
    changes = ctx.values.pop("_changes", []) + changes
    out.append(check("Changes", "changes", "Changes in the last 48h", "ok", str(len(changes)), detail=changes, source="supabase"))
    return out


# ---------------------------------------------------------------- manifest SQL metrics

def run_windows(ctx, sb, sql, lag_hours=0.0, weeks=None):
    wins = windows(ctx.now, ctx.hours, ctx.cfg["baselineWeeks"] if weeks is None else weeks, lag_hours)
    with concurrent.futures.ThreadPoolExecutor(5) as pool:
        return list(pool.map(lambda w: sb.sql(render_sql(sql, *w)), wins))


def count_metric(ctx, sb, metric):
    area, label = metric.get("area", "Metrics"), metric["label"]
    try:
        results = run_windows(ctx, sb, metric["sql"], float(metric.get("lagHours", 0)))
        values = [float((r[0] if r else {}).get("n") or 0) for r in results]
        current, base = values[0], values[1:]
        mean = sum(base) / len(base) if base else None
        status, why = judge_count(current, mean, ctx.cfg, metric.get("better", "lower"))
        ctx.values["metric:" + metric["id"]] = current
        return check(area, metric["id"], label, status, f"{current:,.0f}", "" if mean is None else f"{mean:,.1f}",
                     why + lag_note(metric), source="metrics", cause=metric.get("hint", ""))
    except ProbeError as e:
        return check(area, metric["id"], label, "unknown", why=str(e), source="metrics")


def lag_note(metric):
    return f"; window ends {metric['lagHours']:g}h ago so conversions can land" if metric.get("lagHours") else ""


def rate_metric(ctx, sb, metric):
    """Rows of num, den and optional seg (e.g. platform) and grp (e.g. paywall arm).

    The headline row and each segment are judged against their own baseline. A group is judged
    against its own history, or its segment's when it is new (a freshly launched paywall). Only a
    group that is not green, or that is new with enough events, becomes its own row; the rest are
    listed under the segment so the digest stays scannable.
    """
    area, label, better = metric.get("area", "Conversion"), metric["label"], metric.get("better", "higher")
    try:
        results = run_windows(ctx, sb, metric["sql"], float(metric.get("lagHours", 0)))
    except ProbeError as e:
        return [check(area, metric["id"], label, "unknown", why=str(e), source="metrics")]

    def tot(rows, **match):
        picked = [r for r in rows if all(r.get(k) == v for k, v in match.items())]
        return sum(float(r.get("num") or 0) for r in picked), sum(float(r.get("den") or 0) for r in picked)

    cur, base = results[0], [r for rows in results[1:] for r in rows]
    weeks = len(results) - 1
    out = []
    x1, n1 = tot(cur)
    x0, n0 = tot(base)
    status, why = judge_rate(x1, n1, x0, n0, ctx.cfg, better)
    ctx.values["metric:" + metric["id"]] = n1
    head = check(area, metric["id"], label, status, fmt_pct(x1, n1), fmt_pct(x0 / max(weeks, 1), n0 / max(weeks, 1)),
                 why + lag_note(metric), source="metrics", cause=metric.get("hint", ""))
    out.append(head)
    segs = sorted({r.get("seg") for r in cur if r.get("seg") is not None}, key=str)
    parents = {None: head}
    for seg in segs:
        sx1, sn1 = tot(cur, seg=seg)
        sx0, sn0 = tot(base, seg=seg)
        s, w = judge_rate(sx1, sn1, sx0, sn0, ctx.cfg, better)
        row = check(area, f"{metric['id']}:{seg}", f"{label} · {seg}", s, fmt_pct(sx1, sn1),
                    fmt_pct(sx0 / max(weeks, 1), sn0 / max(weeks, 1)), w, source="metrics")
        out.append(row)
        parents[seg] = row
    groups = sorted({(r.get("seg"), r.get("grp")) for r in cur if r.get("grp") is not None}, key=str)
    for seg, grp in groups:
        gx1, gn1 = tot(cur, seg=seg, grp=grp) if seg is not None else tot(cur, grp=grp)
        own = tot(base, seg=seg, grp=grp) if seg is not None else tot(base, grp=grp)
        fresh = own[1] < ctx.cfg["minBaselineEvents"]
        bx, bn = (tot(base, seg=seg) if seg is not None else (x0, n0)) if fresh else own
        s, w = judge_rate(gx1, gn1, bx, bn, ctx.cfg, better)
        name = f"{seg} · {grp}" if seg is not None else str(grp)
        line = f"{name}: {fmt_pct(gx1, gn1)} vs {fmt_pct(bx / max(weeks, 1), bn / max(weeks, 1))} ({s}{', new' if fresh else ''})"
        if s in ("crit", "warn") or (fresh and s != "low-sample"):
            out.append(check(area, f"{metric['id']}:{name}", f"{label} · {name}", s, fmt_pct(gx1, gn1),
                             fmt_pct(bx / max(weeks, 1), bn / max(weeks, 1)),
                             w + ("; new group, judged against its segment" if fresh else ""), source="metrics"))
        parents.get(seg, head)["detail"].append(line)
    return out


def value_metric(ctx, sb, metric):
    area, label = metric.get("area", "Metrics"), metric["label"]
    try:
        rows = sb.sql(render_sql(metric["sql"], ctx.now - dt.timedelta(hours=ctx.hours), ctx.now))
        value = float((rows[0] if rows else {}).get("n") or 0)
        status, why = judge_threshold(value, metric)
        ctx.values["metric:" + metric["id"]] = value
        ctx.snapshot["m_" + metric["id"]] = value
        if metric.get("trend") and status == "ok":
            # Short-retention tables have no weekly history in SQL, so earlier runs are the baseline.
            past = [float(s["values"]["m_" + metric["id"]]) for s in ctx.snapshots()
                    if 0.5 <= s["_age"] <= 8 and "m_" + metric["id"] in s.get("values", {})]
            status, why = judge_count(value, sum(past) / len(past) if past else None, ctx.cfg,
                                      metric.get("better", "lower"))
            if not past:
                status, why = "ok", "trend baseline starts today"
        detail = [", ".join(f"{k}={v}" for k, v in r.items() if k != "n") for r in rows[:8] if len(r) > 1]
        unit = metric.get("unit", "")
        return check(area, metric["id"], label, status, f"{value:,.1f}{unit}" if unit else f"{value:,.0f}", "",
                     why, detail, "metrics", metric.get("hint", ""))
    except ProbeError as e:
        return check(area, metric["id"], label, "unknown", why=str(e), source="metrics")


def probe_metrics(ctx):
    sb = Supabase(ctx)
    kinds = {"rate": rate_metric, "value": lambda c, s, m: [value_metric(c, s, m)],
             "count": lambda c, s, m: [count_metric(c, s, m)]}

    def one(metric):
        return kinds.get(metric.get("kind", "count"), kinds["count"])(ctx, sb, metric)

    with concurrent.futures.ThreadPoolExecutor(3) as pool:
        return [c for group in pool.map(one, ctx.monitor.get("metrics") or []) for c in group]


# ---------------------------------------------------------------- RevenueCat

def probe_revenuecat(ctx):
    conf = ctx.monitor.get("revenuecat") or {}
    key = ctx.secret(conf.get("keyEnv", "REVENUECAT_API_KEY_V2"))
    data = ctx.http(f"{RC_API}/projects/{conf['projectId']}/metrics/overview", {"Authorization": "Bearer " + key})
    old = ctx.previous_snapshot(min_age_days=6)
    out = []
    for m in data.get("metrics") or []:
        mid, value = str(m.get("id")), float(m.get("value") or 0)
        ctx.snapshot["rc_" + mid] = value
        ctx.values["revenuecat:" + mid] = value
        before = (old or {}).get("values", {}).get("rc_" + mid)
        status, why = "ok", "trend baseline starts today" if before is None else ""
        if before:
            change = (value - before) / before * 100
            why = f"{change:+.0f}% vs {old.get('date')}"
            watched = ("mrr", "active_subscriptions", "revenue", "active_trials")
            if mid in watched and change <= -ctx.cfg["rateCritChangePct"]:
                status = "crit"
            elif mid in watched and change <= -ctx.cfg["rateWarnChangePct"]:
                status = "warn"
        shown = f"${value:,.0f}" if m.get("unit") == "$" else f"{value:,.0f}"
        period = {"P0D": "now", "P28D": "28 days"}.get(m.get("period"), m.get("period") or "")
        out.append(check("Revenue", "rc-" + mid, f"RevenueCat {m.get('name', mid)} ({period})", status, shown,
                         "" if before is None else (f"${before:,.0f}" if m.get("unit") == "$" else f"{before:,.0f}"),
                         why, source="revenuecat"))
    return out or [check("Revenue", "rc", "RevenueCat overview", "unknown", why="no metrics returned", source="revenuecat")]


# ---------------------------------------------------------------- Stripe (restricted key or CLI profile)

class Stripe:
    """Reads through a restricted key over HTTPS when `keyEnv` is set, else the CLI's named profile."""

    def __init__(self, ctx):
        self.ctx, self.conf = ctx, ctx.monitor.get("stripe") or {}
        self.key = ctx.secret(self.conf["keyEnv"]) if self.conf.get("keyEnv") else None
        self.cli = None if self.key else shutil.which("stripe")
        if not self.key and not self.cli:
            raise ProbeError("stripe CLI not installed and no stripe.keyEnv set")

    def get(self, path, params):
        if self.key:
            query = ("?" + urllib.parse.urlencode(list(params))) if params else ""
            data = self.ctx.http(STRIPE_API + path + query, {"Authorization": "Bearer " + self.key})
            if isinstance(data, dict) and data.get("error"):
                raise ProbeError("Stripe error: " + scrub(data["error"].get("message", ""), self.ctx.secrets()))
            return data
        cmd = [self.cli, "get", path, "--live"]
        if self.conf.get("profile"):
            cmd.append("--project-name=" + self.conf["profile"])
        for k, v in params:
            cmd += ["-d", f"{k}={v}"]
        result = subprocess.run(cmd, capture_output=True, text=True, timeout=TIMEOUT, cwd=str(Path.home()))
        for stream in (result.stdout, result.stderr):
            text = stream.strip()
            if text.startswith("{"):
                data, _ = json.JSONDecoder().raw_decode(text)
                if isinstance(data, dict) and data.get("error"):
                    raise ProbeError("Stripe error: " + scrub(data["error"].get("message", ""), self.ctx.secrets()))
                return data
        raise ProbeError("stripe CLI failed: " + scrub(result.stderr or result.stdout, self.ctx.secrets()))

    def tally(self, types, start, end, extra=(), cap=20):
        counts, after = {t: 0 for t in types}, None
        for _ in range(cap):
            params = [("types[]", t) for t in types] + [("created[gte]", int(start.timestamp())),
                                                         ("created[lt]", int(end.timestamp())), ("limit", 100), *extra]
            if after:
                params.append(("starting_after", after))
            page = self.get("/v1/events", params)
            items = page.get("data") or []
            for e in items:
                counts[e.get("type")] = counts.get(e.get("type"), 0) + 1
            if not page.get("has_more") or not items:
                return counts
            after = items[-1]["id"]
        raise ProbeError(f"more than {cap * 100} events in a window; narrow --hours")


def probe_stripe(ctx):
    st = Stripe(ctx)
    expected = st.conf.get("account")
    if expected:
        account = st.get("/v1/account", []).get("id")
        if account != expected:
            raise ProbeError(f"the Stripe CLI profile reads {account}, expected {expected}; run stripe login "
                             "for the manifest's profile and pick the right account")
    types = ["charge.succeeded", "charge.failed", "invoice.payment_failed", "invoice.paid", "charge.dispute.created"]
    wins = windows(ctx.now, ctx.hours, min(ctx.cfg["baselineWeeks"], 4))  # events are kept 30 days
    with concurrent.futures.ThreadPoolExecutor(3) as pool:
        tallies = list(pool.map(lambda w: st.tally(types, *w), wins))
    weeks = len(tallies) - 1
    now, base = tallies[0], tallies[1:]
    s = lambda key: sum(t.get(key, 0) for t in base)  # noqa: E731
    ctx.values["stripe:charge.succeeded"] = now["charge.succeeded"]
    out = []
    for fail, ok, label in (("charge.failed", "charge.succeeded", "Failed charges (share of attempts)"),
                            ("invoice.payment_failed", "invoice.paid", "Failed invoice payments (share)")):
        x1, n1 = now[fail], now[fail] + now[ok]
        x0, n0 = s(fail), s(fail) + s(ok)
        status, why = judge_rate(x1, n1, x0, n0, ctx.cfg, better="lower")
        out.append(check("Revenue", "stripe-" + fail, label, status, fmt_pct(x1, n1),
                         fmt_pct(x0 / max(weeks, 1), n0 / max(weeks, 1)), why, source="stripe"))
    status, why = judge_count(now["charge.succeeded"], s("charge.succeeded") / max(weeks, 1), ctx.cfg, better="higher")
    out.append(check("Revenue", "stripe-succeeded", "Successful Stripe charges", status, str(now["charge.succeeded"]),
                     f"{s('charge.succeeded') / max(weeks, 1):.1f}", why, source="stripe"))
    disputes = now["charge.dispute.created"]
    out.append(check("Revenue", "stripe-disputes", "New disputes", "warn" if disputes else "ok", str(disputes),
                     f"{s('charge.dispute.created') / max(weeks, 1):.1f}", "answer before the evidence due date" if disputes else "",
                     source="stripe"))
    try:
        # Events still undelivered an hour later failed every webhook attempt so far.
        failed = st.tally(types, ctx.now - dt.timedelta(hours=ctx.hours), ctx.now - dt.timedelta(hours=1),
                          extra=[("delivery_success", "false")])
        n = sum(failed.values())
        out.append(check("Errors", "stripe-delivery", "Stripe events with failed webhook delivery",
                         "crit" if n >= ctx.cfg["minEvents"] else "warn" if n else "ok", str(n), "0",
                         "the app is missing payment events; check the webhook function's logs" if n else "",
                         [f"{v}× {k}" for k, v in failed.items() if v], "stripe"))
    except ProbeError as e:
        out.append(check("Errors", "stripe-delivery", "Stripe webhook delivery", "unknown", why=str(e), source="stripe"))
    try:
        hooks = st.get("/v1/webhook_endpoints", [("limit", 100)]).get("data") or []
        off = [h.get("url", "?") for h in hooks if h.get("status") != "enabled"]
        out.append(check("Errors", "stripe-webhooks", "Stripe webhook endpoints enabled", "crit" if off else "ok",
                         f"{len(hooks) - len(off)}/{len(hooks)}", detail=off, source="stripe"))
    except ProbeError as e:
        out.append(check("Errors", "stripe-webhooks", "Stripe webhook endpoints", "unknown", why=str(e), source="stripe"))
    return out


# ---------------------------------------------------------------- Twilio

def probe_twilio(ctx):
    conf = ctx.monitor.get("twilio") or {}
    sid = ctx.secret(conf.get("accountSidEnv", "TWILIO_ACCOUNT_SID"))
    auth = base64.b64encode((ctx.secret(conf.get("keySidEnv", "TWILIO_API_KEY_SID")) + ":" +
                             ctx.secret(conf.get("keySecretEnv", "TWILIO_API_KEY_SECRET"))).encode()).decode()
    headers = {"Authorization": "Basic " + auth}
    services = set(conf.get("messagingServiceSids") or [])

    def tally(start, end):
        """Counts per messaging service. Bodies and phone numbers never leave this function."""
        url = f"{TWILIO_API}/Accounts/{sid}/Messages.json?" + urllib.parse.urlencode(
            {"DateSent>": start.date().isoformat(), "DateSent<": (end + dt.timedelta(days=1)).date().isoformat(),
             "PageSize": 1000})
        per = {}
        for _ in range(int(conf.get("maxPages", 10))):
            page = ctx.http(url, headers)
            for m in page.get("messages") or []:
                sender = str(m.get("from") or "")
                channel = sender.split(":", 1)[0] if ":" in sender else "sms"
                svc = m.get("messaging_service_sid") or f"no service · {channel} …{sender[-4:]}"
                if (services and svc not in services) or str(m.get("direction", "")).startswith("inbound"):
                    continue
                try:
                    stamp = dt.datetime.strptime(m.get("date_sent") or m.get("date_created"), "%a, %d %b %Y %H:%M:%S %z")
                except (TypeError, ValueError):
                    continue
                if not (start <= stamp < end):
                    continue
                row = per.setdefault(svc, {"sent": 0, "failed": 0, "codes": {}})
                row["sent"] += 1
                if m.get("status") in ("failed", "undelivered"):
                    code = str(m.get("error_code"))
                    row["codes"][code] = row["codes"].get(code, 0) + 1
                    if code in RECIPIENT_SIDE_ERRORS:
                        row["recipient"] = row.get("recipient", 0) + 1
                    else:
                        row["failed"] += 1
            nxt = page.get("next_page_uri")
            if not nxt:
                return per
            url = "https://api.twilio.com" + nxt
        raise ProbeError("more messages than maxPages × 1000; raise monitor.twilio.maxPages")

    out = []
    try:
        cur = tally(ctx.now - dt.timedelta(hours=ctx.hours), ctx.now)
        old = tally(ctx.now - dt.timedelta(hours=ctx.hours, weeks=1), ctx.now - dt.timedelta(weeks=1))
        x1, n1 = sum(r["failed"] for r in cur.values()), sum(r["sent"] for r in cur.values())
        x0, n0 = sum(r["failed"] for r in old.values()), sum(r["sent"] for r in old.values())
        status, why = judge_rate(x1, n1, x0, n0, ctx.cfg, better="lower")
        detail = []
        for svc, r in sorted(cur.items(), key=lambda kv: -kv[1]["failed"]):
            codes = ", ".join(f"{n}× {c}" for c, n in sorted(r["codes"].items(), key=lambda kv: -kv[1])[:4])
            label = svc if svc.startswith("no service") else svc[:10]
            detail.append(f"{label}: {fmt_pct(r['failed'], r['sent'])} failed on our side"
                          + (f", {r['recipient']} undeliverable recipients" if r.get("recipient") else "")
                          + (f" ({codes})" if codes else ""))
            past = old.get(svc, {"failed": 0, "sent": 0})
            s, w = judge_rate(r["failed"], r["sent"], past["failed"], past["sent"], ctx.cfg, better="lower")
            share = r["failed"] / r["sent"] * 100 if r["sent"] else 0
            if s in ("ok", "low-sample") and r["failed"] >= ctx.cfg["minEvents"] and share >= ctx.cfg["failShareWarnPct"]:
                # A sender failing this often is broken whether or not it has last week's history.
                s = "crit" if share >= ctx.cfg["failShareCritPct"] else "warn"
                w = f"{share:.0f}% of this sender's messages fail on our side; " + w
            if s in ("crit", "warn"):
                ours = [c for c in r["codes"] if c not in RECIPIENT_SIDE_ERRORS]
                out.append(check("Errors", "twilio-failed:" + svc, f"Message failures · {label}", s,
                                 fmt_pct(r["failed"], r["sent"]), fmt_pct(past["failed"], past["sent"]), w,
                                 [f"{n}× error {c}: https://www.twilio.com/docs/api/errors/{c}"
                                  for c, n in sorted(r["codes"].items(), key=lambda kv: -kv[1])[:4]], "twilio",
                                 "Twilio error " + ", ".join(ours[:3]) + " (sender-side); see its error page" if ours else ""))
        codes = sorted({c for r in cur.values() for c in r["codes"]})
        if codes:
            detail.append("error docs: " + ", ".join(f"https://www.twilio.com/docs/api/errors/{c}" for c in codes[:4]))
        out.append(check("Errors", "twilio-failed", "SMS failed or undelivered (outbound)", status, fmt_pct(x1, n1),
                         fmt_pct(x0, n0), why + " (same window last week)", detail, "twilio"))
    except ProbeError as e:
        out.append(check("Errors", "twilio-failed", "SMS failed or undelivered", "unknown", why=str(e), source="twilio"))
    try:
        url = f"{TWILIO_MONITOR}/Alerts?" + urllib.parse.urlencode({
            "StartDate": (ctx.now - dt.timedelta(hours=ctx.hours)).strftime("%Y-%m-%dT%H:%M:%SZ"),
            "EndDate": ctx.now.strftime("%Y-%m-%dT%H:%M:%SZ"), "PageSize": 1000})
        alerts = ctx.http(url, headers).get("alerts") or []
        codes = {}
        for a in alerts:
            key = f"{a.get('error_code')} ({a.get('log_level')})"
            codes[key] = codes.get(key, 0) + 1
        errors = sum(1 for a in alerts if a.get("log_level") == "error")
        out.append(check("Errors", "twilio-alerts", "Twilio debugger alerts", "warn" if errors >= 10 else "ok",
                         f"{len(alerts)} ({errors} errors)", "", "",
                         [f"{n}× error {c}" for c, n in sorted(codes.items(), key=lambda kv: -kv[1])[:6]], "twilio"))
    except ProbeError as e:
        out.append(check("Errors", "twilio-alerts", "Twilio debugger alerts", "unknown", why=str(e), source="twilio"))
    return out


# ---------------------------------------------------------------- corroboration across sources

def corroborate(ctx):
    """Two sources counting the same thing in the same window should agree within tolerance."""
    out = []
    for pair in ctx.monitor.get("corroborate") or []:
        a, b = ctx.values.get(pair["a"]), ctx.values.get(pair["b"])
        cid = "corroborate-" + re.sub(r"\W+", "-", pair["label"].lower()).strip("-")
        if a is None or b is None:
            missing = pair["a"] if a is None else pair["b"]
            out.append(check("Corroboration", cid, pair["label"], "unknown", why=f"{missing} was not measured this run",
                             source="corroborate"))
            continue
        gap = abs(a - b)
        tolerance = max(float(pair.get("tolerancePct", 20)) / 100 * max(a, b), float(pair.get("minGap", 3)))
        status = "ok" if gap <= tolerance else ("crit" if gap > 2 * tolerance else "warn")
        out.append(check("Corroboration", cid, pair["label"], status, f"{a:g} vs {b:g}", "",
                         f"gap {gap:g} over tolerance {tolerance:g}" if status != "ok" else "",
                         [f"{pair['a']} = {a:g}", f"{pair['b']} = {b:g}"], "corroborate",
                         pair.get("hint", "the two sources disagree; one side is dropping writes")))
    return out


# ---------------------------------------------------------------- orchestration and output

PROBES = {"supabase": probe_supabase, "metrics": probe_metrics, "revenuecat": probe_revenuecat,
          "stripe": probe_stripe, "twilio": probe_twilio}


def enabled(ctx, only):
    names = []
    for name in PROBES:
        conf = ctx.monitor.get("metrics") if name == "metrics" else ctx.monitor.get(name)
        if conf and (not only or name in only):
            names.append(name)
    return names


def run(ctx, only):
    def guarded(name):
        try:
            return PROBES[name](ctx)
        except ProbeError as e:
            return [check(name.capitalize(), name, f"{name} probe", "unknown", why=str(e), source=name)]
        except Exception as e:  # noqa: BLE001 - a probe bug must not hide every other check
            return [check(name.capitalize(), name, f"{name} probe", "unknown",
                          why=f"probe crashed: {type(e).__name__}: {scrub(e, ctx.secrets())}", source=name)]

    with concurrent.futures.ThreadPoolExecutor(len(PROBES)) as pool:
        results = list(pool.map(guarded, enabled(ctx, only)))
    checks = [c for group in results for c in group]
    if not only:
        checks += corroborate(ctx)
    ctx.values.pop("_infra", None)
    previous = ctx.previous_snapshot(min_age_days=0.5)
    before = (previous or {}).get("statuses", {})
    for c in checks:
        c["new"] = c["status"] in ("crit", "warn") and before.get(c["id"]) == "ok"
    acknowledge(ctx, checks)
    pin_causes(ctx, checks)
    return sorted(checks, key=lambda c: (RANK[c["status"]], not c["new"], c["area"], c["label"]))


def acknowledge(ctx, checks):
    """A known, accepted issue reads 🔕 until its date instead of paging every morning; it comes back after."""
    for ack in ctx.monitor.get("acknowledge") or []:
        try:
            until = dt.date.fromisoformat(str(ack["until"]))
        except (KeyError, ValueError):
            continue
        for c in checks:
            if c["id"] == ack.get("id") and c["status"] in ("crit", "warn") and ctx.now.date() <= until:
                c["acked"], c["status"] = c["status"], "ack"
                c["why"] = f"acknowledged until {until} ({ack.get('why', 'no reason given')}); " + c["why"]


def pin_causes(ctx, checks):
    """A root cause triage proved is stored in monitor.causes and shown in the cause column next time."""
    pinned = ctx.monitor.get("causes") or {}
    for c in checks:
        known = pinned.get(c["id"])
        if known and c["status"] != "ok":
            c["cause"] = f"{known.get('cause', '')} (pinned {known.get('found', '?')})"
            if known.get("fix"):
                c["cause"] += f"; fix: {known['fix']}"


def draft_monitor(manifest):
    """The generic part of a monitor block, derived from the manifest's own connectors.

    Project SQL (funnel, paywall, errors the app stores) is left empty: the skill fills it from the
    repo's source and verifies each query read-only before saving.
    """
    env_names = set(load_env(env_paths(manifest)))
    draft = {"baselineWeeks": DEFAULTS["baselineWeeks"]}
    # Production first: a project with stripe-sandbox and stripe-prod monitors prod.
    def prod_first(conn):
        env = str(conn.get("env", "")).lower()
        test = any(w in str(conn.get("name", "")).lower() for w in ("sandbox", "test", "dev"))
        return (0 if env in ("prod", "production") and not test else 1)
    for conn in sorted(manifest.get("connectors", []), key=prod_first):
        name, text = str(conn.get("name", "")).lower(), json.dumps(conn)
        if "supabase" in name and "supabase" not in draft:
            refs = (re.findall(r"project_ref=([a-z]{20})\b", text) or re.findall(r"/projects/([a-z]{20})\b", text)
                    or re.findall(r"https://([a-z]{20})\.supabase\.co", text))
            if refs:
                draft["supabase"] = {"ref": refs[0], "tokenEnv": "SUPABASE_ACCESS_TOKEN"}
                key = next((k for k in ("SUPABASE_SERVICE_KEY", "SUPABASE_SECRET_KEY", "SUPABASE_SERVICE_ROLE_KEY")
                            if k in env_names), None)
                if key:
                    draft["supabase"]["metricsKeyEnv"] = key
        elif name.startswith("stripe") and (conn.get("cli") or {}).get("profile") and "stripe" not in draft:
            draft["stripe"] = {"profile": conn["cli"]["profile"]}
            account = re.findall(r"\b(acct_[A-Za-z0-9]+)\b", text)
            if account:
                draft["stripe"]["account"] = account[0]
        elif name.startswith("revenuecat") and "revenuecat" not in draft:
            project = re.findall(r"\b(proj[0-9a-f]{8})\b", text)
            if project:
                draft["revenuecat"] = {"projectId": project[0], "keyEnv": "REVENUECAT_API_KEY_V2"}
        elif name.startswith("twilio") and "twilio" not in draft:
            draft["twilio"] = {"accountSidEnv": "TWILIO_ACCOUNT_SID", "keySidEnv": "TWILIO_API_KEY_SID",
                               "keySecretEnv": "TWILIO_API_KEY_SECRET"}
    draft["metrics"], draft["corroborate"], draft["acknowledge"], draft["causes"] = [], [], [], {}
    return draft


def uncovered(manifest):
    """Data connectors the engine has no probe for; the skill checks these with their own tools."""
    return sorted({c.get("name") for c in manifest.get("connectors", [])
                   if c.get("name") and not str(c["name"]).lower().startswith(COVERED + NOT_DATA)})


def markdown(ctx, checks):
    counts = {s: sum(1 for c in checks if c["status"] == s) for s in RANK}
    cell = lambda v: str(v).replace("|", "\\|").replace("\n", " ")  # noqa: E731
    lines = [f"# Health pulse · {ctx.project} · {ctx.now.strftime('%Y-%m-%d %H:%M UTC')}", "",
             f"Last {ctx.hours:g}h against the same window on the previous {ctx.cfg['baselineWeeks']} weeks "
             "(logs: previous 24h). " + " · ".join(f"{ICON[s]} {counts[s]} {s}" for s in RANK if counts[s]), "",
             "| | Area | Check | Now | Baseline | Why | Likely cause |", "|---|---|---|---|---|---|---|"]
    for c in checks:
        flag = "**NEW** " if c.get("new") else ""
        lines.append(f"| {ICON[c['status']]} | {c['area']} | {cell(c['label'])} | {cell(c['now'])} | "
                     f"{cell(c['baseline'])} | {flag}{cell(c['why'])} | {cell(c.get('cause', '')) if c['status'] != 'ok' else ''} |")
    details = [c for c in checks if c["detail"] and (c["status"] != "ok" or c["area"] in ("Errors", "Changes", "Conversion"))]
    if details:
        lines += ["", "## Details"]
        for c in details:
            lines += ["", f"**{ICON[c['status']]} {c['label']}**"] + [f"- {cell(d)}" for d in c["detail"][:10]]
    return "\n".join(lines) + "\n"


def save_snapshot(ctx, checks):
    ctx.state_dir.mkdir(parents=True, exist_ok=True)
    path = ctx.state_dir / (ctx.now.strftime("%Y-%m-%d") + ".json")
    path.write_text(json.dumps({"at": ctx.now.isoformat(), "date": ctx.now.strftime("%Y-%m-%d"),
                                "values": ctx.snapshot, "statuses": {c["id"]: c["status"] for c in checks}}))
    return path


def load_manifest(args):
    if args.manifest:
        return json.loads(Path(args.manifest).read_text())
    sys.path.insert(0, str(Path(__file__).resolve().parent))
    if args.project:
        from connector_registry import project_manifest  # the one connector loader
        return project_manifest(args.project)
    from agent_runtime import project  # the one manifest resolver, shared with the launchers
    path, manifest, _ = project(Path.cwd())
    if not path:
        raise ValueError("no connector manifest matches this directory; pass --project")
    return manifest


def main(argv=None):
    ap = argparse.ArgumentParser(description=__doc__.split("\n\n")[0])
    ap.add_argument("--project")
    ap.add_argument("--manifest")
    ap.add_argument("--json", action="store_true")
    ap.add_argument("--only", default="", help="comma list of probes: " + ",".join(PROBES))
    ap.add_argument("--hours", type=float, default=24)
    ap.add_argument("--state-dir", default=str(STATE_DIR))
    ap.add_argument("--no-snapshot", action="store_true")
    ap.add_argument("--draft", action="store_true",
                    help="print a monitor block derived from the manifest's connectors (first run) and exit")
    args = ap.parse_args(argv)
    try:
        manifest = load_manifest(args)
    except (ValueError, OSError, json.JSONDecodeError) as e:
        print(f"health-pulse: {e}", file=sys.stderr)
        return 2
    if args.draft:
        print(json.dumps(draft_monitor(manifest), indent=1))
        return 0
    if not manifest.get("monitor"):
        print(f"health-pulse: {manifest.get('project', 'manifest')} has no monitor block; "
              "see references/production-monitoring.md", file=sys.stderr)
        return 2
    only = {x.strip() for x in args.only.split(",") if x.strip()}
    if only - set(PROBES):
        print(f"health-pulse: unknown probe(s) {', '.join(sorted(only - set(PROBES)))}", file=sys.stderr)
        return 2
    ctx = Context(manifest, args.hours, dt.datetime.now(dt.timezone.utc).replace(microsecond=0), args.state_dir)
    checks = run(ctx, only)
    snap = None if (args.no_snapshot or only) else save_snapshot(ctx, checks)
    if snap:
        snap.with_suffix(".md").write_text(markdown(ctx, checks))
    if args.json:
        print(json.dumps({"project": ctx.project, "at": ctx.now.isoformat(), "hours": ctx.hours,
                          "baselineWeeks": ctx.cfg["baselineWeeks"], "snapshot": str(snap) if snap else None,
                          "uncoveredConnectors": uncovered(manifest), "checks": checks}, indent=1))
    else:
        rest = uncovered(manifest)
        print(markdown(ctx, checks) + (f"\nConnectors with no probe (check by hand): {', '.join(rest)}\n" if rest else "")
              + (f"\nSnapshot: {snap}\n" if snap else ""))
    return 1 if any(c["status"] == "crit" for c in checks) else 0


if __name__ == "__main__":
    sys.exit(main())
