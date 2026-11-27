#!/usr/bin/env python3
"""bin/kpi.py on a synthetic transcript: requests, turns, tools, repeats, stops, polls, rework."""
import importlib.util
import json
import sys
import tempfile
from pathlib import Path

spec = importlib.util.spec_from_file_location("kpi", Path(__file__).with_name("kpi.py"))
kpi = importlib.util.module_from_spec(spec)
spec.loader.exec_module(kpi)
FAILS = []


def check(cond, msg):
    print(("ok    " if cond else "FAIL  ") + msg)
    if not cond:
        FAILS.append(msg)


def user(text, t):
    return {"type": "user", "timestamp": t, "message": {"content": text}}


def tool(mid, name, t, **inp):
    return {"type": "assistant", "timestamp": t, "message": {"id": mid, "content": [
        {"type": "tool_use", "id": mid + name, "name": name, "input": inp}]}}


out = "/private/tmp/claude-501/x/tasks/abc.output"
lines = [
    user("change the header colour to blue", "2026-11-27T10:00:00Z"),
    tool("m1", "Edit", "2026-11-27T10:00:10Z", file_path="a.tsx"),
    tool("m2", "Bash", "2026-11-27T10:00:20Z", command="npx vitest run a.test.ts"),
    tool("m3", "Bash", "2026-11-27T10:00:30Z", command="npx vitest run a.test.ts"),  # repeat, no edit between
    tool("m3", "Bash", "2026-11-27T10:00:31Z", command=f"until grep -q x {out}; do sleep 5; done"),
    {"type": "user", "isMeta": True, "timestamp": "2026-11-27T10:01:00Z",  # as the harness writes it
     "message": {"content": "Stop hook feedback:\nreconcile"}},
    {"type": "attachment", "timestamp": "2026-11-27T10:01:00Z", "attachment": {"type": "hook_blocking_error"}},
    {"type": "attachment", "timestamp": "2026-11-27T10:02:00Z",
     "attachment": {"type": "queued_command", "prompt": "no, you didn't change the footer"}},
    tool("m4", "Agent", "2026-11-27T10:02:30Z", prompt="x"),
    user("<system-reminder>hook text</system-reminder>", "2026-11-27T10:03:00Z"),
]
with tempfile.TemporaryDirectory() as tmp:
    path = Path(tmp) / "s.jsonl"
    path.write_text("\n".join(json.dumps(x) for x in lines) + "\n")
    reqs = kpi.session_metrics(path)
    check(len(reqs) == 2, f"two typed messages (one queued mid-turn) are two requests, a harness block none: {len(reqs)}")
    first, second = reqs
    check(first["turns"] == 3 and first["tools"] == 4, f"turns count distinct message ids, tools every call: {first}")
    check(first["repeats"] == 1, "a check rerun with no edit in between counts once")
    check(first["polls"] == 1 and first["stops"] == 1, "a poll loop on task output and a Stop block count")
    check(not first["correction"] and second["correction"], "a correcting reply marks rework on its own request")
    check(second["agents"] == 1, "a subagent launch counts")
    summary = kpi.summarize(reqs)
    check(summary["quality"]["reworkRate"] == 0.5 and summary["speed"]["repeatedChecks"] == 1,
          f"the summary carries both KPIs: {summary}")
    slo = kpi.slo_report(summary)
    check(slo["speed.polls"]["met"] is False and slo["speed.turnsMedian"]["met"] is True,
          f"each SLI is judged against its KPIS.md target: {slo}")
    check("load1" in summary and summary["speed"]["wallMinMedian"] is not None,
          "wall time is reported with the load beside it")

print(f"\n{'ALL PASSED' if not FAILS else str(len(FAILS)) + ' FAILED'}")
sys.exit(1 if FAILS else 0)
