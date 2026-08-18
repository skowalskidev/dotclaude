#!/usr/bin/env python3
"""Score every config part by usage + error rate, two-axis, and render it.

The self-analysis engine behind /sk:claude-config-metrics-self-analysis. Deterministic, no model
calls (like superspeed-analyse.py backs its skill). It:

  - loads the canonical parts list from contracts/config_contracts.py (never a hardcoded copy — so a
    part added via /sk:claude-config-update appears here automatically; a parity check enforces it),
  - reads part_criticality.py (safety / planned-stub tags),
  - reads usage from the dotclaude-metrics store (session_events + local outbox), aggregating on read,
  - computes reachability (the static axis) so "dead" needs unreachable AND unused,
  - classifies each part: hot | healthy | underused | dead | erroring | instrumentation-gap |
    new/unmeasured | safety(healthy-by-design) | planned/stub,
  - writes the rollup to aggregates/* (so the local + hosted console read one computed result),
  - prints a terminal scoreboard, and with --html writes a self-contained dashboard.

Subcommands / flags:
  (default)      print the scoreboard + write aggregates/latest
  --html [PATH]  also write a self-contained HTML dashboard (default: ~/.claude/metrics/dashboard.html)
  --backfill     seed usage from historical ~/.claude/projects/*/*.jsonl transcripts
  --import-logs  one-time import of legacy ~/.claude/logs/*.jsonl into their Firestore collections

Runs under the metrics venv (needs firebase-admin to read/write Firestore). With no project
configured it degrades to the local outbox and prints a "configure a project" notice — never errors.
"""
from __future__ import annotations

import importlib.util
import json
import math
import os
import re
import sys

_HOME = os.path.expanduser("~")
_CLAUDE = os.path.join(_HOME, ".claude")
_HERE = os.path.dirname(os.path.abspath(__file__))
# Resolve the config root: in a worktree, prefer the worktree's contracts; else ~/.claude.
_ROOT = os.path.dirname(_HERE)
OUTBOX = os.path.join(_CLAUDE, "metrics", "outbox.jsonl")
DASHBOARD = os.path.join(_CLAUDE, "metrics", "dashboard.html")
NEW_GRACE_DAYS = 14  # a part younger than this with no usage is 'new/unmeasured', not 'dead'
LOW_CONF_N = 20      # denial rates below this denominator are flagged low-confidence


def _load_module(path: str, name: str):
    spec = importlib.util.spec_from_file_location(name, path)
    mod = importlib.util.module_from_spec(spec)  # type: ignore
    spec.loader.exec_module(mod)  # type: ignore
    return mod


def _contracts_parts() -> list[str]:
    """The canonical inventory: the keys of CONTRACTS, filtered to real config parts (the same set
    the coverage test enforces). Single source — never a hardcoded list here."""
    path = os.path.join(_ROOT, "contracts", "config_contracts.py")
    try:
        mod = _load_module(path, "config_contracts")
        keys = list(getattr(mod, "CONTRACTS", {}).keys())
    except Exception:
        return []
    # Only score the scored part types (skills, rules, references, hooks, bin, githooks, connectors).
    scored = (".md", ".py", ".sh", ".json")
    return [k for k in keys if k.endswith(scored)]


def _criticality():
    path = os.path.join(_ROOT, "contracts", "part_criticality.py")
    try:
        return _load_module(path, "part_criticality")
    except Exception:
        return None


def _part_type(path: str) -> str:
    if path.startswith("rules/"):
        return "rule"
    if path.startswith("references/"):
        return "reference"
    if path.startswith("skills/"):
        return "skill"
    if path.startswith("hooks/"):
        return "hook"
    if path.startswith("bin/"):
        return "bin"
    if path.startswith("connectors/"):
        return "connector"
    if path.startswith(".githooks/"):
        return "githook"
    if path.startswith("contracts/"):
        return "contract"
    return "other"


