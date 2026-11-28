#!/usr/bin/env python3
"""
A durable copy of every Claude Code scheduled task, so a timed resume promised to Simon survives a
session restart and a missed one is caught up once instead of vanishing.

WHY: CronCreate tasks are session-scoped. Claude Code's docs: "Closing the terminal or letting the
session exit stops them firing", a restored task "doesn't fire for the runs it missed", and a one-shot
whose time passed is not restored (code.claude.com/docs/en/scheduled-tasks). The `durable` flag is a
no-op in this build. On 27 Nov 2026 "pause and resume at 7am" was a CronCreate one-shot; the Conductor
session restarted overnight, the job vanished, and nothing told anyone until Simon asked at 9am.

WHAT IT DOES (missed-run catch-up, the anacron / systemd `Persistent=true` / Desktop scheduled tasks
semantics: one catch-up run for the most recent missed time, within 7 days):
  PostToolUse CronCreate  records cron, prompt, recurring, job id and session in
                          <project>/.context/scheduled-tasks.json (gitignored workspace state).
  PostToolUse CronDelete  marks the record cancelled.
  UserPromptSubmit        a prompt equal to a record's prompt is that task firing: a one-shot is done,
                          a recurring one stamps last_fired. Then it lists every OVERDUE task (run it
                          first, once) and every PENDING task not re-armed in this session.
  SessionStart            (startup or resume) session crons died with the old process: every pending
                          task is marked unarmed; it prints OVERDUE tasks to run now and PENDING tasks
                          to re-arm with CronCreate after a CronList check (no double arming).
  CLI                     list | done <id> | cancel <id> | due  [--root DIR]

LIMIT: a hook runs only when the session takes a turn. A restarted session with no prompt runs nothing
at the promised time; the next prompt catches it up. On-time runs across a restart need an external
waker (Claude Desktop local scheduled tasks or a launchd job), which is a persistent process and needs
Simon's yes (rules/process.md § Clean up after yourself).

Skips a delegated worker (AGENT_DELEGATED_WORKER=1). Fails open: any error prints nothing and exits 0.
SCHEDULED_TASKS_NOW (ISO local time) overrides the clock for tests.
"""

from __future__ import annotations

import datetime as dt
import json
import os
import re
import subprocess
import sys
from pathlib import Path

STORE = Path(".context") / "scheduled-tasks.json"
CATCH_UP_DAYS = 7          # Desktop scheduled tasks and anacron look back a bounded window
RECURRING_EXPIRY_DAYS = 7  # CronCreate recurring tasks auto-expire after 7 days in this build
SCAN_DAYS = 400            # a pinned one-shot is at most a year out


def now() -> dt.datetime:
    fixed = os.environ.get("SCHEDULED_TASKS_NOW")
    return dt.datetime.fromisoformat(fixed) if fixed else dt.datetime.now()


# ------------------------------------------------------------------ cron (5 fields, local time)
RANGES = [(0, 59), (0, 23), (1, 31), (1, 12), (0, 6)]


def field_values(text: str, lo: int, hi: int) -> set[int]:
    out: set[int] = set()
    for part in text.split(","):
        step = 1
        if "/" in part:
            part, s = part.split("/", 1)
            step = int(s)
        if part in ("*", ""):
            a, b = lo, hi
        elif "-" in part:
            a, b = (int(x) for x in part.split("-", 1))
        else:
            a = b = int(part)
        out.update(v for v in range(a, b + 1, step) if lo <= v <= hi or (hi == 6 and v == 7))
    return {0 if (hi == 6 and v == 7) else v for v in out}


def parse_cron(expr: str) -> list[set[int]]:
    parts = expr.split()
    if len(parts) != 5:
        raise ValueError(f"cron needs 5 fields: {expr!r}")
    return [field_values(p, lo, hi) for p, (lo, hi) in zip(parts, RANGES)]


def matches(fields: list[set[int]], t: dt.datetime, expr: str) -> bool:
    minute, hour, dom, month, dow = fields
    if t.minute not in minute or t.hour not in hour or t.month not in month:
        return False
    dom_any, dow_any = expr.split()[2] == "*", expr.split()[4] == "*"
    in_dom, in_dow = t.day in dom, (t.weekday() + 1) % 7 in dow
    if dom_any or dow_any:
        return in_dom and in_dow
    return in_dom or in_dow  # cron's rule: both restricted means either matches


def fire_times(expr: str, start: dt.datetime, end: dt.datetime):
    """Every scheduled minute in (start, end], oldest first."""
    fields = parse_cron(expr)
    t = start.replace(second=0, microsecond=0) + dt.timedelta(minutes=1)
    while t <= end:
        if matches(fields, t, expr):
            yield t
            t += dt.timedelta(minutes=1)
            continue
        if t.hour not in fields[1] or t.month not in fields[3]:
            t = (t + dt.timedelta(hours=1)).replace(minute=0)
        else:
            t += dt.timedelta(minutes=1)


