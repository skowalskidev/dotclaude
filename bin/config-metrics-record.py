#!/usr/bin/env python3
"""Parse one ended session's transcript into minimized metric events → dotclaude.

Called by the SessionEnd hook (config-metrics-log.sh) with the hook payload on stdin
({transcript_path, session_id, reason, cwd}). It walks the transcript ONCE and emits, per session:

  - prompt      events — the request intent (redacted, capped; personal boundary only)
  - tool_call   events — a skill invoked (part_type=skill) or a reference Read (part_type=reference)
  - hook_deny   events — a guard denial, by signature → the hook part that fired
  - error       events — a tool_result with is_error

Then a `sessions` metadata doc and a `pipeline_health` row. Everything routes through the shared
writer (dotclaude-log.write_events), which minimizes, boundary-scopes, stamps TTL, and flushes to
Firestore or the outbox. This script NEVER raises — a bad transcript must not fail SessionEnd.

Boundary: work vs personal is read from ~/.claude/identity.local.json (workOrgMatch / workCloud
projects). A work-boundary session emits the config-part SIGNAL but no request text (the writer drops
`intent` when boundary=='work'). If identity.local.json is absent (a fork), everything is personal.
"""
from __future__ import annotations

import json
import os
import subprocess
import sys

_HERE = os.path.dirname(os.path.abspath(__file__))
_HOME = os.path.expanduser("~")


def _load_writer():
    import importlib.util
    path = os.path.join(_HERE, "dotclaude-log.py")
    spec = importlib.util.spec_from_file_location("dotclaude_log", path)
    mod = importlib.util.module_from_spec(spec)  # type: ignore
    spec.loader.exec_module(mod)  # type: ignore
    return mod.write_events


# Guard denial signatures → the hook part that owns them (mirrors retro-trigger-log.sh's grep).
_DENY_SIGNATURES = {
    "crown-jewel": "hooks/crown-jewel-read-guard.py",
    "TASK INTAKE GATE": "hooks/task-intake.sh",
    "Blocked:": "hooks/work-resource-guard.sh",
    "config-edit-guard": "hooks/config-edit-guard.py",
    "background-process": "hooks/background-process-guard.py",
}


def _identity() -> dict:
    try:
        with open(os.path.join(_HOME, ".claude", "identity.local.json"), encoding="utf-8") as fh:
            return json.load(fh)
    except Exception:
        return {}


def _boundary(cwd: str, ident: dict) -> str:
    """'work' if the session ran in a work repo, else 'personal'. Fail to personal only when there
    is NO work marker configured; when markers exist, fail to work (safer: never leak work content)."""
    org = (ident.get("workOrgMatch") or "").lower()
    projs = [p.lower() for p in ident.get("workCloudProjects", [])]
    if not org and not projs:
        return "personal"  # no work identity configured (a fork) → nothing is work
    try:
        url = subprocess.run(
            ["git", "-C", cwd or ".", "remote", "get-url", "origin"],
            capture_output=True, text=True, timeout=3,
        ).stdout.strip().lower()
    except Exception:
        url = ""
    if org and org in url:
        return "work"
    if any(p in url for p in projs):
        return "work"
    # A configured work identity but no git origin match → treat as personal (a scratch/personal dir).
    return "personal"


def _repo(cwd: str) -> str:
    """The repo NAME (basename only — never the full path, org, or any content), for tagging which
    context a part is used in. Both boundaries carry it; work sessions still drop their request text."""
    try:
        top = subprocess.run(["git", "-C", cwd or ".", "rev-parse", "--show-toplevel"],
                             capture_output=True, text=True, timeout=3).stdout.strip()
        if top:
            return os.path.basename(top)
    except Exception:
        pass
    return os.path.basename(cwd) if cwd else "unknown"


def _content_blocks(rec: dict):
    msg = rec.get("message")
    c = msg.get("content") if isinstance(msg, dict) else rec.get("content")
    return c if isinstance(c, list) else ([] if c is None else [{"type": "text", "text": c}])


def _skill_part(skill_arg: str) -> str | None:
    """Map a Skill tool arg ('sk:ship-pr', 'ship-pr', 'sk-work:foo') to our skill folder name, or
    None if it isn't one of Simon's own (sk/sk-work) skills we track."""
    if not isinstance(skill_arg, str) or not skill_arg:
        return None
    name = skill_arg.split(":", 1)[1] if ":" in skill_arg else skill_arg
    return name.strip() or None


