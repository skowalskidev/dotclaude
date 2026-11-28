#!/usr/bin/env python3
"""Pins bin/scheduled_tasks.py: a CronCreate promise survives a session restart, a missed one is caught
up exactly once, a re-armed or cancelled one goes quiet, and nothing breaks the session.

The first case replays the 27 Nov 2026 incident: "pause and resume at 7am" scheduled at 00:13 local as a
CronCreate one-shot (0 7 28 11 *), the session restarted overnight, and the next prompt came at 09:05.
Without this engine the restarted session's SessionStart and first prompt say nothing about it."""

from __future__ import annotations

import json
import os
import subprocess
import sys
import tempfile
from pathlib import Path

ENGINE = Path(__file__).resolve().parent / "scheduled_tasks.py"
FAILURES: list[str] = []
PROMPT = "Resume the paused session work at 7am: finish POI-1967, re-run the readout."


def check(ok: bool, msg: str) -> None:
    if not ok:
        FAILURES.append(msg)
        print("FAIL:", msg)


def hook(root: Path, payload: dict, at: str, env: dict | None = None) -> str:
    e = {**os.environ, "SCHEDULED_TASKS_NOW": at, "CLAUDE_PROJECT_DIR": str(root), **(env or {})}
    e.pop("AGENT_DELEGATED_WORKER", None) if not (env or {}).get("AGENT_DELEGATED_WORKER") else None
    r = subprocess.run([sys.executable, str(ENGINE), "hook"], input=json.dumps({"cwd": str(root), **payload}),
                       capture_output=True, text=True, env=e, timeout=30)
    check(r.returncode == 0, f"hook exits 0 (got {r.returncode}: {r.stderr[-300:]})")
    return r.stdout


def create(root, cron, prompt=PROMPT, recurring=False, sid="s1", at="2026-11-28T00:13:00", jid="a34ceffb"):
    return hook(root, {"hook_event_name": "PostToolUse", "tool_name": "CronCreate", "session_id": sid,
                       "tool_input": {"cron": cron, "prompt": prompt, "recurring": recurring},
                       "tool_response": f"Scheduled one-shot task {jid} ({cron}). Session-only."}, at)


def start(root, at, sid="s2", source="startup"):
    return hook(root, {"hook_event_name": "SessionStart", "session_id": sid, "source": source}, at)


def prompt(root, text, at, sid="s2"):
    return hook(root, {"hook_event_name": "UserPromptSubmit", "session_id": sid, "prompt": text}, at)


def tasks(root):
    return json.loads((root / ".context" / "scheduled-tasks.json").read_text())["tasks"]


def fresh() -> Path:
    return Path(tempfile.mkdtemp(prefix="sched-"))


# 1. The incident: restart overnight, next prompt at 09:05 -> overdue surfaced at SessionStart and on the prompt.
r = fresh()
create(r, "0 7 28 11 *")
check(len(tasks(r)) == 1 and tasks(r)[0]["job_id"] == "a34ceffb", "CronCreate is recorded durably with its job id")
out = start(r, "2026-11-28T09:05:00")
check("OVERDUE a34ceffb" in out and "2026-11-28T07:00:00" in out and PROMPT in out,
      f"a restarted session is told the 7am resume is overdue, with its prompt: {out!r}")
out = prompt(r, "do you didn't do the 7am tasks? just answer", "2026-11-28T09:05:10")
check("OVERDUE a34ceffb" in out, "the next prompt repeats the overdue task until it is done")
subprocess.run([sys.executable, str(ENGINE), "done", "a34ceffb", "--root", str(r)], capture_output=True,
               env={**os.environ, "SCHEDULED_TASKS_NOW": "2026-11-28T09:06:00"})
check(prompt(r, "next ask", "2026-11-28T09:07:00") == "", "once marked done, prompts are quiet")

# 2. Restart BEFORE the time: the pending task is flagged for re-arming; re-creating it re-links, no duplicate.
r = fresh()
create(r, "0 7 28 11 *")
out = start(r, "2026-11-28T02:00:00")
check("PENDING a34ceffb" in out and "CronList" in out and "OVERDUE" not in out,
      f"a restart before the time asks to re-arm, not to run: {out!r}")
check("PENDING" in prompt(r, "hi", "2026-11-28T02:01:00"), "an unarmed pending task is repeated on the next prompt")
create(r, "0 7 28 11 *", sid="s2", at="2026-11-28T02:02:00", jid="bbbb1111")
check(len(tasks(r)) == 1 and tasks(r)[0]["job_id"] == "bbbb1111", "re-arming updates the same record, no duplicate")
check(prompt(r, "hi", "2026-11-28T02:03:00") == "", "a re-armed task is quiet in the same session")