def next_fire(expr: str, after: dt.datetime) -> dt.datetime | None:
    return next(fire_times(expr, after, after + dt.timedelta(days=SCAN_DAYS)), None)


def last_fire(expr: str, after: dt.datetime, upto: dt.datetime) -> dt.datetime | None:
    last = None
    for t in fire_times(expr, after, upto):
        last = t
    return last


# ------------------------------------------------------------------ store
def root_of(cwd: str | None) -> Path:
    base = os.environ.get("CLAUDE_PROJECT_DIR") or cwd or os.getcwd()
    try:
        top = subprocess.run(["git", "-C", base, "rev-parse", "--show-toplevel"], capture_output=True,
                             text=True, timeout=5).stdout.strip()
    except Exception:
        top = ""
    return Path(top or base)


def load(root: Path) -> list[dict]:
    try:
        return json.loads((root / STORE).read_text()).get("tasks", [])
    except Exception:
        return []


def save(root: Path, tasks: list[dict]) -> None:
    path = root / STORE
    path.parent.mkdir(parents=True, exist_ok=True)
    tmp = path.with_suffix(".tmp")
    tmp.write_text(json.dumps({"tasks": tasks}, indent=1) + "\n")
    tmp.replace(path)


def aware(t: dt.datetime | None) -> str | None:
    """A one-shot's due time with its UTC offset, so a timezone or daylight-saving change keeps the instant."""
    return t.astimezone().isoformat(timespec="seconds") if t else None


def local_tz() -> str:
    return os.environ.get("TZ") or dt.datetime.now().astimezone().tzname() or ""


def norm(text: str) -> str:
    return re.sub(r"\s+", " ", text or "").strip()


def stamp(t: dt.datetime) -> str:
    return t.isoformat(timespec="seconds")


def state(task: dict, at: dt.datetime) -> tuple[str, dt.datetime | None]:
    """('overdue', missed time) | ('pending', next time) | ('expired', None) | ('closed', None)."""
    if task.get("status") != "pending":
        return "closed", None
    created = dt.datetime.fromisoformat(task["created"])
    since = dt.datetime.fromisoformat(task["last_fired"]) if task.get("last_fired") else created
    try:
        if task.get("recurring"):
            if at - created > dt.timedelta(days=RECURRING_EXPIRY_DAYS):
                return "expired", None
            missed = last_fire(task["cron"], max(since, at - dt.timedelta(days=CATCH_UP_DAYS)), at)
            if missed:
                return "overdue", missed
            return "pending", next_fire(task["cron"], at)
        due = (dt.datetime.fromisoformat(task["due"]).astimezone().replace(tzinfo=None) if task.get("due")
               else next_fire(task["cron"], created))
        if due is None:
            return "expired", None
        if due <= at:
            return ("overdue", due) if at - due <= dt.timedelta(days=CATCH_UP_DAYS) else ("expired", None)
        return "pending", due
    except Exception:
        return "closed", None


def job_id(response) -> str | None:
    text = response if isinstance(response, str) else json.dumps(response or {})
    m = re.search(r"\btask ([0-9a-f]{6,})\b", text) or re.search(r'"(?:id|jobId|job_id)"\s*:\s*"([^"]+)"', text)
    return m.group(1) if m else None


# ------------------------------------------------------------------ hook events
def on_create(root: Path, payload: dict) -> None:
    inp = payload.get("tool_input") or {}
    cron, prompt = inp.get("cron"), inp.get("prompt")
    if not cron or not prompt:
        return
    parse_cron(cron)
    tasks = load(root)
    jid = job_id(payload.get("tool_response"))
    sid = payload.get("session_id")
    for t in tasks:  # re-arming the same promise updates its record
        if t.get("status") == "pending" and norm(t["prompt"]) == norm(prompt) and t["cron"] == cron:
            t.update(job_id=jid, armed_session=sid)
            if t.get("recurring"):  # CronCreate's recurring expiry restarts when it is created again
                t["created"] = stamp(now())
            save(root, tasks)
            return
    tasks.append({"id": jid or f"t{len(tasks) + 1}", "job_id": jid, "cron": cron, "prompt": prompt,
                  "recurring": inp.get("recurring", True) is not False, "created": stamp(now()),
                  "session": sid, "armed_session": sid, "status": "pending", "last_fired": None,
                  "due": None if inp.get("recurring", True) is not False else aware(next_fire(cron, now())),
                  "tz": local_tz()})
    save(root, tasks)