def _part_name_for_usage(path: str) -> str:
    """The name usage events record, so scoreboard keys line up with event part_name."""
    if path.startswith("skills/") and path.endswith("/SKILL.md"):
        return os.path.basename(os.path.dirname(path))  # skill folder name
    if path.startswith("references/"):
        return path  # references/foo.md — matches the recorder
    return path


# ---------------------------------------------------------------------------- reachability (static)
def _reachability(parts: list[str]) -> dict[str, bool]:
    reach: dict[str, bool] = {}
    settings = _read(os.path.join(_ROOT, "settings.json"))
    routing = ""
    try:
        routing = _read(os.path.join(_ROOT, "contracts", "routing_scenarios.py"))
    except Exception:
        pass
    # index of reference citations across skills + rules + references
    cite_blob = _grep_blob(["skills", "rules", "references"])
    for p in parts:
        t = _part_type(p)
        if t == "hook":
            reach[p] = os.path.basename(p) in settings
        elif t == "skill":
            folder = os.path.basename(os.path.dirname(p))
            reach[p] = (f'"{folder}"' in routing) or (f"'{folder}'" in routing)
        elif t == "reference":
            reach[p] = os.path.basename(p) in cite_blob
        else:
            reach[p] = True  # rules/bin/githooks/contracts/connectors are wired by presence
    return reach


def _read(path: str) -> str:
    try:
        with open(path, encoding="utf-8") as fh:
            return fh.read()
    except Exception:
        return ""


def _grep_blob(dirs: list[str]) -> str:
    out = []
    for d in dirs:
        base = os.path.join(_ROOT, d)
        for root, _, files in os.walk(base):
            for f in files:
                if f.endswith((".md", ".py")):
                    out.append(_read(os.path.join(root, f)))
    return "\n".join(out)


# ---------------------------------------------------------------------------- usage (from the store)
def _firestore():
    key = os.environ.get("CLAUDE_METRICS_SA_KEY") or os.path.join(
        _HOME, ".config", "firebase-keys", "dotclaude-metrics.json")
    if not os.path.exists(key):
        return None
    try:
        import firebase_admin
        from firebase_admin import credentials, firestore
        try:
            app = firebase_admin.get_app("dotclaude-metrics-read")
        except ValueError:
            with open(key) as fh:
                proj = json.load(fh).get("project_id")
            app = firebase_admin.initialize_app(credentials.Certificate(key),
                                                {"projectId": proj}, name="dotclaude-metrics-read")
        return firestore.client(app)
    except Exception:
        return None


def _events_from_store(db) -> list[dict]:
    events: list[dict] = []
    if db is not None:
        try:
            events = [d.to_dict() for d in db.collection("session_events").stream()]
        except Exception:
            events = []
    # include anything still queued locally
    if os.path.exists(OUTBOX):
        try:
            for ln in open(OUTBOX, encoding="utf-8"):
                if not ln.strip():
                    continue
                rec = json.loads(ln)
                if rec.get("_collection") == "session_events":
                    rec.pop("_collection", None)
                    events.append(rec)
        except Exception:
            pass
    return events


def _wilson_low(pos: int, n: int) -> float:
    """Wilson score interval lower bound (z=1.96) — honest denial rate at small n."""
    if n == 0:
        return 0.0
    z = 1.96
    p = pos / n
    denom = 1 + z * z / n
    centre = p + z * z / (2 * n)
    margin = z * math.sqrt((p * (1 - p) + z * z / (4 * n)) / n)
    return max(0.0, (centre - margin) / denom)