# 3. The cron fires in a live session: its own prompt arriving marks a one-shot done.
r = fresh()
create(r, "0 7 28 11 *", sid="s1")
check(prompt(r, PROMPT, "2026-11-28T07:00:30", sid="s1") == "", "the firing prompt itself is not reported overdue")
check(tasks(r)[0]["status"] == "done", "a one-shot whose prompt fired is done")
check(start(r, "2026-11-28T09:00:00") == "", "a done task never resurfaces after a restart")

# 4. CronDelete cancels it.
r = fresh()
create(r, "0 7 28 11 *")
hook(r, {"hook_event_name": "PostToolUse", "tool_name": "CronDelete", "tool_input": {"id": "a34ceffb"}}, "2026-11-28T01:00:00")
check(tasks(r)[0]["status"] == "cancelled" and start(r, "2026-11-28T09:00:00") == "", "a deleted task is cancelled and quiet")

# 5. Recurring: missed runs give exactly one catch-up, then pending for the next run.
r = fresh()
create(r, "17 * * * *", prompt="hourly check", recurring=True, at="2026-11-28T00:05:00", jid="cccc2222")
out = start(r, "2026-11-28T05:30:00")
check(out.count("OVERDUE cccc2222") == 1 and "2026-11-28T05:17:00" in out,
      f"one catch-up for the most recent missed run: {out!r}")
prompt(r, "hourly check", "2026-11-28T05:31:00", sid="s2")
out = prompt(r, "other", "2026-11-28T05:40:00", sid="s2")
check("OVERDUE" not in out and tasks(r)[0]["status"] == "pending", f"after firing, a recurring task is pending again: {out!r}")

# 6. Out of the window: a one-shot missed by more than 7 days expires instead of nagging.
r = fresh()
create(r, "0 7 28 11 *")
check(start(r, "2026-12-09T09:00:00") == "" and tasks(r)[0]["status"] == "expired", "a stale one-shot expires quietly")

# 7. Fail open and stay out of delegated workers.
r = fresh()
res = subprocess.run([sys.executable, str(ENGINE), "hook"], input="not json", capture_output=True, text=True,
                     env={**os.environ, "CLAUDE_PROJECT_DIR": str(r)})
check(res.returncode == 0 and res.stdout == "", "malformed input exits 0 and prints nothing")
create(r, "0 7 28 11 *")
out = hook(r, {"hook_event_name": "SessionStart", "session_id": "w", "source": "startup"}, "2026-11-28T09:00:00",
           env={"AGENT_DELEGATED_WORKER": "1"})
check(out == "", "a delegated worker gets no scheduled-task context")
check(start(r, "2026-11-28T09:00:00", source="compact").count("OVERDUE") == 1,
      "a compaction keeps arming but still reports an overdue task")

# 8. Cron parsing: weekday and list forms.
sys.path.insert(0, str(ENGINE.parent))
import importlib.util
spec = importlib.util.spec_from_file_location("st", ENGINE)
st = importlib.util.module_from_spec(spec)
spec.loader.exec_module(st)
import datetime as dt
check(st.next_fire("0 9 * * 1-5", dt.datetime(2026, 11, 28, 10)) == dt.datetime(2026, 11, 30, 9),
      "weekdays 9am after a Saturday is Monday 9am")
check(st.next_fire("15,45 */2 * * *", dt.datetime(2026, 11, 28, 1, 50)) == dt.datetime(2026, 11, 28, 2, 15),
      "lists and steps parse")

# 9. Judges' holes: `done` on a recurring task keeps it alive; a one-shot keeps its instant across a timezone change.
r = fresh()
create(r, "17 * * * *", prompt="hourly check", recurring=True, at="2026-11-28T00:05:00", jid="dddd3333")
subprocess.run([sys.executable, str(ENGINE), "done", "dddd3333", "--root", str(r)], capture_output=True,
               env={**os.environ, "SCHEDULED_TASKS_NOW": "2026-11-28T05:30:00"})
check(tasks(r)[0]["status"] == "pending" and tasks(r)[0]["last_fired"], "done on a recurring task stamps it and keeps it pending")
r = fresh()
hook(r, {"hook_event_name": "PostToolUse", "tool_name": "CronCreate", "session_id": "s1",
         "tool_input": {"cron": "0 7 28 11 *", "prompt": PROMPT, "recurring": False},
         "tool_response": "Scheduled one-shot task eeee4444"}, "2026-11-28T00:13:00", env={"TZ": "Asia/Bangkok"})
out = hook(r, {"hook_event_name": "SessionStart", "session_id": "s2", "source": "startup"}, "2026-11-28T01:30:00",
           env={"TZ": "Europe/London"})
check("OVERDUE eeee4444" in out, f"07:00 Bangkok is overdue at 01:30 London (08:30 Bangkok): {out!r}")

print("ok" if not FAILURES else f"{len(FAILURES)} failure(s)")
sys.exit(1 if FAILURES else 0)
