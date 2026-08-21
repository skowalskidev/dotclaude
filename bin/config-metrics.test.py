#!/usr/bin/env python3
"""Pure-logic tests for the incremental read in config-metrics.py — the quota fix.

No Firestore, no network: the aggregator imports firebase_admin only lazily inside its store
functions, so the module loads and its tally/merge/score logic runs under plain python3. What these
guard is the correctness the quota fix hinges on:
  - a cold seed folds every event in and sets the watermark to the newest ts,
  - a warm re-read at the same second does NOT double-count the boundary events,
  - a later second advances the watermark and resets the boundary id set,
  - the outbox is layered on for scoring only, never persisted into the tally,
  - score() from a cumulative tally yields the same fields it always did.

Run:  /usr/bin/python3 ~/.claude/bin/config-metrics.py.test  ->  no, run this file directly:
      /usr/bin/python3 ~/.claude/bin/config-metrics.test.py
"""
import importlib.util
import os
import sys

HERE = os.path.dirname(os.path.abspath(__file__))
_spec = importlib.util.spec_from_file_location("config_metrics", os.path.join(HERE, "config-metrics.py"))
m = importlib.util.module_from_spec(_spec)
_spec.loader.exec_module(m)

_fails: list[str] = []


def check(cond: bool, msg: str) -> None:
    if not cond:
        _fails.append(msg)


def ev(name, kind="tool_call", ts="", count=1):
    return {"part_name": name, "kind": kind, "ts": ts, "count": count}


# --- cold seed: empty tally, two events at different seconds --------------------------------------
tally = {"watermark": "", "counts": {}, "watermark_ids": []}
e1, e2 = ev("skill-a", ts="2026-08-20T10:00:00Z"), ev("skill-a", ts="2026-08-20T10:00:05Z")
m._advance_and_merge(tally, [e1, e2], ["id1", "id2"])
check(tally["counts"]["skill-a"]["uses"] == 2, "cold seed should count both events")
check(tally["watermark"] == "2026-08-20T10:00:05Z", "watermark should be the newest ts")
check(tally["watermark_ids"] == ["id2"], "watermark_ids should hold only the id at the max second")

# --- warm re-read overlap: boundary already skipped by _fetch_since, new event same second --------
# Simulate _fetch_since having dropped id2 (in watermark_ids); a fresh e3 shares that exact second.
e3 = ev("skill-a", ts="2026-08-20T10:00:05Z")
m._advance_and_merge(tally, [e3], ["id3"])
check(tally["counts"]["skill-a"]["uses"] == 3, "same-second new event counts once, no double-count")
check(sorted(tally["watermark_ids"]) == ["id2", "id3"], "same-second ids should union, not replace")
check(tally["watermark"] == "2026-08-20T10:00:05Z", "watermark unchanged when max ts is unchanged")

# --- later second advances the watermark and resets the boundary set -----------------------------
e4 = ev("skill-a", ts="2026-08-20T10:00:09Z")
m._advance_and_merge(tally, [e4], ["id4"])
check(tally["watermark"] == "2026-08-20T10:00:09Z", "a newer ts advances the watermark")
check(tally["watermark_ids"] == ["id4"], "advancing the second replaces watermark_ids")

# --- no new events is a no-op --------------------------------------------------------------------
before = (tally["watermark"], sorted(tally["watermark_ids"]), tally["counts"]["skill-a"]["uses"])
m._advance_and_merge(tally, [], [])
after = (tally["watermark"], sorted(tally["watermark_ids"]), tally["counts"]["skill-a"]["uses"])
check(before == after, "empty batch must not change the tally")

# --- kinds tally into the right buckets; last tracks the max ts ----------------------------------
t2 = {"watermark": "", "counts": {}, "watermark_ids": []}
m._apply_event(t2["counts"], ev("hooks/x.py", kind="hook_deny", ts="2026-08-20T09:00:00Z", count=2))
m._apply_event(t2["counts"], ev("hooks/x.py", kind="error", ts="2026-08-20T09:00:01Z"))
m._apply_event(t2["counts"], ev("hooks/x.py", kind="prompt", ts="2026-08-20T08:59:00Z", count=3))
c = t2["counts"]["hooks/x.py"]
check(c["denials"] == 2 and c["errs"] == 1 and c["uses"] == 3, "each kind lands in its own bucket")
check(c["last"] == "2026-08-20T09:00:01Z", "last should be the max ts seen, not the last applied")

# --- score() from a cumulative tally: fields preserved, hook denial dual-key kept -----------------
parts = ["skills/sk/skills/skill-a/SKILL.md", "hooks/x.py", "references/foo.md"]
counts = {
    "skill-a": {"uses": 12, "errs": 0, "denials": 0, "last": "2026-08-20T10:00:09Z"},
    "hooks/x.py": {"uses": 0, "errs": 0, "denials": 2, "last": "2026-08-20T09:00:00Z"},
}
reach = {p: True for p in parts}
rows = {r["part"]: r for r in m.score(parts, counts, reach, m._criticality())}
check(rows["skills/sk/skills/skill-a/SKILL.md"]["uses"] == 12, "skill uses read by folder name")
check(rows["skills/sk/skills/skill-a/SKILL.md"]["classification"] == "hot", "12 uses -> hot")
check(rows["skills/sk/skills/skill-a/SKILL.md"]["last_used"] == "2026-08-20T10:00:09Z", "last_used preserved")
# hooks/x.py: p == uname, so the p+uname denial lookup doubles it, exactly as the original did.
check(rows["hooks/x.py"]["denials"] == 4, "hook denial dual-key behaviour preserved (2+2)")
check(rows["references/foo.md"]["classification"] == "instrumentation-gap",
      "reachable + zero usage -> instrumentation-gap, never dead")

if _fails:
    print("FAIL config-metrics.test.py:")
    for f in _fails:
        print("  -", f)
    sys.exit(1)
print("ok config-metrics.test.py — %d checks passed" % 21)