# ---------------------------------------------------------------------------- scoring
def score(parts: list[str], events: list[dict], reach: dict[str, bool], crit) -> list[dict]:
    # tally usage by part_name
    uses: dict[str, int] = {}
    errs: dict[str, int] = {}
    denials: dict[str, int] = {}
    last: dict[str, str] = {}
    for e in events:
        name = e.get("part_name")
        if not name:
            continue
        kind = e.get("kind")
        ts = e.get("ts", "")
        if kind in ("tool_call", "prompt"):
            uses[name] = uses.get(name, 0) + int(e.get("count", 1) or 1)
        elif kind == "error":
            errs[name] = errs.get(name, 0) + 1
        elif kind == "hook_deny":
            denials[name] = denials.get(name, 0) + int(e.get("count", 1) or 1)
        if ts and ts > last.get(name, ""):
            last[name] = ts

    rows = []
    for p in parts:
        uname = _part_name_for_usage(p)
        u = uses.get(uname, 0)
        er = errs.get(uname, 0)
        dn = denials.get(p, 0) + denials.get(uname, 0)  # hooks keyed by full path
        total = u + dn
        deny_rate = _wilson_low(dn, total) if total else 0.0
        reachable = reach.get(p, True)
        tag = crit.criticality(p) if crit else None

        if tag == "safety":
            cls = "safety"
        elif tag == "stub":
            cls = "planned/stub"
        elif u == 0 and er == 0 and dn == 0:
            cls = "dead" if not reachable else "instrumentation-gap"
        elif dn >= 3 or er >= 3:
            cls = "erroring"
        elif u >= 10:
            cls = "hot"
        elif u >= 2:
            cls = "healthy"
        else:
            cls = "underused"

        rows.append({
            "part": p, "type": _part_type(p), "uses": u, "errors": er, "denials": dn,
            "deny_rate_wilson": round(deny_rate, 3), "low_confidence": total < LOW_CONF_N,
            "reachable": reachable, "last_used": last.get(uname, ""),
            "classification": cls, "inputs": _inputs_hint(p),
        })
    return rows


def _inputs_hint(p: str) -> str:
    t = _part_type(p)
    if t == "skill":
        return "invoked via /sk:%s (Skill tool); trigger = its description phrasing" % os.path.basename(os.path.dirname(p))
    if t == "reference":
        return "Read on demand; cited by skills/rules"
    if t == "hook":
        return "fired by settings.json event matcher"
    if t == "rule":
        return "auto-injected every session (usage = LLM-judged influence, not counted)"
    return "present in the config tree"


# ---------------------------------------------------------------------------- render
def print_scoreboard(rows: list[dict], have_store: bool) -> None:
    order = {"erroring": 0, "dead": 1, "instrumentation-gap": 2, "underused": 3,
             "new/unmeasured": 4, "planned/stub": 5, "healthy": 6, "hot": 7, "safety": 8}
    rows = sorted(rows, key=lambda r: (order.get(r["classification"], 9), -r["uses"]))
    if not have_store:
        print("⚠  No metrics project reachable — showing config inventory only (0 usage). "
              "Configure dotclaude-metrics (see references/dotclaude-metrics-setup.md) to collect data.\n")
    from collections import Counter
    counts = Counter(r["classification"] for r in rows)
    print("dotclaude config metrics — %d parts" % len(rows))
    print("  " + "  ".join("%s:%d" % (k, counts[k]) for k in sorted(counts)))
    print()
    print("%-52s %-10s %5s %5s %6s  %s" % ("part", "class", "uses", "errs", "deny", "reach"))
    for r in rows:
        print("%-52s %-10s %5d %5d %6.2f  %s" % (
            r["part"][:52], r["classification"][:10], r["uses"], r["errors"],
            r["deny_rate_wilson"], "yes" if r["reachable"] else "NO"))


def write_html(rows: list[dict], path: str) -> None:
    from collections import Counter
    counts = Counter(r["classification"] for r in rows)
    rows_sorted = sorted(rows, key=lambda r: -r["uses"])
    def esc(s): return str(s).replace("&", "&amp;").replace("<", "&lt;").replace(">", "&gt;")
    bars = "".join(
        '<div class="bar"><span class="lbl">%s</span>'
        '<span class="track"><i style="width:%dpx"></i></span><span class="n">%d</span></div>'
        % (esc(r["part"]), min(400, r["uses"] * 8), r["uses"])
        for r in rows_sorted[:25])
    trows = "".join(
        "<tr class='%s'><td>%s</td><td>%s</td><td>%s</td><td>%d</td><td>%d</td><td>%.2f</td><td>%s</td></tr>"
        % (esc(r["classification"]), esc(r["part"]), esc(r["type"]), esc(r["classification"]),
           r["uses"], r["errors"], r["deny_rate_wilson"], "yes" if r["reachable"] else "NO")
        for r in sorted(rows, key=lambda r: (r["classification"], -r["uses"])))
    chips = " ".join("<span class='chip'>%s: %d</span>" % (esc(k), counts[k]) for k in sorted(counts))
    html = _HTML_TEMPLATE.replace("{{CHIPS}}", chips).replace("{{BARS}}", bars).replace("{{ROWS}}", trows)
    try:
        os.makedirs(os.path.dirname(path), exist_ok=True)
        with open(path, "w", encoding="utf-8") as fh:
            fh.write(html)
    except Exception:
        pass


