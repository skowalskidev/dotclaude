#!/usr/bin/env python3
"""kpi.py: the KPIS.md metrics, computed from Claude Code session transcripts.

Load-independent counts decide; wall minutes are reported beside them, never alone (KPIS.md).
A request runs from one message Simon typed to the next. What counts as typed is owned by
hooks/git-commit-guard.py typed_messages (bin/session_learning.py reuses the same reader).

Commands:
  kpi.py session <sid | transcript path> [--record]   one session's metrics (JSON); --record appends
                                                      them to state/kpi-history.jsonl
  kpi.py trend [--days N]                             the last N days against the N before, over
                                                      sessions with 3+ typed messages (default 14)

No command text, prompt text or tool input is ever printed or stored: only counts and categories.
"""
import argparse
import json
import os
import re
import statistics
import sys
import time
from pathlib import Path

HOME = Path(os.path.expanduser("~"))
CONFIG = Path(os.environ.get("CLAUDE_CONFIG_ROOT") or HOME / ".claude")
CODE = Path(__file__).resolve().parents[1]
PROJECTS = Path(os.environ.get("CLAUDE_PROJECTS_DIR") or CONFIG / "projects")
HISTORY = Path(os.environ.get("CLAUDE_KPI_HISTORY") or CONFIG / "state" / "kpi-history.jsonl")
MAX_TRANSCRIPT = 64 * 1024 * 1024
DAY = 86400

# A check: a test, type or lint run whose rerun on unchanged inputs only repeats its answer.
CHECK = re.compile(r"\.test\.(py|ts|js|sh)\b|\bvitest\b|deno (task )?test|\bplaywright\b|\bpytest\b|\bjest\b"
                   r"|(npm|pnpm|yarn|bun) (run )?test\b|xcodebuild\b[^|;&]*\btest|test-without-building"
                   r"|swift test|go test|cargo test|\btsc\b|typecheck|deno (check|lint)|\beslint\b")
POLL = re.compile(r"\b(sleep|until|while)\b[\s\S]*/tasks/[^\s'\"]+\.output|/tasks/[^\s'\"]+\.output[\s\S]*\b(sleep|until)\b")
STOP_BLOCK = re.compile(r"Stop hook (feedback|blocking error)")
# A reply that corrects delivered work: the rework signal of DORA's change-fail and rework rates.
CORRECTION = re.compile(r"^\s*(no\b|nope\b|wrong\b|that'?s (not|wrong)|you (didn'?t|did not|forgot|missed)"
                        r"|still (not|broken|doesn'?t|wrong)|why (did|didn'?t|is it|isn'?t)|fix (that|it|this)\b"
                        r"|it'?s (still|not) |doesn'?t work|not what i)", re.I)
EDITS = {"Edit", "Write", "MultiEdit", "NotebookEdit"}


def _typed_reader():
    import importlib.util
    spec = importlib.util.spec_from_file_location("_guard", CODE / "hooks" / "git-commit-guard.py")
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return mod.own_text


def _parse_ts(value):
    try:
        from datetime import datetime
        return datetime.fromisoformat(str(value).replace("Z", "+00:00")).timestamp()
    except ValueError:
        return None


def _text(content):
    if isinstance(content, str):
        return content
    if isinstance(content, list):
        return "\n".join(c.get("text", "") for c in content if isinstance(c, dict) and c.get("type") == "text")
    return ""


def _is_typed(entry, own_text):
    if entry.get("type") == "attachment":  # a message queued mid-turn (git-commit-guard.py typed_messages)
        att = entry.get("attachment") or {}
        origin = att.get("origin") if isinstance(att.get("origin"), dict) else {}
        if (att.get("type") == "queued_command" and not att.get("isMeta") and att.get("commandMode") != "task-notification"
                and origin.get("kind") not in ("task-notification", "peer")):
            return own_text(str(att.get("prompt") or ""))
        return ""
    if entry.get("type") != "user" or entry.get("isMeta") or entry.get("isSidechain") or entry.get("origin"):
        return ""
    content = (entry.get("message") or {}).get("content")
    if isinstance(content, list) and any(isinstance(c, dict) and c.get("type") == "tool_result" for c in content):
        return ""
    return own_text(_text(content))


def session_metrics(path, own_text=None):
    """Per-request counts for one transcript; None when it is unreadable or too large."""
    path = Path(path)
    try:
        if path.stat().st_size > MAX_TRANSCRIPT:
            return None
        lines = path.read_text(encoding="utf-8", errors="replace").splitlines()
    except OSError:
        return None
    own_text = own_text or _typed_reader()
    requests, cur = [], None
    last_check, edited_since = {}, True
    for line in lines:
        try:
            e = json.loads(line)
        except ValueError:
            continue
        stamp = _parse_ts(e.get("timestamp", "")) if e.get("timestamp") else None
        typed = _is_typed(e, own_text)
        if typed:
            cur = {"start": stamp, "end": stamp, "turns": set(), "tools": 0, "repeats": 0, "stops": 0,
                   "polls": 0, "agents": 0, "edits": 0, "correction": bool(requests and CORRECTION.search(typed))}
            requests.append(cur)
            continue
        if cur is None:
            continue
        if stamp:
            cur["end"] = stamp
        message = e.get("message") or {}
        if e.get("type") == "assistant":
            if message.get("id"):
                cur["turns"].add(message["id"])
            for item in message.get("content") or []:
                if not isinstance(item, dict) or item.get("type") != "tool_use":
                    continue
                cur["tools"] += 1
                name, tin = item.get("name", ""), item.get("input") or {}
                if name in EDITS:
                    cur["edits"] += 1
                    edited_since = True
                elif name in ("Agent", "Task"):
                    cur["agents"] += 1
                elif name == "Bash":
                    cmd = str(tin.get("command", ""))
                    if POLL.search(cmd):
                        cur["polls"] += 1
                    if CHECK.search(cmd):
                        key = re.sub(r"\s+", " ", cmd.strip())
                        if key in last_check and not edited_since:
                            cur["repeats"] += 1
                        last_check[key] = True
                        edited_since = False
        elif STOP_BLOCK.search(_text(message.get("content")) or str(e.get("content", ""))):
            cur["stops"] += 1
    out = []
    for r in requests:
        out.append({"turns": len(r["turns"]), "tools": r["tools"], "repeats": r["repeats"], "stops": r["stops"],
                    "polls": r["polls"], "agents": r["agents"], "edits": r["edits"], "correction": r["correction"],
                    "wallMin": round(((r["end"] or 0) - (r["start"] or 0)) / 60, 2) if r["start"] else None})
    return out