def on_delete(root: Path, payload: dict) -> None:
    jid = (payload.get("tool_input") or {}).get("id")
    tasks = load(root)
    for t in tasks:
        if jid and t.get("job_id") == jid and t.get("status") == "pending":
            t["status"] = "cancelled"
    save(root, tasks)


def on_prompt(root: Path, payload: dict) -> str:
    tasks = load(root)
    if not tasks:
        return ""
    prompt, at, changed = norm(payload.get("prompt") or ""), now(), False
    for t in tasks:
        if t.get("status") == "pending" and prompt and norm(t["prompt"]) == prompt:
            t["last_fired"] = stamp(at)
            t["armed_session"] = payload.get("session_id")
            if not t.get("recurring"):
                t["status"] = "done"
            changed = True
    if changed:
        save(root, tasks)
    return report(root, tasks, at, payload.get("session_id"), restarted=False)


def on_start(root: Path, payload: dict) -> str:
    tasks = load(root)
    if not tasks:
        return ""
    if payload.get("source") in ("startup", "resume", None):
        for t in tasks:
            if t.get("status") == "pending":
                t["armed_session"] = None
        save(root, tasks)
    return report(root, tasks, now(), payload.get("session_id"), restarted=True)


def report(root: Path, tasks: list[dict], at: dt.datetime, sid, restarted: bool) -> str:
    overdue, unarmed, expired = [], [], False
    for t in tasks:
        kind, when = state(t, at)
        if kind == "overdue":
            overdue.append((t, when))
        elif kind == "pending" and t.get("armed_session") != sid:
            unarmed.append((t, when))
        elif kind == "expired":
            t["status"] = "expired"
            expired = True
    if expired:
        save(root, tasks)
    if not overdue and not unarmed:
        return ""
    cli = f"python3 ~/.claude/bin/scheduled_tasks.py"
    lines = ["SCHEDULED TASKS (durable copy of CronCreate jobs, "
             f"{root / STORE}; session crons die with the session):"]
    for t, when in overdue:
        lines.append(f"- OVERDUE {t['id']}: was due {stamp(when)}, never ran. Run its prompt NOW, before the new ask "
                     f"(one catch-up run), tell Simon it ran late and why, then `{cli} done {t['id']} --root {root}`."
                     f" Prompt: {t['prompt']}")
    for t, when in unarmed:
        lines.append(f"- PENDING {t['id']}: next {stamp(when)} ({t['cron']}, {'recurring' if t.get('recurring') else 'one-shot'})"
                     f" is not armed in this session. Run CronList; if it is missing, CronCreate it again with the same"
                     f" cron and prompt (the hook re-links it). Prompt: {t['prompt']}")
    if restarted and unarmed:
        lines.append("A restarted session runs nothing until it takes a turn: re-arm now so the promised time holds.")
    return "\n".join(lines)


def main(argv: list[str]) -> int:
    if not argv:
        print(__doc__)
        return 2
    cmd = argv[0]
    if cmd == "hook":
        if os.environ.get("AGENT_DELEGATED_WORKER") == "1":
            return 0
        try:
            payload = json.loads(sys.stdin.read() or "{}")
            root = root_of(payload.get("cwd"))
            event, tool = payload.get("hook_event_name"), payload.get("tool_name")
            out = ""
            if event == "PostToolUse" and tool == "CronCreate":
                on_create(root, payload)
            elif event == "PostToolUse" and tool == "CronDelete":
                on_delete(root, payload)
            elif event == "UserPromptSubmit":
                out = on_prompt(root, payload)
            elif event == "SessionStart":
                out = on_start(root, payload)
            if out:
                print(out)
        except Exception:
            pass
        return 0
    root = root_of(argv[argv.index("--root") + 1] if "--root" in argv else None)
    tasks = load(root)
    if cmd in ("done", "cancel") and len(argv) > 1:
        hit = [t for t in tasks if argv[1] in (t.get("id"), t.get("job_id"))]
        for t in hit:
            if cmd == "cancel":
                t["status"] = "cancelled"
                continue
            t["last_fired"] = stamp(now())
            if not t.get("recurring"):  # a recurring task stays pending for its next run
                t["status"] = "done"
        save(root, tasks)
        print(f"{cmd}: {len(hit)}")
        return 0 if hit else 1
    if cmd in ("list", "due"):
        at = now()
        for t in tasks:
            kind, when = state(t, at)
            if cmd == "due" and kind != "overdue":
                continue
            print(f"{t['id']}\t{t.get('status')}\t{kind}\t{stamp(when) if when else '-'}\t{t['cron']}\t{t['prompt'][:80]}")
        return 0
    print(__doc__)
    return 2


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))