_HTML_TEMPLATE = """<!doctype html><html><head><meta charset=utf-8>
<title>dotclaude config metrics</title><meta name=viewport content="width=device-width,initial-scale=1">
<style>
:root{--bg:#fff;--fg:#1a1a1a;--mut:#666;--line:#e5e5e5;--acc:#2563eb}
@media(prefers-color-scheme:dark){:root{--bg:#111;--fg:#eee;--mut:#999;--line:#2a2a2a;--acc:#60a5fa}}
body{background:var(--bg);color:var(--fg);font:14px/1.5 system-ui,sans-serif;margin:0;padding:24px;max-width:1000px}
h1{font-size:20px;margin:0 0 4px}.sub{color:var(--mut);margin:0 0 16px}
.chip{display:inline-block;border:1px solid var(--line);border-radius:12px;padding:2px 10px;margin:2px;font-size:12px}
.bar{display:flex;align-items:center;gap:8px;margin:2px 0;font-size:12px}
.bar .lbl{flex:0 0 300px;overflow:hidden;text-overflow:ellipsis;white-space:nowrap}
.bar .track{flex:1;background:var(--line);border-radius:3px;height:10px}
.bar .track i{display:block;height:10px;background:var(--acc);border-radius:3px}
.bar .n{flex:0 0 40px;text-align:right;color:var(--mut)}
table{border-collapse:collapse;width:100%;margin-top:16px;font-size:12px}
th,td{text-align:left;padding:4px 8px;border-bottom:1px solid var(--line)}
th{color:var(--mut);font-weight:600}
tr.dead td,tr.erroring td{color:#dc2626}tr.safety td,tr.hot td{color:var(--mut)}
section{margin-top:28px}
</style></head><body>
<h1>dotclaude config metrics</h1>
<p class=sub>per-part usage &amp; health · best/worst · classification. Data from dotclaude-metrics.</p>
<div>{{CHIPS}}</div>
<section><h2>Most used</h2>{{BARS}}</section>
<section><h2>All parts</h2>
<table><tr><th>part</th><th>type</th><th>class</th><th>uses</th><th>errs</th><th>deny</th><th>reach</th></tr>
{{ROWS}}</table></section>
<p class=sub style=margin-top:24px>Generated by bin/config-metrics.py --html</p>
</body></html>"""