def parse_transcript(path: str, session_id: str, boundary: str) -> list[dict]:
    events: list[dict] = []
    seq = 0
    id_to_tool: dict[str, str] = {}
    try:
        fh = open(path, encoding="utf-8")
    except Exception:
        return events
    with fh:
        for line in fh:
            try:
                rec = json.loads(line)
            except Exception:
                continue
            rtype = rec.get("type")
            for b in _content_blocks(rec):
                if not isinstance(b, dict):
                    continue
                bt = b.get("type")
                if bt == "tool_use":
                    tname = b.get("name") or ""
                    tid = b.get("id")
                    if tid:
                        id_to_tool[tid] = tname
                    inp = b.get("input") or {}
                    if tname == "Skill":
                        part = _skill_part(inp.get("skill") or inp.get("command") or "")
                        if part:
                            seq += 1
                            events.append({"seq": seq, "kind": "tool_call", "part_type": "skill",
                                           "part_name": part, "tool_name": "Skill", "outcome": "used"})
                    elif tname == "Read":
                        fp = str(inp.get("file_path") or "")
                        if "/references/" in fp and fp.endswith(".md"):
                            seq += 1
                            events.append({"seq": seq, "kind": "tool_call", "part_type": "reference",
                                           "part_name": "references/" + os.path.basename(fp),
                                           "tool_name": "Read", "outcome": "used"})
                elif bt == "tool_result":
                    if b.get("is_error"):
                        tid = b.get("tool_use_id")
                        seq += 1
                        events.append({"seq": seq, "kind": "error", "tool_name": id_to_tool.get(tid, "unknown"),
                                       "outcome": "error", "error_type": "tool_error"})
                elif bt == "text" and rtype == "user":
                    txt = b.get("text") or ""
                    if txt and not txt.startswith("[SYSTEM"):
                        seq += 1
                        ev = {"seq": seq, "kind": "prompt", "outcome": "used"}
                        if boundary != "work":
                            ev["intent"] = txt  # writer redacts + caps; dropped entirely if work
                        events.append(ev)
    # Guard-denial signatures from the raw transcript text (cheap, robust to record shape).
    try:
        with open(path, encoding="utf-8") as fh:
            blob = fh.read()
        for sig, part in _DENY_SIGNATURES.items():
            n = blob.count(sig)
            if n:
                seq += 1
                events.append({"seq": seq, "kind": "hook_deny", "part_type": "hook",
                               "part_name": part, "outcome": "denied", "error_type": "guard_denial",
                               "count": n})
    except Exception:
        pass
    for e in events:
        e["session_id"] = session_id
        e["boundary"] = boundary
    return events


def main() -> int:
    raw = sys.stdin.read()
    try:
        payload = json.loads(raw) if raw.strip() else {}
    except Exception:
        payload = {}
    transcript = payload.get("transcript_path") or ""
    session_id = (payload.get("session_id") or "unknown").replace("/", "_")
    cwd = payload.get("cwd") or os.getcwd()
    end_reason = payload.get("reason") or "other"
    if not transcript or not os.path.isfile(transcript):
        return 0  # nothing to record

    ident = _identity()
    boundary = _boundary(cwd, ident)
    repo = _repo(cwd)
    try:
        write_events = _load_writer()
    except Exception:
        return 0  # writer unavailable → nothing we can safely do; never raise

    events = parse_transcript(transcript, session_id, boundary)
    machine = os.uname().nodename if hasattr(os, "uname") else "unknown"
    for e in events:
        e["repo"] = repo

    if events:
        try:
            write_events("session_events", events)
        except Exception:
            pass
    # Session metadata doc.
    try:
        write_events("sessions", [{
            "session_id": session_id, "machine": machine, "boundary": boundary, "repo": repo,
            "end_reason": end_reason, "event_count": len(events),
        }])
    except Exception:
        pass
    # Pipeline self-health (dogfooding + fail-loud): record that capture ran and how it went.
    try:
        outbox = os.path.join(_HOME, ".claude", "metrics", "outbox.jsonl")
        depth = sum(1 for _ in open(outbox, encoding="utf-8")) if os.path.exists(outbox) else 0
        write_events("pipeline_health", [{
            "session_id": session_id, "machine": machine, "boundary": boundary,
            "kind": "capture", "event_count": len(events), "outbox_depth": depth,
        }])
    except Exception:
        pass
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