# KPIS.md SLOs, the SLI <= target form (Google SRE book). Keys are summarize() paths.
SLOS = {
    "quality.reworkRate": 0.05,
    "speed.turnsMedian": 5,
    "speed.stopBlocksPerRequest": 0.3,
    "speed.polls": 0,
    "speed.repeatedChecks": 0,
    "speed.subagentsPerSmallRequest": 0.1,
}


def slo_report(summary):
    """{sli: {"value", "target", "met"}} for every SLO the summary carries."""
    out = {}
    for key, target in SLOS.items():
        group, name = key.split(".")
        value = (summary.get(group) or {}).get(name)
        if value is not None:
            out[key] = {"value": value, "target": target, "met": value <= target}
    return out


def summarize(requests):
    """The KPIS.md table for a list of request records."""
    if not requests:
        return {"requests": 0}
    def med(key):
        values = [r[key] for r in requests if r[key] is not None]
        return statistics.median(values) if values else None
    def p90(key):
        values = sorted(r[key] for r in requests if r[key] is not None)
        return values[min(len(values) - 1, int(0.9 * len(values)))] if values else None
    small = [r for r in requests if r["edits"] <= 5]
    return {
        "requests": len(requests),
        "quality": {"reworkRate": round(sum(r["correction"] for r in requests) / len(requests), 3)},
        "speed": {
            "turnsMedian": med("turns"), "turnsP90": p90("turns"),
            "toolsMedian": med("tools"), "toolsP90": p90("tools"),
            "repeatedChecks": sum(r["repeats"] for r in requests),
            "stopBlocksPerRequest": round(sum(r["stops"] for r in requests) / len(requests), 3),
            "polls": sum(r["polls"] for r in requests),
            "subagentsPerSmallRequest": round(sum(r["agents"] for r in small) / len(small), 3) if small else 0,
            "wallMinMedian": med("wallMin"),
        },
        "load1": round(os.getloadavg()[0], 1),
    }


def with_slos(summary):
    if summary.get("requests"):
        summary["slo"] = slo_report(summary)
    return summary


def transcript_for(sid_or_path):
    p = Path(sid_or_path)
    if p.is_file():
        return p
    hits = list(PROJECTS.glob(f"*/{sid_or_path}.jsonl"))
    return hits[0] if hits else None


def automated(path):
    """Sessions a program prompts (bin/session_learning.py automatedSessionPaths) never count."""
    try:
        import importlib.util
        spec = importlib.util.spec_from_file_location("_sl", CODE / "bin" / "session_learning.py")
        mod = importlib.util.module_from_spec(spec)
        spec.loader.exec_module(mod)
        return bool(mod.automated_root(Path(path)))
    except Exception:
        return False


def trend(days, now=None):
    now = now or time.time()
    own_text = _typed_reader()
    windows = {"current": [], "previous": []}
    for path in PROJECTS.glob("*/*.jsonl"):
        try:
            age = now - path.stat().st_mtime
        except OSError:
            continue
        window = "current" if age < days * DAY else "previous" if age < 2 * days * DAY else None
        if not window or automated(path):
            continue
        reqs = session_metrics(path, own_text)
        if reqs and len(reqs) >= 3:
            windows[window].extend(reqs)
    return {name: with_slos(summarize(reqs)) for name, reqs in windows.items()}


def main(argv=None):
    ap = argparse.ArgumentParser(description=__doc__.split("\n")[0])
    sub = ap.add_subparsers(dest="cmd", required=True)
    s = sub.add_parser("session")
    s.add_argument("target")
    s.add_argument("--record", action="store_true")
    t = sub.add_parser("trend")
    t.add_argument("--days", type=int, default=14)
    a = ap.parse_args(argv)
    if a.cmd == "session":
        path = transcript_for(a.target)
        reqs = session_metrics(path) if path else None
        if reqs is None:
            print(f"kpi: no readable transcript for {a.target}", file=sys.stderr)
            return 1
        summary = with_slos({"session": Path(path).stem, "at": time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime()),
                             **summarize(reqs)})
        print(json.dumps(summary, indent=1))
        if a.record:
            HISTORY.parent.mkdir(parents=True, exist_ok=True)
            with open(HISTORY, "a", encoding="utf-8") as f:
                f.write(json.dumps(summary) + "\n")
        return 0
    print(json.dumps(trend(a.days), indent=1))
    return 0


if __name__ == "__main__":
    sys.exit(main())