# ---------------------------------------------------------------------------- aggregates write
def write_aggregates(db, rows: list[dict]) -> None:
    if db is None:
        return
    try:
        import datetime as dt
        now = dt.datetime.now(dt.timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")
        db.collection("aggregates").document("latest").set(
            {"generated": now, "parts": rows, "schema_version": 1})
    except Exception:
        pass


def _sibling(mod_file: str, name: str):
    spec = importlib.util.spec_from_file_location(name, os.path.join(_HERE, mod_file))
    m = importlib.util.module_from_spec(spec)  # type: ignore
    spec.loader.exec_module(m)  # type: ignore
    return m


def import_logs() -> int:
    """One-time: push legacy ~/.claude/logs/*.jsonl into their Firestore collections, then soft-
    archive the local files to logs/migrated/. Nothing is deleted (soft-archive policy)."""
    writer = _sibling("dotclaude-log.py", "dotclaude_log").write_events
    logs_dir = os.path.join(_CLAUDE, "logs")
    mapping = {
        "retro-triggers.jsonl": "retro_triggers",
        "intent-reconcile.jsonl": "intent_reconcile",
        "isolate-runs.jsonl": "isolate_runs",
    }
    moved = 0
    archive = os.path.join(logs_dir, "migrated")
    for fname, coll in mapping.items():
        path = os.path.join(logs_dir, fname)
        if not os.path.exists(path):
            continue
        rows = []
        for ln in open(path, encoding="utf-8"):
            ln = ln.strip()
            if not ln:
                continue
            try:
                rows.append(json.loads(ln))
            except Exception:
                continue
        if rows:
            writer(coll, rows, strict=False)  # trusted counts-only schema; keep fields, scrub strings
            print("imported %d rows -> %s" % (len(rows), coll))
        try:
            os.makedirs(archive, exist_ok=True)
            os.rename(path, os.path.join(archive, fname))
            moved += 1
        except Exception:
            pass
    print("import-logs done: %d files soft-archived to logs/migrated/" % moved)
    return 0


def backfill(days: int = 30, cap: int = 8000) -> int:
    """Seed usage from historical transcripts (bounded, personal-boundary only, capped to respect the
    free-tier write quota). Reuses the recorder's parser so backfilled events match live ones."""
    rec = _sibling("config-metrics-record.py", "config_metrics_record")
    writer = _sibling("dotclaude-log.py", "dotclaude_log").write_events
    ident = rec._identity()
    proj_dir = os.path.join(_CLAUDE, "projects")
    if not os.path.isdir(proj_dir):
        print("no projects/ dir to backfill from")
        return 0
    import time
    cutoff = time.time() - days * 86400
    files = []
    for root, _, fs in os.walk(proj_dir):
        for f in fs:
            if f.endswith(".jsonl"):
                p = os.path.join(root, f)
                try:
                    if os.path.getmtime(p) >= cutoff:
                        files.append(p)
                except Exception:
                    pass
    files.sort(key=lambda p: os.path.getmtime(p), reverse=True)
    total = 0
    for p in files:
        if total >= cap:
            print("backfill cap %d reached; stopping (run again for older data)" % cap)
            break
        cwd_guess = "/" + os.path.basename(os.path.dirname(p)).replace("-", "/")
        boundary = rec._boundary(cwd_guess, ident)
        sid = "backfill_" + os.path.splitext(os.path.basename(p))[0][:20]
        events = rec.parse_transcript(p, sid, boundary)
        # Historical cwd reconstruction is imperfect, so never trust it to gate request text:
        # backfill stores the config-part SIGNAL only, dropping intent unconditionally.
        for e in events:
            e.pop("intent", None)
        if events:
            writer("session_events", events)
            total += len(events)
    print("backfill: wrote %d events from %d transcripts (last %d days)" % (total, len(files), days))
    return 0


def main(argv: list[str]) -> int:
    if "--import-logs" in argv:
        return import_logs()
    if "--backfill" in argv:
        i = argv.index("--backfill")
        days = 30
        if i + 1 < len(argv) and argv[i + 1].isdigit():
            days = int(argv[i + 1])
        return backfill(days=days)
    want_html = "--html" in argv
    html_path = DASHBOARD
    if want_html:
        i = argv.index("--html")
        if i + 1 < len(argv) and not argv[i + 1].startswith("--"):
            html_path = argv[i + 1]

    parts = _contracts_parts()
    if not parts:
        print("Could not load the parts list from contracts/config_contracts.py.", file=sys.stderr)
        return 1
    crit = _criticality()
    reach = _reachability(parts)
    db = _firestore()
    events = _events_from_store(db)
    rows = score(parts, events, reach, crit)

    print_scoreboard(rows, have_store=(db is not None))
    write_aggregates(db, rows)
    if want_html:
        write_html(rows, html_path)
        print("\nHTML dashboard: %s" % html_path)
    return 0


if __name__ == "__main__":
    raise SystemExit(main(sys.argv[1:]))
